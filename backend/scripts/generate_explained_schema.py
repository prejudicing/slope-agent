"""基于真实数据库 schema 生成初版中文业务解释和向量化 chunk。"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT_DIR / "backend" / "schema_exports" / "database_schema.json"
DEFAULT_OUTPUT = ROOT_DIR / "backend" / "schema_exports" / "database_schema_explained.json"
DEFAULT_CHUNKS = ROOT_DIR / "backend" / "schema_exports" / "schema_chunks.jsonl"
DEFAULT_DOCUMENT_SCHEMA = ROOT_DIR / "backend" / "schema_exports" / "document_schema.json"


TABLE_DESCRIPTIONS = {
    "geo_gqp_jbxx": ("基本信息", "高切坡基本信息主表，记录项目基础属性、地区、建设信息、监测状态、责任单位、风险状态、预警状态等。"),
    "geo_dzbjjbxx": ("地质背景", "高切坡地质背景与工程地质资料表，记录坡高坡长、切坡类型、安全等级、岩性、风化、地质组成、降雨、影响人口房屋等。"),
    "tb_hcs_monitoring": ("群测群防", "群测群防高切坡监测记录表，记录裂缝、落石、坡面破坏、排水堵塞、照片视频、审核状态等日常监测信息。"),
    "tb_hcs_personnel": ("群测群防", "群测群防监测人员表，记录监测人员姓名、联系方式、所属区县街道、职务和人员级别。"),
    "geo_gqp_zyjc": ("专业监测", "专业监测点表，记录高切坡专业监测点编号、坐标、高程、监测等级、技术单位等。"),
    "t_warning_report": ("预警专报", "预警专报附件表，记录高切坡预警专报文件、时间、年份月份和关联高切坡编号。"),
    "t_warning_report_content": ("预警专报", "预警专报内容提取表，记录项目名称、预警时间、监测类型、本月变形监测、处置情况和是否解除预警。"),
    "t_review_record": ("复核处理", "高切坡预警处理和复核记录表，记录复核状态、复核时间、是否24小时复核、备注和附件。"),
    "t_danger_report": ("报告附件", "巡检或险情报告附件表，记录附件名称、存储地址、报告类型、PDF转换状态等。"),
    "t_monthly": ("报告附件", "月报/年报附件表，记录所属地区、年月、上传路径、PDF转换状态和删除标志。"),
    "t_tilt_model": ("空间数据", "倾斜摄影模型管理表，记录模型名称、编号、路径、坐标、高度、角度和关联高切坡编号。"),
    "t_panoramic_data": ("空间数据", "全景数据管理表，记录全景数据名称、编号、路径、压缩包和关联高切坡编号。"),
    "t_drone_dom": ("空间数据", "高精度无人机DOM数据表，记录DOM影像名称、编号、路径、坐标、高度、角度和影像时间。"),
    "t_user": ("系统管理", "系统用户表。智能查询默认不应检索账号、密码等敏感字段。"),
    "t_user_role": ("系统管理", "用户角色关系表。智能查询默认不应面向业务用户暴露。"),
    "t_role": ("系统管理", "角色表。智能查询默认不应面向业务用户暴露。"),
    "t_role_menu": ("系统管理", "角色权限关系表。智能查询默认不应面向业务用户暴露。"),
    "t_dept": ("系统管理", "部门表。可用于机构、部门名称等管理信息查询。"),
    "t_menus": ("系统管理", "菜单权限表。智能查询默认不应面向业务用户暴露。"),
    "t_tree": ("图层管理", "图层树表，记录地图图层、服务地址、排序、状态和图层关联信息。"),
}


TABLE_ALIAS_RULES = {
    "geo_gqp_jbxx": ["高切坡基本信息", "高切坡台账", "项目基本信息", "边坡基本信息"],
    "geo_dzbjjbxx": ["地质背景", "工程地质", "坡体地质资料", "高切坡地质资料"],
    "tb_hcs_monitoring": ["群测群防监测", "日常监测记录", "裂缝落石监测", "巡查监测"],
    "tb_hcs_personnel": ["监测人员", "群测人员", "巡查人员"],
    "geo_gqp_zyjc": ["专业监测点", "监测点", "位移监测点"],
    "t_warning_report_content": ["预警专报内容", "预警分析", "变形监测月度分析"],
    "t_warning_report": ["预警专报", "预警附件"],
    "t_review_record": ["复核记录", "预警处理记录", "24小时复核"],
    "t_danger_report": ["巡检报告", "险情报告", "报告附件"],
    "t_monthly": ["月报", "年报", "统计报告"],
}


FIELD_MEANINGS = {
    "gqpbh": ("高切坡编号", ["编号", "高切坡编号", "项目编号", "边坡编号"]),
    "gqp_no": ("高切坡编号", ["编号", "高切坡编号", "项目编号", "边坡编号"]),
    "xmbh": ("项目编号（高切坡编号）", ["项目编号", "高切坡编号", "边坡编号"]),
    "gqpmc": ("高切坡名称", ["名称", "高切坡名称", "项目名称", "边坡名称"]),
    "xmmc": ("项目名称", ["项目名称", "高切坡名称"]),
    "ssss": ("所属省市", ["省市", "所属省市", "市州"]),
    "ssqx": ("所属区县", ["区县", "所属区县", "区划"]),
    "ssjd": ("所属街道", ["街道", "所属街道"]),
    "create_time": ("创建时间", ["创建时间", "上传时间", "生成时间"]),
    "createdon": ("创建时间", ["创建时间", "监测时间", "记录时间"]),
    "updatedon": ("修改时间", ["修改时间", "更新时间"]),
    "review_time": ("复核时间", ["复核时间", "审核时间"]),
    "tbsj": ("填报时间", ["填报时间", "上报时间"]),
    "tb_time": ("同步时间", ["同步时间", "数据同步时间"]),
    "delete_flag": ("删除标志", ["删除标志", "是否删除"]),
    "iscrack": ("裂缝情况", ["裂缝", "是否有裂缝", "存在裂缝"]),
    "isread": ("是否有裂缝", ["裂缝", "坡面裂痕"]),
    "sfyls": ("是否有落石", ["落石", "是否落石", "存在落石"]),
    "width": ("裂缝宽度", ["裂缝宽度", "宽度"]),
    "overallsituation": ("总体情况", ["总体情况", "总体异常", "整体情况"]),
    "hcslopestatus": ("审核高切坡异常状态", ["异常状态", "审核异常", "高切坡异常状态"]),
    "status": ("状态", ["状态", "审核状态", "启用状态"]),
    "aqdj": ("安全等级", ["安全等级", "风险等级"]),
    "gqpzt": ("高切坡状态", ["高切坡状态", "工程状态", "状态"]),
    "warning_level": ("预警等级", ["预警等级", "告警等级"]),
    "warned": ("是否预警过", ["是否预警", "预警过"]),
    "sfzyjc": ("是否专业监测", ["专业监测", "是否专业监测"]),
    "sfssjc": ("是否实时监测", ["实时监测", "是否实时监测"]),
    "sfzyjcyc": ("是否专业监测异常", ["专业监测异常", "是否异常"]),
    "sfsssjyc": ("是否实时数据异常", ["实时数据异常", "是否异常"]),
    "zbyyrk": ("周边影响人口", ["影响人口", "周边影响人口", "威胁人口"]),
    "zbyxfw": ("周边影响房屋", ["影响房屋", "周边影响房屋"]),
    "zrdw": ("责任单位", ["责任单位", "负责单位"]),
    "zrdwfzr": ("责任单位负责人", ["责任人", "负责人"]),
    "zrdwfzrdh": ("责任单位负责人电话", ["联系电话", "负责人电话"]),
    "pg_m": ("坡高（米）", ["坡高", "高度"]),
    "pc_m": ("坡长（米）", ["坡长", "长度"]),
    "mj_pm": ("面积（平方米）", ["面积", "坡面面积"]),
    "qplx": ("切坡类型", ["切坡类型", "边坡类型"]),
    "x": ("X坐标或经度", ["X坐标", "经度", "坐标X"]),
    "y": ("Y坐标或纬度", ["Y坐标", "纬度", "坐标Y"]),
    "locx": ("经度", ["经度", "坐标X"]),
    "locy": ("纬度", ["纬度", "坐标Y"]),
    "url": ("文件或服务地址", ["地址", "路径", "文件地址"]),
    "pdf": ("PDF文件地址", ["PDF", "PDF路径"]),
    "ifzh": ("是否转换", ["是否转换", "转换状态"]),
    "name": ("名称", ["名称", "文件名", "附件名"]),
    "title": ("标题", ["标题", "专报标题"]),
    "bybxjcqk": ("本月变形监测情况及稳定性分析", ["变形监测", "稳定性分析"]),
    "byczqk": ("本月处置情况", ["处置情况", "治理情况"]),
    "sfjcyj": ("是否解除预警", ["解除预警", "是否解除"]),
    "scyjsj": ("首次预警时间", ["首次预警时间", "预警时间"]),
}


BOOLEAN_INT_FIELDS = {
    "delete_flag": {"1": "未删除或正常", "0": "已删除"},
    "iscrack": {"1": "存在裂缝", "0": "无裂缝"},
    "isread": {"1": "存在裂缝或裂痕", "0": "无裂缝或裂痕"},
    "sfyls": {"1": "有落石", "0": "无落石"},
    "facilities": {"1": "监测设施异常", "0": "监测设施正常"},
    "slopefailure": {"1": "坡面异常破坏", "0": "无坡面异常破坏"},
    "disorderlypush": {"1": "存在坡周乱搭乱堆", "0": "不存在坡周乱搭乱堆"},
    "wallcracking": {"1": "道路或墙体开裂", "0": "无道路或墙体开裂"},
    "sfypmph": {"1": "有坡面破坏", "0": "无坡面破坏"},
    "sfydtqkl": {"1": "有挡土墙开裂", "0": "无挡土墙开裂"},
    "sfypdzzgg": {"1": "有坡顶种植灌溉", "0": "无坡顶种植灌溉"},
    "sfypsgds": {"1": "有排水沟堵塞", "0": "无排水沟堵塞"},
    "sfypskds": {"1": "有排水口堵塞", "0": "无排水口堵塞"},
    "pmsfygzfq": {"1": "坡面有鼓胀或反翘", "0": "坡面无鼓胀或反翘"},
    "overallsituation": {"1": "总体情况异常", "0": "总体情况正常"},
    "isphototon": {"1": "有拍照时间", "0": "无拍照时间"},
    "is_stop": {"1": "未停止监测", "0": "已停止监测"},
    "is_complete": {"1": "完整", "2": "部分完整", "3": "不完整"},
    "sjly": {"1": "源库", "2": "同步"},
    "emergency_response_status": {"1": "非应急", "2": "应急"},
}


JOIN_KEYS = {
    "geo_gqp_jbxx": ["gqpbh"],
    "geo_dzbjjbxx": ["gqpbh"],
    "tb_hcs_monitoring": ["gqpbh", "monitor_id"],
    "tb_hcs_personnel": ["id", "user_id"],
    "geo_gqp_zyjc": ["gqp_no", "jcdbh"],
    "t_warning_report": ["gqpbh"],
    "t_warning_report_content": ["xmbh", "yjzb_id"],
    "t_review_record": ["gqpbh"],
    "t_danger_report": ["gqpbh"],
}


def normalize_name(value: str) -> str:
    """统一表名/字段名格式，便于规则匹配。"""
    return value.strip().strip('"').lower()


def clean_text(value: str | None) -> str:
    """清理文档字段说明中的换行和多余空白。"""
    if value is None:
        return ""
    return " ".join(str(value).replace("\n", " ").split())


def table_info(table_name: str) -> tuple[str, str]:
    """根据表名推断业务域和表说明；未命中时使用保守兜底描述。"""
    key = normalize_name(table_name)
    if key in TABLE_DESCRIPTIONS:
        return TABLE_DESCRIPTIONS[key]
    if key.startswith("geo_gqp"):
        return "高切坡业务", "高切坡空间或业务数据表，需结合字段含义判断具体用途。"
    if key.startswith("geo_"):
        return "空间/地质数据", "空间、地质或高切坡扩展数据表。"
    if "warning" in key:
        return "预警专报", "预警相关数据表。"
    if "report" in key or "monthly" in key:
        return "报告附件", "报告、附件或归档类数据表。"
    if key.startswith("t_user") or key in {"t_role", "t_role_menu", "t_menus", "t_dept"}:
        return "系统管理", "系统管理数据表，默认不作为高切坡业务查询主表。"
    return "未分类", "真实数据库中的业务表，初版解释未能自动识别具体业务域。"


def clean_doc_label(value: str) -> str:
    """清理文档里的表标题/章节标题，去掉表名尾巴，尽量保留人写的业务解释。"""
    value = re.sub(r"\s+", " ", value.strip())
    value = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\s*$", "", value).strip(" -:：")
    return value


def infer_domain_from_doc(document_title: str, document_section: str, fallback_domain: str) -> str:
    """从文档标题/章节里抽一个短业务域，避免把整句表标题原样塞进 business_domain。"""
    if (
        document_section
        and "_" not in document_section
        and len(document_section) <= 8
        and not any(token in document_section for token in ("记录", "说明", "附件", "内容", "数据"))
    ):
        return document_section

    if document_title:
        match = re.match(r"(.+?)(?:表结构说明|数据记录点表|记录点表|记录表|信息表|附件表|内容表|表)$", document_title)
        if match:
            candidate = match.group(1).strip()
            if candidate and len(candidate) <= 12:
                return candidate

    return fallback_domain


def load_document_table_map(path: Path) -> dict[str, dict[str, Any]]:
    """加载 document_schema.json，供 explained schema 吸收文档中的表级和字段级解释。"""
    if not path.exists():
        return {}

    document_schema = json.loads(path.read_text(encoding="utf-8"))
    table_map: dict[str, dict[str, Any]] = {}
    for table in document_schema.get("tables", []):
        key = table.get("normalized_table_name")
        if not key:
            continue
        field_map = {}
        for column in table.get("columns", []):
            normalized_field_name = column.get("normalized_name")
            if not normalized_field_name:
                continue
            field_map[normalized_field_name] = {
                "name": column.get("name", ""),
                "comment": clean_text(column.get("comment", "")),
                "type": clean_text(column.get("type", "")),
            }
        table_map[key] = {
            "table_title": clean_doc_label(table.get("table_title", "")),
            "section": clean_doc_label(table.get("section", "")),
            "fields": field_map,
        }
    return table_map


def resolve_table_explanation(
    table_name: str,
    document_table: dict[str, str] | None,
) -> tuple[str, str, dict[str, str]]:
    """按“手工规则 > 文档解释 > 通用兜底”的优先级确定表说明。"""
    normalized_name = normalize_name(table_name)

    if normalized_name in TABLE_DESCRIPTIONS:
        business_domain, description = TABLE_DESCRIPTIONS[normalized_name]
        return business_domain, description, {"domain": "manual", "description": "manual"}

    fallback_domain, fallback_description = table_info(table_name)
    source_flags = {"domain": "fallback", "description": "fallback"}

    if not document_table:
        return fallback_domain, fallback_description, source_flags

    document_title = document_table.get("table_title", "")
    document_section = document_table.get("section", "")

    business_domain = infer_domain_from_doc(document_title, document_section, fallback_domain)
    description = document_title or fallback_description

    if business_domain != fallback_domain:
        source_flags["domain"] = "document_schema"
    if document_title:
        source_flags["description"] = "document_schema"

    return business_domain, description, source_flags


def infer_field(column: dict[str, Any], document_field: dict[str, str] | None = None) -> dict[str, Any]:
    """根据字段名、注释和规则生成字段业务含义、别名和枚举提示。"""
    name = column["name"]
    normalized = normalize_name(name)
    existing_comment = column.get("comment") or ""
    comment_source = "database_schema" if existing_comment else ""
    if not existing_comment and document_field:
        existing_comment = document_field.get("comment", "")
        if existing_comment:
            comment_source = "document_schema"

    meaning, aliases = FIELD_MEANINGS.get(normalized, (existing_comment or name, []))
    if existing_comment and existing_comment != meaning:
        meaning = existing_comment

    field = {
        "name": name,
        "type": column.get("type", ""),
        "nullable": column.get("nullable", True),
        "primary_key": column.get("primary_key", False),
        "comment": existing_comment,
        "comment_source": comment_source or None,
        "business_meaning": meaning,
        "aliases": aliases,
    }

    value_hints = BOOLEAN_INT_FIELDS.get(normalized)
    if value_hints:
        field["value_hints"] = value_hints

    if "time" in normalized or normalized.endswith("rq") or normalized.endswith("sj") or "date" in normalized:
        field["usage_hint"] = "可作为时间筛选、排序或趋势统计字段，使用前注意真实数据格式。"
    elif normalized in {"gqpbh", "gqp_no", "xmbh"}:
        field["usage_hint"] = "高切坡编号关联字段，可用于跨表 JOIN 或精确查询。"
    elif normalized in {"ssss", "ssqx", "ssjd"}:
        field["usage_hint"] = "行政区划字段，常用于按地区筛选或分组统计。"
    elif value_hints:
        field["usage_hint"] = "枚举/标志字段，生成 SQL 时优先使用数字值，不要使用中文字符串比较。"

    return field


def infer_table_hints(table_name: str, fields: list[dict[str, Any]]) -> list[str]:
    """根据字段组合生成表级查询提示，帮助 Agent 形成正确 SQL 条件。"""
    field_names = {normalize_name(field["name"]) for field in fields}
    hints = []

    if "delete_flag" in field_names:
        hints.append("默认查询有效数据时可加 delete_flag = 1；如需历史或删除数据，用户应明确说明。")
    if {"ssss", "ssqx"} & field_names:
        hints.append("按地区统计时优先使用 ssss（所属省市）和 ssqx（所属区县）。")
    if {"gqpbh", "gqp_no", "xmbh"} & field_names:
        hints.append("高切坡编号常用于与 geo_gqp_jbxx.gqpbh 关联。")
    if "iscrack" in field_names:
        hints.append("查询裂缝时使用 isCrack = 1。")
    if "sfyls" in field_names:
        hints.append("查询落石时使用 sfyls = 1。")
    if "createdon" in field_names:
        hints.append("查询最近监测记录时按 createdOn DESC 排序。")
    if "create_time" in field_names:
        hints.append("查询最近创建或上传记录时按 create_time DESC 排序。")
    if "review_time" in field_names:
        hints.append("查询复核记录时可按 review_time 排序或筛选。")
    if table_name.lower().startswith("t_user") or table_name.lower() in {"t_role", "t_role_menu", "t_menus"}:
        hints.append("该表包含系统管理信息，普通高切坡业务查询默认不应使用。")
    return hints


def build_embedding_text(table: dict[str, Any]) -> str:
    """把一张表的解释压成文本块，后续可直接写入向量数据库。"""
    field_parts = []
    for field in table["fields"]:
        aliases = "、".join(field.get("aliases", []))
        value_hints = field.get("value_hints", {})
        value_text = "；".join(f"{k}={v}" for k, v in value_hints.items())
        field_parts.append(
            f"{field['name']} {field['type']} {field['business_meaning']} {aliases} {value_text}".strip()
        )

    return "\n".join(
        [
            f"表名：{table['table_name']}",
            f"业务域：{table['business_domain']}",
            f"表说明：{table['description']}",
            f"别名：{'、'.join(table['aliases'])}",
            "字段：",
            "\n".join(field_parts),
            "查询提示：",
            "\n".join(table["query_hints"]),
        ]
    )


def generate_explained_schema(
    database_schema: dict[str, Any],
    document_table_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """为真实库中的每张表生成业务解释结构。"""
    document_table_map = document_table_map or {}
    tables = []
    for source_table in database_schema["tables"]:
        table_name = source_table["table_name"]
        document_table = document_table_map.get(source_table["normalized_table_name"])
        business_domain, description, explanation_source = resolve_table_explanation(
            table_name,
            document_table,
        )
        document_fields = document_table.get("fields", {}) if document_table else {}
        fields = [
            infer_field(
                column,
                document_fields.get(column.get("normalized_name", "")),
            )
            for column in source_table["columns"]
        ]
        explained = {
            "table_name": table_name,
            "normalized_table_name": source_table["normalized_table_name"],
            "business_domain": business_domain,
            "description": description,
            "aliases": TABLE_ALIAS_RULES.get(normalize_name(table_name), []),
            "join_keys": JOIN_KEYS.get(normalize_name(table_name), []),
            "fields": fields,
            "query_hints": infer_table_hints(table_name, fields),
            "source": {
                "schema_source": "database_schema.json",
                "document_schema_source": "document_schema.json" if document_table_map else None,
                "column_count": len(fields),
                "generated_by": "generate_explained_schema.py",
                "business_domain_source": explanation_source["domain"],
                "description_source": explanation_source["description"],
            },
        }
        explained["embedding_text"] = build_embedding_text(explained)
        tables.append(explained)

    return {
        "source": "database_schema.json",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "table_count": len(tables),
        "tables": tables,
    }


def write_json(path: Path, data: Any) -> None:
    """写出格式化 JSON，方便人工检查和 git diff。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, tables: list[dict[str, Any]]) -> None:
    """写出 JSONL chunk；默认一个表一个 chunk。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for table in tables:
            chunk = {
                "id": table["table_name"],
                "table_name": table["table_name"],
                "business_domain": table["business_domain"],
                "text": table["embedding_text"],
                "metadata": {
                    "table_name": table["table_name"],
                    "business_domain": table["business_domain"],
                    "join_keys": table["join_keys"],
                    "aliases": table["aliases"],
                },
                "schema": {
                    key: value
                    for key, value in table.items()
                    if key != "embedding_text"
                },
            }
            file.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def main() -> None:
    """命令行入口：读取 database_schema.json，生成 explained schema 和 chunks。"""
    parser = argparse.ArgumentParser(description="Generate first-pass business explanations for exported DB schema.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--document-schema", type=Path, default=DEFAULT_DOCUMENT_SCHEMA)
    args = parser.parse_args()

    database_schema = json.loads(args.input.read_text(encoding="utf-8"))
    document_table_map = load_document_table_map(args.document_schema)
    explained = generate_explained_schema(database_schema, document_table_map)
    write_json(args.output, explained)
    write_jsonl(args.chunks, explained["tables"])

    print(
        json.dumps(
            {
                "table_count": explained["table_count"],
                "output": str(args.output),
                "chunks": str(args.chunks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

"""Deterministic SQL templates for high-frequency high-cut-slope questions."""

import json
import re
from typing import Any

from app.report_charts import generate_displacement_chart


ABNORMAL_TYPE_FIELDS = [
    ("isCrack", "裂缝"),
    ("surfaceRockfall", "落石"),
    ("slopeFailure", "坡面异常破坏"),
    ("wallCracking", "道路或挡墙开裂"),
    ("facilities", "监测设施异常"),
    ("disorderlyPush", "坡周乱搭乱堆"),
    ("ditchBlocking", "排水沟堵塞"),
    ("holeBlocking", "排水口堵塞"),
    ("crestIrrigation", "坡顶灌水"),
]


def get_deterministic_query(question: str) -> dict[str, Any] | None:
    if _is_report_asset_inventory_question(question):
        return {
            "name": "report_asset_inventory",
            "source": "internal_report_inventory",
            "tables": [
                "ai_monthly_report_doc",
                "ai_professional_monitor_monthly_value",
                "ai_report_photo_asset",
                "ai_report_stability_asset",
            ],
            "sql": "",
            "summary": "形成月报内容资产清单，统计月报、专业监测点月度数据、现场照片和稳定性评价沉淀情况。",
        }
    if _is_personnel_info_question(question):
        return {
            "name": "personnel_info",
            "source": "sqlserver",
            "tables": ["tb_system_user", "tb_system_user_ext", "tb_system_user_role", "tb_system_role"],
            "sql": _personnel_info_sql(question),
            "summary": "查询系统人员基础信息，仅返回业务展示字段，屏蔽密码、证件号、IP、重置密钥等敏感字段。",
        }
    if _is_county_monitoring_scale_question(question):
        return {
            "name": "county_monitoring_scale",
            "source": "mixed",
            "tables": ["geo_gqp_jbxx", "ai_professional_monitor_monthly_value", "tb_hcslope", "tb_hcs_monitoring"],
            "sql": "",
            "summary": "按区县汇总高切坡总数、群测群防监测覆盖数量、群测群防记录数、专业监测高切坡数量和专业监测点数量。",
        }
    if _is_recent_large_displacement_question(question):
        return {
            "name": "recent_large_displacement",
            "source": "dm",
            "tables": ["ai_professional_monitor_monthly_value", "ai_report_monitor_slope_map", "geo_gqp_jbxx"],
            "sql": "SELECT '1' AS displacement_dashboard_marker",
            "summary": "生成近期专业监测情况，统计月报中的专业监测坡并筛选年度位移变化相对较大的对象。",
        }
    if _is_report_displacement_chart_question(question):
        county = _extract_county(question)
        return {
            "name": "report_displacement_charts",
            "source": "dm",
            "tables": ["ai_monthly_report_doc", "ai_monthly_report_chunk"],
            "sql": _report_displacement_chart_sql(county),
            "summary": "按区县优先采用最新一期月报提取专业监测点结论，历史月报仅作为趋势补充。",
        }
    if _is_qmqf_review_list_question(question):
        return {
            "name": "qmqf_review_list",
            "source": "sqlserver",
            "tables": ["tb_hcs_monitoring", "tb_hcslope", "tb_area_china"],
            "sql": _qmqf_review_list_sql(),
            "summary": "生成近期群测群防异常复核清单，按区县、高切坡、异常类型、照片情况和复核建议组织明细。",
        }
    if _is_recent_monitoring_abnormal_question(question):
        return {
            "name": "recent_monitoring_abnormal",
            "source": "sqlserver",
            "tables": ["tb_hcs_monitoring", "tb_hcslope", "tb_area_china"],
            "sql": _recent_monitoring_abnormal_sql(),
            "summary": "按群测群防监测记录表查询最近存在异常项的监测记录。",
        }
    if _is_focus_slope_attention_question(question):
        return {
            "name": "focus_slope_attention",
            "source": "sqlserver",
            "tables": ["tb_hcs_monitoring", "tb_hcslope", "tb_area_china"],
            "sql": _recent_monitoring_abnormal_sql(),
            "summary": "按现场异常和专业监测变化筛选近期需要关注的高切坡对象。",
        }
    if _is_recent_risk_county_question(question):
        return {
            "name": "recent_risk_county",
            "source": "dm",
            "tables": ["ai_professional_monitor_monthly_value"],
            "sql": _recent_risk_county_sql(),
            "summary": "按2025年月报专业监测位移变化量研判近期可能出现风险的区县。",
        }
    if _is_county_overview_question(question):
        county = _extract_county(question)
        return {
            "name": "county_overview",
            "source": "dm",
            "tables": ["geo_gqp_jbxx", "ai_professional_monitor_monthly_value"],
            "sql": _county_overview_sql(county),
            "summary": f"生成{county or '指定区县'}高切坡近期情况文字概述。",
        }
    if _is_recent_slope_brief_question(question):
        return {
            "name": "recent_slope_brief",
            "source": "dm",
            "tables": ["geo_gqp_jbxx", "geo_wyjcsjjl"],
            "sql": "SELECT '1' AS recent_slope_brief_marker",
            "summary": "生成近期高切坡业务情况简报，综合群测群防异常、专业监测位移变化和处置建议。",
        }
    if _is_abnormal_type_question(question):
        return {
            "name": "abnormal_type",
            "source": "sqlserver",
            "tables": ["tb_hcs_monitoring", "tb_hcslope", "tb_area_china"],
            "sql": _abnormal_type_sql(),
            "summary": "按群测群防监测记录中的具体异常项识别异常类型。",
        }
    if _is_county_abnormal_compare_question(question):
        return {
            "name": "county_abnormal_compare",
            "source": "dm",
            "tables": ["geo_gqp_jbxx"],
            "sql": _county_abnormal_compare_sql(),
            "summary": "按达梦基础资料表统计各区县异常高切坡数量，优先使用告警标签，告警标签为空时参考基础状态较差/不良。",
        }
    return None


def enrich_rows(query_name: str, columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    if query_name == "recent_slope_brief":
        return ["recent_slope_brief_marker"], [{"recent_slope_brief_marker": "1"}]
    if query_name == "report_displacement_charts":
        return _enrich_report_displacement_rows(columns, rows)
    if query_name == "recent_large_displacement":
        return _enrich_recent_large_displacement_rows(columns, rows)
    if query_name == "recent_monitoring_abnormal":
        return _enrich_qmqf_dashboard_rows(columns, rows)
    if query_name == "focus_slope_attention":
        return _enrich_qmqf_dashboard_rows(columns, rows)
    if query_name not in {"abnormal_type", "recent_monitoring_abnormal"}:
        return columns, rows
    return _enrich_abnormal_type_rows(columns, rows)


def _extract_county(question: str) -> str:
    aliases = {
        "巴东县": ("巴东县", "巴东"),
        "兴山县": ("兴山县", "兴山"),
        "夷陵区": ("夷陵区", "夷陵"),
        "秭归县": ("秭归县", "秭归"),
    }
    compact = "".join(question.split())
    for county, values in aliases.items():
        if any(value in compact for value in values):
            return county
    return ""


def _is_recent_slope_brief_question(question: str) -> bool:
    compact = "".join(question.split())
    if "高切坡" in compact and any(keyword in compact for keyword in ("整体风险", "总体风险", "综合风险")):
        return True
    return (
        ("近期" in compact or "最近" in compact or _extract_county(compact))
        and "高切坡" in compact
        and ("简介" in compact or "简报" in compact or "情况" in compact or "概况" in compact)
    )


def _is_county_overview_question(question: str) -> bool:
    compact = "".join(question.split())
    return (
        bool(_extract_county(compact))
        and "高切坡" in compact
        and any(keyword in compact for keyword in ("情况", "概况", "现状", "怎么样", "简介"))
        and "群测群防" not in compact
        and "专业监测" not in compact
    )


def _is_recent_risk_county_question(question: str) -> bool:
    compact = "".join(question.split())
    county = _extract_county(compact)
    pure_count_query = (
        "异常" in compact
        and any(keyword in compact for keyword in ("数量", "总数", "多少", "统计", "汇总"))
        and not any(keyword in compact for keyword in ("风险", "风险等级", "危险", "不稳定", "预警", "可能出现", "需要关注"))
    )
    if pure_count_query:
        return False
    has_recent = any(keyword in compact for keyword in ("近期", "最近", "当前", "现在", "年度"))
    has_region = any(keyword in compact for keyword in ("哪个区县", "哪些区县", "区县", "地方", "区域", "在哪", "集中", "排序"))
    has_risk = any(keyword in compact for keyword in ("风险", "风险等级", "等级较高", "较高", "危险", "隐患", "异常", "不稳定", "重点关注", "需要关注", "可能出现", "变化最大", "变化大", "较大", "突出", "预警"))
    has_slope = "高切坡" in compact or "坡" in compact
    if has_recent and has_region and any(keyword in compact for keyword in ("重点关注", "需要关注", "风险", "隐患", "异常")):
        return True
    if has_region and has_risk and (has_slope or "专业监测" in compact or "位移" in compact):
        return True
    if has_recent and has_risk and has_slope:
        return True
    return bool(county) and has_risk and has_slope


def _is_focus_slope_attention_question(question: str) -> bool:
    compact = "".join(question.split())
    has_slope = "高切坡" in compact or "边坡" in compact or "坡" in compact
    has_focus = any(keyword in compact for keyword in ("值得重点关注", "需要重点关注", "重点关注", "需要关注", "重点跟踪", "重点复核"))
    has_county_risk = any(keyword in compact for keyword in ("哪个区县", "哪些区县", "区县风险", "风险等级更高", "风险等级较高"))
    return has_slope and has_focus and not has_county_risk


def _is_report_asset_inventory_question(question: str) -> bool:
    compact = "".join(question.split())
    return (
        "月报" in compact
        and any(keyword in compact for keyword in ("资产清单", "内容清单", "内容资产", "梳理", "统计"))
        and any(keyword in compact for keyword in ("照片", "曲线", "表格", "稳定性", "专业监测", "监测点", "清单"))
    )


def _is_county_monitoring_scale_question(question: str) -> bool:
    compact = "".join(question.split())
    if (
        "异常" in compact
        and "群测群防" in compact
        and not any(keyword in compact for keyword in ("监测数量", "总数", "规模", "柱状图", "柱形图", "统计图"))
    ):
        return False
    has_county_scope = any(keyword in compact for keyword in ("各区县", "区县", "分区县", "按区县")) or bool(_extract_county(compact))
    has_count_intent = any(keyword in compact for keyword in ("数量", "总数", "多少", "统计", "汇总", "规模"))
    has_chart_intent = any(keyword in compact for keyword in ("柱状图", "柱形图", "统计图", "图表"))
    has_monitor_target = (
        "群测群防" in compact
        or "专业监测" in compact
        or "监测点" in compact
        or "监测数量" in compact
        or "监测规模" in compact
        or ("高切坡" in compact and "监测" in compact)
    )
    return (has_county_scope or has_chart_intent) and has_count_intent and has_monitor_target


def _is_personnel_info_question(question: str) -> bool:
    compact = "".join(question.split())
    if any(keyword in compact.lower() for keyword in ("密码", "口令", "token", "密钥", "reset", "权限", "身份证", "idnumber", "ip")):
        return False
    has_person_target = any(keyword in compact for keyword in ("人员", "用户", "联系人", "监测员", "审核员", "管理员", "账号信息"))
    has_query_intent = any(keyword in compact for keyword in ("查询", "查看", "统计", "列出", "名单", "信息", "电话", "联系方式", "通讯录", "是谁", "有哪些", "多少"))
    return has_person_target and has_query_intent


def _personnel_info_sql(question: str) -> str:
    compact = "".join(question.split())
    role_filter = ""
    if "监测员" in compact:
        role_filter = "AND r.role_name LIKE '%监测员%'"
    elif "审核员" in compact:
        role_filter = "AND r.role_name LIKE '%审核员%'"
    elif "管理员" in compact:
        role_filter = "AND r.role_name LIKE '%管理员%'"
    keyword = _extract_person_keyword(question)
    keyword_filter = ""
    if keyword:
        escaped = keyword.replace("'", "''")
        keyword_filter = f"""
  AND (
    u.user_name LIKE '%{escaped}%'
    OR e.name LIKE '%{escaped}%'
    OR e.mobile LIKE '%{escaped}%'
    OR e.department LIKE '%{escaped}%'
    OR e.duty LIKE '%{escaped}%'
    OR r.role_name LIKE '%{escaped}%'
  )
"""
    return f"""
SELECT TOP 50
  COALESCE(NULLIF(e.name, ''), u.user_name, '') AS 人员姓名,
  u.user_name AS 登录账号,
  COALESCE(r.role_name, '') AS 角色,
  COALESCE(county.areaname, city.areaname, '') AS 所属区县,
  COALESCE(e.department, '') AS 部门,
  COALESCE(e.duty, '') AS 职务,
  COALESCE(e.mobile, '') AS 手机号,
  COALESCE(e.telephone, '') AS 固定电话,
  COALESCE(e.email, '') AS 电子邮箱
FROM tb_system_user u
LEFT JOIN tb_system_user_ext e ON u.ext_id = e.id
LEFT JOIN tb_system_user_role ur ON ur.user_id = u.user_id
LEFT JOIN tb_system_role r ON r.role_id = ur.role_id
LEFT JOIN tb_area_china county ON e.county_id = county.areano
LEFT JOIN tb_area_china city ON e.city_id = city.areano
WHERE 1 = 1
  {role_filter}
  {keyword_filter}
ORDER BY u.is_disabled ASC, e.name ASC, u.user_name ASC
""".strip()


def _extract_person_keyword(question: str) -> str:
    compact = "".join(question.split())
    ignored = {
        "查询", "查看", "统计", "列出", "人员", "用户", "联系人", "信息", "名单", "电话", "联系方式",
        "通讯录", "监测员", "审核员", "管理员", "账号信息", "有哪些", "多少", "是谁",
    }
    for keyword in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9_]{2,}", compact):
        if keyword not in ignored and not any(token in keyword for token in ignored):
            return keyword[:30]
    return ""


def _recent_risk_county_sql() -> str:
    return """
WITH point_sum AS (
  SELECT
    county,
    gqpbh,
    MAX(gqpmc) AS gqpmc,
    monitor_point,
    COUNT(DISTINCT report_month) AS month_count,
    SUM(COALESCE(current_x, 0)) AS x_change,
    SUM(COALESCE(current_y, 0)) AS y_change,
    SUM(COALESCE(current_h, 0)) AS h_change,
    MAX(GREATEST(
      ABS(COALESCE(current_x, 0)),
      ABS(COALESCE(current_y, 0)),
      ABS(COALESCE(current_h, 0))
    )) AS max_monthly_change
  FROM ai_professional_monitor_monthly_value
  WHERE report_year = 2025
    AND monitor_point IS NOT NULL
    AND monitor_point <> ''
    AND monitor_point NOT LIKE 'KZ%'
  GROUP BY county, gqpbh, monitor_point
),
slope_rank AS (
  SELECT
    county,
    gqpbh,
    MAX(gqpmc) AS gqpmc,
    COUNT(*) AS monitor_point_count,
    MAX(month_count) AS max_month_count,
    MAX(GREATEST(ABS(x_change), ABS(y_change), ABS(h_change))) AS max_displacement_mm,
    MAX(max_monthly_change) AS max_monthly_change_mm
  FROM point_sum
  GROUP BY county, gqpbh
),
county_rank AS (
  SELECT
    county,
    COUNT(*) AS professional_slope_count,
    SUM(CASE WHEN max_displacement_mm >= 10 THEN 1 ELSE 0 END) AS attention_slope_count,
    SUM(CASE WHEN max_displacement_mm >= 20 THEN 1 ELSE 0 END) AS obvious_deformation_count,
    MAX(max_displacement_mm) AS max_displacement_mm,
    MAX(max_monthly_change_mm) AS max_monthly_change_mm,
    MAX(max_month_count) AS max_month_count
  FROM slope_rank
  GROUP BY county
),
top_slope AS (
  SELECT *
  FROM (
    SELECT
      county,
      gqpmc,
      gqpbh,
      max_displacement_mm,
      max_monthly_change_mm,
      ROW_NUMBER() OVER (PARTITION BY county ORDER BY max_displacement_mm DESC, gqpbh ASC) AS rn
    FROM slope_rank
  )
  WHERE rn = 1
)
SELECT
  c.county AS 区县,
  c.professional_slope_count AS 专业监测高切坡数量,
  c.attention_slope_count AS 需关注高切坡数量,
  c.obvious_deformation_count AS 明显变形数量,
  ROUND(c.max_displacement_mm, 1) AS 最大年度位移变化量_mm,
  ROUND(c.max_monthly_change_mm, 1) AS 最大单月位移变化量_mm,
  t.gqpmc AS 代表性高切坡,
  t.gqpbh AS 代表性高切坡编号,
  ROUND(t.max_displacement_mm, 1) AS 代表性高切坡位移变化量_mm,
  ROUND(t.max_monthly_change_mm, 1) AS 代表性高切坡最大单月位移_mm,
  CASE
    WHEN c.max_monthly_change_mm >= 10 OR c.obvious_deformation_count > 0 THEN '专业监测复核'
    WHEN c.attention_slope_count >= 10 THEN '专业监测关注'
    WHEN c.attention_slope_count > 0 THEN '一般关注'
    ELSE '常规跟踪'
  END AS 研判等级
FROM county_rank c
LEFT JOIN top_slope t ON t.county = c.county
ORDER BY c.attention_slope_count DESC, c.max_displacement_mm DESC, c.county ASC
""".strip()


def _is_report_displacement_chart_question(question: str) -> bool:
    compact = "".join(question.split())
    has_cn_report_signal = any(keyword in compact for keyword in ("月报", "年报", "报告", "专业监测", "监测点", "点位"))
    has_cn_displacement_signal = any(keyword in compact for keyword in ("位移", "变化量", "变形", "累计", "本月最大", "较大"))
    has_cn_chart_signal = any(keyword in compact for keyword in ("折线图", "曲线", "图", "列出点"))
    has_cn_conclusion_signal = any(keyword in compact for keyword in ("结论", "评价", "情况", "研判", "稳定性"))
    if has_cn_report_signal and has_cn_displacement_signal and has_cn_conclusion_signal:
        return True
    if has_cn_report_signal and has_cn_displacement_signal and has_cn_chart_signal:
        return True
    has_report_signal = any(keyword in compact for keyword in ("月报", "年报", "报告", "专业监测", "监测点"))
    has_displacement_signal = any(keyword in compact for keyword in ("位移", "变化量", "变形", "累计", "本月最大"))
    has_chart_signal = any(keyword in compact for keyword in ("折线图", "曲线", "图", "列出点"))
    has_conclusion_signal = any(keyword in compact for keyword in ("结论", "评价", "情况", "研判", "稳定性"))
    return has_report_signal and has_displacement_signal and (has_chart_signal or has_conclusion_signal)


def _is_recent_large_displacement_question(question: str) -> bool:
    compact = "".join(question.split())
    if "专业监测" in compact and any(keyword in compact for keyword in ("情况", "概况", "近期", "最近")):
        return True
    if (
        ("高切坡" in compact or "坡" in compact)
        and ("位移" in compact or "变形" in compact)
        and any(keyword in compact for keyword in ("较大", "变化量", "变化较大", "最大", "排行", "排名", "哪些"))
        and not any(keyword in compact for keyword in ("区县", "哪个区县", "风险等级"))
    ):
        return True
    return (
        ("近期" in compact or "最近" in compact or "年度" in compact or "专业监测" in compact)
        and ("位移" in compact or "变形" in compact)
        and ("变化量" in compact or "变化较大" in compact or "较大" in compact or "变化" in compact)
        and ("专业监测" in compact or "监测点" in compact)
        and ("高切坡" in compact or "坡" in compact or bool(_extract_county(compact)))
    )


def _county_overview_sql(county: str) -> str:
    safe_county = (county or "").replace("'", "''")
    return f"""
WITH base AS (
  SELECT *
  FROM geo_gqp_jbxx
  WHERE ssqx = '{safe_county}'
),
professional AS (
  SELECT COUNT(DISTINCT gqpbh) AS professional_slope_count,
         COUNT(DISTINCT gqpbh || monitor_point) AS professional_point_count
  FROM ai_professional_monitor_monthly_value
  WHERE county = '{safe_county}'
    AND report_year = 2025
)
SELECT
  '{safe_county}' AS 区县,
  COUNT(*) AS 高切坡数量,
  COALESCE(MAX(professional.professional_slope_count), 0) AS 专业监测高切坡数量,
  COALESCE(MAX(professional.professional_point_count), 0) AS 专业监测点数量,
  SUM(CASE WHEN COALESCE(TO_CHAR(sfzyjcyc), '') IN ('1', '是', 'true', 'True', 'TRUE') THEN 1 ELSE 0 END) AS 专业监测异常标记数量,
  SUM(CASE WHEN COALESCE(TO_CHAR(sfsssjyc), '') IN ('1', '是', 'true', 'True', 'TRUE') THEN 1 ELSE 0 END) AS 群测群防异常标记数量,
  SUM(CASE WHEN COALESCE(TO_CHAR(qcqf_ztqk), '') <> '' THEN 1 ELSE 0 END) AS 有群测群防状态记录数量
FROM base
CROSS JOIN professional
""".strip()


def _recent_large_displacement_sql() -> str:
    return """
recent_rows AS (
  SELECT r.*
  FROM geo_wyjcsjjl r
  WHERE r.jcsj >= TO_DATE('2025-01-01', 'YYYY-MM-DD')
    AND r.jcsj <= TO_DATE('2025-12-31', 'YYYY-MM-DD')
),
latest_by_point AS (
  SELECT gqpbh, jcdbh, MAX(jcsj) AS latest_date, COUNT(*) AS record_count
  FROM recent_rows
  GROUP BY gqpbh, jcdbh
),
latest_value AS (
  SELECT
    l.gqpbh,
    l.jcdbh,
    l.latest_date,
    l.record_count,
    r.bqxfxwy_mm,
    r.bqyfxwy_mm,
    r.bqhfxwy_mm
  FROM latest_by_point l
  JOIN geo_wyjcsjjl r
    ON r.gqpbh = l.gqpbh
   AND r.jcdbh = l.jcdbh
   AND r.jcsj = l.latest_date
),
point_rank AS (
  SELECT
    lv.gqpbh,
    lv.jcdbh,
    lv.latest_date,
    lv.record_count,
    lv.bqxfxwy_mm,
    lv.bqyfxwy_mm,
    lv.bqhfxwy_mm,
    GREATEST(
      ABS(COALESCE(lv.bqxfxwy_mm, 0)),
      ABS(COALESCE(lv.bqyfxwy_mm, 0)),
      ABS(COALESCE(lv.bqhfxwy_mm, 0))
    ) AS recent_change_mm
  FROM latest_value lv
  WHERE GREATEST(
      ABS(COALESCE(lv.bqxfxwy_mm, 0)),
      ABS(COALESCE(lv.bqyfxwy_mm, 0)),
      ABS(COALESCE(lv.bqhfxwy_mm, 0))
    ) >= 20
),
slope_rank AS (
  SELECT
    gqpbh,
    COUNT(DISTINCT jcdbh) AS point_count,
    MAX(recent_change_mm) AS max_recent_change_mm
  FROM point_rank
  GROUP BY gqpbh
),
top_slope AS (
  SELECT *
  FROM slope_rank
  ORDER BY max_recent_change_mm DESC, point_count DESC
  FETCH FIRST 8 ROWS ONLY
)
SELECT
  p.gqpbh,
  COALESCE(j.gqpmc, p.gqpbh) AS gqpmc,
  COALESCE(j.ssqx, '') AS ssqx,
  t.point_count,
  t.max_recent_change_mm,
  p.jcdbh,
  p.record_count,
  p.bqxfxwy_mm,
  p.bqyfxwy_mm,
  p.bqhfxwy_mm,
  p.recent_change_mm,
  ROUND(p.recent_change_mm / 12, 2) AS avg_monthly_rate,
  CASE
    WHEN t.max_recent_change_mm >= 20 THEN '稳定性较差'
    WHEN t.max_recent_change_mm >= 8 THEN '稳定性一般'
    ELSE '总体较稳定'
  END AS stability_level,
  CASE
    WHEN t.max_recent_change_mm >= 20 THEN '2025年度累计位移已达到20mm告警阈值，建议开展现场复核并跟踪后续变化。'
    WHEN t.max_recent_change_mm >= 8 THEN '建议保持月度跟踪，若连续2-3期增大则提高巡查频次。'
    ELSE '建议按常规频率监测，保留趋势跟踪。'
  END AS stability_advice,
  '/report-assets/displacement_dashboard/' || p.gqpbh || '.html' AS displacement_chart_url
FROM top_slope t
JOIN point_rank p ON p.gqpbh = t.gqpbh
LEFT JOIN geo_gqp_jbxx j ON j.gqpbh = p.gqpbh
ORDER BY t.max_recent_change_mm DESC, p.recent_change_mm DESC, p.gqpbh ASC, p.jcdbh ASC
""".strip()


def _is_abnormal_type_question(question: str) -> bool:
    compact = "".join(question.split())
    if (
        "高切坡" in compact
        and "照片" in compact
        and any(keyword in compact for keyword in ("典型破坏", "破坏状态", "现状照片"))
    ):
        return True
    return (
        "异常" in compact
        and (
            "异常类型" in compact
            or "哪一种异常" in compact
            or "哪类异常" in compact
            or "属于哪一种" in compact
            or "裂缝" in compact
            or "落石" in compact
            or "典型破坏" in compact
            or "破坏状态" in compact
            or "现状照片" in compact
            or "现场照片" in compact
            or "照片" in compact
        )
    )


def _is_county_abnormal_compare_question(question: str) -> bool:
    compact = "".join(question.split())
    has_county_scope = "区县" in compact
    has_abnormal_target = "高切坡" in compact and "异常" in compact
    has_compare_intent = any(keyword in compact for keyword in ("对比", "比较", "分布", "排行", "排名"))
    has_count_intent = "数量" in compact or "多少" in compact or "统计" in compact
    return has_county_scope and has_abnormal_target and (has_compare_intent or has_count_intent)


def _is_recent_monitoring_abnormal_question(question: str) -> bool:
    compact = "".join(question.split())
    if "群测群防" in compact and any(keyword in compact for keyword in ("情况", "记录", "异常", "风险", "关注", "排序")):
        return True
    if any(keyword in compact for keyword in ("现场", "巡查", "巡检", "裂缝", "落石", "现场照片", "照片异常")) and any(
        keyword in compact for keyword in ("近期", "最近", "情况", "异常", "风险", "区县", "集中", "问题多")
    ):
        return True
    return (
        ("最近" in compact or "近期" in compact)
        and ("异常" in compact or "情况" in compact)
        and ("群测群防" in compact or "监测记录" in compact or "监测" in compact)
    )


def _is_qmqf_review_list_question(question: str) -> bool:
    compact = "".join(question.split())
    has_qmqf = "群测群防" in compact or "现场异常" in compact
    has_detail = any(keyword in compact for keyword in ("复核清单", "明细清单", "异常清单", "记录明细", "展开明细", "处置建议", "照片标注", "明细", "清单", "列表", "列出", "详细"))
    return has_qmqf and has_detail


def _report_displacement_chart_sql(county: str = "") -> str:
    county_filter = f"  AND d.county = '{county}'\n" if county else ""
    return f"""
WITH latest_doc AS (
  SELECT
    d.*,
    ROW_NUMBER() OVER (
      PARTITION BY d.county
      ORDER BY
        d.report_year DESC NULLS LAST,
        d.report_month DESC NULLS LAST,
        CASE
          WHEN d.report_type LIKE '%专业监测%' THEN 0
          WHEN d.report_type LIKE '%工作月报%' THEN 1
          WHEN d.report_type LIKE '%简报%' THEN 2
          ELSE 3
        END,
        d.file_name ASC
    ) AS rn
  FROM ai_monthly_report_doc d
  WHERE d.parse_status = 'ok'
    AND d.report_year IS NOT NULL
    AND d.report_month IS NOT NULL
    AND d.county IS NOT NULL
    AND d.county <> ''
{county_filter}
),
latest_chunks AS (
  SELECT
    d.county,
    d.report_year,
    d.report_month,
    d.report_type,
    d.file_name,
    d.title,
    d.key_points,
    d.mentioned_slopes,
    c.chunk_index,
    c.content,
    ROW_NUMBER() OVER (
      PARTITION BY d.file_hash
      ORDER BY
        CASE
          WHEN c.content LIKE '%位移%' OR c.content LIKE '%变形%' OR c.content LIKE '%稳定%' OR c.content LIKE '%监测点%' THEN 0
          ELSE 1
        END,
        c.chunk_index ASC
    ) AS chunk_rank
  FROM latest_doc d
  LEFT JOIN ai_monthly_report_chunk c ON c.file_hash = d.file_hash
  WHERE d.rn = 1
)
SELECT
  county AS 区县,
  report_year AS 年份,
  report_month AS 月份,
  report_type AS 报告类型,
  file_name AS 主依据月报,
  chunk_index AS 片段序号,
  SUBSTR(content, 1, 1200) AS 最新月报结论片段,
  SUBSTR(key_points, 1, 1200) AS 最新月报要点,
  SUBSTR(mentioned_slopes, 1, 1200) AS 涉及高切坡或监测点,
  '主依据为该区县最新一期月报；更早月报仅用于趋势对比和补充说明。' AS 采用口径
FROM latest_chunks
WHERE chunk_rank <= 3
ORDER BY county ASC, chunk_rank ASC
""".strip()


def _abnormal_type_sql() -> str:
    abnormal_conditions = _effective_abnormal_sql_condition()
    return f"""
WITH latest_photo AS (
  SELECT
    hcs_id,
    photoNo1,
    photoNo2,
    photoNo3,
    crackImageUri,
    wallCrackingImageUri
  FROM (
    SELECT
      hcs_id,
      photoNo1,
      photoNo2,
      photoNo3,
      crackImageUri,
      wallCrackingImageUri,
      ROW_NUMBER() OVER (
        PARTITION BY hcs_id
        ORDER BY COALESCE(photoOn, createdOn, updatedOn) DESC, id DESC
      ) AS rn
    FROM tb_hcs_monitoring
    WHERE
      COALESCE(photoOn, createdOn, updatedOn) >= '2025-06-01'
      AND (
      COALESCE(photoNo1, '') <> ''
      OR COALESCE(photoNo2, '') <> ''
      OR COALESCE(photoNo3, '') <> ''
      OR COALESCE(crackImageUri, '') <> ''
      OR COALESCE(wallCrackingImageUri, '') <> ''
      )
  ) p
  WHERE rn = 1
)
SELECT
  s.code AS gqpbh,
  s.name AS gqpmc,
  COALESCE(county.areaname, city.areaname, s.location) AS ssqx,
  m.isCrack,
  m.width,
  m.surfaceRockfall,
  m.slopeFailure,
  m.wallCracking,
  m.facilities,
  m.disorderlyPush,
  m.ditchBlocking,
  m.holeBlocking,
  m.crestIrrigation,
  m.overallSituation,
  m.hcSlopeStatus,
  m.statusReason,
  m.photoOn,
  COALESCE(
    CASE WHEN COALESCE(m.photoOn, m.createdOn, m.updatedOn) >= '2025-06-01' THEN NULLIF(m.photoNo1, '') ELSE NULL END,
    lp.photoNo1
  ) AS photoNo1,
  COALESCE(
    CASE WHEN COALESCE(m.photoOn, m.createdOn, m.updatedOn) >= '2025-06-01' THEN NULLIF(m.photoNo2, '') ELSE NULL END,
    lp.photoNo2
  ) AS photoNo2,
  COALESCE(
    CASE WHEN COALESCE(m.photoOn, m.createdOn, m.updatedOn) >= '2025-06-01' THEN NULLIF(m.photoNo3, '') ELSE NULL END,
    lp.photoNo3
  ) AS photoNo3,
  COALESCE(
    CASE WHEN COALESCE(m.photoOn, m.createdOn, m.updatedOn) >= '2025-06-01' THEN NULLIF(m.crackImageUri, '') ELSE NULL END,
    lp.crackImageUri
  ) AS crackImageUri,
  COALESCE(
    CASE WHEN COALESCE(m.photoOn, m.createdOn, m.updatedOn) >= '2025-06-01' THEN NULLIF(m.wallCrackingImageUri, '') ELSE NULL END,
    lp.wallCrackingImageUri
  ) AS wallCrackingImageUri,
  m.createdOn
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
LEFT JOIN latest_photo lp ON m.hcs_id = lp.hcs_id
WHERE {abnormal_conditions}
ORDER BY m.createdOn DESC, s.code ASC
""".strip()


def _county_abnormal_compare_sql() -> str:
    return """
SELECT
  ssqx,
  COUNT(*) AS abnormal_slope_count
FROM geo_gqp_jbxx
WHERE delete_flag = 1
  AND ssqx IS NOT NULL
  AND TRIM(ssqx) <> ''
  AND (
    COALESCE(TRIM(CAST(warned AS VARCHAR(20))), '') NOT IN ('', '0', '否', 'false', 'False')
    OR COALESCE(TRIM(CAST(warning_level AS VARCHAR(50))), '') <> ''
    OR gqpzt IN ('较差', '不良')
  )
GROUP BY ssqx
ORDER BY abnormal_slope_count DESC, ssqx ASC
""".strip()


def _recent_monitoring_abnormal_sql() -> str:
    abnormal_conditions = _effective_abnormal_sql_condition()
    return f"""
SELECT TOP 50
  s.code AS gqpbh,
  s.name AS gqpmc,
  COALESCE(county.areaname, city.areaname, s.location) AS ssqx,
  m.isCrack,
  m.width,
  m.surfaceRockfall,
  m.slopeFailure,
  m.wallCracking,
  m.facilities,
  m.disorderlyPush,
  m.ditchBlocking,
  m.holeBlocking,
  m.crestIrrigation,
  m.overallSituation,
  m.hcSlopeStatus,
  m.statusReason,
  m.photoOn,
  m.photoNo1,
  m.photoNo2,
  m.photoNo3,
  m.crackImageUri,
  m.wallCrackingImageUri,
  m.createdOn
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
WHERE {abnormal_conditions}
ORDER BY m.createdOn DESC, m.id DESC
""".strip()


def _qmqf_review_list_sql() -> str:
    abnormal_conditions = _effective_abnormal_sql_condition()
    return f"""
SELECT TOP 30
  COALESCE(county.areaname, city.areaname, s.location) AS 所属区县,
  s.code AS 高切坡编号,
  s.name AS 高切坡名称,
  LTRIM(RTRIM(
    (CASE WHEN m.isCrack = 1 AND NULLIF(LTRIM(RTRIM(CONVERT(varchar(50), m.width))), '') IS NOT NULL THEN '裂缝（' + CONVERT(varchar(50), m.width) + 'mm）;' ELSE '' END) +
    (CASE WHEN m.surfaceRockfall = 1 THEN '落石;' ELSE '' END) +
    (CASE WHEN m.slopeFailure = 1 THEN '坡面异常破坏;' ELSE '' END) +
    (CASE WHEN m.wallCracking = 1 THEN '道路或挡墙开裂;' ELSE '' END) +
    (CASE WHEN m.facilities = 1 THEN '监测设施异常;' ELSE '' END) +
    (CASE WHEN m.disorderlyPush = 1 THEN '坡周乱搭乱堆;' ELSE '' END) +
    (CASE WHEN m.ditchBlocking = 1 THEN '排水沟堵塞;' ELSE '' END) +
    (CASE WHEN m.holeBlocking = 1 THEN '排水口堵塞;' ELSE '' END) +
    (CASE WHEN m.crestIrrigation = 1 THEN '坡顶灌水;' ELSE '' END)
  )) AS 异常内容,
  CASE
    WHEN m.slopeFailure = 1 OR m.wallCracking = 1 OR m.surfaceRockfall = 1 THEN '现场复核'
    WHEN m.isCrack = 1 AND NULLIF(LTRIM(RTRIM(CONVERT(varchar(50), m.width))), '') IS NOT NULL THEN '核实裂缝变化'
    WHEN m.ditchBlocking = 1 OR m.holeBlocking = 1 OR m.crestIrrigation = 1 THEN '排水条件复核'
    ELSE '持续跟踪'
  END AS 复核类型,
  CASE
    WHEN COALESCE(m.photoNo1, m.photoNo2, m.photoNo3, m.crackImageUri, m.wallCrackingImageUri, '') <> '' THEN '有现场照片'
    ELSE '暂无照片'
  END AS 照片情况,
  CONVERT(varchar(16), COALESCE(m.photoOn, m.createdOn), 120) AS 记录时间,
  CASE
    WHEN m.slopeFailure = 1 OR m.wallCracking = 1 OR m.surfaceRockfall = 1 THEN '建议优先核实异常部位、影响范围和是否持续发展。'
    WHEN m.isCrack = 1 THEN '建议复测裂缝宽度、长度及扩展趋势，补充现场照片。'
    WHEN m.ditchBlocking = 1 OR m.holeBlocking = 1 OR m.crestIrrigation = 1 THEN '建议核查排水条件并及时清理疏通。'
    ELSE '建议纳入近期巡查台账，持续跟踪变化。'
  END AS 复核建议
FROM tb_hcs_monitoring m
LEFT JOIN tb_hcslope s ON m.hcs_id = s.id
LEFT JOIN tb_area_china county ON s.county_id = county.areano
LEFT JOIN tb_area_china city ON s.city_id = city.areano
WHERE {abnormal_conditions}
ORDER BY
  CASE
    WHEN m.slopeFailure = 1 OR m.wallCracking = 1 OR m.surfaceRockfall = 1 THEN 0
    WHEN m.isCrack = 1 THEN 1
    ELSE 2
  END,
  m.createdOn DESC,
  s.code ASC
""".strip()


def _effective_abnormal_sql_condition() -> str:
    return " OR ".join(
        ["(m.isCrack = 1 AND NULLIF(LTRIM(RTRIM(CONVERT(varchar(50), m.width))), '') IS NOT NULL)"]
        + [f"m.{field_name} = 1" for field_name, _ in ABNORMAL_TYPE_FIELDS if field_name != "isCrack"]
    )


def _is_truthy_flag(value) -> bool:
    return str(value).strip() in {"1", "1.0", "true", "True"}


def _has_crack_measure(row: dict) -> bool:
    value = str(row.get("width") or "").strip()
    return bool(value and value.lower() not in {"none", "null"})


def _enrich_recent_large_displacement_rows(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    try:
        from app.displacement_dashboard import get_recent_displacement_dashboard

        get_recent_displacement_dashboard()
    except Exception as exc:
        print(f">>> displacement dashboard generation skipped: {exc}")

    return ["displacement_dashboard_marker"], [{"displacement_dashboard_marker": "1"}]


def _enrich_qmqf_dashboard_rows(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    return ["qmqf_dashboard_marker"], [{"qmqf_dashboard_marker": "1"}]


def _enrich_abnormal_type_rows(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    flag_fields = {field_name for field_name, _ in ABNORMAL_TYPE_FIELDS}
    display_columns = [column for column in columns if column not in flag_fields]
    if "abnormal_type" not in display_columns:
        insert_at = 3 if len(display_columns) >= 3 else len(display_columns)
        display_columns.insert(insert_at, "abnormal_type")

    enriched_rows = []
    for row in rows:
        abnormal_types = []
        for field_name, label in ABNORMAL_TYPE_FIELDS:
            if not _is_truthy_flag(row.get(field_name)):
                continue
            if field_name == "isCrack" and not _has_crack_measure(row):
                continue
            abnormal_types.append(label)
        enriched = {
            column: row.get(column, "")
            for column in display_columns
            if column != "abnormal_type"
        }
        enriched["abnormal_type"] = "、".join(abnormal_types) or "未识别到具体异常项"
        enriched_rows.append(enriched)

    return display_columns, enriched_rows


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item).strip()]
    except Exception:
        return []
    return []


def _extract_displacement_snippets(text_value: str) -> list[str]:
    text_value = str(text_value or "").replace("\r", "\n")
    pieces = re.split(r"[。；;\n]", text_value)
    snippets = []
    for piece in pieces:
        compact = " ".join(piece.split())
        if 12 <= len(compact) <= 260 and (
            ("位移" in compact and ("mm" in compact or "最大" in compact))
            or ("监测点" in compact and "现存" in compact)
        ):
            snippets.append(compact)
        if len(snippets) >= 3:
            break
    if snippets:
        return snippets
    fallback = " ".join(text_value.split())
    return [fallback[:220]] if fallback else []


def _extract_key_points(row: dict) -> tuple[str, str]:
    text_value = str(row.get("text_excerpt") or "")
    monitors = [
        item
        for item in _json_list(row.get("monitor_points"))
        if re.match(r"^(?:JC|KZ)\d+(?:-\d+)?$", item, re.IGNORECASE)
    ]
    slopes = _json_list(row.get("slope_codes"))
    for snippet in _extract_displacement_snippets(text_value):
        monitors.extend(re.findall(r"\b(?:JC|KZ)\d+(?:-\d+)?\b", snippet, re.IGNORECASE))
        slopes.extend(re.findall(r"\b(?:[A-Z]{1,5}\d{3,6}|420\d{10,})\b", snippet))
    monitors = list(dict.fromkeys(monitors))[:8]
    slopes = list(dict.fromkeys(slopes))[:8]
    return ("、".join(monitors) or "见报告页", "、".join(slopes) or "见报告页")


def _enrich_report_displacement_rows(columns: list[str], rows: list[dict]) -> tuple[list[str], list[dict]]:
    return columns, rows

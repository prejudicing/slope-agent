"""Question routing and business-boundary checks."""

from dataclasses import dataclass
import re

from app.business_queries import get_deterministic_query


BUSINESS_KEYWORDS = {
    "高切坡",
    "切坡",
    "边坡",
    "坡",
    "监测",
    "专业监测",
    "群测群防",
    "巡查",
    "巡检",
    "预警",
    "复核",
    "雨量",
    "异常",
    "裂缝",
    "落石",
    "挡墙",
    "排水",
    "地质",
    "坡高",
    "坡长",
    "面积",
    "风险",
    "安全等级",
    "区县",
    "街道",
    "监测点",
    "专报",
    "月报",
    "年报",
    "险情",
    "全景",
    "照片",
    "图片",
    "影像",
    "dom",
    "人员",
    "联系人",
    "通讯录",
    "监测员",
    "审核员",
    "管理员",
    "业务人员",
}

GENERIC_QUERY_WORDS = {"查询", "统计", "分析", "总结", "报告", "数据", "记录", "结果", "情况"}

ANALYSIS_KEYWORDS = {
    "分析",
    "总结",
    "研判",
    "趋势",
    "变化",
    "对比",
    "比较",
    "归纳",
    "评估",
    "重点关注",
    "特征",
    "分布",
    "排行",
    "排名",
}

OUT_OF_SCOPE_KEYWORDS = {
    "天气",
    "股票",
    "基金",
    "电影",
    "音乐",
    "菜谱",
    "翻译",
    "写代码",
    "编程",
    "python",
    "java",
    "作文",
    "小说",
    "简历",
    "面试",
    "数学",
    "历史",
    "英语",
    "新闻",
}

SENSITIVE_SYSTEM_KEYWORDS = {"密码", "账号", "登录", "token", "权限", "角色", "菜单", "用户表", "系统管理"}

VAGUE_PATTERNS = (
    "查一下",
    "看一下",
    "看看",
    "查查",
    "分析一下",
    "总结一下",
    "出个报告",
    "生成报告",
    "帮我看看",
)

WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class QueryRouteDecision:
    status: str
    query_type: str
    summary: str
    suggestion: str | None = None
    reason: str | None = None
    route_name: str | None = None


def _normalize_question(question: str) -> str:
    return WHITESPACE_RE.sub("", (question or "").strip())


def route_question(question: str) -> QueryRouteDecision:
    normalized = _normalize_question(question)

    if not normalized:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="您好，请输入需要了解的高切坡业务问题。我可以协助查询高切坡基础台账、专业监测、群测群防、现场异常和近期风险研判等内容。",
            suggestion="例如可以提问：“近期哪个区县高切坡风险较高”“巴东高切坡情况”“近期群测群防情况”。",
            reason="empty_question",
            route_name="clarify",
        )

    if normalized in {"你是谁", "你能做什么", "可以做什么", "你会什么"}:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="您好，我是高切坡业务智能助手，主要协助查询和研判高切坡基础台账、专业监测、群测群防、现场异常、照片记录和近期风险情况。",
            suggestion="可以直接提问：“巴东高切坡情况”“近期专业监测情况”“最近哪个区县高切坡风险较高”。",
            reason="assistant_intro",
            route_name="clarify",
        )

    if len(normalized) <= 3 or normalized in {"查一下", "看一下", "查查", "看看"}:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="这个问题信息稍少，暂时无法判断要查询的高切坡业务内容。请补充区县、编号、监测类型、异常类型或时间范围。",
            suggestion="例如可以补充为：“巴东县近期高切坡情况”或“近期专业监测位移变化较大的高切坡”。",
            reason="too_short",
            route_name="clarify",
        )

    sensitive_hits = [keyword for keyword in SENSITIVE_SYSTEM_KEYWORDS if keyword in normalized]
    business_hits = [keyword for keyword in BUSINESS_KEYWORDS if keyword.lower() in normalized.lower()]
    credential_sensitive_hits = [
        keyword
        for keyword in ("密码", "口令", "token", "密钥", "reset_key", "reset_pwd", "重置密钥", "登录密码")
        if keyword.lower() in normalized.lower()
    ]
    if credential_sensitive_hits:
        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，人员信息查询不支持查看密码、密钥、令牌、重置凭据等敏感内容。可以查询人员姓名、角色、部门、职务和业务联系方式。",
            suggestion="例如可以提问：“查询监测员名单”“查看管理员联系方式”“列出人员通讯录”。",
            reason="credential_sensitive",
            route_name="out_of_scope",
        )
    if sensitive_hits and not business_hits:
        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，我主要用于高切坡业务数据查询与研判，暂不处理账号、权限或系统管理类问题。",
            suggestion="可以改为查询高切坡基础信息、监测预警、巡查异常或现场复核情况。",
            reason="system_sensitive",
            route_name="out_of_scope",
        )

    out_of_scope_hits = [keyword for keyword in OUT_OF_SCOPE_KEYWORDS if keyword.lower() in normalized.lower()]
    if out_of_scope_hits and not business_hits:
        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，这个问题不属于高切坡业务查询范围。我可以协助分析高切坡台账、专业监测、群测群防、现场照片、异常记录和近期风险情况。",
            suggestion="例如可以提问：“近期哪个区县高切坡风险较高”“近期群测群防情况”“某区县高切坡概况”。",
            reason="non_business_topic",
            route_name="out_of_scope",
        )

    deterministic_query = get_deterministic_query(question)
    if deterministic_query:
        return QueryRouteDecision(
            status="query",
            query_type="template_query",
            summary="问题命中稳定业务模板，优先使用固定查询路径。",
            reason="matched_template_query",
            route_name=deterministic_query["name"],
        )

    generic_hits = [keyword for keyword in GENERIC_QUERY_WORDS if keyword in normalized]
    if not business_hits:
        if any(pattern in normalized for pattern in VAGUE_PATTERNS) or generic_hits:
            return QueryRouteDecision(
                status="clarify",
                query_type="clarify",
                summary="这个问题还缺少明确的高切坡业务对象或查询范围。请补充区县、编号、监测类别、异常类型或希望了解的时间范围。",
                suggestion="例如可以提问：“巴东县高切坡情况”“近期专业监测情况”“近期现场异常主要在哪些区县”。",
                reason="missing_business_context",
                route_name="clarify",
            )

        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，我暂时只能回答高切坡业务相关问题。你可以询问高切坡基本信息、区县概况、专业监测、群测群防、巡查异常、现场照片或近期风险研判。",
            suggestion="例如：“巴东高切坡情况”“近期哪个区县高切坡风险较高”“近期群测群防情况”。",
            reason="no_business_signal",
            route_name="out_of_scope",
        )

    analysis_hits = [keyword for keyword in ANALYSIS_KEYWORDS if keyword in normalized]
    if analysis_hits:
        return QueryRouteDecision(
            status="query",
            query_type="result_analysis",
            summary="问题已识别为高切坡业务分析类查询，将先查询数据库再生成分析总结。",
            reason="analysis_query",
            route_name="result_analysis",
        )

    return QueryRouteDecision(
        status="query",
        query_type="db_query",
        summary="问题已识别为高切坡业务查询，进入数据库查询流程。",
        reason="business_query",
        route_name="db_query",
    )

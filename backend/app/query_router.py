"""问题路由与越界拒答规则。

当前统一将问题划分为 5 类：
1. db_query：普通事实查询，直接进入数据库查询主链路；
2. result_analysis：分析/总结/对比/趋势类问题，先查表再做结果分析；
3. template_query：命中稳定业务模板的问题，优先使用固定 SQL；
4. clarify：条件不足，需要用户补充对象、地区、时间或异常类型；
5. out_of_scope：越界或敏感问题，直接拒答。
"""

from dataclasses import dataclass
import re

from app.business_queries import get_deterministic_query


BUSINESS_KEYWORDS = {
    "高切坡",
    "切坡",
    "边坡",
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
    "责任单位",
    "区县",
    "街道",
    "监测点",
    "预警专报",
    "月报",
    "年报",
    "险情",
    "全景",
    "倾斜摄影",
    "dom",
}

GENERIC_QUERY_WORDS = {
    "查询",
    "统计",
    "分析",
    "总结",
    "报告",
    "数据",
    "记录",
    "结果",
    "情况",
}

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
    "原因",
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
    "周报",
    "日报",
    "简历",
    "面试",
    "数学",
    "历史",
    "英语",
    "笑话",
    "新闻",
}

SENSITIVE_SYSTEM_KEYWORDS = {
    "密码",
    "账号",
    "登录",
    "token",
    "权限",
    "角色",
    "菜单",
    "用户表",
    "系统管理",
}

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
    "帮我查一下",
)

WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class QueryRouteDecision:
    """问题路由结果。"""

    status: str
    query_type: str
    summary: str
    suggestion: str | None = None
    reason: str | None = None
    route_name: str | None = None


def _normalize_question(question: str) -> str:
    return WHITESPACE_RE.sub("", (question or "").strip())


def route_question(question: str) -> QueryRouteDecision:
    """对用户问题做轻量路由。"""
    normalized = _normalize_question(question)

    if not normalized:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="当前问题为空，暂时无法发起高切坡业务查询。",
            suggestion="请直接描述要查询的高切坡信息，例如“统计各区县高切坡数量”或“查询最近异常巡查记录”。",
            reason="empty_question",
            route_name="clarify",
        )

    if len(normalized) <= 3 or normalized in {"查一下", "看一下", "查查", "看看"}:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="当前问题过于简短，暂时无法确定具体查询口径。",
            suggestion="请补充查询对象、地区、时间或异常类型，例如“查询渝北区最近30天的异常巡查记录”。",
            reason="too_short",
            route_name="clarify",
        )

    sensitive_hits = [keyword for keyword in SENSITIVE_SYSTEM_KEYWORDS if keyword in normalized]
    if sensitive_hits:
        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题涉及账号、权限或系统管理信息，不属于高切坡业务智能查询范围。",
            suggestion="请改为查询高切坡基础信息、监测、预警、巡查或复核相关业务数据。",
            reason="system_sensitive",
            route_name="out_of_scope",
        )

    business_hits = [keyword for keyword in BUSINESS_KEYWORDS if keyword.lower() in normalized.lower()]
    generic_hits = [keyword for keyword in GENERIC_QUERY_WORDS if keyword in normalized]
    out_of_scope_hits = [keyword for keyword in OUT_OF_SCOPE_KEYWORDS if keyword.lower() in normalized.lower()]

    if out_of_scope_hits and not business_hits:
        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题与高切坡业务查询无关，系统不提供该类回答。",
            suggestion="请改为查询高切坡台账、监测记录、巡查异常、预警专报或复核处理等业务数据。",
            reason="non_business_topic",
            route_name="out_of_scope",
        )

    if not business_hits:
        if any(pattern in normalized for pattern in VAGUE_PATTERNS) or generic_hits:
            return QueryRouteDecision(
                status="clarify",
                query_type="clarify",
                summary="当前问题缺少明确的高切坡业务对象或查询范围。",
                suggestion="请补充高切坡相关对象，例如编号、区县、监测、巡查、预警或异常类型。",
                reason="missing_business_context",
                route_name="clarify",
            )

        return QueryRouteDecision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题不属于高切坡业务智能查询范围。",
            suggestion="请改为查询高切坡基本信息、地质背景、监测、巡查、预警或复核数据。",
            reason="no_business_signal",
            route_name="out_of_scope",
        )

    if any(pattern in normalized for pattern in VAGUE_PATTERNS) and len(business_hits) <= 1:
        return QueryRouteDecision(
            status="clarify",
            query_type="clarify",
            summary="当前问题仍然偏模糊，建议补充更具体的查询条件。",
            suggestion="可以补充地区、时间、编号或异常类型，例如“分析江北区最近一个月的裂缝异常记录”。",
            reason="vague_business_question",
            route_name="clarify",
        )

    deterministic_query = get_deterministic_query(question)
    if deterministic_query:
        return QueryRouteDecision(
            status="query",
            query_type="template_query",
            summary="问题命中稳定业务模板，优先使用固定查询口径。",
            reason="matched_template_query",
            route_name=deterministic_query["name"],
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

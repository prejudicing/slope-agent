"""问题路由与越界拒答规则。

当前统一将问题划分为 5 类：
1. db_query：普通事实查询，直接进入数据库查询主链路；
2. result_analysis：分析/总结/对比/趋势类问题，先查表再做结果分析；
3. template_query：命中稳定业务模板的问题，优先使用固定 SQL；
4. clarify：条件不足，需要用户补充对象、地区、时间或异常类型；
5. out_of_scope：越界或敏感问题，直接拒答。

另外，身份介绍/能力说明属于 chat：直接聊天回复，不进入 SQL 查询链路。
"""

from dataclasses import dataclass
import json
import re
from typing import Any

from app.business_queries import get_deterministic_query
from app.conversation_context import ConversationTurn, build_routing_context


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

SMALL_TALK_PATTERNS = (
    "你是谁",
    "你叫什么",
    "你的身份",
    "你身份",
    "身份是什么",
    "你是什么身份",
    "你能做什么",
    "你是做什么的",
    "介绍一下你自己",
    "自我介绍",
    "你是什么",
)

ASSISTANT_IDENTITY_SUMMARY = (
    "你好，我是高切坡AI助手，可以帮你查询和分析高切坡基础信息、"
    "监测、巡查、预警、复核处理、异常状态等业务数据。"
)
ASSISTANT_IDENTITY_SUGGESTION = (
    "你可以直接问我，例如“查询渝北区高切坡基本信息”或“分析最近异常高切坡的分布情况”。"
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
    effective_question: str | None = None
    use_history: bool = False
    confidence: float | None = None


QUERY_TYPES = {
    "chat",
    "db_query",
    "template_query",
    "result_analysis",
    "clarify",
    "out_of_scope",
}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _coerce_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, number))


def _normalize_question(question: str) -> str:
    return WHITESPACE_RE.sub("", (question or "").strip())


def _build_decision(
    *,
    status: str,
    query_type: str,
    summary: str,
    suggestion: str | None = None,
    reason: str | None = None,
    route_name: str | None = None,
    effective_question: str | None = None,
    use_history: bool = False,
    confidence: float | None = None,
) -> QueryRouteDecision:
    return QueryRouteDecision(
        status=status,
        query_type=query_type,
        summary=summary,
        suggestion=suggestion,
        reason=reason,
        route_name=route_name,
        effective_question=effective_question,
        use_history=use_history,
        confidence=confidence,
    )


def _safety_route_question(question: str) -> QueryRouteDecision | None:
    """规则安全兜底：只拦截空问题、明显过短和敏感系统类请求。"""
    normalized = _normalize_question(question)

    if not normalized:
        return _build_decision(
            status="clarify",
            query_type="clarify",
            summary="当前问题为空，暂时无法发起高切坡业务查询。",
            suggestion="请直接描述要查询的高切坡信息，例如“统计各区县高切坡数量”或“查询最近异常巡查记录”。",
            reason="empty_question",
            route_name="clarify",
        )

    if normalized in {"查一下", "看一下", "查查", "看看"}:
        return _build_decision(
            status="clarify",
            query_type="clarify",
            summary="当前问题过于简短，暂时无法确定具体查询口径。",
            suggestion="请补充查询对象、地区、时间或异常类型，例如“查询渝北区最近30天的异常巡查记录”。",
            reason="too_short",
            route_name="clarify",
        )

    if any(pattern in normalized for pattern in SMALL_TALK_PATTERNS):
        return _build_decision(
            status="success",
            query_type="chat",
            summary=ASSISTANT_IDENTITY_SUMMARY,
            suggestion=ASSISTANT_IDENTITY_SUGGESTION,
            reason="assistant_identity",
            route_name="chat",
        )

    sensitive_hits = [keyword for keyword in SENSITIVE_SYSTEM_KEYWORDS if keyword in normalized]
    if sensitive_hits:
        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题涉及账号、权限或系统管理信息，不属于高切坡业务智能查询范围。",
            suggestion="请改为查询高切坡基础信息、监测、预警、巡查或复核相关业务数据。",
            reason="system_sensitive",
            route_name="out_of_scope",
        )

    return None


def _fallback_route_question(question: str) -> QueryRouteDecision:
    """LLM 不可用时的轻量规则回退。"""
    normalized = _normalize_question(question)

    safety_decision = _safety_route_question(question)
    if safety_decision:
        return safety_decision

    business_hits = [keyword for keyword in BUSINESS_KEYWORDS if keyword.lower() in normalized.lower()]
    generic_hits = [keyword for keyword in GENERIC_QUERY_WORDS if keyword in normalized]
    out_of_scope_hits = [keyword for keyword in OUT_OF_SCOPE_KEYWORDS if keyword.lower() in normalized.lower()]

    if out_of_scope_hits and not business_hits:
        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题与高切坡业务查询无关，系统不提供该类回答。",
            suggestion="请改为查询高切坡台账、监测记录、巡查异常、预警专报或复核处理等业务数据。",
            reason="non_business_topic",
            route_name="out_of_scope",
        )

    if not business_hits:
        if any(pattern in normalized for pattern in VAGUE_PATTERNS) or generic_hits:
            return _build_decision(
                status="clarify",
                query_type="clarify",
                summary="当前问题缺少明确的高切坡业务对象或查询范围。",
                suggestion="请补充高切坡相关对象，例如编号、区县、监测、巡查、预警或异常类型。",
                reason="missing_business_context",
                route_name="clarify",
            )

        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="当前问题不属于高切坡业务智能查询范围。",
            suggestion="请改为查询高切坡基本信息、地质背景、监测、巡查、预警或复核数据。",
            reason="no_business_signal",
            route_name="out_of_scope",
        )

    if any(pattern in normalized for pattern in VAGUE_PATTERNS) and len(business_hits) <= 1:
        return _build_decision(
            status="clarify",
            query_type="clarify",
            summary="当前问题仍然偏模糊，建议补充更具体的查询条件。",
            suggestion="可以补充地区、时间、编号或异常类型，例如“分析江北区最近一个月的裂缝异常记录”。",
            reason="vague_business_question",
            route_name="clarify",
        )

    deterministic_query = get_deterministic_query(question)
    if deterministic_query:
        return _build_decision(
            status="query",
            query_type="template_query",
            summary="问题命中稳定业务模板，优先使用固定查询口径。",
            reason="matched_template_query",
            route_name=deterministic_query["name"],
        )

    analysis_hits = [keyword for keyword in ANALYSIS_KEYWORDS if keyword in normalized]
    if analysis_hits:
        return _build_decision(
            status="query",
            query_type="result_analysis",
            summary="问题已识别为高切坡业务分析类查询，将先查询数据库再生成分析总结。",
            reason="analysis_query",
            route_name="result_analysis",
        )

    return _build_decision(
        status="query",
        query_type="db_query",
        summary="问题已识别为高切坡业务查询，进入数据库查询流程。",
        reason="business_query",
        route_name="db_query",
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象。"""
    content = text.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"\s*```$", "", content)

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("router_llm_json_not_found")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("router_llm_json_not_object")
    return data


def _invoke_router_llm(question: str, history: list[ConversationTurn], llm) -> dict[str, Any]:
    routing_context = build_routing_context(history)
    prompt = (
        "你是高切坡系统智能体的意图路由器，只负责判断用户问题应该如何进入后续链路。"
        "请严格输出一个 JSON 对象，不要输出 Markdown、解释文字或代码块。\n\n"
        "路由类型只能是：chat、db_query、template_query、result_analysis、clarify、out_of_scope。\n"
        "状态只能是：success、query、clarify、rejected。\n\n"
        "业务范围：高切坡基础信息、群测群防、专业监测、巡查记录、预警专报、复核处理、报告附件、空间数据、异常状态、裂缝、落石、挡墙、排水等。\n"
        "身份范围：用户询问你是谁、叫什么、能做什么时，属于 chat；你要说明自己是高切坡AI助手，不要拒答。\n"
        "越界范围：账号、权限、密码、角色、菜单、系统管理、通用编程、写作、翻译、天气、股票、新闻、菜谱等。\n\n"
        "判断原则：\n"
        "1. 先判断当前新问题自身是不是全新问题；不要因为历史里有高切坡内容就污染全新问题。\n"
        "2. 只有当前新问题明显依赖上一轮对象、地区、时间、统计结果或代词时，use_history 才能为 true。\n"
        "3. 如果 use_history 为 true，请把 effective_question 改写成完整、可独立理解的高切坡业务问题。\n"
        "4. 如果 use_history 为 false，effective_question 必须等于或基本等于当前新问题。\n"
        "5. 高切坡业务的查询、统计、列表、明细属于 db_query。\n"
        "6. 分析、对比、趋势、总结、分布、排行、研判属于 result_analysis。\n"
        "7. 询问异常类型、哪一种异常、哪类异常等高风险固定口径问题属于 template_query。\n"
        "8. 业务对象或条件不足且无法从历史补全时属于 clarify。\n"
        "9. 询问你的身份或能力介绍属于 chat，status 使用 success，use_history 必须为 false。\n"
        "10. 非高切坡业务或敏感系统管理问题属于 out_of_scope。\n\n"
        "输出 JSON 字段：\n"
        "{"
        "\"status\":\"success|query|clarify|rejected\","
        "\"query_type\":\"chat|db_query|template_query|result_analysis|clarify|out_of_scope\","
        "\"use_history\":true,"
        "\"effective_question\":\"...\","
        "\"summary\":\"给用户看的简短路由说明\","
        "\"suggestion\":\"需要澄清或越界时给用户的建议，否则为空字符串\","
        "\"reason\":\"英文或拼音短原因\","
        "\"confidence\":0.0"
        "}\n\n"
        f"最近会话上下文：\n{routing_context or '无'}\n\n"
        f"当前新问题：{question}"
    )
    response = llm.invoke(prompt)
    content = getattr(response, "content", response)
    return _extract_json_object(str(content))


def _decision_from_llm_payload(question: str, payload: dict[str, Any]) -> QueryRouteDecision:
    query_type = str(payload.get("query_type") or "").strip()
    status = str(payload.get("status") or "").strip()

    if query_type not in QUERY_TYPES:
        raise ValueError(f"router_llm_invalid_query_type:{query_type}")
    if status not in {"success", "query", "clarify", "rejected"}:
        raise ValueError(f"router_llm_invalid_status:{status}")

    if query_type == "chat":
        status = "success"
        summary = ASSISTANT_IDENTITY_SUMMARY
        suggestion = ASSISTANT_IDENTITY_SUGGESTION
    elif query_type in {"clarify", "out_of_scope"}:
        status = "clarify" if query_type == "clarify" else "rejected"
    elif status != "query":
        raise ValueError("router_llm_query_type_status_mismatch")

    effective_question = str(payload.get("effective_question") or question).strip() or question
    use_history = _coerce_bool(payload.get("use_history"))
    if query_type != "chat":
        summary = str(payload.get("summary") or "").strip()
        suggestion = str(payload.get("suggestion") or "").strip() or None
    reason = str(payload.get("reason") or "llm_route").strip()
    confidence = _coerce_confidence(payload.get("confidence"))

    if query_type == "template_query":
        route_name = "template_query"
        deterministic_query = get_deterministic_query(effective_question)
        if deterministic_query:
            route_name = deterministic_query["name"]
    else:
        route_name = query_type

    return _build_decision(
        status=status,
        query_type=query_type,
        summary=summary or _default_summary(status, query_type),
        suggestion=suggestion,
        reason=reason,
        route_name=route_name,
        effective_question=effective_question,
        use_history=use_history,
        confidence=confidence,
    )


def _default_summary(status: str, query_type: str) -> str:
    if status == "clarify":
        return "当前问题缺少足够的高切坡业务查询条件，需要进一步补充。"
    if status == "rejected":
        return "当前问题不属于高切坡业务智能查询范围。"
    if query_type == "chat":
        return "你好，我是高切坡AI助手，可以帮你查询和分析高切坡业务数据。"
    if query_type == "result_analysis":
        return "问题已识别为高切坡业务分析类查询，将先查询数据库再生成分析总结。"
    if query_type == "template_query":
        return "问题命中稳定业务模板，优先使用固定查询口径。"
    return "问题已识别为高切坡业务查询，进入数据库查询流程。"


def route_question(
    question: str,
    history: list[ConversationTurn] | None = None,
    llm=None,
    llm_factory=None,
) -> QueryRouteDecision:
    """路由用户问题：规则安全兜底 + LLM 意图/续问判定 + 规则回退。"""
    safety_decision = _safety_route_question(question)
    if safety_decision:
        return safety_decision

    conversation_history = history or []

    if llm is not None or llm_factory is not None:
        try:
            if llm is None and llm_factory is not None:
                llm = llm_factory()
            payload = _invoke_router_llm(question, conversation_history, llm)
            decision = _decision_from_llm_payload(question, payload)
            deterministic_query = get_deterministic_query(decision.effective_question or question)
            if deterministic_query:
                decision.query_type = "template_query"
                decision.status = "query"
                decision.route_name = deterministic_query["name"]
                decision.summary = "问题命中稳定业务模板，优先使用固定查询口径。"
                decision.reason = decision.reason or "matched_template_query"
            elif decision.query_type == "template_query":
                decision.query_type = "db_query"
                decision.route_name = "db_query"
                decision.summary = "问题已识别为高切坡业务查询，进入数据库查询流程。"
                decision.reason = f"{decision.reason or 'llm_route'};template_without_implementation"
            return decision
        except Exception as exc:
            fallback = _fallback_route_question(question)
            fallback.reason = f"{fallback.reason or 'fallback'};router_llm_failed:{exc}"
            return fallback

    return _fallback_route_question(question)

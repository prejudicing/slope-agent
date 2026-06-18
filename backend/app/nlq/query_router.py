"""问题路由与越界拒答规则。"""

from dataclasses import dataclass
import json
import re
from typing import Any

from app.nlq.business_queries import get_deterministic_query
from app.nlq.conversation_context import ConversationTurn, SLOPE_CODE_RE, build_routing_context


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
    "降雨",
    "降水",
    "强降雨",
    "雨后",
    "水位",
    "库水位",
    "三峡库水位",
    "水文",
    "水文站",
    "雨量站",
    "库水位变化",
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
    "专报",
    "预警专报",
    "月报",
    "年报",
    "险情",
    "全景",
    "倾斜摄影",
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
    "综合研判",
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

SENSITIVE_SYSTEM_KEYWORDS = {"密码", "账号", "登录", "token", "权限", "角色", "菜单", "用户表", "系统管理"}
CREDENTIAL_SENSITIVE_KEYWORDS = {"密码", "口令", "token", "密钥", "reset_key", "reset_pwd", "重置密钥", "登录密码"}

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
    "可以做什么",
    "你会什么",
)

ASSISTANT_IDENTITY_SUMMARY = (
    "您好，我是高切坡业务智能助手，主要协助查询和研判高切坡基础台账、"
    "专业监测、群测群防、现场异常、照片记录和近期风险情况。"
)
ASSISTANT_IDENTITY_SUGGESTION = (
    "可以直接提问：“巴东高切坡情况”“近期专业监测情况”“最近哪个区县高切坡风险较高”。"
)

WHITESPACE_RE = re.compile(r"\s+")


def _business_hits(normalized: str) -> list[str]:
    hits = [keyword for keyword in BUSINESS_KEYWORDS if keyword.lower() in normalized.lower()]
    if SLOPE_CODE_RE.search(normalized.upper()):
        hits.append("高切坡编号")
    return hits


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
    """规则安全兜底：只拦截空问题、过短问题、闲聊身份和敏感系统类请求。"""
    normalized = _normalize_question(question)

    if not normalized:
        return _build_decision(
            status="clarify",
            query_type="clarify",
            summary="您好，请输入需要了解的高切坡业务问题。我可以协助查询高切坡基础台账、专业监测、群测群防、现场异常和近期风险研判等内容。",
            suggestion="例如可以提问：“近期哪个区县高切坡风险较高”“巴东高切坡情况”“近期群测群防情况”。",
            reason="empty_question",
            route_name="clarify",
        )

    if len(normalized) <= 3 or normalized in {"查一下", "看一下", "查查", "看看"}:
        return _build_decision(
            status="clarify",
            query_type="clarify",
            summary="这个问题信息稍少，暂时无法判断要查询的高切坡业务内容。请补充区县、编号、监测类型、异常类型或时间范围。",
            suggestion="例如可以补充为：“巴东县近期高切坡情况”或“近期专业监测位移变化较大的高切坡”。",
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

    business_hits = _business_hits(normalized)
    credential_hits = [keyword for keyword in CREDENTIAL_SENSITIVE_KEYWORDS if keyword.lower() in normalized.lower()]
    if credential_hits:
        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，人员信息查询不支持查看密码、密钥、令牌、重置凭据等敏感内容。可以查询人员姓名、角色、部门、职务和业务联系方式。",
            suggestion="例如可以提问：“查询监测员名单”“查看管理员联系方式”“列出人员通讯录”。",
            reason="credential_sensitive",
            route_name="out_of_scope",
        )

    sensitive_hits = [keyword for keyword in SENSITIVE_SYSTEM_KEYWORDS if keyword in normalized]
    if sensitive_hits and not business_hits:
        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，我主要用于高切坡业务数据查询与研判，暂不处理账号、权限或系统管理类问题。",
            suggestion="可以改为查询高切坡基础信息、监测预警、巡查异常或现场复核情况。",
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

    business_hits = _business_hits(normalized)
    generic_hits = [keyword for keyword in GENERIC_QUERY_WORDS if keyword in normalized]
    out_of_scope_hits = [keyword for keyword in OUT_OF_SCOPE_KEYWORDS if keyword.lower() in normalized.lower()]

    if out_of_scope_hits and not business_hits:
        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，这个问题不属于高切坡业务查询范围。我可以协助分析高切坡台账、专业监测、群测群防、现场照片、异常记录和近期风险情况。",
            suggestion="例如可以提问：“近期哪个区县高切坡风险较高”“近期群测群防情况”“某区县高切坡概况”。",
            reason="non_business_topic",
            route_name="out_of_scope",
        )

    if not business_hits:
        if any(pattern in normalized for pattern in VAGUE_PATTERNS) or generic_hits:
            return _build_decision(
                status="clarify",
                query_type="clarify",
                summary="这个问题还缺少明确的高切坡业务对象或查询范围。请补充区县、编号、监测类别、异常类型或希望了解的时间范围。",
                suggestion="例如可以提问：“巴东县高切坡情况”“近期专业监测情况”“近期现场异常主要在哪些区县”。",
                reason="missing_business_context",
                route_name="clarify",
            )

        return _build_decision(
            status="rejected",
            query_type="out_of_scope",
            summary="抱歉，我暂时只能回答高切坡业务相关问题。你可以询问高切坡基本信息、区县概况、专业监测、群测群防、巡查异常、现场照片或近期风险研判。",
            suggestion="例如：“巴东高切坡情况”“近期哪个区县高切坡风险较高”“近期群测群防情况”。",
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
            summary="问题命中稳定业务模板，优先使用固定查询路径。",
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
        "业务范围：高切坡基础信息、群测群防、专业监测、巡查记录、预警专报、复核处理、报告附件、空间数据、异常状态、裂缝、落石、挡墙、排水、现场照片、人员通讯录等。\n"
        "身份范围：用户询问你是谁、叫什么、能做什么时，属于 chat；你要说明自己是高切坡业务智能助手，不要拒答。\n"
        "越界范围：账号、权限、密码、菜单、系统管理、通用编程、写作、翻译、天气、股票、新闻、菜谱等。\n\n"
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


def _default_summary(status: str, query_type: str) -> str:
    if status == "clarify":
        return "当前问题缺少足够的高切坡业务查询条件，需要进一步补充。"
    if status == "rejected":
        return "当前问题不属于高切坡业务智能查询范围。"
    if query_type == "chat":
        return ASSISTANT_IDENTITY_SUMMARY
    if query_type == "result_analysis":
        return "问题已识别为高切坡业务分析类查询，将先查询数据库再生成分析总结。"
    if query_type == "template_query":
        return "问题命中稳定业务模板，优先使用固定查询口径。"
    return "问题已识别为高切坡业务查询，进入数据库查询流程。"


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
        summary = str(payload.get("summary") or "").strip()
        suggestion = str(payload.get("suggestion") or "").strip() or None
    elif status != "query":
        raise ValueError("router_llm_query_type_status_mismatch")
    else:
        summary = str(payload.get("summary") or "").strip()
        suggestion = str(payload.get("suggestion") or "").strip() or None

    effective_question = str(payload.get("effective_question") or question).strip() or question
    use_history = _coerce_bool(payload.get("use_history"))
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

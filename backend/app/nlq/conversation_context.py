"""会话上下文整理。

上下文不再无条件拼进 SQL Agent 输入，而是先交给路由模型判断：
如果当前问题是全新问题，就完全忽略历史；如果明显是续问，再生成
一个可独立理解的 effective question 交给查询链路。
"""

from __future__ import annotations

from dataclasses import dataclass
MAX_HISTORY_TURNS = 4
MAX_HISTORY_SUMMARY_LEN = 240


@dataclass
class ConversationTurn:
    question: str
    summary: str = ""
    total_rows: int = 0


def normalize_history(history: list[dict] | None) -> list[ConversationTurn]:
    """把前端传来的历史记录收成后端更稳定的结构。"""
    turns: list[ConversationTurn] = []
    for item in history or []:
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        turns.append(
            ConversationTurn(
                question=question,
                summary=str(item.get("summary") or "").strip(),
                total_rows=int(item.get("total_rows") or 0),
            )
        )
    return turns[-MAX_HISTORY_TURNS:]


def _compact_summary(summary: str) -> str:
    if len(summary) <= MAX_HISTORY_SUMMARY_LEN:
        return summary
    return summary[:MAX_HISTORY_SUMMARY_LEN] + "..."


def build_effective_question(question: str, history: list[ConversationTurn]) -> str:
    """兼容旧调用：返回带历史提示的问题文本。

    新链路优先使用路由结果里的 effective_question；这个函数保留给脚本、
    调试工具或未来需要显式拼接上下文的场景。
    """
    if not history:
        return question

    return (
        "以下是当前会话最近几轮上下文，请结合这些历史信息理解当前问题。"
        "如果当前问题是一个全新的问题，就忽略这些历史内容；"
        "如果当前问题明显是在延续前文，再利用这些上下文补全查询口径。\n"
        + build_routing_context(history)
        + f"\n当前用户的新问题：{question}"
    )


def resolve_effective_question(
    question: str,
    history: list[ConversationTurn],
    *,
    routed_question: str | None = None,
    use_history: bool = False,
) -> str:
    """根据路由器判定得到最终交给查询链路的问题。"""
    if use_history and routed_question:
        return routed_question
    return question


def build_routing_context(history: list[ConversationTurn]) -> str:
    """生成给路由模型看的紧凑历史摘要。"""
    if not history:
        return ""

    history_lines = []
    for index, turn in enumerate(history, start=1):
        line = f"{index}. 用户问题：{turn.question}"
        if turn.summary:
            line += f"；查询报告摘要：{_compact_summary(turn.summary)}"
        if turn.total_rows:
            line += f"；结果总数：{turn.total_rows} 条"
        history_lines.append(line)
    return "\n".join(history_lines)

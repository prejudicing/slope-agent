"""轻量会话上下文整理。

当前系统仍然以“单次查询 -> 查询结果/查询报告”为主，
这里补一层最近几轮的会话摘要，作为附加材料一并交给模型理解，
由模型自己判断当前问题是全新问题还是基于前文的延续问题。
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
    """把最近几轮会话拼进当前问题，交给模型自行判断是否需要继承上下文。"""
    if not history:
        return question

    history_lines = []
    for index, turn in enumerate(history, start=1):
        line = f"{index}. 用户问题：{turn.question}"
        if turn.summary:
            line += f"；查询报告摘要：{_compact_summary(turn.summary)}"
        if turn.total_rows:
            line += f"；结果总数：{turn.total_rows} 条"
        history_lines.append(line)

    return (
        "以下是当前会话最近几轮上下文，请结合这些历史信息理解当前问题。"
        "如果当前问题是一个全新的问题，就忽略这些历史内容；"
        "如果当前问题明显是在延续前文，再利用这些上下文补全查询口径。\n"
        + "\n".join(history_lines)
        + f"\n当前用户的新问题：{question}"
    )

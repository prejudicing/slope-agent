"""运行正式 Agent 效果测试集，并生成带时间戳的 JSON 结果和 Markdown 报告。"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[4]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent import run_agent
from app.nlq.query_router import route_question
from app.nlq.question_normalizer import normalize_query_question

EVAL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = EVAL_DIR / "datasets" / "agent_eval_5routes_20each.json"
DOCS_DIR = EVAL_DIR / "docs"
RESULTS_DIR = EVAL_DIR / "results"
REPORTS_DIR = EVAL_DIR / "reports"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行高切坡 Agent 正式评测集")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="测试集 JSON 路径")
    parser.add_argument("--limit", type=int, default=0, help="只运行前 N 题")
    parser.add_argument("--route", action="append", default=[], help="只运行指定 query_type，可多次传入")
    parser.add_argument("--question", action="append", default=[], help="只运行指定题目文本，可多次传入")
    parser.add_argument("--per-case-timeout", type=int, default=120, help="单题最长运行秒数，超时后记为 error 并继续")
    return parser


def load_dataset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def filter_cases(cases: list[dict], routes: list[str], questions: list[str], limit: int) -> list[dict]:
    selected = list(cases)
    if routes:
        route_set = set(routes)
        selected = [case for case in selected if case["expected_query_type"] in route_set]
    if questions:
        question_set = set(questions)
        selected = [case for case in selected if case["question"] in question_set]
    if limit and limit > 0:
        selected = selected[:limit]
    return selected


def summarize_agent_result(result: dict) -> dict:
    rows = result.get("rows") or []
    return {
        "status": result.get("status"),
        "query_type": result.get("query_type"),
        "sql": result.get("sql") or "",
        "summary": result.get("summary") or "",
        "suggestion": result.get("suggestion"),
        "columns": result.get("columns") or [],
        "row_count": len(rows),
        "total_rows": int(result.get("total_rows", len(rows)) or 0),
        "sample_rows": rows[:5],
        "error": result.get("error"),
    }


class CaseTimeoutError(TimeoutError):
    """单题评测超时。"""


def _handle_timeout(signum, frame):  # pragma: no cover - integration behavior
    raise CaseTimeoutError("case_timeout")


def run_case(case: dict, per_case_timeout: int) -> dict:
    question = case["question"]
    normalized_question = normalize_query_question(question)
    route_decision = route_question(normalized_question)
    started_at = datetime.now()
    started_perf = time.perf_counter()

    try:
        previous_handler = signal.signal(signal.SIGALRM, _handle_timeout)
        if per_case_timeout > 0:
            signal.alarm(per_case_timeout)
        try:
            agent_result = run_agent(question)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous_handler)
        result_summary = summarize_agent_result(agent_result)
    except Exception as exc:  # pragma: no cover - integration behavior
        result_summary = {
            "status": "error",
            "query_type": "error",
            "sql": "",
            "summary": "",
            "suggestion": None,
            "columns": [],
            "row_count": 0,
            "total_rows": 0,
            "sample_rows": [],
            "error": str(exc),
        }
    finished_at = datetime.now()
    elapsed_seconds = round(time.perf_counter() - started_perf, 3)

    checks = evaluate_case(case, route_decision, result_summary)
    return {
        "id": case["id"],
        "question": question,
        "normalized_question": normalized_question,
        "timing": {
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "elapsed_seconds": elapsed_seconds,
        },
        "expected": {
            "query_type": case["expected_query_type"],
            "status": case["expected_status"],
            "route_name": case.get("expected_route_name"),
            "expect_non_empty": case.get("expect_non_empty", False),
        },
        "route_decision": {
            "status": route_decision.status,
            "query_type": route_decision.query_type,
            "reason": route_decision.reason,
            "route_name": route_decision.route_name,
            "summary": route_decision.summary,
            "suggestion": route_decision.suggestion,
        },
        "result": result_summary,
        "checks": checks,
    }


def evaluate_case(case: dict, route_decision, result_summary: dict) -> dict:
    expected_query_type = case["expected_query_type"]
    expected_status = case["expected_status"]
    expected_route_name = case.get("expected_route_name")
    expect_non_empty = case.get("expect_non_empty", False)

    actual_query_type = result_summary["query_type"]
    actual_status = result_summary["status"]
    total_rows = result_summary["total_rows"]
    row_count = result_summary["row_count"]
    summary = result_summary["summary"]

    flags: list[str] = []
    if actual_query_type != expected_query_type:
        flags.append("query_type_mismatch")
    if actual_status != expected_status:
        flags.append("status_mismatch")
    if expected_route_name and route_decision.route_name != expected_route_name:
        flags.append("route_name_mismatch")
    if expect_non_empty and total_rows <= 0:
        flags.append("unexpected_empty_result")
    if total_rows > 0 and _mentions_no_result(summary):
        flags.append("report_claims_empty_but_has_rows")
    if total_rows > row_count and row_count > 0 and not _mentions_sample_scope(summary):
        flags.append("large_result_without_sample_scope")
    if total_rows == 0 and expected_query_type in {"clarify", "out_of_scope"} and row_count != 0:
        flags.append("non_query_route_returned_rows")
    if total_rows > 0 and not summary.startswith("查询报告"):
        flags.append("report_format_missing_title")

    return {
        "route_match": actual_query_type == expected_query_type,
        "status_match": actual_status == expected_status,
        "route_name_match": (not expected_route_name) or route_decision.route_name == expected_route_name,
        "non_empty_expectation_met": (not expect_non_empty) or total_rows > 0,
        "flags": flags,
    }


def _mentions_no_result(summary: str) -> bool:
    return any(
        phrase in summary
        for phrase in (
            "没有返回匹配记录",
            "未返回匹配记录",
            "未返回可展示",
            "数据库未返回匹配记录",
            "未查询到",
        )
    )


def _mentions_sample_scope(summary: str) -> bool:
    return any(
        phrase in summary
        for phrase in (
            "样本",
            "前20条",
            "前 20 条",
            "前200条",
            "前 200 条",
            "当前展示前",
            "仅基于返回结果中的前20条",
            "仅基于返回结果中的前 20 条",
        )
    )


def build_report(run_payload: dict) -> str:
    generated_at = run_payload["generated_at"]
    dataset_name = run_payload["dataset"]["name"]
    results = run_payload["results"]
    total_cases = len(results)
    total_elapsed_seconds = run_payload["summary"]["total_elapsed_seconds"]

    route_counter = Counter(item["expected"]["query_type"] for item in results)
    route_match_counter = Counter(
        item["expected"]["query_type"] for item in results if item["checks"]["route_match"]
    )
    status_match_counter = Counter(
        item["expected"]["query_type"] for item in results if item["checks"]["status_match"]
    )
    empty_failures = [
        item for item in results if "unexpected_empty_result" in item["checks"]["flags"]
    ]
    flagged_cases = [item for item in results if item["checks"]["flags"]]
    slowest_cases = sorted(
        results,
        key=lambda item: item["timing"]["elapsed_seconds"],
        reverse=True,
    )[:10]

    lines = [
        "# Agent 效果测试报告",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 数据集：`{dataset_name}`",
        f"- 总题数：`{total_cases}`",
        f"- 总耗时：`{total_elapsed_seconds:.3f}` 秒",
        "",
        "## 一、总体结论",
        "",
        f"- 路由匹配题数：`{sum(route_match_counter.values())} / {total_cases}`",
        f"- 状态匹配题数：`{sum(status_match_counter.values())} / {total_cases}`",
        f"- 需要关注的异常题数：`{len(flagged_cases)}`",
        f"- 其中非预期空结果题数：`{len(empty_failures)}`",
        "",
        "## 二、按路由分类统计",
        "",
        "| 路由 | 题数 | 路由匹配 | 状态匹配 |",
        "|---|---:|---:|---:|",
    ]

    for route_name in ("db_query", "template_query", "result_analysis", "clarify", "out_of_scope"):
        total = route_counter.get(route_name, 0)
        route_ok = route_match_counter.get(route_name, 0)
        status_ok = status_match_counter.get(route_name, 0)
        lines.append(f"| {route_name} | {total} | {route_ok} | {status_ok} |")

    lines.extend(
        [
            "",
            "## 三、重点异常清单",
            "",
        ]
    )

    if not flagged_cases:
        lines.append("本轮没有检测到自动规则能识别的异常项。")
    else:
        for item in flagged_cases:
            lines.extend(
                [
                    f"### {item['id']} {item['question']}",
                    "",
                    f"- 预期：`{item['expected']['query_type']}` / `{item['expected']['status']}`",
                    f"- 实际：`{item['result']['query_type']}` / `{item['result']['status']}`",
                    f"- 标记：`{', '.join(item['checks']['flags'])}`",
                    f"- 总条数：`{item['result']['total_rows']}`，样本条数：`{item['result']['row_count']}`",
                    "",
                ]
            )
            if item["result"]["summary"]:
                lines.append("查询报告摘录：")
                lines.append("")
                lines.append("```text")
                lines.append(item["result"]["summary"][:900])
                lines.append("```")
                lines.append("")

    per_route_samples: dict[str, list[dict]] = defaultdict(list)
    for item in results:
        route = item["expected"]["query_type"]
        if len(per_route_samples[route]) < 3:
            per_route_samples[route].append(item)

    lines.extend(
        [
            "## 四、各路由样例",
            "",
        ]
    )
    for route_name in ("db_query", "template_query", "result_analysis", "clarify", "out_of_scope"):
        lines.append(f"### {route_name}")
        lines.append("")
        for item in per_route_samples.get(route_name, []):
            lines.append(
                f"- `{item['id']}` {item['question']} -> 实际 `{item['result']['query_type']}` / `{item['result']['status']}` / 总条数 `{item['result']['total_rows']}`"
            )
        lines.append("")

    lines.extend(
        [
            "## 五、最慢题目",
            "",
            "| 题目ID | 路由 | 耗时（秒） | 问题 |",
            "|---|---|---:|---|",
        ]
    )
    for item in slowest_cases:
        lines.append(
            f"| {item['id']} | {item['expected']['query_type']} | {item['timing']['elapsed_seconds']:.3f} | {item['question']} |"
        )

    lines.extend(
        [
            "",
            "## 六、下一步建议",
            "",
            "1. 先重点看 `db_query` 和 `result_analysis` 里的非预期空结果题，判断是模型口径问题还是数据库里确实无数据。",
            "2. 重点复查被标记为 `large_result_without_sample_scope` 的题，收紧查询报告对大结果集的描述边界。",
            "3. 对 `query_type_mismatch` 或 `route_name_mismatch` 的题，优先补路由规则或模板命中同义词。",
            "4. 针对高频稳定题，把表现不稳但口径固定的问题继续沉淀为 `template_query`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = build_parser().parse_args()
    dataset_path = Path(args.dataset).resolve()
    dataset = load_dataset(dataset_path)
    cases = filter_cases(dataset["cases"], args.route, args.question, args.limit)
    if not cases:
        raise SystemExit("没有选中任何测试题，请检查 --route / --question / --limit 参数。")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = RESULTS_DIR / f"agent_effectiveness_results_{timestamp}.json"
    report_path = REPORTS_DIR / f"agent_effectiveness_report_{timestamp}.md"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    run_results = []
    total = len(cases)
    run_started_perf = time.perf_counter()
    for index, case in enumerate(cases, start=1):
        print(f"\n===== [{index}/{total}] {case['id']} {case['question']} =====")
        record = run_case(case, args.per_case_timeout)
        run_results.append(record)
        print(
            json.dumps(
                {
                    "expected_query_type": record["expected"]["query_type"],
                    "actual_query_type": record["result"]["query_type"],
                    "status": record["result"]["status"],
                    "total_rows": record["result"]["total_rows"],
                    "elapsed_seconds": record["timing"]["elapsed_seconds"],
                    "flags": record["checks"]["flags"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    total_elapsed_seconds = round(time.perf_counter() - run_started_perf, 3)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": {
            "name": dataset.get("name"),
            "version": dataset.get("version"),
            "path": str(dataset_path),
            "case_count": len(cases),
        },
        "summary": {
            "total_elapsed_seconds": total_elapsed_seconds,
            "average_elapsed_seconds": round(total_elapsed_seconds / len(cases), 3),
        },
        "results": run_results,
    }
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_text = build_report(payload)
    report_path.write_text(report_text, encoding="utf-8")

    print(f"\n结构化结果已写入：{results_path}")
    print(f"分析报告已写入：{report_path}")


if __name__ == "__main__":
    main()

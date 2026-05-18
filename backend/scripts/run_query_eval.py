"""批量运行查询评测题，并导出结果。

运行方式示例：

    conda run -n dm python backend/scripts/run_query_eval.py
    conda run -n dm python backend/scripts/run_query_eval.py --limit 5
    conda run -n dm python backend/scripts/run_query_eval.py --question "查询渝北区高切坡基本信息"

输出：
1. 终端打印简要摘要；
2. backend/runtime/query_eval_results.json 写入结构化结果，便于继续人工评估。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.agent import run_agent


ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "backend" / "runtime" / "query_eval_results.json"

DEFAULT_QUESTIONS = [
    "查询渝北区高切坡基本信息",
    "查询渝北地区高切坡信息",
    "查询最近30天的预警专报记录",
    "查询渝北区最近的巡查异常记录",
    "我想知道哪些高切坡处于异常状态，并告诉我属于哪一种异常类型",
    "对比一下各区县高切坡异常数量",
    "帮我分析最近异常高切坡的分布情况",
    "帮我分析 2024 年预警高切坡的分布情况",
    "查询最近有哪些高切坡处于异常状态",
    "查一下",
    "查询系统账号和密码",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行高切坡智能查询评测题集")
    parser.add_argument("--limit", type=int, default=0, help="仅运行前 N 道默认题目")
    parser.add_argument("--question", action="append", default=[], help="单独附加要测试的问题，可多次传入")
    return parser


def summarize_result(result: dict) -> dict:
    rows = result.get("rows") or []
    return {
        "status": result.get("status"),
        "query_type": result.get("query_type"),
        "sql": result.get("sql"),
        "summary": result.get("summary"),
        "row_count": len(rows),
        "total_rows": result.get("total_rows", len(rows)),
        "columns": result.get("columns") or [],
        "sample_rows": rows[:5],
        "error": result.get("error"),
    }


def main() -> None:
    args = build_parser().parse_args()

    questions = list(DEFAULT_QUESTIONS)
    if args.limit and args.limit > 0:
        questions = questions[: args.limit]
    if args.question:
        questions.extend(args.question)

    results = []
    for index, question in enumerate(questions, start=1):
        print(f"\n===== [{index}] {question} =====")
        try:
            result = run_agent(question)
            summary = summarize_result(result)
            results.append({"question": question, "result": summary})
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        except Exception as exc:
            failure = {
                "status": "error",
                "query_type": "error",
                "sql": "",
                "summary": "",
                "row_count": 0,
                "total_rows": 0,
                "columns": [],
                "sample_rows": [],
                "error": str(exc),
            }
            results.append({"question": question, "result": failure})
            print(json.dumps(failure, ensure_ascii=False, indent=2))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "question_count": len(results),
        "results": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n评测结果已写入：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()

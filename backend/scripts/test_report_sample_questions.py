from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import DM_HOST, DM_PASSWORD, DM_PORT, DM_USER  # noqa: E402


def dm_engine():
    password = quote_plus(DM_PASSWORD)
    return create_engine(f"dm+dmPython://{DM_USER}:{password}@{DM_HOST}:{DM_PORT}/")


def run_question_check(conn, question: dict) -> tuple[str, str]:
    qid = question["question_id"]
    qtype = question["query_type"]
    source = question["expected_source"]

    if qtype in {"summary", "risk", "monitoring_workload", "knowledge_inventory"}:
        row = conn.execute(text("""
            SELECT COUNT(*) FROM ai_report_page_sample
            WHERE file_name=:source AND LENGTH(text_excerpt) > 20
        """), {"source": source}).scalar()
        return ("passed" if row else "failed", f"matched_text_pages={row}")

    if qtype == "table":
        row = conn.execute(text("""
            SELECT COUNT(*) FROM ai_report_page_sample
            WHERE file_name=:source AND (asset_type='表格/统计' OR table_score > 0)
        """), {"source": source}).scalar()
        return ("passed" if row else "failed", f"matched_table_pages={row}")

    if qtype == "photo":
        row = conn.execute(text("""
            SELECT COUNT(*) FROM ai_report_asset_sample
            WHERE file_name=:source AND (asset_type IN ('现场照片/图片', '图片') OR image_count_on_page > 0)
        """), {"source": source}).scalar()
        return ("passed" if row else "failed", f"matched_photo_assets={row}")

    if qtype in {"chart", "chart_analysis"}:
        row = conn.execute(text("""
            SELECT COUNT(*) FROM ai_report_page_sample
            WHERE file_name=:source AND (asset_type='监测曲线/折线图' OR chart_score > 0)
        """), {"source": source}).scalar()
        return ("passed" if row else "failed", f"matched_chart_pages={row}")

    return "skipped", f"unknown_query_type={qtype}; question_id={qid}"


def main() -> int:
    engine = dm_engine()
    results = []
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT question_id, question, expected_source, county, report_year, report_month,
                       query_type, expected_asset_type
                FROM ai_report_question_sample
                ORDER BY question_id
            """)).mappings().all()
            for row in rows:
                question = dict(row)
                status, detail = run_question_check(conn, question)
                conn.execute(text("""
                    UPDATE ai_report_question_sample
                    SET test_status=:status, test_result=:detail
                    WHERE question_id=:question_id
                """), {
                    "status": status,
                    "detail": detail,
                    "question_id": question["question_id"],
                })
                results.append({**question, "test_status": status, "test_result": detail})
    finally:
        engine.dispose()

    summary = {
        "total": len(results),
        "passed": sum(1 for item in results if item["test_status"] == "passed"),
        "failed": sum(1 for item in results if item["test_status"] == "failed"),
        "skipped": sum(1 for item in results if item["test_status"] == "skipped"),
        "by_type": {},
    }
    for item in results:
        qtype = item["query_type"]
        summary["by_type"].setdefault(qtype, {"total": 0, "passed": 0, "failed": 0, "skipped": 0})
        summary["by_type"][qtype]["total"] += 1
        summary["by_type"][qtype][item["test_status"]] += 1

    out = BACKEND_DIR / "report_extract_sample" / "report_question_test_results.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

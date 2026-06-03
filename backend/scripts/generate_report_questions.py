from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND_DIR / "report_extract"


@dataclass
class GeneratedQuestion:
    question_id: str
    question: str
    expected_source: str
    county: str
    report_year: int | None
    report_month: int | None
    query_type: str
    expected_asset_type: str
    test_status: str = "pending"
    test_result: str = ""


def load_docs(out_dir: Path) -> list[dict]:
    path = out_dir / "report_doc_index.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_period(doc: dict) -> str:
    year = doc.get("report_year")
    month = doc.get("report_month")
    if year and month:
        return f"{year}年{month}月"
    if year:
        return f"{year}年"
    return "该期"


def qid(source: str, question: str) -> str:
    return hashlib.sha1((source + question).encode("utf-8")).hexdigest()[:24]


def add_question(result: list[GeneratedQuestion], doc: dict, question: str, qtype: str, asset_type: str) -> None:
    source = doc.get("file_name", "")
    result.append(
        GeneratedQuestion(
            question_id=qid(source, question),
            question=question,
            expected_source=source,
            county=doc.get("county") or "",
            report_year=doc.get("report_year"),
            report_month=doc.get("report_month"),
            query_type=qtype,
            expected_asset_type=asset_type,
        )
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    docs = load_docs(out_dir)
    questions: list[GeneratedQuestion] = []
    for doc in docs:
        county = doc.get("county") or "该区县"
        period = make_period(doc)
        report_type = doc.get("report_type") or "报告"
        prefix = f"{county}{period}{report_type}"
        add_question(questions, doc, f"{prefix}的主要监测结论是什么？", "summary", "文本")
        add_question(questions, doc, f"{prefix}中提到了哪些异常、风险、预警或处置情况？", "risk", "文本")
        add_question(questions, doc, f"{prefix}有哪些统计表或监测成果表可以查看？", "table", "表格/统计")
        if doc.get("image_count", 0) > 0:
            add_question(questions, doc, f"{prefix}包含哪些现场照片或图片资料？", "photo", "现场照片/图片")
        if doc.get("chart_page_count", 0) > 0:
            add_question(questions, doc, f"{prefix}有哪些监测点累计位移曲线或折线图？", "chart", "监测曲线/折线图")
            add_question(questions, doc, f"{prefix}中监测点曲线反映了哪些位移变化趋势？", "chart_analysis", "监测曲线/折线图")
        if "专业监测" in report_type or "简报" in report_type:
            add_question(questions, doc, f"{prefix}的基准点、监测点和周期观测情况是什么？", "monitoring_workload", "文本")
        if county in {"兴山县", "夷陵区", "秭归县", "巴东县"}:
            add_question(questions, doc, f"{period}{county}高切坡监测资料中哪些内容适合进入业务知识库？", "knowledge_inventory", "综合")
        if len(questions) >= args.limit:
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "report_generated_questions.json"
    out.write_text(json.dumps([asdict(item) for item in questions[: args.limit]], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"questions": len(questions[: args.limit]), "out": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

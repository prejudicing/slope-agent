from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.nlq.business_queries import get_deterministic_query  # noqa: E402
from app.nlq.query_router import route_question  # noqa: E402


QUESTIONS = [
    "近期哪个区县高切坡可能出现风险",
    "最近哪些区县的高切坡风险比较高",
    "当前哪个地方高切坡需要重点关注",
    "哪些区域高切坡近期可能不稳定",
    "最近高切坡隐患主要集中在哪个区县",
    "近期高切坡风险区县排序",
    "现在哪些区县高切坡比较危险",
    "哪个区县高切坡近期异常更多",
    "近期高切坡重点关注区域有哪些",
    "高切坡近期风险主要在哪些地方",
    "近期专业监测情况",
    "最近专业监测怎么样",
    "专业监测近期有什么变化",
    "专业监测高切坡近期情况",
    "近期专业监测点位移情况",
    "最近专业监测点变化大吗",
    "专业监测位移变化较大的坡有哪些",
    "近期专业监测哪些坡要关注",
    "看一下专业监测近期情况",
    "专业监测最近有没有风险",
    "近期群测群防情况",
    "最近群测群防监测情况",
    "群测群防近期有没有异常",
    "近期群测群防异常有哪些",
    "最近现场巡查异常情况",
    "近期群众监测发现了什么",
    "群测群防最近情况怎么样",
    "查看近期群测群防记录",
    "近期现场照片异常有哪些",
    "最近裂缝落石现场情况",
    "巴东高切坡情况",
    "巴东县高切坡概况",
    "巴东高切坡现在怎么样",
    "巴东县高切坡近期情况",
    "巴东有哪些高切坡需要关注",
    "巴东专业监测情况",
    "巴东群测群防情况",
    "巴东县近期风险情况",
    "巴东高切坡有没有异常",
    "巴东高切坡整体情况",
    "兴山高切坡情况",
    "兴山县高切坡概况",
    "兴山专业监测情况",
    "兴山群测群防情况",
    "兴山近期哪个坡变化较大",
    "兴山县高切坡近期风险",
    "兴山高切坡有没有隐患",
    "兴山县现场异常情况",
    "兴山专业监测位移情况",
    "兴山高切坡总体情况",
    "夷陵高切坡情况",
    "夷陵区高切坡概况",
    "夷陵专业监测情况",
    "夷陵群测群防情况",
    "夷陵近期风险怎么样",
    "夷陵区高切坡有没有异常",
    "夷陵高切坡专业监测点情况",
    "夷陵现场巡查近期情况",
    "夷陵高切坡整体情况",
    "夷陵哪些坡需要关注",
    "秭归高切坡情况",
    "秭归县高切坡概况",
    "秭归专业监测情况",
    "秭归群测群防情况",
    "秭归近期风险情况",
    "秭归高切坡有没有异常",
    "秭归专业监测位移变化",
    "秭归现场异常情况",
    "秭归高切坡整体情况",
    "秭归哪些坡风险较高",
    "生成近期高切坡业务情况简报",
    "近期高切坡业务情况",
    "最近高切坡总体情况",
    "近期高切坡有哪些需要关注",
    "高切坡近期简报",
    "帮我总结近期高切坡情况",
    "生成高切坡近期情况业务简报",
    "近期高切坡风险和处置建议",
    "最近高切坡监测结论",
    "当前高切坡整体风险情况",
    "哪个区县专业监测变化最大",
    "哪些区县专业监测风险高",
    "专业监测风险集中在哪",
    "近期位移变化大的区县",
    "高切坡位移风险哪个区县更突出",
    "最近专业监测预警区县",
    "年度位移变化较大的区县",
    "近期不稳定高切坡在哪些区县",
    "高切坡专业监测风险排序",
    "从专业监测看哪个区县风险更高",
    "最近群测群防异常多的区县",
    "群测群防风险在哪些地方",
    "近期现场异常集中在哪",
    "哪些区县现场照片异常明显",
    "最近裂缝落石主要在哪些区县",
    "群测群防近期风险排序",
    "现场巡查哪个区县问题多",
    "高切坡现场异常风险区县",
    "近期群测群防重点关注区域",
    "群测群防和专业监测综合风险",
]


EXPECTED_KEYWORDS = {
    "recent_risk_county": ("风险", "危险", "隐患", "不稳定", "重点关注", "排序"),
    "recent_large_displacement": ("专业监测", "位移", "监测点"),
    "recent_monitoring_abnormal": ("群测群防", "现场", "巡查", "裂缝", "落石"),
    "county_overview": ("巴东", "兴山", "夷陵", "秭归"),
    "recent_slope_brief": ("简报", "总体", "整体", "综合"),
}


def expected(question: str) -> str:
    if any(word in question for word in ("群测群防", "现场", "巡查", "裂缝", "落石")):
        return "recent_monitoring_abnormal"
    if any(word in question for word in ("区县", "集中", "排序", "哪个")) and any(word in question for word in ("风险", "位移变化", "变化大", "较大")):
        return "recent_risk_county"
    if any(word in question for word in ("专业监测", "位移", "监测点")) and any(word in question for word in ("情况", "变化", "风险", "关注", "排序", "大")):
        if "区县" in question and any(word in question for word in ("风险", "排序", "集中", "哪个")):
            return "recent_risk_county"
        return "recent_large_displacement"
    if "高切坡" in question and any(word in question for word in ("整体风险", "总体风险", "综合风险")):
        return "recent_slope_brief"
    if any(word in question for word in ("哪个区县", "哪些区县", "区域", "地方")) and any(word in question for word in ("风险", "隐患", "危险", "不稳定", "重点关注")):
        return "recent_risk_county"
    if any(word in question for word in ("巴东", "兴山", "夷陵", "秭归")) and "高切坡" in question:
        if any(word in question for word in ("风险", "隐患", "异常", "关注")):
            return "recent_risk_county"
        return "county_overview"
    if any(word in question for word in ("简报", "总体", "整体", "综合")):
        return "recent_slope_brief"
    return "db_query"


def main() -> None:
    results = []
    for question in QUESTIONS:
        decision = route_question(question)
        query = get_deterministic_query(question)
        actual = query["name"] if query else decision.route_name or decision.query_type
        exp = expected(question)
        ok = actual == exp or (exp == "db_query" and decision.status == "query")
        results.append({
            "question": question,
            "expected": exp,
            "actual": actual,
            "status": decision.status,
            "ok": ok,
        })
    summary = {
        "total": len(results),
        "passed": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "actual_counts": dict(Counter(item["actual"] for item in results)),
        "failed_items": [item for item in results if not item["ok"]],
    }
    out_dir = BACKEND_DIR / "generated" / "question_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "natural_language_questions.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**summary, "output": str(out_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

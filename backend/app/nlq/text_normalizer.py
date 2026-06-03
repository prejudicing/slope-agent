"""Text normalization helpers for user-facing query input."""

from __future__ import annotations


TRADITIONAL_TO_SIMPLIFIED = {
    "專": "专",
    "業": "业",
    "監": "监",
    "測": "测",
    "變": "变",
    "較": "较",
    "點": "点",
    "關": "关",
    "風": "风",
    "險": "险",
    "區": "区",
    "縣": "县",
    "鄉": "乡",
    "鎮": "镇",
    "問": "问",
    "題": "题",
    "詢": "询",
    "統": "统",
    "計": "计",
    "緩": "缓",
    "顯": "显",
    "穩": "稳",
    "評": "评",
    "價": "价",
    "預": "预",
    "縫": "缝",
    "擋": "挡",
    "牆": "墙",
    "現": "现",
    "場": "场",
    "異": "异",
    "數": "数",
    "據": "据",
    "簡": "简",
    "報": "报",
    "會": "会",
    "話": "话",
    "導": "导",
    "載": "载",
    "處": "处",
    "聯": "联",
    "繫": "系",
    "電": "电",
    "員": "员",
    "狀": "状",
    "態": "态",
    "況": "况",
    "圖": "图",
    "軸": "轴",
    "積": "积",
    "臺": "台",
    "灣": "湾",
    "歸": "归",
    "夷": "夷",
    "陵": "陵",
    "秭": "秭",
    "巴": "巴",
    "東": "东",
    "興": "兴",
    "山": "山",
}


PHRASE_REPLACEMENTS = (
    ("高切破", "高切坡"),
    ("高清坡", "高切坡"),
    ("高青坡", "高切坡"),
    ("高边坡", "高切坡"),
    ("群测群房", "群测群防"),
    ("群策群防", "群测群防"),
    ("专页监测", "专业监测"),
    ("專業監測", "专业监测"),
    ("位移變化量", "位移变化量"),
    ("近期群測群防情況", "近期群测群防情况"),
    ("其哪些", "哪些"),
)


def normalize_query_text(text: str | None) -> str:
    """Normalize ASR/user query text to simplified Chinese business wording."""
    if not text:
        return ""
    normalized = "".join(TRADITIONAL_TO_SIMPLIFIED.get(ch, ch) for ch in str(text))
    normalized = "".join(normalized.split())
    for old, new in PHRASE_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized

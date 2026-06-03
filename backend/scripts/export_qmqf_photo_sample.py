from __future__ import annotations

import json
from pathlib import Path

from app.dashboards.qmqf_dashboard import get_qmqf_abnormal_dashboard


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "generated" / "qmqf_crack_test" / "sample_photos.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    data = get_qmqf_abnormal_dashboard(limit=12)
    samples = []
    for item in data.get("items", []):
        for photo in item.get("photos", [])[:3]:
            samples.append({
                "gqpbh": item.get("gqpbh", ""),
                "gqpmc": item.get("gqpmc", ""),
                "ssqx": item.get("ssqx", ""),
                "abnormal_types": item.get("abnormal_types", []),
                "severity": item.get("severity", ""),
                "photo": photo,
                "has_crack_label": item.get("has_crack_marker", False),
            })
            if len(samples) >= 30:
                break
        if len(samples) >= 30:
            break
    output.write_text(json.dumps({"samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

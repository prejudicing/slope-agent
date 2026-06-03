from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


PHOTO_BASE_URL = "http://1.13.19.44:8080/u/mon"


def build_image_url(value: str) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("http"):
        return raw
    normalized = raw.replace("\\", "/").lstrip("/")
    if normalized.lower().startswith("u/mon/"):
        return f"http://1.13.19.44:8080/{normalized}"
    filename = normalized.split("/")[-1] or normalized
    month = ""
    parts = normalized.split("/")
    for part in parts:
        if len(part) == 6 and part.startswith("20") and part.isdigit():
            month = part
            break
    if not month:
        marker = filename.find("_20")
        if marker >= 0 and marker + 7 <= len(filename):
            month = filename[marker + 1: marker + 7]
    return f"{PHOTO_BASE_URL}/{month}/{filename}" if month else f"{PHOTO_BASE_URL}/{normalized}"


def download(url: str, target: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GQPAI-crack-test/1.0"})
        with urllib.request.urlopen(req, timeout=12) as response:
            if response.status != 200:
                return False
            target.write_bytes(response.read())
        return True
    except Exception:
        return False


def detect_candidates(image_path: Path, output_path: Path) -> dict:
    image = Image.open(image_path).convert("RGB")
    original_size = image.size
    max_width = 960
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)))

    gray = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = gray.shape
    # Keep thin, dark, locally high-contrast structures. This is a trial
    # detector, not a final crack model.
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    edge = gx + gy
    local_dark = gray < np.percentile(gray, 38)
    strong_edge = edge > np.percentile(edge, 92)
    mask = local_dark & strong_edge

    # Downweight common building/window straight edges by removing long perfect
    # horizontal/vertical runs.
    row_counts = mask.sum(axis=1)
    col_counts = mask.sum(axis=0)
    mask[row_counts > w * 0.35, :] = False
    mask[:, col_counts > h * 0.35] = False

    visited = np.zeros(mask.shape, dtype=bool)
    candidates = []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if not mask[y, x] or visited[y, x]:
                continue
            stack = [(x, y)]
            visited[y, x] = True
            points = []
            while stack:
                px, py = stack.pop()
                points.append((px, py))
                for nx in range(max(0, px - 1), min(w, px + 2)):
                    for ny in range(max(0, py - 1), min(h, py + 2)):
                        if not visited[ny, nx] and mask[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((nx, ny))
            if len(points) < 16:
                continue
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            bw = x1 - x0 + 1
            bh = y1 - y0 + 1
            area = bw * bh
            if area <= 0:
                continue
            fill = len(points) / area
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if aspect < 2.2 or fill > 0.45:
                continue
            score = min(0.95, 0.35 + 0.08 * math.log(len(points) + 1) + 0.05 * min(aspect, 8))
            candidates.append((score, x0, y0, x1, y1, len(points)))

    candidates = sorted(candidates, reverse=True)[:4]
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    for score, x0, y0, x1, y1, _ in candidates:
        pad = 10
        box = (max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad))
        draw.ellipse(box, outline=(225, 29, 72), width=4)
        draw.text((box[0], max(0, box[1] - 18)), f"{score:.2f}", fill=(225, 29, 72))
    marked.save(output_path)
    return {
        "original_size": original_size,
        "candidate_count": len(candidates),
        "max_score": round(candidates[0][0], 2) if candidates else 0,
        "candidates": [
            {"score": round(score, 2), "box": [x0, y0, x1, y1], "pixels": pixels}
            for score, x0, y0, x1, y1, pixels in candidates
        ],
    }


def write_report(results: list[dict], output_path: Path) -> None:
    cards = []
    for item in results:
        cards.append(f"""
        <article>
          <div class="meta">
            <strong>{item['gqpmc']}</strong>
            <span>{item['gqpbh']} · {item['ssqx']} · {item['abnormal_summary']}</span>
          </div>
          <div class="imgs">
            <a href="{item['source_url']}" target="_blank"><img src="{item['local_raw_url']}" /></a>
            <a href="{item['marked_url']}" target="_blank"><img src="{item['marked_url']}" /></a>
          </div>
          <p>候选部位 {item['candidate_count']} 个，最高置信 {item['max_score']:.2f}。当前结果为测试算法候选，不作为最终裂缝判定。</p>
        </article>
        """)
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>群测群防裂缝识别测试</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: Arial, "Microsoft YaHei", sans-serif; }}
    main {{ width: min(1280px, calc(100vw - 24px)); margin: 14px auto 24px; }}
    h1 {{ font-size: 22px; margin: 0 0 6px; }}
    .note {{ color: #667085; margin: 0 0 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    article {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }}
    .meta strong {{ display: block; line-height: 1.45; }}
    .meta span {{ display: block; margin-top: 3px; color: #667085; font-size: 13px; }}
    .imgs {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 10px; }}
    img {{ width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border: 1px solid #d9e3f5; border-radius: 8px; }}
    p {{ color: #475467; font-size: 13px; line-height: 1.6; margin: 10px 0 0; }}
    @media (max-width: 860px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>群测群防裂缝识别测试</h1>
    <p class="note">左侧为原图，右侧为疑似裂缝候选红圈。此页用于测试误报，后续可接正式图像识别模型。</p>
    <div class="grid">{''.join(cards)}</div>
  </main>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "generated" / "qmqf_crack_test"
    sample_path = root / "sample_photos.json"
    raw_dir = root / "raw"
    marked_dir = root / "marked"
    raw_dir.mkdir(parents=True, exist_ok=True)
    marked_dir.mkdir(parents=True, exist_ok=True)
    samples = json.loads(sample_path.read_text(encoding="utf-8")).get("samples", [])
    results = []
    for index, sample in enumerate(samples[:24], 1):
        url = build_image_url(sample["photo"])
        raw_path = raw_dir / f"sample_{index:02d}.jpg"
        marked_path = marked_dir / f"sample_{index:02d}_marked.jpg"
        if not raw_path.exists() and not download(url, raw_path):
            continue
        detection = detect_candidates(raw_path, marked_path)
        item = {
            **sample,
            "source_url": url,
            "abnormal_summary": "、".join(sample.get("abnormal_types") or []),
            "local_raw_url": f"/report-assets/qmqf_crack_test/raw/{raw_path.name}",
            "marked_url": f"/report-assets/qmqf_crack_test/marked/{marked_path.name}",
            **detection,
        }
        results.append(item)
    (root / "crack_detection_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(results, root / "crack_detection_report.html")
    print(root / "crack_detection_report.html")


if __name__ == "__main__":
    main()

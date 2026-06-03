from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
BUNDLED_SITE_PACKAGES = Path(
    r"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
)
if BUNDLED_SITE_PACKAGES.exists() and str(BUNDLED_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(BUNDLED_SITE_PACKAGES))

from PIL import Image, ImageEnhance, ImageFilter  # noqa: E402
from pypdf import PdfReader  # noqa: E402


SOURCE_FILE = Path(
    r"C:\Users\DELL\Documents\GQPAI\doc\月报\兴山县高切坡监测工作月报（2025.03）-盖章扫描件.pdf"
)
OUT_DIR = BACKEND_DIR / "generated" / "report_chart_sources" / "xingshan_2025_03"


def enhance_chart_image(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    # The report charts are usually small raster images. Upscale first, then
    # sharpen and boost contrast so line colors and axes are easier to inspect.
    scale = 2
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    image = ImageEnhance.Contrast(image).enhance(1.25)
    image = ImageEnhance.Sharpness(image).enhance(1.8)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=3))
    return image


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(SOURCE_FILE))
    records = []
    for page_no in range(19, 41):
        if page_no > len(reader.pages):
            continue
        page = reader.pages[page_no - 1]
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image_index, image_file in enumerate(images, start=1):
            raw_name = f"page_{page_no:03d}_image_{image_index:02d}.png"
            enhanced_name = f"page_{page_no:03d}_image_{image_index:02d}_enhanced.png"
            raw_path = OUT_DIR / raw_name
            enhanced_path = OUT_DIR / enhanced_name
            try:
                image = image_file.image
                image.save(raw_path)
                enhanced = enhance_chart_image(image)
                enhanced.save(enhanced_path)
                records.append({
                    "page_no": page_no,
                    "image_index": image_index,
                    "width": image.width,
                    "height": image.height,
                    "raw_path": str(raw_path),
                    "enhanced_path": str(enhanced_path),
                    "raw_url": f"http://127.0.0.1:8000/report-assets/report_chart_sources/xingshan_2025_03/{raw_name}",
                    "enhanced_url": f"http://127.0.0.1:8000/report-assets/report_chart_sources/xingshan_2025_03/{enhanced_name}",
                })
            except Exception as exc:
                records.append({
                    "page_no": page_no,
                    "image_index": image_index,
                    "error": str(exc),
                })
    index_path = OUT_DIR / "index.json"
    index_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"source": str(SOURCE_FILE), "images": len(records), "out": str(index_path)}, ensure_ascii=False, indent=2))
    for record in records[:12]:
        print(record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

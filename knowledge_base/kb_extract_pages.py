#!/usr/bin/env python3
"""把 moves.json 里 book_ref 引用到的教材页渲染成 JPEG，供 moves_viewer.html 展示。

用法：python3 knowledge_base/kb_extract_pages.py
依赖：poppler（brew install poppler，用其中的 pdftoppm）
输出：knowledge_base/book_pages/p{印刷页码:03d}.jpg（不入 git，可随时重新生成）

页码换算：PDF 文件页码 = 书本印刷页码 + 2（封面 + 版权页共两页无印刷编号，已实测校验）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
PDF = HERE.parent / "攀岩技術教本詳細圖解_抓撐轉跳我就是蜘蛛人.pdf"
MOVES_JSON = HERE / "moves.json"
OUT_DIR = HERE / "book_pages"
DPI = 110
PDF_PAGE_OFFSET = 2  # PDF页 = 印刷页 + 2

PAGE_RE = re.compile(r"p\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?")


def pages_from_ref(ref: str) -> list[int]:
    pages = set()
    for lo, hi in PAGE_RE.findall(ref):
        lo = int(lo)
        hi = int(hi) if hi else lo
        pages.update(range(lo, hi + 1))
    return sorted(pages)


def main():
    if not PDF.exists():
        sys.exit(f"❌ 找不到教材 PDF：{PDF}")
    moves = json.loads(MOVES_JSON.read_text(encoding="utf-8"))
    all_pages = sorted({p for m in moves for p in pages_from_ref(m["book_ref"])})
    OUT_DIR.mkdir(exist_ok=True)

    rendered, skipped = 0, 0
    for printed in all_pages:
        out = OUT_DIR / f"p{printed:03d}.jpg"
        if out.exists():
            skipped += 1
            continue
        pdf_page = printed + PDF_PAGE_OFFSET
        subprocess.run(
            [
                "pdftoppm", "-jpeg", "-jpegopt", "quality=72",
                "-r", str(DPI),
                "-f", str(pdf_page), "-l", str(pdf_page),
                "-singlefile",
                str(PDF), str(out.with_suffix("")),
            ],
            check=True,
        )
        rendered += 1

    total_mb = sum(f.stat().st_size for f in OUT_DIR.glob("p*.jpg")) / 1e6
    print(f"✅ book_pages/：新渲染 {rendered} 页，已存在跳过 {skipped} 页，"
          f"共 {len(all_pages)} 页引用，合计 {total_mb:.1f} MB")


if __name__ == "__main__":
    main()

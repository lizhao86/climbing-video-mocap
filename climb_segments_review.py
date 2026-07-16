#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_segments_review.py —— 生成分段审阅视频（老板人眼核对边界用）

把 <base>_segments.json 的 move/static 分段烧进原视频：
  - 顶部横幅：橙=MOVE（标段号+主导肢体），灰=static，含时间码
  - 底部分段时间轴：全程段落色条 + 白色播放头，预判下一个边界
输出 H.264 mp4，手机/QuickTime 直接播。

用法：
  /opt/homebrew/bin/python3 climb_segments_review.py <原视频> <segments.json> [--out xxx.mp4]
"""
import json, os, sys, argparse, subprocess, tempfile
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    # Windows（2026-07-16 补：原来只有 Mac 路径，next() 在 Windows 上直接 StopIteration）
    "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",    # 黑体
    "C:/Windows/Fonts/simsun.ttc",    # 宋体
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
FONT = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
if FONT is None:
    sys.exit("找不到中文字体，请把可用字体路径加进 FONT_CANDIDATES：\n  " +
             "\n  ".join(FONT_CANDIDATES))
C_MOVE = (255, 216, 168)    # 橙（RGB）
C_STAT = (222, 226, 230)    # 灰
C_MOVE_D = (232, 89, 12)    # 深橙（时间轴）
C_STAT_D = (134, 142, 150)  # 深灰


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("segjson")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    seg = json.load(open(args.segjson))
    segs = seg["segments"]
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.video)), "标注视频",
        f"{seg['base']}_segments_review.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_s = segs[-1]["end_s"]

    banner_h = max(64, H // 18)
    bar_h = max(20, H // 60)
    font = ImageFont.truetype(FONT, int(banner_h * 0.52))
    font_s = ImageFont.truetype(FONT, int(bar_h * 0.9))

    # 预生成整条时间轴色条（宽 W）
    bar = np.zeros((bar_h, W, 3), dtype=np.uint8)
    for s in segs:
        x0 = int(s["start_s"] / total_s * W); x1 = max(x0 + 1, int(s["end_s"] / total_s * W))
        c = C_MOVE_D if s["kind"] == "move" else C_STAT_D
        bar[:, x0:x1] = c[::-1]  # BGR

    events = seg.get("events", [])

    def seg_at(ts):
        for i, s in enumerate(segs):
            if ts <= s["end_s"]: return i, s
        return len(segs) - 1, segs[-1]

    def limbs_at(ts):
        """当前时刻正在换点的肢体（按位移大小排序），带 manual 标记。"""
        act = [e for e in events if e["start_s"] <= ts <= e["end_s"]]
        act.sort(key=lambda e: -e["disp"])
        return act

    tmp = tempfile.mktemp(suffix=".mp4")
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok: break
        ts = n / fps
        i, s = seg_at(min(ts, total_s))
        is_move = s["kind"] == "move"

        # 顶部横幅（PIL 画中文）
        pil = Image.new("RGB", (W, banner_h), C_MOVE if is_move else C_STAT)
        d = ImageDraw.Draw(pil)
        if is_move:
            act = limbs_at(ts)
            if act:
                parts = ["出" + e["limb"] + ("✎" if e["source"] == "manual" else "")
                         for e in act]
                label = f"#{i}  {' + '.join(parts)}   {s['start_s']:.1f}-{s['end_s']:.1f}s"
            else:
                label = f"#{i}  MOVE   {s['start_s']:.1f}-{s['end_s']:.1f}s"
        else:
            label = f"静止 #{i}   {s['start_s']:.1f}-{s['end_s']:.1f}s"
        d.text((16, banner_h * 0.18), label, font=font, fill=(33, 37, 41))
        tc = f"{ts:5.1f}s"
        d.text((W - 16 - d.textlength(tc, font=font), banner_h * 0.18), tc, font=font, fill=(33, 37, 41))
        frame[0:banner_h] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

        # 底部时间轴 + 播放头
        yb = H - bar_h
        frame[yb:H] = bar
        x = int(min(ts, total_s) / total_s * W)
        cv2.rectangle(frame, (max(0, x - 2), yb - 4), (min(W, x + 2), H), (255, 255, 255), -1)

        vw.write(frame); n += 1
    cap.release(); vw.release()

    # 转 H.264 保证兼容
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                    "-pix_fmt", "yuv420p", out], check=True)
    os.remove(tmp)
    print(f"✅ 审阅视频 → {out}  ({n} 帧, {n/fps:.1f}s)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""climb_keyframes.py —— 卡点关键帧联络表（C 路线，2026-07-18）

对每个「卡住型难点」（metrics_v2 里 source=v2a 的 crux）切 [t-2, t+4] 窗口、
每秒抽一帧，按骨架并集取景裁剪，拼成一张带时间戳的联络表图，供视觉判定用。

为什么只扫卡点不扫全程：视觉判定成本高、可复现性弱（决策文档 C 路线），把它
用在「几何指标已经筛出来的、最值得看的时刻」上，骨架当筛选器、眼睛做判断。

视觉判定协议（判定者=Claude 看联络表，人工同样适用）：
  1. 动作词汇只允许来自 knowledge_base/moves.json 的 54 个动作名；描述错误只允许
     引用其中的 common_errors 或画面直接可见的事实。
  2. 每个判断必须指回具体帧（用图上的时间戳），禁止推断画面外的东西（脚下的点、
     深度方向的弯曲、看不见的那只手）。
  3. 输出写进 <base>_recognition.json 的 crux_notes[]：
     {"t_s": 卡点时刻, "note": "≤3 句，结论先行", "frames_cited": ["19s","22s"],
      "source": "vision", "confidence": "high|medium|low"}
     —— recognition.json 是唯一真相文件，vision 覆写 rule（CLAUDE.md 契约）。
  4. 看不清就写看不清（confidence=low 或不写），不硬猜。

用法：python3 climb_keyframes.py <metrics_v2.json> <视频> [--out-dir D]
输出：<数据目录>/keyframes/stuck_<i>.jpg + 同名 .json（帧时刻清单）
时间轴：cv2 名义时间轴（VFR 素材禁用 ffmpeg -ss，见 CLAUDE.md）。
"""
import json, os, sys, argparse
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import cv2
import numpy as np

WIN_PRE, WIN_POST, STEP_S = 2.0, 4.0, 1.0
TILE_H = 420          # 单帧贴片高度


def imwrite_unicode(path, img, q=90):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
    if not ok:
        raise IOError(f"imencode 失败: {path}")
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("metrics")
    ap.add_argument("video")
    ap.add_argument("--out-dir", default=None)
    A = ap.parse_args()
    M = json.load(open(A.metrics, encoding="utf-8"))
    base = M["base"]
    d = A.out_dir or os.path.join(os.path.dirname(os.path.abspath(A.metrics)), "keyframes")
    os.makedirs(d, exist_ok=True)

    # 骨架包围盒来自 pose2d（取景用），与报告卡同思路
    import csv
    p2 = os.path.join(os.path.dirname(os.path.abspath(A.metrics)), f"{base}_pose2d.csv")
    rows = list(csv.DictReader(open(p2, encoding="utf-8")))
    t = np.array([float(r["time_s"]) for r in rows])
    names = [c[:-3] for c in rows[0] if c.endswith("_nx")]
    X = np.array([[float(r[n + "_nx"]) if r[n + "_nx"] not in ("", "nan") else np.nan
                   for n in names] for r in rows])
    Y = np.array([[float(r[n + "_ny"]) if r[n + "_ny"] not in ("", "nan") else np.nan
                   for n in names] for r in rows])

    cap = cv2.VideoCapture(A.video)
    if not cap.isOpened():
        raise IOError(f"打不开视频: {A.video}")
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    stuck = [c for c in M["crux"]["items"] if c.get("source") == "v2a"]
    made = []
    for i, c in enumerate(stuck):
        ts = c["t"]
        times = [ts - WIN_PRE + k * STEP_S
                 for k in range(int((WIN_PRE + WIN_POST) / STEP_S) + 1) if ts - WIN_PRE + k * STEP_S >= 0]
        # 窗口骨架并集取景（加 25% 余量）
        w0, w1 = np.searchsorted(t, times[0]), np.searchsorted(t, times[-1]) + 1
        xs, ys = X[w0:w1].ravel(), Y[w0:w1].ravel()
        xs, ys = xs[~np.isnan(xs)], ys[~np.isnan(ys)]
        if len(xs) == 0:
            continue
        cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
        bw, bh = (xs.max() - xs.min()) * 1.5, (ys.max() - ys.min()) * 1.25
        bh = max(bh, 0.30); bw = max(bw, bh * 0.6)
        x0 = int(np.clip((cx - bw / 2) * W, 0, W)); x1 = int(np.clip((cx + bw / 2) * W, 0, W))
        y0 = int(np.clip((cy - bh / 2) * H, 0, H)); y1 = int(np.clip((cy + bh / 2) * H, 0, H))

        tiles = []
        for tt in times:
            cap.set(cv2.CAP_PROP_POS_MSEC, tt * 1000.0)
            ok, f = cap.read()
            if not ok:
                continue
            crop = f[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            s = TILE_H / crop.shape[0]
            tile = cv2.resize(crop, (int(crop.shape[1] * s), TILE_H))
            mark = "*" if abs(tt - ts) < STEP_S / 2 else " "
            cv2.putText(tile, f"{tt:.0f}s{mark}", (6, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 255, 255), 2, cv2.LINE_AA)
            tiles.append(tile)
        if not tiles:
            continue
        board = np.hstack(tiles)
        fn = os.path.join(d, f"stuck_{i}.jpg")
        imwrite_unicode(fn, board)
        meta = {"t_s": ts, "kind": c["kind"], "detail": c["detail"],
                "frames_s": [round(x, 1) for x in times], "img": os.path.basename(fn)}
        json.dump(meta, open(os.path.join(d, f"stuck_{i}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        made.append(meta)
    cap.release()
    print(f"✅ {base}: {len(made)} 个卡点联络表 → {d}")
    for m in made:
        print(f"   stuck@{m['t_s']}s ({m['kind']}) → {m['img']}")


if __name__ == "__main__":
    main()

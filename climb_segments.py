#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_segments.py —— 全身动作分段（PLAN.md 决策 §2）

从 v1 的「单肢体 count_moves」升级为全身状态机分段：
  allspeed = max(四肢速度) → 滞回二值化 → 间隙合并/短段丢弃 → move/static 段
move 段记主导肢体、位移方向/幅度、COM 位移、峰值速度；
static 段同样输出（posture 类动作的识别主战场）。

口径与 v1（climb_analyze_report.py）严格对齐：
  - 坐标 pt(n)=(nx, 1.0-ny)，y 向上为正
  - body_scale = median(||肩中-髋中||)，长度/速度全部除以它归一化
  - 四肢速度 = smooth2d(点,9) 求梯度 /dt /body_scale

用法：
  python3 climb_segments.py <pose2d.csv> [--out <segments.json>] [--plot <overlay.png>]
默认从 pose2d.csv 路径推断 <base> 与输出文件名。
"""
import csv, json, sys, os, argparse
import numpy as np

# ── 分段参数（顶部集中，已用 IMG_6952 调参 2026-07-15）──────────────
# PLAN 初值 K_HI=1.0/K_LO=0.4 实测只出 7 个 move 段（allspeed 分布重尾，
# σ=2.71 > mean=2.10，mean+1σ 阈值过高）。0.6/0.2 出 13 段但漏掉慢速爬升
# （12-15s、24-27s 高度升 2+ 身长却被判 static）。0.4/0.1 → 16 段，
# 慢速动作被正确切出、休息平台期仍为 static，与高度曲线吻合。
K_HI      = 0.4    # 进入 move 阈值 = mean + K_HI*σ
K_LO      = 0.1    # 退出 move 阈值 = mean + K_LO*σ（滞回，抗抖动）
GAP_MERGE = 0.40   # 相邻 move 段间隙 < 此秒数则合并
MIN_MOVE  = 0.25   # 合并后 move 段时长 < 此秒数则丢弃（并回 static）
SMOOTH_LIMB = 9    # 四肢点平滑窗（与 v1 limb_speed 一致）

JOINTS = ["nose","left_shoulder","right_shoulder","left_elbow","right_elbow",
          "left_wrist","right_wrist","left_hip","right_hip",
          "left_knee","right_knee","left_ankle","right_ankle"]
LIMBS = {"left_wrist":"左手","right_wrist":"右手",
         "left_ankle":"左脚","right_ankle":"右脚"}


def load_csv(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def col(rows, name):
    o = []
    for r in rows:
        try: o.append(float(r.get(name, "")))
        except Exception: o.append(np.nan)
    return np.array(o)


def smooth2d(a, w=11):
    k = np.ones(w) / w
    out = np.copy(a)
    for c in range(a.shape[1]):
        x = a[:, c].copy(); nan = np.isnan(x)
        if nan.any():
            x[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(~nan), x[~nan])
        out[:, c] = np.convolve(x, k, mode="same")
    return out


def hysteresis(sig, t_hi, t_lo):
    """滞回二值化：>t_hi 进入 active，<t_lo 退出，中间保持上一状态。"""
    active = np.zeros(len(sig), dtype=bool)
    state = False
    for i, v in enumerate(sig):
        if state:
            if v < t_lo: state = False
        else:
            if v > t_hi: state = True
        active[i] = state
    return active


def runs(active):
    """返回连续 True 段的 [start_idx, end_idx_exclusive) 列表。"""
    out = []; i = 0; n = len(active)
    while i < n:
        if active[i]:
            j = i
            while j < n and active[j]: j += 1
            out.append([i, j]); i = j
        else:
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pose2d")
    ap.add_argument("--out", default=None)
    ap.add_argument("--plot", default=None)
    args = ap.parse_args()

    base = os.path.basename(args.pose2d).replace("_pose2d.csv", "").replace(".csv", "")
    outdir = os.path.dirname(os.path.abspath(args.pose2d))
    out_json = args.out or os.path.join(outdir, f"{base}_segments.json")
    out_plot = args.plot or os.path.join(outdir, f"{base}_segments_overlay.png")

    d2 = load_csv(args.pose2d)
    t = col(d2, "time_s"); N = len(t)
    fps = 1.0 / np.nanmedian(np.diff(t))

    def pt(n):
        return np.vstack([col(d2, f"{n}_nx"), 1.0 - col(d2, f"{n}_ny")]).T
    P = {j: pt(j) for j in JOINTS}

    def mid(a, b): return (P[a] + P[b]) / 2
    sh = mid("left_shoulder", "right_shoulder"); hp = mid("left_hip", "right_hip")
    body_scale = np.nanmedian(np.linalg.norm(sh - hp, axis=1))
    dt = np.gradient(t)

    # COM（与 v1 一致的加权重心）
    trunk = (sh + hp) / 2
    thigh = (mid("left_hip", "left_knee") + mid("right_hip", "right_knee")) / 2
    shank = (mid("left_knee", "left_ankle") + mid("right_knee", "right_ankle")) / 2
    arm = (mid("left_shoulder", "left_wrist") + mid("right_shoulder", "right_wrist")) / 2
    com = 0.08 * P["nose"] + 0.50 * trunk + 0.20 * thigh + 0.12 * shank + 0.10 * arm
    com_s = smooth2d(com, 13)

    # 四肢速度（口径同 v1 limb_speed）
    def limb_speed(n):
        p = smooth2d(P[n], SMOOTH_LIMB)
        v = np.gradient(p, axis=0) / dt[:, None] / body_scale
        return np.linalg.norm(v, axis=1)
    lspeed = {k: limb_speed(k) for k in LIMBS}
    allspeed = np.nanmax(np.vstack([lspeed[k] for k in LIMBS]), axis=0)

    mu, sg = np.nanmean(allspeed), np.nanstd(allspeed)
    t_hi = mu + K_HI * sg
    t_lo = mu + K_LO * sg

    # 1) 滞回二值化 → move 段
    active = hysteresis(allspeed, t_hi, t_lo)
    move_runs = runs(active)

    # 2) 间隙 < GAP_MERGE 合并
    merged = []
    for r in move_runs:
        if merged and (t[r[0]] - t[merged[-1][1] - 1]) < GAP_MERGE:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))

    # 3) 合并后时长 < MIN_MOVE 丢弃
    move_runs = [r for r in merged if (t[r[1] - 1] - t[r[0]]) >= MIN_MOVE]

    # 4) move 段之间的空隙 = static 段，拼成完整时间轴
    segments = []
    cursor = 0
    for r in move_runs:
        if r[0] > cursor:
            segments.append(("static", cursor, r[0]))
        segments.append(("move", r[0], r[1]))
        cursor = r[1]
    if cursor < N:
        segments.append(("static", cursor, N))

    def describe(kind, i0, i1):
        i1c = min(i1, N - 1)
        seg = {
            "kind": kind,
            "start_frame": int(i0), "end_frame": int(i1 - 1),
            "start_s": round(float(t[i0]), 2), "end_s": round(float(t[i1c]), 2),
            "dur_s": round(float(t[i1c] - t[i0]), 2),
        }
        com0, com1 = com_s[i0], com_s[i1c]
        seg["com_dx"] = round(float((com1[0] - com0[0]) / body_scale), 3)
        seg["com_dy"] = round(float((com1[1] - com0[1]) / body_scale), 3)
        seg["com_disp"] = round(float(np.linalg.norm(com1 - com0) / body_scale), 3)
        if kind == "move":
            # 主导肢体 = 段内累计路程最大的四肢
            usage = {LIMBS[k]: float(np.nansum(lspeed[k][i0:i1] * dt[i0:i1])) for k in LIMBS}
            dom = max(usage, key=usage.get)
            seg["dominant_limb"] = dom
            seg["peak_com_speed"] = round(float(np.nanpercentile(speed_seg(i0, i1), 99)), 2)
            seg["peak_allspeed"] = round(float(np.nanmax(allspeed[i0:i1])), 2)
            # 位移方向/幅度（身长归一化）
            ang = np.degrees(np.arctan2(seg["com_dy"], seg["com_dx"]))
            seg["com_dir_deg"] = round(float(ang), 1)
            seg["com_up"] = seg["com_dy"] > 0
        return seg

    def speed_seg(i0, i1):
        vel = np.gradient(com_s, axis=0) / dt[:, None] / body_scale
        return np.linalg.norm(vel, axis=1)[i0:i1]

    seg_list = [describe(k, a, b) for (k, a, b) in segments]
    move_ct = sum(1 for s in seg_list if s["kind"] == "move")
    static_ct = len(seg_list) - move_ct

    result = {
        "base": base,
        "fps": round(float(fps), 2),
        "n_frames": int(N),
        "duration_s": round(float(t[-1] - t[0]), 2),
        "body_scale": round(float(body_scale), 4),
        "params": {"K_HI": K_HI, "K_LO": K_LO, "GAP_MERGE": GAP_MERGE,
                   "MIN_MOVE": MIN_MOVE, "SMOOTH_LIMB": SMOOTH_LIMB},
        "thresholds": {"allspeed_mean": round(float(mu), 3),
                       "allspeed_std": round(float(sg), 3),
                       "t_hi": round(float(t_hi), 3), "t_lo": round(float(t_lo), 3)},
        "n_move": move_ct, "n_static": static_ct,
        "segments": seg_list,
    }
    with open(out_json, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 段边界叠加图 ────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "PingFang SC", "Arial Unicode MS", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, ax = plt.subplots(2, 1, figsize=(14, 6), sharex=True)
        ax[0].plot(t, allspeed, color="#495057", lw=0.8, label="allspeed = max(limb)")
        ax[0].axhline(t_hi, color="#d6336c", ls="--", lw=0.8, label=f"T_hi={t_hi:.2f}")
        ax[0].axhline(t_lo, color="#1c7ed6", ls="--", lw=0.8, label=f"T_lo={t_lo:.2f}")
        height = (com_s[:, 1] - np.nanmin(com_s[:, 1])) / body_scale
        ax[1].plot(t, height, color="#1c7ed6", lw=1.0, label="height [bl]")
        for s in seg_list:
            c = "#ffd8a8" if s["kind"] == "move" else "#e9ecef"
            for a in ax:
                a.axvspan(s["start_s"], s["end_s"], color=c, alpha=0.55, lw=0)
        ax[0].set_ylabel("limb speed [bl/s]"); ax[0].legend(loc="upper right", fontsize=8)
        ax[0].set_title(f"{base} 全身分段  move={move_ct}  static={static_ct}  (橙=move 灰=static)")
        ax[1].set_ylabel("height [bl]"); ax[1].set_xlabel("time [s]")
        ax[1].legend(loc="upper left", fontsize=8)
        fig.tight_layout(); fig.savefig(out_plot, dpi=110); plt.close(fig)
        plot_msg = out_plot
    except Exception as e:
        plot_msg = f"(叠加图跳过: {e})"

    print(f"✅ {base}: move={move_ct} static={static_ct} 总={len(seg_list)} 段")
    print(f"   时长 {result['duration_s']}s  fps={result['fps']}  body_scale={result['body_scale']}")
    print(f"   T_hi={t_hi:.3f} T_lo={t_lo:.3f} (mean={mu:.3f} σ={sg:.3f})")
    print(f"   JSON → {out_json}")
    print(f"   叠加图 → {plot_msg}")


if __name__ == "__main__":
    main()

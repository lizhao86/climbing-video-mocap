#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_segments.py —— 全身动作分段（PLAN.md 决策 §2，检测核心 v2）

检测核心 v2（2026-07-16，锚点位移法）：
  每个关节在 DISP_WIN 滑窗内位移 > D_MOVE 即判"正在换点"，
  六关节(四肢端点+双膝)取并集 → 间隙合并/短段丢弃 → move/static 段。
v1 的"速度滞回阈值法"已废弃：对慢速换点有结构性盲区——IMG_6952 的
14-20s 慢速横移整段漏检，与全程 3fps 抽帧人眼直读对照后否决（速度可以
一直低于任何合理阈值，但位移必然累积，位移法无此盲区）。
move 段记主导肢体 + 全部动过的肢体、位移方向/幅度、COM 位移、峰值速度；
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

# ── 分段参数（顶部集中，用 IMG_6952 + 3fps 抽帧人眼时间轴校准）──────
D_MOVE    = 0.30   # 滑窗内位移 > 此值(身长)判"换点中"。换点位移通常 0.3-1.0bl，
                   # 原地微调 <0.2bl；抖动是高频小位移，天然被滤
DISP_WIN  = 0.50   # 位移滑窗时长(s)：慢速换点在 0.5s 内也能累积出可测位移
GAP_MERGE = 0.40   # 相邻 move 段间隙 < 此秒数则合并
MIN_MOVE  = 0.25   # 合并后 move 段时长 < 此秒数则丢弃（并回 static）
SMOOTH_LIMB = 9    # 四肢点平滑窗（与 v1 limb_speed 一致）
# 事件层过滤（对 IMG_6952 人眼时间轴 18 窗口扫参：40 事件/零漏检）
EV_GAP    = 0.50   # 同肢体相邻事件间隙 < 此秒数合并（一次伸手常带微停顿）
EV_MIN_DEV = 0.40  # run 内距起点最大偏移 < 此值(身长)丢弃（抖动）
EV_MIN_DUR = 0.30  # 回吐后事件时长 < 此秒数丢弃

JOINTS = ["nose","left_shoulder","right_shoulder","left_elbow","right_elbow",
          "left_wrist","right_wrist","left_hip","right_hip",
          "left_knee","right_knee","left_ankle","right_ankle"]

# 检测关节池：四肢端点 + 双膝。膝盖纳入是为了捕捉"脚踩住不动、屈膝/开胯
# 调整"这类端点不动的动作（IMG_6952 实测 23.7-24.2s 有一段纯膝部动作）。
TRACK_JOINTS = ["left_wrist","right_wrist","left_ankle","right_ankle",
                "left_knee","right_knee"]

# ⚠️ 主导肢体的左右判定（2026-07-16 用 IMG_6952 全量核对得出）：
# MediaPipe 标签多数段正确（12/15），但扭身/遮挡时会整臂认错人，
# 且几何位置/肩朝向/骨架链距离等启发式都无法可靠识别这些错误段
# （全局镜像互换、几何 x 判定均实测翻错更多）。最终方案：
#   1. 标签默认可信（source=rule）
#   2. 老板核对的错误段走 annotations/<base>_side_overrides.json
#      人工覆写（source=manual），与 recognition.json 分层覆写架构一致
#   3. 躯干朝向不明（|肩向|<0.02，深度扭身）时标 side_confidence=low
LIMB_NAME = {"left_wrist": "左手", "right_wrist": "右手",
             "left_ankle": "左脚", "left_knee": "左脚",
             "right_ankle": "右脚", "right_knee": "右脚"}
TWIST_ORI_TH = 0.02   # 段内 |右肩x-左肩x| 低于此值 → 深度扭身，左右低置信
EDGE_CLAMP_S = 0.25   # 首尾钳制时长：平滑+梯度在边界产生假高速（t=0 实测 19bl/s）


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


def rolling_disp(p, half):
    """每帧在 ±half 帧窗口内的位移模长（端点截断取边界帧）。"""
    n = len(p)
    lo = np.clip(np.arange(n) - half, 0, n - 1)
    hi = np.clip(np.arange(n) + half, 0, n - 1)
    return np.linalg.norm(p[hi] - p[lo], axis=1)


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
    ap.add_argument("--overrides", default=None,
                    help="人工左右覆写 JSON（默认 annotations/<base>_side_overrides.json）")
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

    # 每关节滑窗位移（身长归一化）；速度仅用于段内峰值统计
    n_clamp = max(2, int(EDGE_CLAMP_S * fps))
    half = max(2, int(DISP_WIN * fps / 2))
    psm = {k: smooth2d(P[k], SMOOTH_LIMB) for k in TRACK_JOINTS}
    ldisp = {k: rolling_disp(psm[k], half) / body_scale for k in TRACK_JOINTS}

    def limb_speed(n):
        v = np.gradient(psm[n], axis=0) / dt[:, None] / body_scale
        s = np.linalg.norm(v, axis=1)
        # 首尾钳制：平滑+梯度的边界伪影会造出 15-20bl/s 的假速度
        s[:n_clamp] = s[n_clamp]
        s[-n_clamp:] = s[-n_clamp - 1]
        return s
    lspeed = {k: limb_speed(k) for k in TRACK_JOINTS}
    allspeed = np.nanmax(np.vstack([lspeed[k] for k in TRACK_JOINTS]), axis=0)

    # 1) 换点判定：任一关节滑窗位移超 D_MOVE → 该帧在 move
    moving = {k: ldisp[k] > D_MOVE for k in TRACK_JOINTS}
    active = np.any(np.vstack([moving[k] for k in TRACK_JOINTS]), axis=0)
    move_runs = runs(active)

    # 1.5) 肢体级换点事件（每一手/每一步，S4 动作识别的基本单元）
    #      同肢体多关节(踝|膝)掩码取并；事件边界回吐滑窗带来的 ±half 膨胀
    limb_mask = {}
    for k in TRACK_JOINTS:
        lb = LIMB_NAME[k]
        limb_mask[lb] = limb_mask.get(lb, np.zeros(N, bool)) | moving[k]
    events = []
    for lb, mask in limb_mask.items():
        lruns = []
        for r in runs(mask):   # 同肢体间隙 < EV_GAP 合并（一次伸手的微停顿）
            if lruns and (t[r[0]] - t[lruns[-1][1] - 1]) < EV_GAP:
                lruns[-1][1] = r[1]
            else:
                lruns.append(list(r))
        for r in lruns:
            # 轻回吐 1/4 窗（全回吐会把短事件裁没）
            i0 = min(r[0] + half // 2, N - 1); i1 = max(r[1] - 1 - half // 2, i0)
            # 该肢体代表关节：run 内距起点最大偏移最大的（净位移会漏掉
            # "探出又收回"型调整——路径大但净位移小）
            jbest, dbest = None, -1.0
            for k in TRACK_JOINTS:
                if LIMB_NAME[k] != lb: continue
                dev = np.linalg.norm(psm[k][r[0]:r[1]] - psm[k][r[0]], axis=1) / body_scale
                dv = float(np.nanmax(dev)) if len(dev) else 0.0
                if dv > dbest: jbest, dbest = k, dv
            if dbest < EV_MIN_DEV or t[i1] - t[i0] < EV_MIN_DUR:
                continue  # 偏移太小/太短 → 抖动，丢弃
            dxy = (psm[jbest][i1] - psm[jbest][i0]) / body_scale
            events.append({
                "limb": lb, "joint": jbest,
                "start_s": round(float(t[i0]), 2), "end_s": round(float(t[i1]), 2),
                "dur_s": round(float(t[i1] - t[i0]), 2),
                "disp": round(dbest, 2),
                "dx": round(float(dxy[0]), 2), "dy": round(float(dxy[1]), 2),
                "source": "rule",
            })
    events.sort(key=lambda e: e["start_s"])

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
            # 主导肢体（"出哪只手/脚"）= 段内累计路程最大的关节（见头部注释）
            # 每关节段内净位移（起止点距离，身长归一化）
            disp = {k: float(np.linalg.norm(psm[k][i1c] - psm[k][i0]) / body_scale)
                    for k in TRACK_JOINTS}
            dom_joint = max(disp, key=disp.get)
            dom = LIMB_NAME[dom_joint]
            seg["dominant_joint"] = dom_joint
            # 动过的全部肢体：净位移超过 0.6*D_MOVE 的关节归并到肢体名
            moved = {}
            for k in TRACK_JOINTS:
                if disp[k] > 0.6 * D_MOVE:
                    lb = LIMB_NAME[k]
                    moved[lb] = max(moved.get(lb, 0.0), disp[k])
            seg["moved_limbs"] = sorted(moved, key=moved.get, reverse=True)
            seg["limb_disp"] = {lb: round(v, 2) for lb, v in moved.items()}
            # 深度扭身检测：肩连线在画面上投影过短 → 左右低置信
            ori = np.nanmean(P["right_shoulder"][i0:i1, 0] - P["left_shoulder"][i0:i1, 0])
            seg["side_confidence"] = "low" if abs(ori) < TWIST_ORI_TH else "high"
            seg["dominant_limb_source"] = "rule"
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

    # ── 人工左右覆写（老板核对结果，source=manual 优先于 rule）────────
    ov_path = args.overrides or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "annotations",
        f"{base}_side_overrides.json")
    n_override = 0
    if os.path.exists(ov_path):
        for ov in json.load(open(ov_path)):
            for s in seg_list:
                if s["kind"] == "move" and s["start_s"] <= ov["t"] <= s["end_s"]:
                    s["dominant_limb"] = ov["limb"]
                    s["dominant_limb_source"] = "manual"
                    s["side_confidence"] = "high"
                    n_override += 1
                    break
            # 事件层同步覆写：该时刻位移最大的事件改名
            hit = [e for e in events if e["start_s"] <= ov["t"] <= e["end_s"]]
            if hit:
                ebest = max(hit, key=lambda e: e["disp"])
                ebest["limb"] = ov["limb"]
                ebest["source"] = "manual"

    move_ct = sum(1 for s in seg_list if s["kind"] == "move")
    static_ct = len(seg_list) - move_ct

    result = {
        "base": base,
        "fps": round(float(fps), 2),
        "n_frames": int(N),
        "duration_s": round(float(t[-1] - t[0]), 2),
        "body_scale": round(float(body_scale), 4),
        "detector": "displacement_v2",
        "params": {"D_MOVE": D_MOVE, "DISP_WIN": DISP_WIN, "GAP_MERGE": GAP_MERGE,
                   "MIN_MOVE": MIN_MOVE, "SMOOTH_LIMB": SMOOTH_LIMB},
        "n_move": move_ct, "n_static": static_ct, "n_events": len(events),
        "segments": seg_list,
        "events": events,
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
        alldisp = np.nanmax(np.vstack([ldisp[k] for k in TRACK_JOINTS]), axis=0)
        ax[0].plot(t, alldisp, color="#495057", lw=0.8, label=f"max joint disp / {DISP_WIN}s window [bl]")
        ax[0].axhline(D_MOVE, color="#d6336c", ls="--", lw=0.8, label=f"D_MOVE={D_MOVE}")
        height = (com_s[:, 1] - np.nanmin(com_s[:, 1])) / body_scale
        ax[1].plot(t, height, color="#1c7ed6", lw=1.0, label="height [bl]")
        for s in seg_list:
            c = "#ffd8a8" if s["kind"] == "move" else "#e9ecef"
            for a in ax:
                a.axvspan(s["start_s"], s["end_s"], color=c, alpha=0.55, lw=0)
        ax[0].set_ylabel("joint disp [bl]"); ax[0].legend(loc="upper right", fontsize=8)
        ax[0].set_title(f"{base} 全身分段  move={move_ct}  static={static_ct}  (橙=move 灰=static)")
        ax[1].set_ylabel("height [bl]"); ax[1].set_xlabel("time [s]")
        ax[1].legend(loc="upper left", fontsize=8)
        fig.tight_layout(); fig.savefig(out_plot, dpi=110); plt.close(fig)
        plot_msg = out_plot
    except Exception as e:
        plot_msg = f"(叠加图跳过: {e})"

    print(f"✅ {base}: move={move_ct} static={static_ct} 总={len(seg_list)} 段 (detector=displacement_v2)")
    print(f"   时长 {result['duration_s']}s  fps={result['fps']}  body_scale={result['body_scale']}")
    print(f"   D_MOVE={D_MOVE}bl / {DISP_WIN}s 窗  人工覆写 {n_override} 段")
    print(f"   JSON → {out_json}")
    print(f"   叠加图 → {plot_msg}")


if __name__ == "__main__":
    main()

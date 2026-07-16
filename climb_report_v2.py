#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_report_v2.py —— 节奏统计报告 v2a（PLAN.md §8 v2a，S3 交付）

不依赖动作识别，只吃 S2 分段 + v1 CSV，产出「节奏」层面的统计：
  1. 完成时间   起攀（COM 首次持续上升 >0.3bl）→ 完攀（COM 达全局最高后保持 >1.5s）
  2. 切换耗时   每个 move 段前的 static 段时长 = 准备/犹豫时间
  3. 难点       准备时长 > 中位数×2.5，或同高度区间反复 move ≥3 次；
                与 v1 crux 互证，双命中标「确认难点」
  4. 三段占比   move / rest（直臂+低速+>2s）/ adjust
  5. 弯臂检测   静止段「最直的那条臂」也 <150° 且持续 >2s = 弯臂耗力
  6. 休息点质量 直臂(+) 脚高髋低(+) 难点前(+) 弯臂(−) 过长(−)

口径与 v1（climb_analyze_report.py）严格对齐：
  - 坐标 pt(n)=(nx, 1.0-ny)，y 向上为正
  - body_scale = median(||肩中-髋中||)，长度/速度全部除以它归一化
  - COM = 0.08*nose + 0.50*trunk + 0.20*thigh + 0.12*shank + 0.10*arm，smooth2d(...,13)
v1 脚本不改；本脚本只读不写 v1 产物（metrics.json 仅用于 crux 互证）。

用法：
  python3 climb_report_v2.py --dir <CSV所在目录> --base <文件名前缀> --out <报告输出目录> \
      [--segments <segments.json>] [--metrics-v1 <metrics.json>] [--route "V2 抱石·绿线"] [--title "..."]
"""
import csv, json, os, argparse
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── 参数旋钮（集中在顶部，验收后按老板反馈调）────────────────────────
START_RISE   = 0.30   # 起攀：COM 相对起攀前最低点上升超过此值(身长)算"真的开始爬"
ENGAGE_HOLD_S = 0.50  # 上墙门：手举过肩需持续此秒数才算"搭上岩点"，见下方说明
TOP_HOLD_S   = 1.50   # 完攀：到达最高点后需保持此秒数
TOP_TOL      = 0.15   # 完攀判定的高度容差(身长)：认为"还在最高点附近"
PREP_CRUX_K  = 2.50   # 难点：准备时长 > 中位数 × 此倍数
HEIGHT_BIN   = 0.50   # 难点：高度分箱宽度(身长)
BIN_MOVE_N   = 3      # 难点：同一高度箱内 move 次数 ≥ 此值算"原地反复试探"
REPEAT_MIN_SPAN_S = 4.0  # 难点：上述反复出手还需横跨此秒数才算数。没有这条会在**起攀
                      # 处必然误报**——起步几手的中点高度天然都落在最低那个箱里。
                      # 2026-07-17 用 IMG_6152 标定：起步 0.23-3.23s 出手 3 次但 3 秒爬了
                      # 0.67bl（正常起步，应滤掉）；9.2-17.37s 出手 3 次却 8 秒只升 0.22bl
                      # （真卡住，应保留）。IMG_6942 的真难点横跨 8.15s，同样保留。
CRUX_MATCH_S = 2.50   # 与 v1 crux 时间差 < 此秒数算双命中（= v1 的 crux 最小间隔）
ELBOW_STRAIGHT = 150  # 直臂阈值(度)：肘角 ≥ 此值算直臂（与知识库"直臂悬挂"口径一致）
BENT_MIN_S   = 2.00   # 弯臂耗力：连续弯臂超过此秒数才记一次
REST_MIN_S   = 2.00   # rest 判定：static 段时长下限
REST_MAX_SPD = 0.15   # rest 判定：段内 COM 速度中位数上限(身长/秒)
REST_LONG_S  = 8.00   # 休息点质量：超过此秒数扣分（挂太久也是耗力）
FOOT_HIGH    = 0.80   # "脚高髋低"：髋-踝垂直落差 < 此值(身长) 算脚踩得高、重心压在脚上
                      # （2026-07-16 用 IMG_6942/6947 标定：落差中位数 0.9-1.0bl，
                      #   取 25 分位 0.8 才是"明显比平时踩得高"；设成中位数等于抛硬币）
REST_BEFORE_CRUX_S = 5.0  # 休息点质量：难点前此秒数内的休息算"会调整节奏"(+)
VIS_MIN      = 0.30   # 可见度门槛，**左右臂各自独立判定**（见 elbow_open 处注释）。
                      # 攀岩时手抓在岩点上贴着墙，MediaPipe 给手腕的 visibility 长期很低
                      # （实测中位数 0.19-0.38）。原先要求"左右肘+左右腕四点同时 >0.5"
                      # 只剩 9% 的帧可用，rest/弯臂必然全灭；改成单臂门槛 0.3 后
                      # "至少一条臂可用"的帧回到 77%。肘角本身取自 world landmarks，
                      # 已抽帧人眼核对：低可见度下角度依然准（IMG_6942 的 3.8s 直臂 167°、
                      # 4.2s 弯臂 94° 与画面一致），故门槛只挡真遮挡，不宜设高。
ANAT_LO, ANAT_HI = 0.70, 1.40
                      # ★解剖学体检★ 3D 重建的 前臂/上臂 长度比若落在此区间外，判定该帧
                      # 该条手臂的 world landmarks 是坏的，肘角不采信。真人这个比值 ≈0.95-1.05。
                      # 2026-07-17 加，起因：老板说「14.4s 图里右臂看着挺直的」，查下去发现
                      # 左臂的 3D 前臂比上臂长 65%（解剖学不可能），角度自然是垃圾。
                      # 实测更糟：全片只有 47-63% 的帧解剖学可信，而且**可见度分数预测不了**
                      # 重建质量——15-20% 的帧可见度达标却解剖学不可能。可见度和解剖学是
                      # 两个独立的体检项，必须都过。实测这条门槛把一个被烂重建撑到 149°
                      # （差点够到直臂线 150° 被判成"休息"）的静止段打回 123° 真值。
VIS_GAP_FILL_S = 0.50 # 短于此秒数的"看不见"空洞按线性插值补上：可见度会瞬时闪断，
                      # 0.2s 的闪断不代表手臂状态变了，但会把连续弯臂段切碎、
                      # 使其达不到 BENT_MIN_S 而漏检（实测 4.6s 的弯臂段被切成 2.1s）。
                      # 长于此值的空洞保持 NaN = 真遮挡，不参与判定。

# 休息点质量评分权重（基准分 60，clip 到 0-100）
Q_BASE, Q_STRAIGHT, Q_FOOT, Q_PRECRUX, Q_BENT, Q_LONG = 60, 15, 10, 15, -25, -15

JOINTS = ["nose", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
          "left_wrist", "right_wrist", "left_hip", "right_hip",
          "left_knee", "right_knee", "left_ankle", "right_ankle"]


def load_csv(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def col(rows, name):
    o = []
    for r in rows:
        try:
            o.append(float(r.get(name, "")))
        except Exception:
            o.append(np.nan)
    return np.array(o)


def smooth2d(a, w=11):
    k = np.ones(w) / w
    out = np.copy(a)
    for c in range(a.shape[1]):
        x = a[:, c].copy()
        nan = np.isnan(x)
        if nan.any():
            x[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(~nan), x[~nan])
        out[:, c] = np.convolve(x, k, mode="same")
    return out


def smooth1d(x, w=15):
    k = np.ones(w) / w
    y = np.asarray(x, float).copy()
    nan = np.isnan(y)
    if nan.any():
        y[nan] = np.interp(np.flatnonzero(nan), np.flatnonzero(~nan), y[~nan])
    return np.convolve(y, k, mode="same")


def fill_short_nan(x, max_gap):
    """线性插值补掉长度 <= max_gap 帧的 NaN 空洞；更长的空洞保持 NaN。"""
    y = np.asarray(x, float).copy()
    nan = np.isnan(y)
    if not nan.any() or (~nan).sum() < 2:
        return y
    idx = np.flatnonzero(~nan)
    filled = y.copy()
    filled[nan] = np.interp(np.flatnonzero(nan), idx, y[idx])
    for r in runs_true(nan):
        if (r[1] - r[0]) > max_gap or r[0] == 0 or r[1] == len(y):
            filled[r[0]:r[1]] = np.nan   # 长空洞 / 首尾外插 → 不采信
    return filled


def runs_true(mask):
    """连续 True 段的 [start, end_exclusive) 列表。"""
    out, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            out.append([i, j])
            i = j
        else:
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--segments", default=None)
    ap.add_argument("--metrics-v1", default=None)
    ap.add_argument("--route", default="")
    ap.add_argument("--title", default="")
    A = ap.parse_args()

    seg_path = A.segments or os.path.join(A.dir, f"{A.base}_segments.json")
    v1_path = A.metrics_v1 or os.path.join(A.dir, f"{A.base}_metrics.json")
    ASSET = os.path.join(A.out, "report_assets_v2")
    os.makedirs(ASSET, exist_ok=True)

    # ── 读数据 ───────────────────────────────────────────────
    d2 = load_csv(os.path.join(A.dir, f"{A.base}_pose2d.csv"))
    an = load_csv(os.path.join(A.dir, f"{A.base}_angles.csv"))
    lm = load_csv(os.path.join(A.dir, f"{A.base}_landmarks.csv"))   # 3D，做解剖学体检用
    S = json.load(open(seg_path, encoding="utf-8"))
    v1 = json.load(open(v1_path, encoding="utf-8")) if os.path.exists(v1_path) else {}

    t = col(d2, "time_s")
    N = len(t)
    fps = 1.0 / np.nanmedian(np.diff(t))

    def pt(n):
        return np.vstack([col(d2, f"{n}_nx"), 1.0 - col(d2, f"{n}_ny")]).T
    P = {j: pt(j) for j in JOINTS}

    def mid(a, b):
        return (P[a] + P[b]) / 2
    sh, hp = mid("left_shoulder", "right_shoulder"), mid("left_hip", "right_hip")
    body_scale = np.nanmedian(np.linalg.norm(sh - hp, axis=1))

    trunk = (sh + hp) / 2
    thigh = (mid("left_hip", "left_knee") + mid("right_hip", "right_knee")) / 2
    shank = (mid("left_knee", "left_ankle") + mid("right_knee", "right_ankle")) / 2
    arm = (mid("left_shoulder", "left_wrist") + mid("right_shoulder", "right_wrist")) / 2
    com = 0.08 * P["nose"] + 0.50 * trunk + 0.20 * thigh + 0.12 * shank + 0.10 * arm
    com_s = smooth2d(com, 13)
    dt = np.gradient(t)
    com_speed = np.linalg.norm(np.gradient(com_s, axis=0) / dt[:, None] / body_scale, axis=1)
    height = (com_s[:, 1] - np.nanmin(com_s[:, 1])) / body_scale

    # 肘角按 frame 号对齐到 pose2d（两份 CSV 都只在检出帧写行，但不保证等长）
    fr2 = col(d2, "frame").astype(int)
    fra = col(an, "frame").astype(int)
    amap_l = dict(zip(fra, col(an, "left_elbow")))
    amap_r = dict(zip(fra, col(an, "right_elbow")))
    el = np.array([amap_l.get(f, np.nan) for f in fr2])
    er = np.array([amap_r.get(f, np.nan) for f in fr2])
    # 可见度门槛按**每条手臂独立**判定：该臂的肘和腕都看得见，这条臂的角度才采信。
    # 不能用"四点同时可见"的与门——攀岩时另一只手往往正抓着岩点被身体挡住，
    # 与门会把整帧废掉（实测只剩 9% 帧可用）。
    ok_l = (col(d2, "left_elbow_vis") > VIS_MIN) & (col(d2, "left_wrist_vis") > VIS_MIN)
    ok_r = (col(d2, "right_elbow_vis") > VIS_MIN) & (col(d2, "right_wrist_vis") > VIS_MIN)

    # 解剖学体检：3D 重建的 前臂/上臂 比不合人体 → 该帧该臂的肘角不采信（见 ANAT_LO/HI）
    def anat_ok(side):
        def P3(j):
            return np.vstack([col(lm, f"{side}_{j}_x"), col(lm, f"{side}_{j}_y"),
                              col(lm, f"{side}_{j}_z")]).T
        sh3, el3, wr3 = P3("shoulder"), P3("elbow"), P3("wrist")
        upper = np.linalg.norm(el3 - sh3, axis=1)
        fore = np.linalg.norm(wr3 - el3, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = fore / upper
        return (r > ANAT_LO) & (r < ANAT_HI)
    # landmarks.csv 与 pose2d.csv 都只在检出帧写行，行数一致；保险起见按长度对齐
    n_ok = min(len(lm), N)
    a_l, a_r = np.zeros(N, bool), np.zeros(N, bool)
    a_l[:n_ok] = anat_ok("left")[:n_ok]
    a_r[:n_ok] = anat_ok("right")[:n_ok]
    ok_l &= a_l
    ok_r &= a_r
    # 「最直的那条臂」——只要有一条臂是直的就不算弯臂耗力；看不见的臂不参与取 max
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # 两臂都不可见的帧 → NaN
            elbow_open = np.nanmax(np.vstack([np.where(ok_l, el, np.nan),
                                              np.where(ok_r, er, np.nan)]), axis=0)
    # 补掉可见度瞬时闪断造成的短空洞，避免连续弯臂段被切碎而漏检
    elbow_open = fill_short_nan(elbow_open, int(VIS_GAP_FILL_S * fps))
    vis_ok = ~np.isnan(elbow_open)

    # ── 1. 完成时间 ──────────────────────────────────────────
    # 【上墙门】先把"走向岩壁"的阶段排除出起攀搜索窗口。
    # 为什么需要：相机静止，人走向岩壁 = 在**深度方向**远离相机 = 在画面里变小且上移，
    # 2D 重心高度会被透视被动抬高。IMG_6942 实测：走近的 2s 里 COM"上升"1.09 身长
    # （0.55bl/s），而真正爬墙 25s 才升 2.5 身长（0.1bl/s）——**走路比爬墙"升"得还快**，
    # 任何基于速率或位移的规则都分不开两者，全局最低点必然落在 t=0 的走路起点。
    # 解法：用**深度无关**的身体自身相对量（同一深度两点之比不受距离影响）判断人是否已
    # 搭上岩点——较高那只手腕高过肩线，且持续 ENGAGE_HOLD_S。
    # （每帧表观肩髋距也试过，被躯干旋转带来的 ±20% 波动淹没，实测不可用。）
    shy = (P["left_shoulder"][:, 1] + P["right_shoulder"][:, 1]) / 2
    hpy2 = (P["left_hip"][:, 1] + P["right_hip"][:, 1]) / 2
    torso = np.abs(shy - hpy2)
    wy = np.maximum(P["left_wrist"][:, 1], P["right_wrist"][:, 1])
    engaged = smooth1d((wy - shy) / torso) > 0      # 手举过肩 = 搭上岩点
    n_eng = max(2, int(ENGAGE_HOLD_S * fps))
    i_engage = 0
    for r in runs_true(engaged):
        if (r[1] - r[0]) >= n_eng:
            i_engage = r[0]
            break
    t_engage = float(t[i_engage])

    # 起攀：从上墙门之后开始找，首个「相对此前最低点上升超过 START_RISE」的帧，回溯到最低点
    t_start, i_start = t_engage, i_engage
    for j in range(i_engage, N):
        lo = i_engage + int(np.nanargmin(height[i_engage:j + 1]))
        if height[j] - height[lo] > START_RISE:
            i_start, t_start = lo, float(t[lo])
            break
    # 完攀：到达全局最高附近并保持 TOP_HOLD_S 的最早时刻
    h_max = float(np.nanmax(height))
    hold_n = max(2, int(TOP_HOLD_S * fps))
    near_top = height >= h_max - TOP_TOL
    i_end, top_held = int(np.nanargmax(height)), False
    # 记录顶点实际保持了多久：只报 True/False 会把"差 0.1s 没够阈值"和"根本没到顶"
    # 混为一谈（IMG_6152 实测保持 1.37s vs 阈值 1.5s，其实是正常完攀后下撤）
    top_runs = [(t[min(r[1] - 1, N - 1)] - t[r[0]]) for r in runs_true(near_top)]
    top_hold_s = round(float(max(top_runs)), 2) if top_runs else 0.0
    for r in runs_true(near_top):
        if (r[1] - r[0]) >= hold_n:
            i_end, top_held = r[0], True
            break
    t_end = float(t[min(i_end, N - 1)])
    if t_end <= t_start:  # 兜底：没识别出保持段就用全局最高点
        i_end = int(np.nanargmax(height))
        t_end, top_held = float(t[i_end]), False
    climb_s = round(t_end - t_start, 2)

    def in_climb(s):
        return s["end_s"] > t_start and s["start_s"] < t_end

    segs = S["segments"]

    # ── 2. 切换耗时：每个 move 段前紧邻的 static 段时长 ───────────
    preps = []
    for i, s in enumerate(segs):
        if s["kind"] != "move" or not in_climb(s):
            continue
        prev = segs[i - 1] if i > 0 else None
        if prev is None or prev["kind"] != "static":
            continue
        # 起攀前的那段 static 是「上场准备」，不算路线上的犹豫；
        # 横跨起攀点的那段只算起攀之后的部分
        if prev["end_s"] <= t_start:
            continue
        p_s = round(prev["end_s"] - max(prev["start_s"], t_start), 2)
        if p_s <= 0:
            continue
        preps.append({
            "move_idx": i,
            "move_start_s": s["start_s"],
            "prep_s": p_s,
            "dominant_limb": s.get("dominant_limb", ""),
        })
    prep_vals = [p["prep_s"] for p in preps]
    prep_med = float(np.median(prep_vals)) if prep_vals else 0.0

    # ── 3. 难点 ─────────────────────────────────────────────
    crux = []
    # 3a 犹豫型：准备时长 > 中位数 × PREP_CRUX_K
    for p in preps:
        if prep_med > 0 and p["prep_s"] > prep_med * PREP_CRUX_K:
            crux.append({"t": p["move_start_s"], "kind": "hesitation",
                         "detail": f"起手前停顿 {p['prep_s']}s（中位数 {round(prep_med,2)}s 的 "
                                   f"{round(p['prep_s']/prep_med,1)} 倍）"})
    # 3b 试探型：同一高度箱内 move ≥ BIN_MOVE_N 次
    bins = {}
    for i, s in enumerate(segs):
        if s["kind"] != "move" or not in_climb(s):
            continue
        im = int(np.clip((s["start_frame"] + s["end_frame"]) // 2, 0, N - 1))
        b = int(height[im] // HEIGHT_BIN)
        bins.setdefault(b, []).append(s)
    for b, ss in sorted(bins.items()):
        span = ss[-1]["end_s"] - ss[0]["start_s"]
        if len(ss) >= BIN_MOVE_N and span >= REPEAT_MIN_SPAN_S:
            gain = round(float(height[min(ss[-1]["end_frame"], N - 1)]
                               - height[ss[0]["start_frame"]]), 2)
            crux.append({"t": round(float(np.mean([x["start_s"] for x in ss])), 2),
                         "kind": "repeat",
                         "detail": f"高度 {round(b*HEIGHT_BIN,1)}-{round((b+1)*HEIGHT_BIN,1)}bl "
                                   f"区间内反复出手 {len(ss)} 次，横跨 {round(span,1)}s "
                                   f"（{ss[0]['start_s']}-{ss[-1]['end_s']}s）却只上升 {gain}bl"})
    # 3c 与 v1 crux 的关系（2026-07-17 老板拍板改为**并列展示**，不再用双命中定可信度）：
    # IMG_6942 实测双命中 0，抽帧核对确认 v2a 判对了（19-24s 人确实卡在同一高度弯臂硬扛），
    # v1 完全没发现该段。原因：两者测的是**正交**的现象——v1 靠重心加速度+肢体速度+关节
    # 极端屈曲找「动作剧烈」的瞬间（发力型），v2a 靠停顿时长+同高度反复出手找「卡住不动」
    # 的时刻（卡住型），而真正的难点常常是后者。互证前提不成立，硬套只会把真难点标成
    # 「疑似」。改为两类难点并列列出、各自标来源；仍记录时间邻近关系供参考，但不作判据。
    v1_crux = [x for x in v1.get("crux_times_s", []) if t_start <= x <= t_end]
    v1_crux_all = v1.get("crux_times_s", [])
    for c in crux:
        c["source"] = "v2a"
        near = [x for x in v1_crux if abs(x - c["t"]) < CRUX_MATCH_S]
        c["v1_nearby_t"] = near[0] if near else None   # 仅供参考，不影响可信度
    # v1 的发力型吃力点作为并列的另一类（只取攀爬区间内的，v1 不区分起攀/完攀）
    for x in v1_crux:
        crux.append({"t": x, "kind": "power", "source": "v1",
                     "detail": "v1 吃力点：重心加速度 + 肢体速度 + 关节极端屈曲综合最强",
                     "v1_nearby_t": None})
    crux.sort(key=lambda c: c["t"])
    n_v2a = sum(1 for c in crux if c["source"] == "v2a")
    n_v1 = sum(1 for c in crux if c["source"] == "v1")
    n_near = sum(1 for c in crux if c.get("v1_nearby_t") is not None)

    # ── 5. 弯臂检测（先于 rest 分类，rest 质量要用）────────────────
    bent = []
    bent_mask_all = np.zeros(N, dtype=bool)
    for s in segs:
        if s["kind"] != "static" or not in_climb(s):
            continue
        i0, i1 = s["start_frame"], min(s["end_frame"] + 1, N)
        m = (elbow_open[i0:i1] < ELBOW_STRAIGHT) & vis_ok[i0:i1]
        for r in runs_true(m):
            a, b = i0 + r[0], i0 + r[1] - 1
            if t[b] - t[a] < BENT_MIN_S:
                continue
            bent.append({
                "start_s": round(float(t[a]), 2), "end_s": round(float(t[b]), 2),
                "dur_s": round(float(t[b] - t[a]), 2),
                "min_elbow_deg": round(float(np.nanmin(elbow_open[a:b + 1])), 1),
                "mean_elbow_deg": round(float(np.nanmean(elbow_open[a:b + 1])), 1),
            })
            bent_mask_all[a:b + 1] = True
    bent_total = round(float(sum(b["dur_s"] for b in bent)), 2)

    # ── 4. 三段占比：static 再分 rest / adjust ────────────────────
    hip_y, ank_y = hp[:, 1], (P["left_ankle"][:, 1] + P["right_ankle"][:, 1]) / 2
    foot_gap = (hip_y - ank_y) / body_scale   # 髋-踝垂直落差(身长)，越小=脚踩得越高

    rests, adjusts = [], []
    for s in segs:
        if s["kind"] != "static" or not in_climb(s):
            continue
        i0, i1 = s["start_frame"], min(s["end_frame"] + 1, N)
        spd = float(np.nanmedian(com_speed[i0:i1]))
        eo = float(np.nanmedian(elbow_open[i0:i1][vis_ok[i0:i1]])) if vis_ok[i0:i1].any() else np.nan
        straight = bool(eo >= ELBOW_STRAIGHT) if not np.isnan(eo) else False
        is_rest = (s["dur_s"] >= REST_MIN_S) and (spd <= REST_MAX_SPD) and straight
        rec = {"start_s": s["start_s"], "end_s": s["end_s"], "dur_s": s["dur_s"],
               "com_speed_med": round(spd, 3),
               "elbow_open_med": round(eo, 1) if not np.isnan(eo) else None,
               "straight_arm": straight}
        if is_rest:
            gap = float(np.nanmedian(foot_gap[i0:i1]))
            foot_high = bool(gap < FOOT_HIGH)
            has_bent = bool(bent_mask_all[i0:i1].any())
            too_long = bool(s["dur_s"] > REST_LONG_S)
            pre_crux = any(0 <= c["t"] - s["end_s"] <= REST_BEFORE_CRUX_S for c in crux)
            q = Q_BASE + (Q_STRAIGHT if straight else 0) + (Q_FOOT if foot_high else 0) \
                + (Q_PRECRUX if pre_crux else 0) + (Q_BENT if has_bent else 0) \
                + (Q_LONG if too_long else 0)
            reasons = []
            if straight: reasons.append("直臂挂着(+)")
            if foot_high: reasons.append("脚高髋低、重心压脚(+)")
            if pre_crux: reasons.append("难点前调整(+)")
            if has_bent: reasons.append("段内有弯臂耗力(−)")
            if too_long: reasons.append(f"挂了 {s['dur_s']}s 偏久(−)")
            rec.update({"hip_ankle_gap_bl": round(gap, 2), "foot_high": foot_high,
                        "has_bent_arm": has_bent, "too_long": too_long,
                        "before_crux": pre_crux,
                        "quality": int(np.clip(q, 0, 100)),
                        "reasons": reasons})
            rests.append(rec)
        else:
            adjusts.append(rec)

    def clip_dur(s):
        return max(0.0, min(s["end_s"], t_end) - max(s["start_s"], t_start))
    move_s = sum(clip_dur(s) for s in segs if s["kind"] == "move" and in_climb(s))
    rest_s = sum(clip_dur(s) for s in rests)
    adj_s = sum(clip_dur(s) for s in adjusts)
    tot = move_s + rest_s + adj_s or 1.0
    ratios = {"move_pct": round(100 * move_s / tot, 1),
              "rest_pct": round(100 * rest_s / tot, 1),
              "adjust_pct": round(100 * adj_s / tot, 1),
              "move_s": round(move_s, 2), "rest_s": round(rest_s, 2), "adjust_s": round(adj_s, 2)}

    # ── 汇总 metrics_v2.json ─────────────────────────────────
    M = {
        "title": A.title or A.base, "route": A.route, "base": A.base,
        "generated_by": "climb_report_v2.py (v2a)",
        "source": {"segments": os.path.basename(seg_path),
                   "metrics_v1": os.path.basename(v1_path) if v1 else None,
                   "detector": S.get("detector")},
        "fps": round(float(fps), 2), "n_frames": N,
        "body_scale": round(float(body_scale), 4),
        "video_duration_s": round(float(t[-1] - t[0]), 2),
        "completion": {"start_s": round(t_start, 2), "end_s": round(t_end, 2),
                       "climb_time_s": climb_s, "top_hold_confirmed": top_held,
                       "top_hold_s": top_hold_s,   # 顶点实际保持时长（阈值 TOP_HOLD_S）
                       "engage_s": round(t_engage, 2),   # 上墙门（手首次举过肩）
                       "approach_trimmed_s": round(t_engage, 2),  # 被排除的走近时长
                       "net_gain_bl": round(h_max - float(height[i_start]), 2)},
        "prep": {"median_s": round(prep_med, 2),
                 "mean_s": round(float(np.mean(prep_vals)), 2) if prep_vals else 0,
                 "max_s": round(float(np.max(prep_vals)), 2) if prep_vals else 0,
                 "n": len(preps), "items": preps},
        "crux": {"n": len(crux), "n_v2a": n_v2a, "n_v1": n_v1, "n_time_adjacent": n_near,
                 "v1_crux_times_s_in_climb": v1_crux,
                 "v1_crux_times_s_raw": v1_crux_all,
                 "items": crux},
        "ratios": ratios,
        "bent_arm": {"n": len(bent), "total_s": bent_total,
                     "pct_of_climb": round(100 * bent_total / climb_s, 1) if climb_s else 0,
                     "items": bent},
        "rests": {"n": len(rests),
                  "mean_quality": round(float(np.mean([r["quality"] for r in rests])), 1) if rests else None,
                  "items": rests},
        "adjusts": {"n": len(adjusts), "items": adjusts},
        "params": {"START_RISE": START_RISE, "ENGAGE_HOLD_S": ENGAGE_HOLD_S,
                   "TOP_HOLD_S": TOP_HOLD_S, "TOP_TOL": TOP_TOL,
                   "PREP_CRUX_K": PREP_CRUX_K, "HEIGHT_BIN": HEIGHT_BIN, "BIN_MOVE_N": BIN_MOVE_N,
                   "REPEAT_MIN_SPAN_S": REPEAT_MIN_SPAN_S, "VIS_GAP_FILL_S": VIS_GAP_FILL_S,
                   "ANAT_LO": ANAT_LO, "ANAT_HI": ANAT_HI,
                   "CRUX_MATCH_S": CRUX_MATCH_S, "ELBOW_STRAIGHT": ELBOW_STRAIGHT,
                   "BENT_MIN_S": BENT_MIN_S, "REST_MIN_S": REST_MIN_S,
                   "REST_MAX_SPD": REST_MAX_SPD, "REST_LONG_S": REST_LONG_S,
                   "FOOT_HIGH": FOOT_HIGH, "VIS_MIN": VIS_MIN},
    }
    out_json = os.path.join(A.dir, f"{A.base}_metrics_v2.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(M, f, ensure_ascii=False, indent=2)

    # ── 图表 ────────────────────────────────────────────────
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "PingFang SC",
                                       "Hiragino Sans GB", "Arial Unicode MS", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.3
    C_MOVE, C_REST, C_ADJ = "#ff922b", "#51cf66", "#adb5bd"

    # 图1 节奏时间轴：高度曲线 + move/rest/adjust 三色带 + 难点/弯臂标记
    fig, ax = plt.subplots(2, 1, figsize=(13, 6), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(t, height, color="#1c7ed6", lw=1.4, label="重心高度 [身长]")
    for s in segs:
        if not in_climb(s):
            continue
        c = C_MOVE if s["kind"] == "move" else None
        if c is None:
            c = C_REST if any(r["start_s"] == s["start_s"] for r in rests) else C_ADJ
        for a in ax:
            a.axvspan(max(s["start_s"], t_start), min(s["end_s"], t_end), color=c, alpha=0.5, lw=0)
    ax[0].axvline(t_start, color="#495057", ls=":", lw=1.5)
    ax[0].axvline(t_end, color="#495057", ls=":", lw=1.5)
    ax[0].annotate(f"起攀 {round(t_start,1)}s", (t_start, h_max * 0.02), fontsize=9,
                   rotation=90, va="bottom", ha="right", color="#495057")
    ax[0].annotate(f"完攀 {round(t_end,1)}s", (t_end, h_max * 0.02), fontsize=9,
                   rotation=90, va="bottom", ha="right", color="#495057")
    for c in crux:
        col_ = "#e03131" if c["source"] == "v2a" else "#7048e8"
        ax[0].axvline(c["t"], color=col_, ls="--", lw=1.2, alpha=0.9)
        ax[0].plot([c["t"]], [h_max * 1.02], marker="v", color=col_, ms=7)
    ax[0].set_ylabel("高度 [身长]")
    ax[0].set_title(f"{A.base} 攀爬节奏时间轴　橙=move 绿=rest 灰=adjust／"
                    f"红▽=v2a 卡住型难点 紫▽=v1 发力型吃力点")
    ax[0].legend(loc="upper left", fontsize=8)
    ax[1].plot(t, elbow_open, color="#7048e8", lw=1.0, label="较直一侧肘角 [度]")
    ax[1].axhline(ELBOW_STRAIGHT, color="#d6336c", ls="--", lw=0.9,
                  label=f"直臂线 {ELBOW_STRAIGHT}°")
    for b in bent:
        ax[1].axvspan(b["start_s"], b["end_s"], color="#d6336c", alpha=0.28, lw=0)
    ax[1].set_ylabel("肘角 [度]")
    ax[1].set_xlabel("时间 [s]")
    ax[1].set_ylim(30, 190)
    ax[1].legend(loc="lower left", fontsize=8)
    ax[1].set_title("静止段弯臂耗力（粉底=最直的臂也 <150° 且持续 >2s）", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSET, "rhythm_timeline.png"), dpi=110)
    plt.close(fig)

    # 图2 切换耗时条形图
    fig, ax = plt.subplots(figsize=(13, 3.6))
    if preps:
        xs = np.arange(len(preps))
        cols = ["#e03131" if p["prep_s"] > prep_med * PREP_CRUX_K else "#4dabf7" for p in preps]
        ax.bar(xs, [p["prep_s"] for p in preps], color=cols)
        ax.axhline(prep_med, color="#51cf66", ls="--", lw=1.4, label=f"中位数 {round(prep_med,2)}s")
        ax.axhline(prep_med * PREP_CRUX_K, color="#e03131", ls=":", lw=1.2,
                   label=f"难点线 中位数×{PREP_CRUX_K} = {round(prep_med*PREP_CRUX_K,2)}s")
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{p['move_start_s']}s\n{p['dominant_limb']}" for p in preps], fontsize=7)
        ax.legend(loc="upper right", fontsize=8)
    ax.set_ylabel("准备/犹豫时长 [s]")
    ax.set_xlabel("每次出手（标注=出手时刻 + 主导肢体）")
    ax.set_title("切换耗时：每次出手前停顿了多久（红=超过难点线）")
    fig.tight_layout()
    fig.savefig(os.path.join(ASSET, "prep_times.png"), dpi=110)
    plt.close(fig)

    # 图3 三段占比
    fig, ax = plt.subplots(figsize=(6.5, 2.2))
    left = 0
    for lab, key, c in [("move 爬升", "move_s", C_MOVE), ("rest 休息", "rest_s", C_REST),
                        ("adjust 找点/调整", "adjust_s", C_ADJ)]:
        w = ratios[key]
        if w <= 0:
            continue
        ax.barh([0], [w], left=[left], color=c, edgecolor="white")
        ax.text(left + w / 2, 0, f"{lab}\n{round(100*w/tot,1)}%", ha="center", va="center",
                fontsize=9, color="#212529")
        left += w
    ax.set_xlim(0, tot)
    ax.set_yticks([])
    ax.set_xlabel("时间 [s]（起攀→完攀）")
    ax.set_title("时间构成")
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(os.path.join(ASSET, "time_split.png"), dpi=110)
    plt.close(fig)

    # ── 解读 ────────────────────────────────────────────────
    takeaways = []
    if top_held:
        top_note = ""
    elif top_hold_s >= TOP_HOLD_S * 0.6:
        top_note = (f"（顶点保持 {top_hold_s}s，略低于 {TOP_HOLD_S}s 阈值——通常是到顶后随即下撤，"
                    f"完攀时刻取的是重心最高帧，可信）")
    else:
        top_note = (f"⚠️ 顶点几乎没有停留（仅 {top_hold_s}s），完攀时刻取的是重心最高帧；"
                    f"可能是没到顶、直接跳下，或人爬出了画面。")
    takeaways.append(f"完攀用时 {climb_s}s（起攀 {round(t_start,1)}s → 完攀 {round(t_end,1)}s），"
                     f"净上升 {M['completion']['net_gain_bl']} 身长。{top_note}")
    if prep_vals:
        takeaways.append(f"每次出手前平均停顿 {M['prep']['mean_s']}s（中位数 {M['prep']['median_s']}s，"
                         f"最长 {M['prep']['max_s']}s）。中位数 {'偏长，属想清楚再动的稳健型' if prep_med > 1.0 else '较短，动作衔接果断'}。")
    if n_v2a:
        cs = [c for c in crux if c["source"] == "v2a"]
        span = f"{min(c['t'] for c in cs)}-{max(c['t'] for c in cs)}s" if len(cs) > 1 else f"{cs[0]['t']}s"
        takeaways.append(f"「卡住型」难点 {n_v2a} 处（{span}）：停顿异常长或在同一高度反复出手，"
                         f"是不知道怎么办的地方——最值得回看录像琢磨解法。")
    else:
        takeaways.append("没有「卡住型」难点：全程没有异常长的停顿，也没有在同一高度反复试探。")
    if n_v1:
        takeaways.append(f"「发力型」吃力点 {n_v1} 处：动作最剧烈、关节屈曲最深的瞬间，是体力开销大的地方。"
                         + (f"其中 {n_near} 处与卡住型难点时间邻近（同一处既难想又难拉）。" if n_near else
                            "与卡住型难点不重合——费力的地方和想不明白的地方是分开的。"))
    if ratios["rest_pct"] < 5:
        takeaways.append(f"几乎没有真正的休息（rest {ratios['rest_pct']}%），"
                         f"停顿基本都是找点/调整（adjust {ratios['adjust_pct']}%）——"
                         f"停下来时手臂还在弯着扛，比直臂挂着更耗前臂。")
    else:
        takeaways.append(f"时间构成：爬升 {ratios['move_pct']}% / 休息 {ratios['rest_pct']}% / "
                         f"找点调整 {ratios['adjust_pct']}%。")
    if bent:
        takeaways.append(f"弯臂耗力 {len(bent)} 段共 {bent_total}s（占攀爬时间 "
                         f"{M['bent_arm']['pct_of_climb']}%）——静止时最直的那条臂也没伸直，"
                         f"体重挂在肌肉上而不是骨架上，是前臂先泵的主因。最长一段 "
                         f"{max(bent, key=lambda b: b['dur_s'])['dur_s']}s。")
    else:
        takeaways.append("静止段没有检测到持续弯臂，停顿时基本能把手臂伸直挂着，省力习惯不错。")

    # ── HTML ────────────────────────────────────────────────
    def card(v, l, h, cls=""):
        return f'<div class="card"><div class="v {cls}">{v}</div><div class="l">{l}</div><div class="h">{h}</div></div>'

    KIND_ZH = {"hesitation": "卡住型 · 犹豫", "repeat": "卡住型 · 反复试探",
               "power": "发力型 · 动作剧烈"}

    def crux_row(c):
        is_v2a = c["source"] == "v2a"
        tag = ('<span class="tag-v2a">v2a 节奏</span>' if is_v2a
               else '<span class="tag-v1">v1 强度</span>')
        near = c.get("v1_nearby_t")
        extra = f' · 与 v1 {near}s 邻近' if near is not None else ""
        return (f'<tr><td>{c["t"]}s</td><td>{KIND_ZH.get(c["kind"], c["kind"])}</td>'
                f'<td>{c["detail"]}</td><td>{tag}{extra}</td></tr>')

    crux_rows = "".join(crux_row(c) for c in crux) or \
        '<tr><td colspan="4" style="color:#9aa0aa">未识别到难点</td></tr>'

    bent_rows = "".join(
        f'<tr><td>{b["start_s"]}–{b["end_s"]}s</td><td>{b["dur_s"]}s</td>'
        f'<td>{b["min_elbow_deg"]}°</td><td>{b["mean_elbow_deg"]}°</td></tr>'
        for b in bent) or '<tr><td colspan="4" style="color:#9aa0aa">无</td></tr>'

    rest_rows = "".join(
        f'<tr><td>{r["start_s"]}–{r["end_s"]}s</td><td>{r["dur_s"]}s</td>'
        f'<td><b>{r["quality"]}</b>/100</td><td>{"、".join(r["reasons"]) or "—"}</td></tr>'
        for r in rests) or '<tr><td colspan="4" style="color:#9aa0aa">全程没有符合 rest 条件的停顿（需同时满足：直臂 + 低速 + 超过 2 秒）</td></tr>'

    take_html = "".join(f'<div class="take">{x}</div>' for x in takeaways)
    route_badge = f'<span class="badge">{A.route}</span>' if A.route else ""
    mq = M["rests"]["mean_quality"]

    HTML = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>攀岩节奏报告卡 v2a · {A.base}</title><style>
:root{{--bg:#0f1115;--card:#1a1d24;--card2:#21252e;--ink:#e8eaed;--mut:#9aa0aa;--acc:#4dabf7;--pink:#f06595;--green:#51cf66;--orange:#ff922b;--line:#2b303b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;line-height:1.6;padding:32px 18px}}
.wrap{{max-width:1080px;margin:0 auto}}h1{{font-size:26px;margin:0 0 6px}}
.badge{{display:inline-block;background:#1b3a1f;color:#69db7c;border:1px solid #2b5e34;border-radius:6px;padding:2px 10px;font-size:13px;margin-left:8px;vertical-align:middle}}
.v2{{background:#1a2a3a;color:#4dabf7;border:1px solid #2b4a6e}}
.sub{{color:var(--mut);font-size:14px;margin-bottom:24px}}
h2{{font-size:18px;margin:34px 0 14px;padding-left:10px;border-left:3px solid var(--acc)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
.card .v{{font-size:26px;font-weight:700}}.card .l{{font-size:12px;color:var(--mut);margin-top:2px}}.card .h{{font-size:12px;color:var(--mut);margin-top:6px}}
.acc{{color:var(--acc)}}.pink{{color:var(--pink)}}.green{{color:var(--green)}}.orange{{color:var(--orange)}}
.fig{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}}.fig img{{width:100%;border-radius:8px;display:block}}.fig .cap{{font-size:13px;color:var(--mut);margin-top:8px}}
.note{{background:#1c2129;border:1px solid var(--line);border-left:3px solid var(--orange);border-radius:8px;padding:14px 16px;font-size:13px;color:var(--mut);margin-top:10px}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}}th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}}th{{color:var(--mut)}}
.take{{font-size:14px;margin:6px 0;padding-left:18px;position:relative}}.take:before{{content:"▸";position:absolute;left:0;color:var(--acc)}}
.tag-v2a{{display:inline-block;background:#3a1c22;color:#ff8787;border:1px solid #6e2b35;border-radius:5px;padding:1px 7px;font-size:12px}}
.tag-v1{{display:inline-block;background:#241c3a;color:#9775fa;border:1px solid #402b6e;border-radius:5px;padding:1px 7px;font-size:12px}}
</style></head><body><div class="wrap">
<h1>攀岩节奏报告卡{route_badge}<span class="badge v2">v2a 节奏统计</span></h1>
<div class="sub">素材 {A.base} · 视频 {M['video_duration_s']} 秒 · {N} 帧 @ {M['fps']}fps · 分段来自 {M['source']['detector']} · 单机位 MediaPipe</div>

<h2>核心指标</h2><div class="cards">
{card(str(climb_s)+"s", "完攀用时", f"起攀 {round(t_start,1)}s → 完攀 {round(t_end,1)}s", "acc")}
{card(M['completion']['net_gain_bl'], "净上升（身长）", "起攀点 → 最高点", "acc")}
{card(str(M['prep']['median_s'])+"s", "出手前停顿中位数", f"共 {M['prep']['n']} 次出手", "pink")}
{card(f"{n_v2a} <span style='font-size:15px;color:#9aa0aa'>+ {n_v1}</span>", "难点数", f"v2a 卡住型 {n_v2a} · v1 发力型 {n_v1}", "orange")}
{card(str(ratios['rest_pct'])+"%", "真休息占比", f"爬升 {ratios['move_pct']}% / 调整 {ratios['adjust_pct']}%", "green")}
{card(str(bent_total)+"s", "弯臂耗力总时长", f"{len(bent)} 段 · 占攀爬 {M['bent_arm']['pct_of_climb']}%", "pink")}
</div>

<h2>攀爬节奏时间轴</h2><div class="fig"><img src="report_assets_v2/rhythm_timeline.png">
<div class="cap">上：重心高度曲线，色带为分段类型（橙=出手移动 / 绿=真休息 / 灰=找点调整），▽=难点（红=与 v1 双命中确认）。下：较直一侧的肘角，粉底=弯臂耗力段。</div></div>

<h2>切换耗时（准备/犹豫时间）</h2><div class="fig"><img src="report_assets_v2/prep_times.png">
<div class="cap">每根柱=一次出手前的停顿时长。绿虚线=中位数，红点线=难点线（中位数×{PREP_CRUX_K}），超过即计为犹豫型难点。</div></div>

<h2>时间构成</h2><div class="fig"><img src="report_assets_v2/time_split.png">
<div class="cap">起攀→完攀区间内的时间去向。rest 需同时满足直臂 + 重心低速 + 持续 &gt;{REST_MIN_S}s；其余停顿归为 adjust。</div></div>

<h2>难点明细</h2><table><tr><th>时刻</th><th>类型</th><th>依据</th><th>来源</th></tr>{crux_rows}</table>
<div class="note"><b>两类难点并列，不分主次</b>——它们测的是正交的现象，谁也不是谁的验证：
<br>· <span class="tag-v2a">v2a 节奏</span>「<b>卡住型</b>」：停顿异常长，或在同一高度反复出手。你在这里<b>不知道怎么办</b>。
<br>· <span class="tag-v1">v1 强度</span>「<b>发力型</b>」：重心加速度 + 肢体速度 + 关节极端屈曲综合最强。你在这里<b>拼尽全力</b>。
<br>真正的难点常常是前者，而 v1 结构上看不见它（IMG_6942 实测：19-24s 卡住 5 秒，v1 五个吃力点无一命中）。
v1 吃力点原始时刻（含起攀前/完攀后）：{v1_crux_all or "（无 v1 metrics.json）"}，其中落在攀爬区间内的：{v1_crux or "无"}。</div>

<h2>弯臂耗力段</h2><table><tr><th>时段</th><th>时长</th><th>最小肘角</th><th>平均肘角</th></tr>{bent_rows}</table>
<div class="note">判定口径：静止段内，<b>较直的那条手臂</b>肘角仍 &lt;{ELBOW_STRAIGHT}° 且连续超过 {BENT_MIN_S}s。只要有一条臂伸直就不算——挂在骨架上不费力，弯着才是肌肉在扛。肘/腕可见度 &lt;{VIS_MIN} 的帧已排除（遮挡≠弯臂）。</div>

<h2>休息点质量{f'（均分 {mq}/100）' if mq is not None else ''}</h2>
<table><tr><th>时段</th><th>时长</th><th>质量分</th><th>加减分依据</th></tr>{rest_rows}</table>
<div class="note">评分：基准 {Q_BASE}，直臂 +{Q_STRAIGHT}，脚高髋低（髋-踝落差 &lt;{FOOT_HIGH} 身长，重心压在脚上）+{Q_FOOT}，难点前 {REST_BEFORE_CRUX_S}s 内 +{Q_PRECRUX}，段内有弯臂 {Q_BENT}，超过 {REST_LONG_S}s {Q_LONG}。</div>

<h2>解读 &amp; 建议</h2>{take_html}

<div class="note"><b>数据口径：</b>本报告卡不依赖动作识别，只统计节奏。分段来自 climb_segments.py（锚点位移法）。长度/速度以「身长」为单位（尺度无关），与 v1 报告卡同口径。单摄像头 + 相机静止假设，单目对深度不敏感。阈值参数全部集中在 climb_report_v2.py 顶部，验收后可调；本次取值见 metrics_v2.json 的 params 字段。</div>
</div></body></html>"""
    out_html = os.path.join(A.out, "攀岩节奏报告卡.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(HTML)

    print(f"✅ {A.base} v2a")
    print(f"   完攀用时 {climb_s}s（{round(t_start,1)}→{round(t_end,1)}s，顶点保持确认={top_held}）")
    print(f"   出手 {len(preps)} 次，停顿中位数 {round(prep_med,2)}s，最长 {M['prep']['max_s']}s")
    print(f"   难点：v2a 卡住型 {n_v2a} 处 + v1 发力型 {n_v1} 处（时间邻近 {n_near}）")
    print(f"   占比 move {ratios['move_pct']}% / rest {ratios['rest_pct']}% / adjust {ratios['adjust_pct']}%")
    print(f"   弯臂 {len(bent)} 段共 {bent_total}s；休息点 {len(rests)} 个，均分 {mq}")
    print(f"   JSON → {out_json}")
    print(f"   报告卡 → {out_html}")


if __name__ == "__main__":
    main()

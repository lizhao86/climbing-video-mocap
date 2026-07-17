#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""攀岩姿态提取——远景 ROI 跟踪版（六盘水类素材：4K 里人只有 ~300px 高）。

为什么另立脚本而不改 climb_pose.py：v1 勿动（硬约定，保历史可比）。
为什么需要 ROI：全画幅缩到 960 宽后人只剩 ~160px，MediaPipe **谁都检不出**
（2026-07-17 实测，不是跟错人，是没人）。在 4K 原片上裁人周围一块再放大，
检出率 100%（连续 10min/1200 帧实测，PLAN.md §9）。

跟踪：人工播种首帧 ROI 中心 → 每帧按骨架均值重新居中 → 连续丢检超时则全画幅
网格重扫（选离丢失位置最近的检出）。ROI 尺寸固定即可——实测尺寸对骨架质量
几乎没影响（瓶颈是机位角度不是分辨率），不做自适应变焦。

输出与 climb_pose.py **逐列同格式**（landmarks / angles / pose2d 三份 CSV +
标注视频），下游 climb_segments / climb_report_v2 / climb_report_card 零改动。
关键换算：pose2d 的 nx/ny/px/py 全部换回**全画幅坐标系**——ROI 是动的，
不换算的话人不动而 ROI 动就会造出假位移，重心轨迹全毁。
world landmarks（角度用）以髋为原点，与裁剪无关，照抄 v1 逻辑。
额外产出 <base>_roi_track.csv（ROI 中心轨迹），供核对「跟的是不是攀岩者」——
检出率证明不了这个（IMG_6947 教训）。

用法：
  python climb_pose_roi.py <视频> <输出目录> --seed X,Y [--roi W,H] [--end-s S]
  --seed 是首帧攀岩者在**全画幅像素坐标**里的位置（必给：远景常有 belayer 等
  第二个人，自动找人不可靠，尤其起步时两人贴在一起）。
环境变量：CLIMB_STEP（默认 2，隔帧取一）、CLIMB_COMPLEXITY（默认 2）。
时间轴：time_s = frame_idx / fps 名义时间，与 v1 同口径（VFR 素材勿用 PTS，
见 CLAUDE.md 的 VFR 条款）。
"""
import sys, os, csv, math, argparse
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  # 控制台 GBK 防线
import cv2
import numpy as np
import mediapipe as mp

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles
L = mp_pose.PoseLandmark

ANGLE_DEFS = {  # 与 climb_pose.py 完全一致
    "left_elbow":    (L.LEFT_SHOULDER,  L.LEFT_ELBOW,    L.LEFT_WRIST),
    "right_elbow":   (L.RIGHT_SHOULDER, L.RIGHT_ELBOW,   L.RIGHT_WRIST),
    "left_shoulder": (L.LEFT_ELBOW,     L.LEFT_SHOULDER, L.LEFT_HIP),
    "right_shoulder":(L.RIGHT_ELBOW,    L.RIGHT_SHOULDER,L.RIGHT_HIP),
    "left_hip":      (L.LEFT_SHOULDER,  L.LEFT_HIP,      L.LEFT_KNEE),
    "right_hip":     (L.RIGHT_SHOULDER, L.RIGHT_HIP,     L.RIGHT_KNEE),
    "left_knee":     (L.LEFT_HIP,       L.LEFT_KNEE,     L.LEFT_ANKLE),
    "right_knee":    (L.RIGHT_HIP,      L.RIGHT_KNEE,    L.RIGHT_ANKLE),
}
POSE_NAMES = [lm.name.lower() for lm in L]

LOST_RESCAN_S = 2.0    # 连续丢检超过此秒数（有效帧计）→ 全画幅网格重扫
ANNOT_W = 480          # 标注视频宽（ROI 放大后再缩到这个宽写盘；28min 全量要控体积）


def angle_3pt(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    ba, bc = a - b, c - b
    n = np.linalg.norm(ba) * np.linalg.norm(bc)
    if n == 0:
        return float("nan")
    cosv = np.clip(np.dot(ba, bc) / n, -1.0, 1.0)
    return math.degrees(math.acos(cosv))


def rescan(frame, pose_scan, roi_w, roi_h, last_cx, last_cy):
    """全画幅网格扫描找人。候选=有检出的窗口，取离丢失位置最近的。
    用独立的 static Pose 实例——不能污染主实例的 tracking 状态。"""
    H, W = frame.shape[:2]
    best = None
    xs = list(range(0, max(1, W - roi_w) + 1, max(1, roi_w // 2))) or [0]
    ys = list(range(0, max(1, H - roi_h) + 1, max(1, roi_h // 2))) or [0]
    for y0 in ys:
        for x0 in xs:
            roi = frame[y0:y0 + roi_h, x0:x0 + roi_w]
            big = cv2.resize(roi, (960, int(roi_h * 960 / roi_w)))
            r = pose_scan.process(cv2.cvtColor(big, cv2.COLOR_BGR2RGB))
            if not r.pose_landmarks:
                continue
            lm = r.pose_landmarks.landmark
            mx = float(np.mean([p.x for p in lm])); my = float(np.mean([p.y for p in lm]))
            cx = x0 + mx * roi_w; cy = y0 + my * roi_h
            d = (cx - last_cx) ** 2 + (cy - last_cy) ** 2
            if best is None or d < best[0]:
                best = (d, cx, cy)
    return (best[1], best[2]) if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--seed", required=True, help="首帧攀岩者中心，全画幅像素 X,Y")
    ap.add_argument("--roi", default="760,950", help="ROI 尺寸 W,H（默认 760,950）")
    ap.add_argument("--seed-roi", default=None,
                    help="播种期窄 ROI W,H。场景里有第二个人贴着攀岩者时必须给：标准 ROI"
                         "会把两人都框进去，MediaPipe 挑谁不可控（六盘水 t=0 实测抓了"
                         " belayer，检出率 100% 全程没暴露）。窄框只装得下攀岩者，首次"
                         "检出锁定后自动恢复标准 ROI，之后靠 tracking 粘住。")
    ap.add_argument("--start-s", type=float, default=0.0)
    ap.add_argument("--end-s", type=float, default=None)
    A = ap.parse_args()

    cx, cy = (float(v) for v in A.seed.split(","))
    roi_w, roi_h = (int(v) for v in A.roi.split(","))
    seed_roi = tuple(int(v) for v in A.seed_roi.split(",")) if A.seed_roi else None
    # 三态。有第二个人贴着攀岩者时（给了 --seed-roi），标准 ROI 必须等攀岩者爬高、
    # 把那个人甩出框外之后才能用——实测「锁定后立刻恢复标准框」不行：框一变宽
    # belayer 回到框内，tracking 先验因画面剧变失效，MediaPipe 重新选人又选了他。
    # 0 = seeding：窄框等首次检出（不重扫——「离上次最近」在两人贴着时必选错）
    # 1 = tight：  锁定了，但继续窄框跟踪，直到垂直逃逸（cy 高过 escape_y）
    # 2 = full：   标准框 + 丢失重扫
    phase = 0 if seed_roi else 2
    escape_y = cy - (roi_h / 2 + 150)   # 中心高过此线 → 标准框下缘够不着播种点附近的人
    STEP = int(os.environ.get("CLIMB_STEP", "2"))
    COMPLEX = int(os.environ.get("CLIMB_COMPLEXITY", "2"))

    os.makedirs(A.out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(A.video))[0]

    cap = cv2.VideoCapture(A.video)   # 非 ASCII 路径 OK（FFmpeg 后端；只有 imwrite/imread 有坑）
    if not cap.isOpened():
        print("无法打开视频:", A.video); sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out_fps = fps / STEP

    out_video = os.path.join(A.out_dir, f"{base}_annotated.mp4")
    paths = {k: os.path.join(A.out_dir, f"{base}_{k}.csv")
             for k in ("landmarks", "angles", "pose2d", "roi_track")}

    big_w, big_h = 960, int(roi_h * 960 / roi_w)
    ann_h = int(big_h * ANNOT_W / big_w)
    writer = cv2.VideoWriter(out_video, cv2.VideoWriter_fourcc(*"mp4v"),
                             out_fps, (ANNOT_W, ann_h))

    lm_f = open(paths["landmarks"], "w", newline="")
    ang_f = open(paths["angles"], "w", newline="")
    d2_f = open(paths["pose2d"], "w", newline="")
    tr_f = open(paths["roi_track"], "w", newline="")
    lm_w, ang_w, d2_w, tr_w = (csv.writer(f) for f in (lm_f, ang_f, d2_f, tr_f))

    lm_header = ["frame", "time_s"]
    for nm in POSE_NAMES:
        lm_header += [f"{nm}_x", f"{nm}_y", f"{nm}_z", f"{nm}_vis"]
    lm_w.writerow(lm_header)
    d2_header = ["frame", "time_s", "img_w", "img_h"]
    for nm in POSE_NAMES:
        d2_header += [f"{nm}_nx", f"{nm}_ny", f"{nm}_px", f"{nm}_py", f"{nm}_vis"]
    d2_w.writerow(d2_header)
    ang_w.writerow(["frame", "time_s"] + list(ANGLE_DEFS.keys()) + ["torso_lean_deg", "mean_visibility"])
    tr_w.writerow(["frame", "time_s", "roi_cx", "roi_cy", "detected", "rescanned"])

    pose = mp_pose.Pose(model_complexity=COMPLEX, min_detection_confidence=0.3,
                        min_tracking_confidence=0.3, smooth_landmarks=True)
    pose_scan = mp_pose.Pose(static_image_mode=True, model_complexity=COMPLEX,
                             min_detection_confidence=0.3)

    if A.start_s > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, A.start_s * 1000.0)
    frame_idx = int(round(A.start_s * fps))
    proc_idx = detected = rescans = 0
    lost_run = 0                       # 连续丢检的有效帧数
    end_frame = int(A.end_s * fps) if A.end_s else None
    angle_accum = {k: [] for k in ANGLE_DEFS}

    while True:
        ok, frame = cap.read()
        if not ok or (end_frame and frame_idx >= end_frame):
            break
        if frame_idx % STEP != 0:
            frame_idx += 1
            continue
        t = frame_idx / fps
        proc_idx += 1

        cur_w, cur_h = (roi_w, roi_h) if phase == 2 else seed_roi
        x0 = int(np.clip(cx - cur_w / 2, 0, W - cur_w))
        y0 = int(np.clip(cy - cur_h / 2, 0, H - cur_h))
        roi = frame[y0:y0 + cur_h, x0:x0 + cur_w]
        big = cv2.resize(roi, (960, int(cur_h * 960 / cur_w)))
        res = pose.process(cv2.cvtColor(big, cv2.COLOR_BGR2RGB))

        rescanned = 0
        if not res.pose_landmarks:
            lost_run += 1
            # 重扫只在 full 态才允许：seeding/tight 期检不出不叫「丢」，继续拿窄框等
            # （六盘水实测：t=0 攀岩者弯腰抠脚点检不出 → 旧逻辑 2s 后全画幅重扫 →
            # 「离上次位置最近」选中了 175px 外的 belayer——多人贴着时这条准则必错）。
            if phase == 2 and lost_run >= int(LOST_RESCAN_S * out_fps):
                got = rescan(frame, pose_scan, roi_w, roi_h, cx, cy)
                rescans += 1
                rescanned = 1
                if got:
                    cx, cy = got
                    lost_run = 0
            elif phase == 0 and lost_run == int(10 * out_fps):
                print(f"⚠️ 播种期 10s 没检出（t≈{t:.1f}s）。攀岩者姿势可能太难"
                      f"（弯腰/蹲着检不出），换个他站直的时刻 --start-s 重跑。", flush=True)
        else:
            lost_run = 0
            detected += 1
            if phase == 0:
                phase = 1
                print(f"  锁定攀岩者 @ t={t:.1f}s ({int(cx)},{int(cy)})，窄框跟踪中", flush=True)
            lm2 = res.pose_landmarks.landmark
            wlm = res.pose_world_landmarks.landmark
            vis = [lm2[i].visibility for i in range(len(POSE_NAMES))]
            mean_vis = float(np.mean(vis))

            # 更新 ROI 中心（全画幅坐标）
            mx = float(np.mean([p.x for p in lm2])); my = float(np.mean([p.y for p in lm2]))
            cx = x0 + np.clip(mx, 0, 1) * cur_w
            cy = y0 + np.clip(my, 0, 1) * cur_h
            if phase == 1 and cy < escape_y:
                phase = 2
                print(f"  垂直逃逸 @ t={t:.1f}s（中心 y={int(cy)} < {int(escape_y)}），"
                      f"切换标准 ROI", flush=True)

            row = [frame_idx, round(t, 3)]
            for i in range(len(POSE_NAMES)):
                p = wlm[i]
                row += [round(p.x, 4), round(p.y, 4), round(p.z, 4), round(vis[i], 3)]
            lm_w.writerow(row)

            # ★ 全脚本的关键行：ROI 内归一化 → 全画幅归一化。img_w/img_h 写全画幅。
            d2row = [frame_idx, round(t, 3), W, H]
            for i in range(len(POSE_NAMES)):
                fx = (x0 + lm2[i].x * cur_w) / W
                fy = (y0 + lm2[i].y * cur_h) / H
                d2row += [round(fx, 5), round(fy, 5),
                          round(fx * W, 1), round(fy * H, 1), round(vis[i], 3)]
            d2_w.writerow(d2row)

            def P(idx):
                p = wlm[idx.value]
                return (p.x, p.y, p.z)
            angs = []
            for name, (a, b, c) in ANGLE_DEFS.items():
                v = angle_3pt(P(a), P(b), P(c))
                angs.append(round(v, 1) if not math.isnan(v) else "")
                if not math.isnan(v):
                    angle_accum[name].append(v)
            sh = (np.array(P(L.LEFT_SHOULDER)) + np.array(P(L.RIGHT_SHOULDER))) / 2
            hp = (np.array(P(L.LEFT_HIP)) + np.array(P(L.RIGHT_HIP))) / 2
            spine = sh - hp
            nn = np.linalg.norm(spine)
            torso = math.degrees(math.acos(np.clip(np.dot(spine, np.array([0, -1, 0])) / nn, -1, 1))) if nn else float("nan")
            ang_w.writerow([frame_idx, round(t, 3)] + angs +
                           [round(torso, 1) if not math.isnan(torso) else "", round(mean_vis, 3)])

            mp_draw.draw_landmarks(big, res.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                                   landmark_drawing_spec=mp_styles.get_default_pose_landmarks_style())

        tr_w.writerow([frame_idx, round(t, 3), round(cx, 1), round(cy, 1),
                       1 if res.pose_landmarks else 0, rescanned])
        ann = cv2.resize(big, (ANNOT_W, ann_h))
        mm, ss = divmod(int(t), 60)
        cv2.putText(ann, f"{mm}:{ss:02d} roi({int(cx)},{int(cy)})", (6, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)
        writer.write(ann)

        frame_idx += 1
        if proc_idx % 500 == 0:
            print(f"  进度 {frame_idx}/{total} 帧 ({100*frame_idx/max(total,1):.0f}%)  "
                  f"检出 {detected}/{proc_idx}  重扫 {rescans} 次", flush=True)

    cap.release(); writer.release(); pose.close(); pose_scan.close()
    for f in (lm_f, ang_f, d2_f, tr_f):
        f.close()

    rate = 100 * detected / proc_idx if proc_idx else 0
    print("\n=== 完成 ===")
    print(f"视频: {os.path.basename(A.video)}  {W}x{H} {fps:.2f}fps  STEP={STEP} (有效 {out_fps:.1f}fps)")
    print(f"处理 {proc_idx} 帧  检出 {detected} ({rate:.0f}%)  全画幅重扫 {rescans} 次")
    for name, acc in angle_accum.items():
        if acc:
            print(f"  {name:<15} 均值 {np.mean(acc):5.1f}  范围 {np.min(acc):5.1f}~{np.max(acc):5.1f}")
    print("输出:")
    for k, p in paths.items():
        print(f"  {k}: {p}")
    print(f"  标注视频: {out_video}")


if __name__ == "__main__":
    main()

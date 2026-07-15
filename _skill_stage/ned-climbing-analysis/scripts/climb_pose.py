#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
攀岩姿态分析 - 轻量验证脚本 (MediaPipe Pose)
输入一段攀岩视频, 输出:
  1) <name>_annotated.mp4   骨骼叠加的标注视频
  2) <name>_landmarks.csv   每帧 33 个关键点的 3D 坐标 (world, 单位米, 以髋中心为原点)
  3) <name>_angles.csv      每帧关节角度 (肘/肩/髋/膝 左右 + 躯干倾角)
用法:
  python3 climb_pose.py <视频文件>            # 输出到视频同目录
  python3 climb_pose.py <视频文件> <输出目录>
不传参数时, 自动处理脚本所在文件夹里的第一个视频文件。
"""
import sys, os, csv, math, glob
import cv2
import numpy as np
import mediapipe as mp

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils
mp_styles = mp.solutions.drawing_styles

L = mp_pose.PoseLandmark  # 枚举

# 需要计算的关节角度: 名称 -> (点A, 顶点B, 点C)  角度即 B 处 A-B-C 夹角
ANGLE_DEFS = {
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


def angle_3pt(a, b, c):
    """B 顶点处 A-B-C 的夹角(度)。a,b,c 为 (x,y,z)。"""
    a, b, c = np.array(a), np.array(b), np.array(c)
    ba, bc = a - b, c - b
    n = np.linalg.norm(ba) * np.linalg.norm(bc)
    if n == 0:
        return float("nan")
    cosv = np.clip(np.dot(ba, bc) / n, -1.0, 1.0)
    return math.degrees(math.acos(cosv))


def detect_rotation(path):
    """读取视频旋转标记(度)。优先 ffprobe; 失败返回 0。可用 CLIMB_ROTATE 覆盖。"""
    env = os.environ.get("CLIMB_ROTATE")
    if env is not None:
        return int(env) % 360
    try:
        import subprocess, re
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_streams", path],
            capture_output=True, text=True, timeout=20).stdout
        rot = 0
        m = re.search(r"^TAG:rotate=(-?\d+)", out, re.M)
        if m:
            rot = int(m.group(1)) % 360
        m2 = re.search(r"^rotation=(-?\d+)", out, re.M)  # displaymatrix, 符号相反
        if m2:
            rot = (-int(m2.group(1))) % 360
        return rot % 360
    except Exception:
        return 0


def apply_rotation(frame, rot):
    if rot == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if rot == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if rot == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def find_default_video():
    here = os.path.dirname(os.path.abspath(__file__))
    exts = ("*.mp4", "*.mov", "*.MOV", "*.MP4", "*.avi", "*.mkv", "*.m4v")
    for e in exts:
        hits = sorted(glob.glob(os.path.join(here, e)))
        if hits:
            return hits[0]
    return None


def main():
    if len(sys.argv) >= 2:
        video_path = sys.argv[1]
    else:
        video_path = find_default_video()
        if not video_path:
            print("没找到视频。请把攀岩视频放到脚本同目录，或: python3 climb_pose.py <视频路径>")
            sys.exit(1)
    if not os.path.exists(video_path):
        print("文件不存在:", video_path); sys.exit(1)

    out_dir = sys.argv[2] if len(sys.argv) >= 3 else os.path.dirname(os.path.abspath(video_path))
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(video_path))[0]

    # 性能开关 (环境变量): 降分辨率 / 抽帧 / 模型精度
    MAX_W = int(os.environ.get("CLIMB_MAX_W", "0"))       # 0=不缩放; 否则按最大宽度等比缩放
    STEP  = int(os.environ.get("CLIMB_STEP", "1"))        # 每隔几帧处理一帧
    COMPLEX = int(os.environ.get("CLIMB_COMPLEXITY", "2"))  # 0/1/2 mediapipe 模型复杂度

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("无法打开视频:", video_path); sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    rot = detect_rotation(video_path)
    if rot in (90, 270):           # 转正后宽高互换
        w, h = h, w
    if rot:
        print(f"检测到旋转标记 {rot}°, 已自动转正 (输出 {w}x{h})")

    out_video = os.path.join(out_dir, f"{base}_annotated.mp4")
    out_lm    = os.path.join(out_dir, f"{base}_landmarks.csv")
    out_ang   = os.path.join(out_dir, f"{base}_angles.csv")
    out_2d    = os.path.join(out_dir, f"{base}_pose2d.csv")

    # 计算输出尺寸与帧率
    scale = 1.0
    if MAX_W and w > MAX_W:
        scale = MAX_W / w
    ow, oh = int(round(w * scale)), int(round(h * scale))
    out_fps = fps / STEP

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_video, fourcc, out_fps, (ow, oh))

    lm_f = open(out_lm, "w", newline="")
    ang_f = open(out_ang, "w", newline="")
    d2_f = open(out_2d, "w", newline="")
    lm_w = csv.writer(lm_f)
    ang_w = csv.writer(ang_f)
    d2_w = csv.writer(d2_f)

    lm_header = ["frame", "time_s"]
    for nm in POSE_NAMES:
        lm_header += [f"{nm}_x", f"{nm}_y", f"{nm}_z", f"{nm}_vis"]
    lm_w.writerow(lm_header)

    # 2D 画面坐标 (归一化 0~1, 左上原点; 另存像素). 用于全局重心轨迹/效率
    d2_header = ["frame", "time_s", "img_w", "img_h"]
    for nm in POSE_NAMES:
        d2_header += [f"{nm}_nx", f"{nm}_ny", f"{nm}_px", f"{nm}_py", f"{nm}_vis"]
    d2_w.writerow(d2_header)
    ang_w.writerow(["frame", "time_s"] + list(ANGLE_DEFS.keys()) + ["torso_lean_deg", "mean_visibility"])

    pose = mp_pose.Pose(model_complexity=COMPLEX, min_detection_confidence=0.5,
                        min_tracking_confidence=0.5, smooth_landmarks=True)

    frame_idx = 0      # 原始帧号
    proc_idx = 0       # 已处理帧数
    detected = 0
    angle_accum = {k: [] for k in ANGLE_DEFS}
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % STEP != 0:
            frame_idx += 1
            continue
        if rot:
            frame = apply_rotation(frame, rot)
        if scale != 1.0:
            frame = cv2.resize(frame, (ow, oh))
        t = frame_idx / fps
        proc_idx += 1
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = pose.process(rgb)

        if res.pose_landmarks:
            detected += 1
            mp_draw.draw_landmarks(
                frame, res.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=mp_styles.get_default_pose_landmarks_style())

            # world landmarks 用于角度 (米制, 视角无关); 2D 用于可视性
            wlm = res.pose_world_landmarks.landmark
            vis = [res.pose_landmarks.landmark[i].visibility for i in range(len(POSE_NAMES))]
            mean_vis = float(np.mean(vis))

            row = [frame_idx, round(t, 3)]
            for i, nm in enumerate(POSE_NAMES):
                p = wlm[i]
                row += [round(p.x, 4), round(p.y, 4), round(p.z, 4), round(vis[i], 3)]
            lm_w.writerow(row)

            # 2D 画面坐标
            d2row = [frame_idx, round(t, 3), ow, oh]
            for i, nm in enumerate(POSE_NAMES):
                lp = res.pose_landmarks.landmark[i]
                d2row += [round(lp.x, 5), round(lp.y, 5),
                          round(lp.x * ow, 1), round(lp.y * oh, 1), round(vis[i], 3)]
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

            # 躯干倾角: 肩中点->髋中点 向量 与 垂直方向夹角
            sh = (np.array(P(L.LEFT_SHOULDER)) + np.array(P(L.RIGHT_SHOULDER))) / 2
            hp = (np.array(P(L.LEFT_HIP)) + np.array(P(L.RIGHT_HIP))) / 2
            spine = sh - hp
            vert = np.array([0, -1, 0])  # mediapipe world: y 向下为正
            nn = np.linalg.norm(spine)
            torso = math.degrees(math.acos(np.clip(np.dot(spine, vert) / nn, -1, 1))) if nn else float("nan")

            ang_w.writerow([frame_idx, round(t, 3)] + angs +
                           [round(torso, 1) if not math.isnan(torso) else "", round(mean_vis, 3)])

            # 在画面左上角叠加几个关键角度, 方便直接看
            y0 = 30
            for label, key in [("L elbow", "left_elbow"), ("R elbow", "right_elbow"),
                               ("L knee", "left_knee"), ("R knee", "right_knee")]:
                val = dict(zip(ANGLE_DEFS.keys(), angs)).get(key, "")
                cv2.putText(frame, f"{label}: {val}", (10, y0), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (0, 255, 0), 2, cv2.LINE_AA)
                y0 += 28
        writer.write(frame)
        frame_idx += 1
        if total and frame_idx % 100 == 0:
            print(f"  进度 {frame_idx}/{total} 帧 ({100*frame_idx/total:.0f}%)  已处理{proc_idx}帧 检出{detected}", flush=True)

    cap.release(); writer.release(); lm_f.close(); ang_f.close(); d2_f.close(); pose.close()

    rate = 100 * detected / proc_idx if proc_idx else 0
    print("\n=== 完成 ===")
    print(f"视频: {os.path.basename(video_path)}  原始 {frame_idx} 帧, {w}x{h}, {fps:.1f}fps")
    print(f"处理参数: 缩放至 {ow}x{oh}, 每{STEP}帧取1, 模型复杂度{COMPLEX}; 实际处理 {proc_idx} 帧")
    print(f"检测到人体的帧: {detected}/{proc_idx} ({rate:.0f}%)  <- 攀岩遮挡多, 这个比例是关键参考")
    print("各关节平均角度(度):")
    for k, vals in angle_accum.items():
        if vals:
            print(f"  {k:14s} 均值 {np.mean(vals):5.1f}  范围 {np.min(vals):5.1f}~{np.max(vals):5.1f}")
    print("\n输出:")
    print("  标注视频:", out_video)
    print("  关键点CSV:", out_lm)
    print("  角度CSV:", out_ang)


if __name__ == "__main__":
    main()

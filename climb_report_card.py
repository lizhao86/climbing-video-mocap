#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_report_card.py —— 合并报告卡（v1 强度 + v2a 节奏，一条线一张卡）

老板 2026-07-17：报告卡不该分两张。v1/v2a 是开发阶段代号，不该漏到用户面前。
本脚本只做「展示」，不算指标：读 metrics.json(v1) + metrics_v2.json(v2a) +
segments.json + 两份 CSV，出一张「攀岩报告卡.html」。
v1/v2a 的脚本都不用改——metrics 文件就是它们的产出契约。

设计：暗色·影像优先（老板 2026-07-17 拍板）。画面是主角，数据是标注。
  - 图表全部内联 SVG（可主题化 / 任意缩放清晰 / 与 HTML 精确对齐 / 无中文字体依赖）
  - 难点截图按骨架包围盒自动取景，出的是动作特写而不是人占 15% 的全景

用法：
  python3 climb_report_card.py --dir <数据目录> --base <片名> --video <原片> --out <输出目录>
"""
import csv, json, os, argparse, warnings, contextlib
import numpy as np


@contextlib.contextmanager
def warnings_ignore():
    """np.nanmin/nanmax 遇到全 NaN 切片会刷 RuntimeWarning，语义上就是"这段没数据"，
    返回 NaN 正是想要的，不需要吵。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield

# ── 设计令牌（与 HTML 里的 CSS 变量同源）────────────────────────────
C_MOVE   = "#e08a42"   # 出手移动（= 全页强色，chrome 与数据同一含义：动作）
C_REST   = "#5fa07a"   # 真休息
C_ADJUST = "#5a6070"   # 找点调整
C_STUCK  = "#45a8c4"   # 卡住型难点（v2a）
C_POWER  = "#c9556b"   # 发力型吃力点（v1）

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


def imwrite_unicode(path, img, quality=88):
    """写图。**不要用 cv2.imwrite**：它在 Windows 上遇到含非 ASCII 的路径会
    **静默失败**——返回 False、不抛异常、不留文件（本项目路径含「我的代码」「素材」，
    2026-07-17 实测必中）。v1 的 climb_analyze_report.py 就栽在这上面：它写的 5 张 crux
    截图从来没落盘，报告卡里一直是裂图，直到今天才发现。
    这里走 imencode + Python 的 open()，绕开 OpenCV 的窄字符文件 I/O；写不成就抛异常，
    绝不再静默骗人。"""
    import cv2
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise IOError(f"imencode 失败: {path}")
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise IOError(f"写盘失败: {path}")
    return True


CLIP_PRE, CLIP_POST = 1.0, 2.0   # 片段覆盖切面前 1 秒、后 2 秒
CLIP_CRF = 24                    # 片段帧率跟源走，不重采样（见 grab_shots 的 VFR 注释）

# 悬浮播放的 JS。**放模块级常量、不写进 HTML 的 f-string**：f-string 会把 JS 的 `{`
# 当插值起手，非得写成 `{{` 才行，一段几十行的 JS 会被转义符淹掉。
HOVER_JS = """<script>
// 视频是 preload="none"，不悬浮就一个字节都不下载。
// 事件挂在 .crux / .hot 上而不是 video 自己：浮窗里的 video 只在父级 :hover 时
// 才可见，鼠标根本落不到 video 身上。
(function () {
  document.querySelectorAll('.crux video, .pop video').forEach(function (v) {
    var host = v.closest('.crux, .hot');
    if (!host) return;
    host.addEventListener('mouseenter', function () {
      v.currentTime = 0;   // 每次都从片头（切面前 1 秒）看起，否则第二次悬浮会从
                           // 上次 mouseleave 停的地方（切面）起播，"前 1 秒"就没了
      // 快速划过时 play() 的 Promise 会被随即而来的 pause() 打断而 reject，吞掉
      var p = v.play();
      if (p && p.catch) p.catch(function () {});
    });
    host.addEventListener('mouseleave', function () {
      v.pause();
      // 回到「切面那一刻」而不是片头：片子是从切面前 1 秒起的，归零会让卡片停在
      // 早 1 秒的帧上，跟旁边写的时刻/角度对不上。data-t 就是这个偏移。
      v.currentTime = parseFloat(v.dataset.t) || 0;
    });
  });
})();
</script>"""


def video_size(video):
    """视频的 (宽, 高)。走 cv2.VideoCapture——读非 ASCII 路径是正常的（FFmpeg 后端），
    只有 imwrite/imread 有那个坑。"""
    import cv2
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise IOError(f"打不开视频: {video}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return w, h


def frame_box(bb_at, bb_win, W, H, width=520, aspect=(4, 5)):
    """算 4:5 竖构图的裁切框，返回 (x0, y0, cw, ch) 像素整数 + 输出尺寸。

    bb_at  = 切面那一帧的骨架包围盒；bb_win = 整个片段窗口内的包围盒并集。
    取景同时满足两条：
      ① 不比只出静态图那会儿（单帧盒 ×1.9）更紧 —— 老报告卡的观感不变；
      ② 装得下 3 秒里人跑到过的所有位置（并集盒 ×1.12）—— 否则片子里人会被裁掉。
    实测 3 秒窗口的并集盒比单帧盒高 1.13-1.20 倍（最大 1.59），宽 1.22-1.48 倍
    （最大 2.50，IMG_6411 的 5.5s）——高度那 1.9 倍余量本来就够，宽度不够，
    所以下面单独按宽度反算一次 ch。
    """
    aw, ah = aspect
    cx, cy, bw, bh = bb_win
    ch_for_w = bw * 1.12 * (W / H) * (ah / aw)   # 装下并集宽度所需的 ch
    ch = min(1.0, max(bb_at[3] * 1.9, bh * 1.12, ch_for_w, 0.34))
    cw = min(1.0, ch * (aw / ah) * (H / W))
    x0 = min(max(cx - cw / 2, 0.0), 1.0 - cw)
    y0 = min(max(cy - ch / 2, 0.0), 1.0 - ch)
    # 转像素并取偶数：h264 的 yuv420p 要求宽高可被 2 整除
    px = lambda v, n: max(0, min(int(v * n) // 2 * 2, n))
    x0p, y0p, cwp, chp = px(x0, W), px(y0, H), px(cw, W), px(ch, H)
    cwp, chp = min(cwp, W - x0p), min(chp, H - y0p)
    return x0p, y0p, cwp, chp, width, int(round(width * ah / aw))


def grab_shots(video, times, boxes, outdir, tag):
    """一次顺序解码，同时出静态图和 3 秒片段（切面前 1 后 2）。
    返回 (jpg列表, mp4列表, 偏移列表)——偏移 = 切面那一帧在片段内的秒数，给 data-t 用。

    ⚠️ **定位必须走 cv2，绝不能让 ffmpeg 自己 -ss 找时刻**（2026-07-17 实测踩过）：
    本项目素材是 VFR（IMG_6411：r_frame_rate 29.92 / avg_frame_rate 32.61 对不上）。
    climb_pose.py 的 `time_s = frame_idx / avg_fps` 是**名义时间**，不是真实 PTS；
    cv2 的 POS_MSEC 走的也是 round(ts*fps)→帧号 这个名义映射，两者对得上，所以
    metrics 里的时刻和 cv2 抽的帧一直是一致的。但 ffmpeg 的 -ss 走**真实 PTS**——
    两条时间轴在 VFR 上会漂，实测 IMG_6411 上漂 53-105ms（约 3 帧）且**逐处不同**
    （1.5s 处 105ms、5.5s 处 53ms），固定偏移糊不过去。先前让 ffmpeg -ss 切片，
    片段第 1.0s 和 poster 差了整整 3 帧，正是「数字描述的不是读者看到的那一帧」。
    这里 ffmpeg 只当编码器用，帧由 cv2 按名义时间轴喂进去。

    静态图直接取自片段的同一批帧（第 i_poster 帧），所以 poster 和片段停住时
    是**同一帧**——靠构造保证，不靠两边取整凑巧一致。

    **用 MP4 不用 GIF**（同日实测，同一 3 秒切片 520x650）：
      GIF 15fps 3444KB / GIF 10fps 2645KB / 动图 WebP 15fps 593KB / h264 30fps 90KB。
    GIF 双输——体积是 h264 的 29 倍，画质还更差（128 色 + 抖动，紫墙和衣服一片噪点）。

    ffmpeg 不在就只出静态图（片段列表全 None），报告卡自动退回纯静态，不报错。
    """
    import cv2, shutil, subprocess
    os.makedirs(outdir, exist_ok=True)
    has_ff = bool(shutil.which("ffmpeg"))
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise IOError(f"打不开视频: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    jpgs, mp4s, offs = [], [], []
    for i, (ts, bx) in enumerate(zip(times, boxes)):
        x0, y0, cw, ch, ow, oh = bx
        start = max(0.0, ts - CLIP_PRE)
        n_want = int(round((CLIP_PRE + CLIP_POST) * fps))
        i_poster = int(round((ts - start) * fps))       # 切面在这批帧里的下标
        # data-t 取**帧中心**而不是 i_poster/fps：第 k 帧占 [k/fps, (k+1)/fps)，
        # 把 currentTime 设成 k/fps 会因浮点/取整落到第 k-1 帧上——刚好差一帧，
        # 静止时看到的就不是文案说的那一刻了。
        offs.append((i_poster + 0.5) / fps)
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)

        proc, jpg_done = None, None
        for k in range(n_want):
            ok, f = cap.read()
            if not ok:
                break
            crop = f[y0:y0 + ch, x0:x0 + cw]
            if crop.size == 0:
                break
            crop = cv2.resize(crop, (ow, oh))
            if k == i_poster:                            # 静态图 = 片段里的这一帧
                jpg_done = f"{tag}_{i}.jpg"
                imwrite_unicode(os.path.join(outdir, jpg_done), crop)
            if has_ff:
                if proc is None:
                    cmd = ["ffmpeg", "-v", "error", "-y",
                           "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{ow}x{oh}", "-r", f"{fps:.6f}", "-i", "-",
                           "-an", "-c:v", "libx264", "-crf", str(CLIP_CRF),
                           "-preset", "slow", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart",
                           os.path.join(outdir, f"{tag}_{i}.mp4")]
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE)
                try:
                    proc.stdin.write(crop.tobytes())
                except (BrokenPipeError, OSError):
                    break
        jpgs.append(jpg_done)
        if proc is None:
            mp4s.append(None)
            continue
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.wait()
        out = os.path.join(outdir, f"{tag}_{i}.mp4")
        # 不静默失败：编码器报错或没落盘就记 None，让上层的计数打印出来
        mp4s.append(f"{tag}_{i}.mp4" if proc.returncode == 0 and os.path.exists(out)
                    and os.path.getsize(out) > 0 else None)
    cap.release()
    return jpgs, mp4s, offs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--route", default="")
    A = ap.parse_args()

    ASSET = os.path.join(A.out, "报告卡素材")
    os.makedirs(ASSET, exist_ok=True)

    d2 = load_csv(os.path.join(A.dir, f"{A.base}_pose2d.csv"))
    v1 = json.load(open(os.path.join(A.dir, f"{A.base}_metrics.json"), encoding="utf-8"))
    v2 = json.load(open(os.path.join(A.dir, f"{A.base}_metrics_v2.json"), encoding="utf-8"))
    S = json.load(open(os.path.join(A.dir, f"{A.base}_segments.json"), encoding="utf-8"))
    # 动作识别（climb_match.py 窄版）可选：没跑过就没有这个区块，报告卡照常出
    rec_path = os.path.join(A.dir, f"{A.base}_recognition.json")
    REC = json.load(open(rec_path, encoding="utf-8")) if os.path.exists(rec_path) else None

    t = col(d2, "time_s")
    N = len(t)

    def pt(n):
        return np.vstack([col(d2, f"{n}_nx"), 1.0 - col(d2, f"{n}_ny")]).T
    P = {j: pt(j) for j in JOINTS}
    sh = (P["left_shoulder"] + P["right_shoulder"]) / 2
    hp = (P["left_hip"] + P["right_hip"]) / 2
    body_scale = np.nanmedian(np.linalg.norm(sh - hp, axis=1))
    trunk = (sh + hp) / 2
    thigh = ((P["left_hip"] + P["left_knee"]) / 2 + (P["right_hip"] + P["right_knee"]) / 2) / 2
    shank = ((P["left_knee"] + P["left_ankle"]) / 2 + (P["right_knee"] + P["right_ankle"]) / 2) / 2
    arm = ((P["left_shoulder"] + P["left_wrist"]) / 2 + (P["right_shoulder"] + P["right_wrist"]) / 2) / 2
    com = smooth2d(0.08 * P["nose"] + 0.50 * trunk + 0.20 * thigh + 0.12 * shank + 0.10 * arm, 13)
    height = (com[:, 1] - np.nanmin(com[:, 1])) / body_scale

    C = v2["completion"]
    t0, t1 = C["start_s"], C["end_s"]

    def idx_at(ts):
        return int(np.clip(np.searchsorted(t, ts), 0, N - 1))

    def _box(sl):
        """把 P 的一个时间切片压成归一化包围盒 (cx, cy, w, h)，y 换回图像坐标（向下）。"""
        xs = np.concatenate([P[j][sl, 0] for j in JOINTS])
        ys = np.concatenate([1.0 - P[j][sl, 1] for j in JOINTS])
        xs, ys = xs[~np.isnan(xs)], ys[~np.isnan(ys)]
        if len(xs) == 0:
            return (0.5, 0.5, 0.3, 0.4)
        return (float((xs.min() + xs.max()) / 2), float((ys.min() + ys.max()) / 2),
                float(xs.max() - xs.min()), float(ys.max() - ys.min()))

    def bbox_at(ts):
        """该时刻骨架的归一化包围盒。"""
        return _box(slice(idx_at(ts), idx_at(ts) + 1))

    def bbox_win(ts):
        """片段窗口 [ts-1, ts+2] 内骨架包围盒的并集——取景要装得下人跑到过的地方。"""
        return _box(slice(idx_at(ts - CLIP_PRE), idx_at(ts + CLIP_POST) + 1))

    vw_, vh_ = video_size(A.video)

    def boxes_for(times):
        return [frame_box(bbox_at(x), bbox_win(x), vw_, vh_) for x in times]

    # ── 给 v1 的发力型吃力点补上「当时到底什么在极端」──────────────
    # v1 的 metrics.json 只给了时刻，不给依据，于是 4 张卡文案全一样、毫无信息量。
    # v1 的 crux 强度 = 重心加速度 + 肢体速度 + 关节极端屈曲的综合，这里把这三项在
    # 该时刻的实际值算出来，挑最突出的说人话。
    an_rows = load_csv(os.path.join(A.dir, f"{A.base}_angles.csv"))
    fra = col(an_rows, "frame").astype(int)
    fr2 = col(d2, "frame").astype(int)

    def ang_series(name):
        mp = dict(zip(fra, col(an_rows, name)))
        return np.array([mp.get(f, np.nan) for f in fr2])
    A_ = {k: ang_series(k) for k in ["left_knee", "right_knee", "left_elbow", "right_elbow"]}
    # 可见度门槛：和 metrics_v2 的口径一致，**每条肢体各自判定**。不加这个会把遮挡时的
    # 噪声当结论印在卡上——实测左肘原始最小值 12°，那是骨架飘了，不是他真把手臂折成 12°。
    # 另加**解剖学体检**（与 metrics_v2 同口径）：3D 重建的 前臂/上臂 比不合人体的帧，
    # 该臂的肘角是垃圾，不采信。可见度分数**预测不了**重建质量——实测 15-20% 的帧
    # 可见度达标却解剖学不可能，两个体检项互相独立，必须都过。
    VIS_MIN, ANAT_LO, ANAT_HI = 0.30, 0.70, 1.40
    lm = load_csv(os.path.join(A.dir, f"{A.base}_landmarks.csv"))

    def anat_ok(side, a, b, c_):
        def P3(j):
            return np.vstack([col(lm, f"{side}_{j}_x"), col(lm, f"{side}_{j}_y"),
                              col(lm, f"{side}_{j}_z")]).T
        p1, p2, p3 = P3(a), P3(b), P3(c_)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.linalg.norm(p3 - p2, axis=1) / np.linalg.norm(p2 - p1, axis=1)
        out = np.zeros(N, bool)
        m_ = min(len(r), N)
        out[:m_] = (r[:m_] > ANAT_LO) & (r[:m_] < ANAT_HI)
        return out

    gate = {}
    for side in ["left", "right"]:
        gate[f"{side}_elbow"] = ((col(d2, f"{side}_elbow_vis") > VIS_MIN)
                                 & (col(d2, f"{side}_wrist_vis") > VIS_MIN)
                                 & anat_ok(side, "shoulder", "elbow", "wrist"))
        gate[f"{side}_knee"] = ((col(d2, f"{side}_knee_vis") > VIS_MIN)
                                & (col(d2, f"{side}_ankle_vis") > VIS_MIN)
                                & anat_ok(side, "hip", "knee", "ankle"))
    Ag = {k: np.where(gate[k], v, np.nan) for k, v in A_.items()}
    # 「较直那条臂」的肘角——弯臂判定的核心量，与 metrics_v2 同口径
    with warnings_ignore():
        eo_g = np.nanmax(np.vstack([Ag["left_elbow"], Ag["right_elbow"]]), axis=0)
    dt = np.gradient(t)
    com_spd = np.linalg.norm(np.gradient(com, axis=0) / dt[:, None] / body_scale, axis=1)

    # ── 复算 v1 的强度四项，用来**诚实标注**每个吃力点到底是什么在主导 ──────
    # v1 原式（climb_analyze_report.py，冻结不改）：
    #   强度 = z(重心加速度) + z(肢体速度) + (120-膝角)/40 + (120-肘角)/40
    # 2026-07-17 拆解实测（老板一眼看出「14.4s 那张图人明明在放松」后查的）：
    #   z加速度 中位 -0.12 / 90分位 0.04 / 最大 28.55
    #   z速度   中位 -0.26 / 90分位 0.73 / 最大 13.70
    #   膝屈项  中位  0.48 / 90分位 1.44 / 最大  2.08
    #   肘屈项  中位  0.61 / 90分位 1.43 / 最大  2.69
    # 两个 z 分数被极端离群值撑大的标准差压扁，正常帧几乎恒为 0；**屈曲项才是实际主导**。
    # 结论：v1 的「吃力点」实际是「关节弯得深」排序，不是「用力」排序。攀岩时膝盖弯 78°
    # 完全可以是舒服地踩在脚点上。所以这里不再声称「动作剧烈」，改为报出真实主导项。
    v1_acc = np.gradient(np.gradient(com, axis=0) / dt[:, None] / body_scale,
                         axis=0) / dt[:, None]
    v1_acc_mag = np.linalg.norm(v1_acc, axis=1)

    def limb_speed(n):
        p = smooth2d(P[n], 9)
        return np.linalg.norm(np.gradient(p, axis=0) / dt[:, None] / body_scale, axis=1)
    v1_allspeed = np.nanmax(np.vstack([limb_speed(k) for k in
                                       ["left_wrist", "right_wrist", "left_ankle", "right_ankle"]]), axis=0)
    with warnings_ignore():
        v1_knee = np.nanmin(np.vstack([A_["left_knee"], A_["right_knee"]]), axis=0)
        v1_elbow = np.nanmin(np.vstack([A_["left_elbow"], A_["right_elbow"]]), axis=0)
    v1_terms = {
        "重心变向最急": (v1_acc_mag - np.nanmean(v1_acc_mag)) / (np.nanstd(v1_acc_mag) + 1e-6),
        "手脚挥得最快": (v1_allspeed - np.nanmean(v1_allspeed)) / (np.nanstd(v1_allspeed) + 1e-6),
        "膝盖弯得最深": (120 - v1_knee) / 40,
        "手肘弯得最深": (120 - v1_elbow) / 40,
    }
    # 每个主导项对应的「原始量 + 该量的极端方向」，用来生成和标签一致的依据。
    # ⚠️ 曾经标签报四肢速度、依据却报重心速度，两个不同的量——老板：「你提到挥动最快，
    # 但你没提到速度」。一张卡只说一件事：哪一项最极端 + 那一项的实际值 + 它有多极端。
    LIMB_ZH = {"left_wrist": "左手", "right_wrist": "右手",
               "left_ankle": "左脚", "right_ankle": "右脚"}
    limb_spd = {k: limb_speed(k) for k in LIMB_ZH}

    def pct_rank(arr, val, high_is_extreme):
        """该值在全片中有多极端，返回「前 X%」的 X。"""
        a = arr[~np.isnan(arr)]
        if not len(a):
            return None
        frac = np.mean(a > val) if high_is_extreme else np.mean(a < val)
        return max(1, round(frac * 100))

    def power_detail(ts):
        """报出**图上这一帧**里最极端的那一项，以及它在全片中的位置。
        ⚠️ 数字只取该帧，不做 ±3 帧取极值——老板一眼看出「图里两手都伸直了，凭什么说
        肘屈到 92°」：那 92° 来自 3 帧之前。数字必须描述读者看到的那一帧。"""
        i = idx_at(ts)
        vals = {k: float(v[i]) for k, v in v1_terms.items()}
        dom = max(vals, key=lambda k: vals[k])
        with warnings_ignore():
            if dom == "膝盖弯得最深":
                l_, r_ = Ag["left_knee"][i], Ag["right_knee"][i]
                a = float(np.nanmin([l_, r_]))
                if np.isnan(a):
                    return dom, "看不清（膝盖被挡住）"
                p = pct_rank(v1_knee, a, False)
                return dom, f"{'左' if l_ < r_ else '右'}膝弯到 {a:.0f}°，全片最弯的 {p}%"
            if dom == "手肘弯得最深":
                l_, r_ = Ag["left_elbow"][i], Ag["right_elbow"][i]
                a = float(np.nanmin([l_, r_]))
                if np.isnan(a):
                    return dom, "看不清（手臂被挡住）"
                p = pct_rank(v1_elbow, a, False)
                return dom, f"{'左' if l_ < r_ else '右'}肘弯到 {a:.0f}°，全片最弯的 {p}%"
            if dom == "手脚挥得最快":
                which = max(LIMB_ZH, key=lambda k: limb_spd[k][i])
                v_ = float(limb_spd[which][i])
                p = pct_rank(v1_allspeed, v_, True)
                return dom, f"{LIMB_ZH[which]}挥到 {v_:.1f} 身长/秒，全片最快的 {p}%"
            v_ = float(v1_acc_mag[i])
            p = pct_rank(v1_acc_mag, v_, True)
            return dom, f"重心猛地变向，全片最急的 {p}%"

    # ── 抽帧：每个难点一张动作特写 ─────────────────────────────
    crux = v2["crux"]["items"]
    for c in crux:
        if c["source"] == "v1":
            c["driver"], c["detail"] = power_detail(c["t"])
    ctimes = [c["t"] for c in crux]
    cfiles, cclips, coffs = grab_shots(A.video, ctimes, boxes_for(ctimes), ASSET, "crux")
    for c, fn, cl, off in zip(crux, cfiles, cclips, coffs):
        c["img"], c["clip"], c["clip_t"] = fn, cl, off

    # 弯臂段也抽帧（老板要求悬浮预览）：取段内肘角最弯的那一刻，最能说明问题
    bents = v2["bent_arm"]["items"]
    btimes = []
    for b in bents:
        i0b, i1b = idx_at(b["start_s"]), idx_at(b["end_s"])
        with warnings_ignore():
            seg = np.where(np.isnan(eo_g[i0b:i1b + 1]), np.inf, eo_g[i0b:i1b + 1])
        btimes.append(float(t[i0b + int(np.argmin(seg))]) if len(seg) else b["start_s"])
    bfiles, bclips, boffs = grab_shots(A.video, btimes, boxes_for(btimes), ASSET, "bent")
    for b, ts_, fn, cl, off in zip(bents, btimes, bfiles, bclips, boffs):
        b["img"], b["clip"], b["clip_t"], b["peak_s"] = fn, cl, off, round(ts_, 2)

    # ── SVG 时间线：分三层堆叠 ────────────────────────────────
    # 一开始把分段做成全高色带糊在曲线后面，近黑底 + 18% 透明 = 一片棕色泥浆，
    # 什么也读不出。改成剪辑软件式的分层：曲线干净地画，分段独立成细条，肘角单独一行。
    VW, VH = 1200, 296
    PADL, PADR = 46, 10
    PLOT_W = VW - PADL - PADR
    H_TOP, H_BOT = 14, 176          # 重心高度曲线
    SEG_TOP, SEG_H = 190, 16        # 分段细条
    E_TOP, E_BOT = 224, 272         # 肘角

    def x_of(ts):
        return PADL + (ts - t0) / max(t1 - t0, 1e-6) * PLOT_W

    hmax = float(np.nanmax(height))

    def y_of(h):
        return H_BOT - (h / max(hmax, 1e-6)) * (H_BOT - H_TOP)

    m = (t >= t0) & (t <= t1)
    mi = np.flatnonzero(m)
    pts = " ".join(f"{x_of(t[i]):.1f},{y_of(height[i]):.1f}" for i in mi)
    # 曲线下方填充，让"爬升"这件事有体量感
    area = (f'{x_of(t0):.1f},{H_BOT} ' + pts + f' {x_of(t1):.1f},{H_BOT}')

    gridlines = "".join(
        f'<line x1="{PADL}" y1="{y_of(h):.1f}" x2="{VW-PADR}" y2="{y_of(h):.1f}" '
        f'stroke="#262a33" stroke-width="1"/>'
        f'<text x="{PADL-8}" y="{y_of(h)+3.5:.1f}" fill="#6b7280" font-size="10" '
        f'text-anchor="end" font-family="Space Mono, monospace">{h}</text>'
        for h in range(0, int(hmax) + 1))

    # 分段细条
    rest_starts = {r["start_s"] for r in v2["rests"]["items"]}
    bands = []
    for s in S["segments"]:
        if s["end_s"] <= t0 or s["start_s"] >= t1:
            continue
        a, b = max(s["start_s"], t0), min(s["end_s"], t1)
        c_ = C_MOVE if s["kind"] == "move" else (
            C_REST if s["start_s"] in rest_starts else C_ADJUST)
        bands.append(f'<rect x="{x_of(a):.1f}" y="{SEG_TOP}" '
                     f'width="{max(x_of(b)-x_of(a),0.8):.1f}" height="{SEG_H}" fill="{c_}"/>')

    # 肘角曲线（较直那条臂）+ 弯臂高亮 + 直臂线
    # 原始逐帧肘角毛刺很重（±20° 的高频抖动），画出来是一团毛线。这里做 9 帧滑动
    # 平均——只为**看**，判定用的仍是 metrics_v2.json 里未平滑的原值。
    eo = eo_g.copy()
    good = ~np.isnan(eo_g)
    if good.sum() > 9:
        k = np.ones(9) / 9
        filled = eo_g.copy()
        filled[~good] = np.interp(np.flatnonzero(~good), np.flatnonzero(good), eo_g[good])
        sm = np.convolve(filled, k, mode="same")
        eo = np.where(good, sm, np.nan)      # 原本就没数据的帧保持断开，不要连虚线
    E_LO, E_HI = 40, 180

    def ey(v):
        return E_BOT - (np.clip(v, E_LO, E_HI) - E_LO) / (E_HI - E_LO) * (E_BOT - E_TOP)

    esegs, cur = [], []
    for i in mi:
        if np.isnan(eo[i]):
            if len(cur) > 1:
                esegs.append(cur)
            cur = []
        else:
            cur.append(f"{x_of(t[i]):.1f},{ey(eo[i]):.1f}")
    if len(cur) > 1:
        esegs.append(cur)
    elbow_paths = "".join(
        f'<polyline points="{" ".join(sg)}" fill="none" stroke="#a2a9b8" stroke-width="1.2" '
        f'vector-effect="non-scaling-stroke"/>' for sg in esegs)

    bent = "".join(
        f'<rect x="{x_of(b["start_s"]):.1f}" y="{E_TOP}" '
        f'width="{max(x_of(b["end_s"])-x_of(b["start_s"]),1):.1f}" '
        f'height="{E_BOT-E_TOP}" fill="{C_POWER}" opacity="0.3"/>'
        for b in v2["bent_arm"]["items"])

    straight_line = (f'<line x1="{PADL}" y1="{ey(150):.1f}" x2="{VW-PADR}" y2="{ey(150):.1f}" '
                     f'stroke="{C_REST}" stroke-width="1" stroke-dasharray="4 4" opacity="0.8"/>'
                     f'<text x="{PADL-8}" y="{ey(150)+3.5:.1f}" fill="{C_REST}" font-size="9" '
                     f'text-anchor="end" font-family="Space Mono, monospace">150°</text>')

    # 难点竖线 + 顶部三角
    marks = ""
    for c in crux:
        x = x_of(c["t"])
        c_ = C_STUCK if c["source"] == "v2a" else C_POWER
        marks += (f'<line x1="{x:.1f}" y1="{H_TOP}" x2="{x:.1f}" y2="{SEG_TOP+SEG_H}" '
                  f'stroke="{c_}" stroke-width="1" stroke-dasharray="2 4" opacity="0.85"/>'
                  f'<path d="M{x-5:.1f},{H_TOP-11} L{x+5:.1f},{H_TOP-11} L{x:.1f},{H_TOP-2} Z" '
                  f'fill="{c_}"/>')

    ticks = ""
    step = 5 if (t1 - t0) < 45 else 10
    for ts in range(0, int(t1 - t0) + 1, step):
        x = x_of(t0 + ts)
        ticks += (f'<line x1="{x:.1f}" y1="{E_BOT}" x2="{x:.1f}" y2="{E_BOT+4}" stroke="#3a404d"/>'
                  f'<text x="{x:.1f}" y="{E_BOT+17}" fill="#6b7280" font-size="10" '
                  f'text-anchor="middle" font-family="Space Mono, monospace">{ts}s</text>')

    def shot(img, clip, clip_t):
        """预览画面。有片段就出 <video>、静态图当 poster；没片段退回 <img>；都没有出空。

        preload="none" + 悬浮才播：一份报告 7-10 个片段，全 autoplay 会同时解码
        10 路 h264，笔记本风扇直接起飞；而且不悬浮就一个字节都不下，实际流量跟
        以前的纯静态图持平。播放由页尾那段 JS 接管（HOVER_JS）。

        data-t = 切面那一帧在片段内的秒数（grab_shots 按实际帧号算的，取帧中心）。
        **不能省**：片段是从切面前 1 秒起头的，鼠标移开时把 currentTime 归零的话，
        卡片就永久停在比切面早 1 秒的那一帧上，旁边的时刻/角度却还在描述切面——
        图文对不上。回到 data-t，静止帧才跟 poster、跟文案说的是同一刻。"""
        if not img:
            return ""
        if not clip:
            return f'<img src="报告卡素材/{img}" alt="" loading="lazy">'
        return (f'<video src="报告卡素材/{clip}" poster="报告卡素材/{img}" '
                f'data-t="{clip_t:.4f}" preload="none" muted loop playsinline></video>')

    # ── 时间线热区：悬浮浮出当时的画面 ────────────────────────────
    # 热区定位纯 CSS：SVG 的 viewBox→渲染宽度是线性映射（width:100% + height:auto），
    # 所以按百分比定位的 HTML 热区能和 SVG 里的图元精确对齐（实测 6 个标记偏差 0px）。
    def hotspot(ts, cls, label, img, clip=None, clip_t=0.0, width_s=None,
                top_u=0, bot_u=None):
        # clip_t 单独传、不由 ts 推：弯臂段的热区 ts 是**段的起点**，而片段切在段内
        # 最弯的那一刻（peak_s），两者不是一回事，拿 ts 去推 data-t 会算错。
        """top_u / bot_u 用的是 **SVG 坐标**，这里换算成百分比。
        ⚠️ 不能直接当 CSS px 用：SVG 按容器宽度缩放（实测 1200 → 1122，系数 0.935），
        两套单位对不上，窗口一变宽热区就和图元错位。百分比才跟着一起缩放。"""
        bot_u = E_BOT if bot_u is None else bot_u
        top_pct = top_u / VH * 100
        bot_pct = (VH - bot_u) / VH * 100
        xp = x_of(ts) / VW * 100
        # 贴边的浮窗会溢出容器，按位置换对齐方式。阈值 = 浮窗半宽占容器的比例
        # （172px 浮窗 / ~1120px 容器 ≈ 7.7%），再留一点余量。设太大会让本来放得下的
        # 浮窗白白偏离标记（实测：阈值 10% 会让 8.3% 处的标记白白偏移）。
        align = "l" if xp < 8 else ("r" if xp > 92 else "c")
        w = (f"width:{(x_of(ts + width_s) - x_of(ts)) / VW * 100:.3f}%;transform:none;left:"
             f"{x_of(ts) / VW * 100:.3f}%") if width_s else f"left:{xp:.3f}%"
        return f'''<div class="hot {cls}" style="{w};top:{top_pct:.2f}%;bottom:{bot_pct:.2f}%">
  <figure class="pop {align}">{shot(img, clip, clip_t)}
    <figcaption><b>{label[0]}</b><span>{label[1]}</span></figcaption>
  </figure></div>'''

    hotspots = ""
    for c in crux:
        kind = {"hesitation": "犹豫", "repeat": "反复试探",
                "power": c.get("driver", "姿态极端")}[c["kind"]]
        label = ("卡住型 · " if c["source"] == "v2a" else "姿态极端 · ") + kind
        # 难点热区：覆盖高度曲线 + 分段条，不伸到肘角那一行（留给弯臂热区）
        hotspots += hotspot(c["t"], "stuck" if c["source"] == "v2a" else "power",
                            (f'{c["t"]:.1f}s', label), c.get("img"), c.get("clip"),
                            c.get("clip_t", 0.0), top_u=0, bot_u=SEG_TOP + SEG_H)
    # 弯臂段：热区横跨整个区间，只压在肘角那一行，不跟上面的难点竖线抢
    for b in bents:
        hotspots += hotspot(b["start_s"], "bentzone",
                            (f'{b["dur_s"]:.1f}s', f'弯臂耗力 · 最弯 {b["min_elbow_deg"]:.0f}°'),
                            b.get("img"), b.get("clip"), b.get("clip_t", 0.0),
                            width_s=b["end_s"] - b["start_s"],
                            top_u=E_TOP - 6, bot_u=E_BOT)

    timeline_svg = f'''<svg viewBox="0 0 {VW} {VH}" class="tl">
  <defs><linearGradient id="hg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#e9ecf1" stop-opacity="0.16"/>
    <stop offset="1" stop-color="#e9ecf1" stop-opacity="0"/>
  </linearGradient></defs>
  <text x="{PADL-8}" y="{H_TOP-2}" fill="#6b7280" font-size="9" text-anchor="end">身长</text>
  {gridlines}
  <polygon points="{area}" fill="url(#hg)"/>
  <polyline points="{pts}" fill="none" stroke="#e9ecf1" stroke-width="2"
            stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  {''.join(bands)}
  {marks}
  <text x="{PADL-8}" y="{E_TOP-4}" fill="#6b7280" font-size="9" text-anchor="end">肘角</text>
  {bent}
  {straight_line}
  {elbow_paths}
  {ticks}
</svg>'''

    # ── 关键数字 ───────────────────────────────────────────────
    stuck = [c for c in crux if c["source"] == "v2a"]
    power = [c for c in crux if c["source"] == "v1"]

    # 两类难点分组呈现，不按时间混排——卡住型才是能改的东西，给它主视觉；
    # 发力型是体力开销的记录，压成紧凑一排即可。
    def card(c, cls):
        if c["source"] == "v2a":
            tag = "卡住型 · " + {"hesitation": "犹豫", "repeat": "反复试探"}[c["kind"]]
        else:
            # 不再叫「发力型 · 动作剧烈」——见上方 v1_terms 的拆解注释。
            # 也去掉了「占 X%」：那是公式内部的分量占比，对读者是黑话（老板看不懂）。
            tag = c["driver"]
        img = (shot(c.get("img"), c.get("clip"), c.get("clip_t", 0.0))
               or '<div class="ph">[抽帧失败]</div>')
        # 悬浮才播的东西必须自己说「我能播」，否则跟静态图长得一样，没人会去悬浮
        hint = '<span class="shot-hint"></span>' if c.get("clip") else ""
        return f'''<figure class="crux {cls}">{img}{hint}<figcaption>
  <div class="tm">{c["t"]:.1f}<span>s</span></div>
  <div class="tag">{tag}</div>
  <p>{c["detail"]}</p></figcaption></figure>'''

    stuck_cards = "".join(card(c, "stuck") for c in stuck)
    # 「姿态最极端的瞬间」卡片区块 2026-07-18 砍掉：v1 crux 已实锤退化成「关节弯得深」
    # 排序，弯得深≠费力，摆出来只会误导（老板 review + 决策文档）。时间线上的标记保留
    # （描述性、可悬浮回看画面），只是不再单开区块给它写卡片。

    # ── 省力：弯臂段明细 ────────────────────────────────────
    bent_rows = "".join(
        f'<tr><td class="mono">{b["start_s"]:.1f}–{b["end_s"]:.1f}s</td>'
        f'<td class="mono">{b["dur_s"]:.1f}s</td>'
        f'<td class="mono">{b["min_elbow_deg"]:.0f}°</td>'
        f'<td class="mono">{b["mean_elbow_deg"]:.0f}°</td></tr>'
        for b in bents) or '<tr><td colspan="4" class="empty">全程没有持续弯臂——省力习惯不错</td></tr>'

    # ── 节奏细节：切换耗时条形图（SVG）──────────────────────
    preps = v2["prep"]["items"]
    pmed = v2["prep"]["median_s"]
    plim = pmed * v2["params"]["PREP_CRUX_K"]
    BW, BH = 1200, 190
    BL, BR, BT, BB = 58, 10, 12, 40   # BL 留宽一点，装得下左侧的参考线标签
    pmax = max([p["prep_s"] for p in preps] + [plim]) * 1.12 if preps else 1
    bars = ""
    if preps:
        # 参考线先画，柱子和数值标签后画——反过来会让虚线横穿标签，读不清。
        # 标签放**左侧留白**（BL 那条 gutter）而不是右侧：右侧会和最后几根柱子的数值标签
        # 抢位置（IMG_6152 实测 23s 那根的「0.9」直接压在「中位数 0.60s」上）。
        for val, c_, lab in [(pmed, C_REST, "中位"), (plim, C_STUCK, "难点线")]:
            y = BH - BB - val / pmax * (BH - BT - BB)
            bars += (f'<line x1="{BL}" y1="{y:.1f}" x2="{BW-BR}" y2="{y:.1f}" stroke="{c_}" '
                     f'stroke-width="1" stroke-dasharray="4 4" opacity="0.75"/>'
                     f'<text x="{BL-6}" y="{y+3.5:.1f}" fill="{c_}" font-size="10" '
                     f'text-anchor="end">{lab}</text>')
        n = len(preps)
        slot = (BW - BL - BR) / n
        bw = min(slot * 0.62, 54)
        for i, p in enumerate(preps):
            cx = BL + slot * (i + 0.5)
            h = p["prep_s"] / pmax * (BH - BT - BB)
            over = p["prep_s"] > plim
            op = "" if over else ' opacity="0.75"'
            fill = C_STUCK if over else C_ADJUST
            lab_fill = "#e9ecf1" if over else "#6b7280"
            bars += (f'<rect x="{cx-bw/2:.1f}" y="{BH-BB-h:.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}" fill="{fill}"{op}/>'
                     # 描边光晕：矮柱的数值标签会正好落在中位线上，没有底衬就被虚线穿过
                     f'<text x="{cx:.1f}" y="{BH-BB-h-6:.1f}" fill="{lab_fill}" '
                     f'font-size="11" text-anchor="middle" font-family="Space Mono, monospace" '
                     f'paint-order="stroke" stroke="#14161b" stroke-width="3" '
                     f'stroke-linejoin="round">{p["prep_s"]:.1f}</text>'
                     f'<text x="{cx:.1f}" y="{BH-BB+15:.1f}" fill="#6b7280" font-size="10" '
                     f'text-anchor="middle" font-family="Space Mono, monospace">{p["move_start_s"]:.0f}s</text>'
                     f'<text x="{cx:.1f}" y="{BH-BB+28:.1f}" fill="#6b7280" font-size="10" '
                     f'text-anchor="middle">{p["dominant_limb"]}</text>')
    prep_svg = (f'<svg viewBox="0 0 {BW} {BH}" class="bar">'
                f'<line x1="{BL}" y1="{BH-BB}" x2="{BW-BR}" y2="{BH-BB}" stroke="#262a33"/>'
                f'{bars}</svg>')

    # ── 节奏细节：时间构成（SVG 堆叠条）────────────────────
    R = v2["ratios"]
    SW, SH = 1200, 54
    xacc, split = 0.0, ""
    # 条内的百分比字色随底色走：琥珀/绿够亮，压深色字才看得清；石板灰上必须用亮字
    for lab, key, c_, ink in [("出手爬升", "move_s", C_MOVE, "#0b0c0f"),
                              ("真休息", "rest_s", C_REST, "#0b0c0f"),
                              ("找点调整", "adjust_s", C_ADJUST, "#e9ecf1")]:
        secs = R[key]
        if secs <= 0:
            continue
        tot_s = R["move_s"] + R["rest_s"] + R["adjust_s"]
        w, pct = secs / tot_s * SW, secs / tot_s * 100
        split += (f'<rect x="{xacc:.1f}" y="0" width="{w-2:.1f}" height="26" fill="{c_}"/>'
                  f'<text x="{xacc+6:.1f}" y="45" fill="#a2a9b8" font-size="12">{lab}</text>'
                  f'<text x="{xacc+8:.1f}" y="19" fill="{ink}" font-size="12" '
                  f'font-weight="700" font-family="Space Mono, monospace">{pct:.0f}%</text>')
        xacc += w
    split_svg = f'<svg viewBox="0 0 {SW} {SH}" class="bar">{split}</svg>'

    # ── 解读 ───────────────────────────────────────────────
    det_rate = f"{v1['frames']}/{v1['frames']} (100%)" if len(d2) == v1["frames"] else \
        f"{len(d2)}/{v1['frames']} ({100*len(d2)/v1['frames']:.0f}%)"
    ELBOW_STRAIGHT_TXT = v2["params"]["ELBOW_STRAIGHT"]
    # 肘角有效帧占比：可见度 + 解剖学两道门槛都过的帧。这个数字要露出来——
    # 它决定了弯臂/休息这两项结论有多硬
    elbow_valid_pct = 100 * float(np.mean(~np.isnan(eo_g)))

    # ⚠️ 这段话曾经写成「全程没有一次真休息，你的停顿全是弯着胳膊找点，这是前臂先泵的
    # 直接原因」，被老板顶回来了，两处都该顶：
    #   ① 「全是弯着」是假的——逐段看，只有长停顿明确弯着（81-86°），短停顿手臂接近伸直
    #      （131-143°）。用一个"没够到 150°"的阈值判定，去概括所有停顿的姿态，是过度推断。
    #   ② 「前臂先泵」是**凭空捏造**的——老板从没说过他前臂泵，我从阈值判定跳到了一个
    #      没人报告过的生理症状，还反过来给它编因果。
    # 现在只报数据本身，把"弯"和"接近直"分开数，不下没有证据的结论。
    # 结论先行：先回答「我省不省力」，再给数，定义能省则省。
    # 老板 2026-07-17：「省力这里也说了一堆有的没的，看不懂的话」——上一版开头就甩
    # 「较直那条臂 ≥150° 且持续 >2 秒」，等于先背定义再讲结论。
    BENT_ISH = 120   # 静止段中位肘角低于此值 = 明确弯着扛；高于 = 接近伸直（只是没到 2 秒）
    stat_segs = [s for s in v2["adjusts"]["items"] if s.get("elbow_open_med") is not None]
    bent_segs = [s for s in stat_segs if s["elbow_open_med"] < BENT_ISH]
    straight_segs = [s for s in stat_segs if s["elbow_open_med"] >= BENT_ISH]
    if v2["rests"]["n"] == 0 and bent_segs and straight_segs:
        # 「最长」必须从**弯着的那几次**里取，不能从所有停顿里取——否则会拿一个
        # 手臂其实伸直的长停顿去佐证"弯着扛"
        longest = max(bent_segs, key=lambda s: s["dur_s"])
        sm = [s["elbow_open_med"] for s in straight_segs]
        rest_head = "长停顿在扛，短停顿不。"
        rest_line = (f"你一共停了 {len(stat_segs)} 次。{len(bent_segs)} 次手臂弯着扛"
                     f"（最长 {longest['dur_s']:.1f} 秒，肘角 {longest['elbow_open_med']:.0f}°）；"
                     f"{len(straight_segs)} 次手臂基本是直的（{min(sm):.0f}–{max(sm):.0f}°），"
                     f"但都不到 2 秒。<b>没有一次算真休息</b>：真休息要伸直挂着超过 2 秒。")
    elif v2["rests"]["n"] == 0 and bent_segs:
        rest_head = "停下来的时候手臂都弯着。"
        rest_line = (f"{len(bent_segs)} 次停顿手臂都在扛，没有一次伸直挂着超过 2 秒。")
    elif v2["rests"]["n"] == 0:
        rest_head = "没有一次算真休息。"
        rest_line = "停顿都不到 2 秒，手臂没来得及伸直挂着歇。"
    else:
        rest_head = f"全程休息了 {v2['rests']['n']} 次。"
        # 光给「平均质量 60/100」不行——分数得能指回依据（老板的规矩：每句话都要能
        # 指回一个具体数字）。休息次数少（先锋以外通常 1-2 次），直接逐次把扣分原因说出来。
        if v2["rests"]["n"] <= 2:
            parts = []
            for r in v2["rests"]["items"]:
                why = "；".join(x.rstrip("(+−)").rstrip("(") for x in r["reasons"]) or "无明显加减分"
                parts.append(f"{r['start_s']:.1f}–{r['end_s']:.1f} 秒那次 "
                             f"{r['quality']}/100：{why}")
            rest_line = "。".join(parts) + "。"
        else:
            rest_line = f"平均质量 {v2['rests']['mean_quality']}/100。"

    # 行文原则（老板 2026-07-17：「行文能不能简洁，用词简单」）：
    # 短句、常用词、一句话说一件事。不要「——」串下去，不要为了气势加修辞。
    takes = []
    if stuck:
        sp = (f"{min(c['t'] for c in stuck):.0f}–{max(c['t'] for c in stuck):.0f} 秒"
              if len(stuck) > 1 else f"{stuck[0]['t']:.0f} 秒")
        takes.append(f"<b>先看 {sp}。</b>你卡在这里。不是拉不动，是没想好下一步。")
    else:
        takes.append("<b>全程没卡壳。</b>没有特别长的停顿，也没在同一高度反复试探。")
    if v2["bent_arm"]["n"]:
        wb = max(bents, key=lambda b: b["dur_s"])
        takes.append(f"<b>{wb['start_s']:.0f}–{wb['end_s']:.0f} 秒，手臂弯着扛了 "
                     f"{wb['dur_s']:.1f} 秒</b>（平均 {wb['mean_elbow_deg']:.0f}°）。"
                     f"正好是你卡住的那段。想不出下一步时先把手臂伸直挂着，省力。")
    # 停顿不再打「果断/犹豫」标签（2026-07-18 决策：21 项研究的系统综述说高手静止
    # 占比反而更高——停顿被用来主动恢复和看路，把停顿量当坏事报是错的解读框架。
    # 「攀爬效率」同日砍掉：横移线上直接失真，意义无从解释。见 docs/2026-07-18 决策文档。
    fl = v2.get("fluency") or {}
    if fl.get("gie") is not None:
        takes.append(f"<b>轨迹熵 {fl['gie']:.2f}</b>。重心一共走了 {fl['path_len_bl']:.1f} 身长"
                     f"（这条线的外框只有 {fl['hull_perim_bl']:.1f}）。数字本身没有好坏——"
                     f"下次再爬同一条线，这个数降了，就是走得更顺了。")
    arm, leg = v1["left_arm_usage_pct"], v1["left_leg_usage_pct"]
    imb = max(abs(arm - 50), abs(leg - 50))
    if imb >= 10:   # 阈值 12 会漏掉 IMG_6152 的 61/39（偏差 11）——那已经是 1.6 倍差距了
        w_ = "手" if abs(arm - 50) >= abs(leg - 50) else "脚"
        p_ = arm if w_ == "手" else leg
        takes.append(f"<b>{w_}上偏{'左' if p_ > 50 else '右'}，{p_}%。</b>"
                     f"多找{'右' if p_ > 50 else '左'}{w_}点，两边能匀一些。")
    take_html = "".join(f'<div class="take">{x}</div>' for x in takes)
    route_badge = f' · {A.route}' if A.route else ""

    # 开场白只讲这条线上真实发生的事，不外推到「你这个人怎么样」
    vd = [f"<b>{C['climb_time_s']:.1f} 秒</b>完攀，净上升 <b>{C['net_gain_bl']:.2f} 身长</b>。"]
    if stuck:
        sp = (f"{min(c['t'] for c in stuck):.0f}–{max(c['t'] for c in stuck):.0f} 秒"
              if len(stuck) > 1 else f"{stuck[0]['t']:.0f} 秒")
        vd.append(f"最值得回看 <b>{sp}</b>，你卡在同一个高度上不去")
        ov = [b for b in bents if b["end_s"] > min(c["t"] for c in stuck)
              and b["start_s"] < max(c["t"] for c in stuck)] if bents else []
        if ov:
            # 「其中 X 秒」而不是「一直」——弯臂只占卡住窗口的一部分，别夸大
            vd.append(f"，其中 <b>{sum(b['dur_s'] for b in ov):.1f} 秒</b>手臂弯着扛。")
        else:
            vd.append("。")
    verdict = "".join(vd)
    # KPI 第 3 格：流畅度。fluency 缺失（老 json 没重跑）时显示 —，不挡整卡生成
    _g = (v2.get("fluency") or {}).get("gie")
    gie_str = f"{_g:.2f}" if _g is not None else '—'

    # ── 动作记录（识别窄版）：只陈列 conf≥medium，不解读——判断留给人。
    # cross/heel_hook 是 low（左右标签/脚跟点不可靠，抽验有误报），刻意不上卡。
    moves_html = ""
    if REC and (REC.get("moves") or REC.get("hand_sequence")):
        ok_moves = [m for m in REC["moves"] if m["confidence"] in ("high", "medium")
                    and t0 <= m["t_s"] <= t1]
        hs = REC.get("hand_sequence") or {}
        rows_ = "".join(
            f"<tr><td>{m['t_s']:.1f}s</td><td>{m['name_zh']}</td><td>{m['limb']}</td>"
            f"<td>{'书 p.' + str(m['book_ref']).split('p.')[-1] if m.get('book_ref') else ''}</td></tr>"
            for m in ok_moves)
        seq_line = (f"出手 {hs.get('n_hand_moves', 0)} 次，左右轮流占 "
                    f"{hs.get('alternating_pct')}%。" if hs.get("n_hand_moves") else "")
        if ok_moves or seq_line:
            body = (f"<table><tr><th>时刻</th><th>动作</th><th>肢体</th><th>出处</th></tr>"
                    f"{rows_}</table>" if ok_moves else
                    '<p class="sub">这条线上没识别出教材动作（只认位置信号可判的几种）。</p>')
            moves_html = f'''
  <h2>动作记录<span class="cnt">{len(ok_moves)} 个 · 只记不评</span></h2>
  <p class="sub">{seq_line}只列骨架位置信号能可靠判定的动作（高抬脚、两手同点、换手）。
  侧身、掛旗这类要看朝向的，骨架判不可靠，不硬猜。</p>
  {body}'''

    HTML = f'''<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>攀岩报告卡 · {A.base}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#0b0c0f; --surface:#14161b; --surface2:#1b1e25; --line:#262a33;
  --ink:#e9ecf1; --ink2:#a2a9b8; --ink3:#6b7280;
  --accent:{C_MOVE}; --rest:{C_REST}; --adjust:{C_ADJUST};
  --stuck:{C_STUCK}; --power:{C_POWER};
  --sans:"Space Grotesk","Microsoft YaHei","PingFang SC",sans-serif;
  --mono:"Space Mono",ui-monospace,monospace;
}}
*{{box-sizing:border-box}}
em,i,cite{{font-style:normal}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1200px;margin:0 auto;padding:56px 24px 96px}}
/* 字距只给拉丁文——中文加 letter-spacing 会被拉散成"标语体"，很丑 */
.eyebrow{{font-family:var(--mono);font-size:11px;color:var(--ink3)}}
.eyebrow .lat{{letter-spacing:.18em;text-transform:uppercase}}
h1{{font-size:clamp(32px,4vw,46px);font-weight:700;letter-spacing:-.02em;margin:6px 0 0;
  font-family:var(--mono)}}
.verdict{{font-size:19px;color:var(--ink2);max-width:60ch;margin:18px 0 0;text-wrap:pretty}}
.verdict b{{color:var(--ink);font-weight:700}}

h2{{font-size:14px;font-weight:700;color:var(--ink2);margin:64px 0 18px;
  padding-bottom:10px;border-bottom:1px solid var(--line);display:flex;
  justify-content:space-between;align-items:baseline;gap:16px}}
h2 .cnt{{font-family:var(--mono);font-size:11px;color:var(--ink3);font-weight:400}}

.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);
  border:1px solid var(--line);margin-top:40px}}
.kpi{{background:var(--surface);padding:22px}}
.kpi .n{{font-size:52px;font-weight:700;line-height:1;letter-spacing:-.03em;
  font-variant-numeric:tabular-nums}}
.kpi .n .u{{font-size:17px;font-weight:500;color:var(--ink3);margin-left:3px}}
.kpi .k{{font-size:13px;color:var(--ink2);margin-top:10px}}
.kpi .s{{font-family:var(--mono);font-size:11px;color:var(--ink3);margin-top:3px}}
.kpi.hi .n{{color:var(--accent)}}

.tlbox{{border:1px solid var(--line);background:var(--surface);padding:18px 14px 12px}}
.tlwrap{{position:relative}}
.tl{{width:100%;height:auto;display:block;overflow:visible}}

/* 悬浮热区：鼠标扫过标记，浮出当时的画面 */
.hot{{position:absolute;width:26px;transform:translateX(-50%);cursor:pointer}}
.hot::before{{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;
  transform:translateX(-50%);background:currentColor;opacity:0;transition:opacity .14s ease-out}}
.hot:hover::before{{opacity:.5}}
.hot.stuck{{color:var(--stuck)}}
.hot.power{{color:var(--power)}}
/* 弯臂段：热区是一整个区间，高亮整块而不是一条竖线 */
.hot.bentzone{{color:var(--power)}}
.hot.bentzone::before{{left:0;right:0;width:auto;transform:none;background:currentColor;
  opacity:0;border-radius:2px}}
.hot.bentzone:hover::before{{opacity:.22}}
.pop{{position:absolute;bottom:calc(100% + 6px);margin:0;width:172px;background:var(--surface2);
  border:1px solid var(--line);border-top:2px solid currentColor;
  box-shadow:0 16px 40px rgba(0,0,0,.75);opacity:0;pointer-events:none;z-index:20;
  transform:translateY(5px);transition:opacity .14s ease-out,transform .14s ease-out}}
.pop.c{{left:50%;margin-left:-86px}}
.pop.l{{left:-10px}}
.pop.r{{right:-10px}}
.hot:hover .pop{{opacity:1;transform:translateY(0)}}
.pop img,.pop video{{width:100%;display:block;aspect-ratio:4/5;object-fit:cover;
  background:var(--surface2)}}
.pop figcaption{{padding:8px 10px;display:flex;flex-direction:column;gap:2px}}
.pop b{{font-family:var(--mono);font-size:15px;color:var(--ink)}}
.pop span{{font-size:11px;color:currentColor;font-weight:700}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;padding:0 4px}}
.legend span{{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink2)}}
.legend i{{width:10px;height:10px;border-radius:2px;display:block}}

.crux{{margin:0;background:var(--surface);border:1px solid var(--line);overflow:hidden;
  transition:border-color .15s ease-out}}
.crux:hover{{border-color:#3a4150}}
.crux img,.crux video{{width:100%;display:block;object-fit:cover;background:var(--surface2)}}
/* 悬浮才播，所以得让人知道这里有得播：静止时角上一个小三角，播起来就淡出 */
.crux{{position:relative}}
.shot-hint{{position:absolute;top:10px;right:10px;width:22px;height:22px;border-radius:50%;
  background:rgba(12,14,18,.62);backdrop-filter:blur(2px);display:grid;place-items:center;
  pointer-events:none;transition:opacity .18s;z-index:2}}
.shot-hint::after{{content:"";border-left:7px solid rgba(255,255,255,.92);
  border-top:4.5px solid transparent;border-bottom:4.5px solid transparent;margin-left:2px}}
.crux:hover .shot-hint{{opacity:0}}
.crux .ph{{display:grid;place-items:center;color:var(--ink3);font-size:12px;aspect-ratio:4/5}}
.crux figcaption{{padding:14px 16px 16px}}
.crux .tm{{font-family:var(--mono);font-weight:700;line-height:1;
  font-variant-numeric:tabular-nums}}
.crux .tm span{{font-size:.5em;color:var(--ink3);margin-left:2px}}
.crux .tag{{font-size:11px;font-weight:700;margin-top:8px;display:inline-block;
  padding:3px 8px;border-radius:2px}}
.crux p{{font-size:12.5px;color:var(--ink2);margin:10px 0 0;line-height:1.6}}
.crux.stuck .tag{{color:var(--stuck);background:color-mix(in srgb,var(--stuck) 15%,transparent)}}
.crux.power .tag{{color:var(--power);background:color-mix(in srgb,var(--power) 15%,transparent)}}
.crux.stuck{{border-top:2px solid var(--stuck)}}
.crux.power{{border-top:2px solid var(--power)}}
/* 卡住型=主角，两栏大图；发力型=体力开销记录，紧凑一排 */
.cruxes.big{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}}
.cruxes.big .crux img{{aspect-ratio:4/5}}
.cruxes.big .tm{{font-size:30px}}
.cruxes.small{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}}
.cruxes.small .crux img{{aspect-ratio:1/1}}
.cruxes.small .tm{{font-size:19px}}
.cruxes.small figcaption{{padding:11px 12px 13px}}
.cruxes.small p{{font-size:11.5px}}
.sub{{font-size:13px;color:var(--ink2);margin:0 0 12px;max-width:76ch;line-height:1.75}}
.sub b{{color:var(--ink)}}
/* 结论先行：一句话的答案，比下面的解释大一号 */
.lead{{font-size:17px;font-weight:700;color:var(--ink);margin:0 0 8px}}
@media(max-width:860px){{.cruxes.big,.cruxes.small{{grid-template-columns:repeat(2,1fr)}}}}

.note{{font-size:12.5px;color:var(--ink3);margin-top:14px;line-height:1.7;max-width:80ch}}
.note b{{color:var(--ink2)}}
.note.foot{{margin-top:64px;padding-top:20px;border-top:1px solid var(--line);max-width:none}}
.bar{{width:100%;height:auto;display:block}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}}
th{{color:var(--ink3);font-weight:400;font-size:12px}}
td.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
td.empty{{color:var(--ink3)}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:32px;margin-top:32px}}
.lbl{{font-size:12px;color:var(--ink3);margin-bottom:8px}}
.split{{height:8px;background:var(--surface2);border:1px solid var(--line);overflow:hidden}}
.split i{{display:block;height:100%;background:var(--accent)}}
.ends{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;
  color:var(--ink2);margin-top:6px}}
.take{{font-size:14.5px;color:var(--ink2);margin:14px 0;padding-left:20px;position:relative;
  line-height:1.75;max-width:74ch;text-wrap:pretty}}
.take:before{{content:"";position:absolute;left:0;top:.62em;width:8px;height:1px;
  background:var(--accent)}}
.take b{{color:var(--ink)}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(2,1fr)}}
  .two{{grid-template-columns:1fr;gap:20px}}}}
</style>

<div class="wrap">
  <div class="eyebrow"><span class="lat">Climb Report</span>{route_badge}</div>
  <h1>{A.base}</h1>
  <p class="verdict">{verdict}</p>

  <div class="kpis">
    <div class="kpi hi"><div class="n">{C['climb_time_s']:.1f}<span class="u">s</span></div>
      <div class="k">完攀用时</div><div class="s">{C['start_s']:.1f} → {C['end_s']:.1f}s</div></div>
    <div class="kpi"><div class="n">{C['net_gain_bl']:.2f}<span class="u">身长</span></div>
      <div class="k">净上升</div><div class="s">起攀点 → 最高点</div></div>
    <div class="kpi"><div class="n">{gie_str}</div>
      <div class="k">流畅度（轨迹熵）</div><div class="s">越低越顺 · 只跟这条线的自己比</div></div>
    <div class="kpi"><div class="n">{len(stuck)}<span class="u">处</span></div>
      <div class="k">卡住的地方</div><div class="s">往下看，最值得回看的时段</div></div>
  </div>

  <h2>整条线的节奏<span class="cnt">起攀 {C['start_s']:.1f}s → 完攀 {C['end_s']:.1f}s</span></h2>
  <div class="tlbox">
    <div class="tlwrap">{timeline_svg}{hotspots}</div>
    <div class="legend">
      <span><i style="background:{C_MOVE}"></i>出手移动</span>
      <span><i style="background:{C_REST}"></i>真休息</span>
      <span><i style="background:{C_ADJUST}"></i>找点调整</span>
      <span><i style="background:{C_STUCK}"></i>卡住型难点</span>
      <span><i style="background:{C_POWER}"></i>发力型吃力点 / 弯臂段</span>
    </div>
  </div>
  <p class="note">白线是重心高度。下面窄条是较直那条手臂的肘角，粉底那段是弯着扛。
  <b style="color:var(--ink2)">鼠标扫过顶部的三角，能看到那一刻的画面。</b></p>

  <h2>卡住的地方<span class="cnt">{len(stuck)} 处 · 最值得回看</span></h2>
  <p class="sub">停顿特别长，或者在同一高度反复出手却上不去。<b>这里是你没想明白怎么走的地方。</b></p>
  <div class="cruxes big">{stuck_cards}</div>

  <h2>省力<span class="cnt">弯臂 {v2['bent_arm']['n']} 段 · 真休息 {v2['rests']['n']} 次</span></h2>
  <p class="lead">{rest_head}</p>
  <p class="sub">{rest_line}</p>
  <table>
    <tr><th>弯臂时段</th><th>时长</th><th>最弯</th><th>平均</th></tr>{bent_rows}
  </table>
  <p class="note">只要有一条手臂伸直，体重就挂在骨头上，不费力。所以只看比较直的那条。
  <br>肘角靠单目猜 3D，不太准：<b>只有 {elbow_valid_pct:.0f}% 的帧够可信</b>，其余不参与判定。
  朝镜头方向弯的手臂，画面上看着也是直的，分不出来。</p>

  <div class="two">
    <div>
      <div class="lbl">左右手用力分布</div>
      <div class="split"><i style="width:{v1['left_arm_usage_pct']}%"></i></div>
      <div class="ends"><span>左手 {v1['left_arm_usage_pct']}%</span>
        <span>右手 {100-v1['left_arm_usage_pct']}%</span></div>
    </div>
    <div>
      <div class="lbl">左右腿用力分布</div>
      <div class="split"><i style="width:{v1['left_leg_usage_pct']}%"></i></div>
      <div class="ends"><span>左腿 {v1['left_leg_usage_pct']}%</span>
        <span>右腿 {100-v1['left_leg_usage_pct']}%</span></div>
    </div>
  </div>

  {moves_html}

  <h2>每次出手前，你停了多久<span class="cnt">中位数 {pmed:.2f}s · 最长 {v2['prep']['max_s']:.2f}s</span></h2>
  <div class="tlbox">{prep_svg}</div>
  <p class="note">每根柱是一次出手前的停顿，柱下是出手时刻和主导肢体。
  绿线是中位数 {pmed:.2f}s，青线是<b>难点线</b>（中位数的 {v2['params']['PREP_CRUX_K']} 倍
  = {plim:.2f}s）。超过青线的算「卡住型 · 犹豫」。
  <b>停顿本身不是坏事</b>——高手停下来的时间反而更多，用来甩手恢复和看下一步。
  值得注意的只有超出青线那种量级的停。</p>

  <h2>时间去哪了<span class="cnt">起攀 → 完攀 共 {C['climb_time_s']:.1f}s</span></h2>
  <div class="tlbox">{split_svg}</div>
  <p class="note">「真休息」需同时满足：直臂 + 重心低速 + 持续 &gt;2 秒。其余停顿都算「找点调整」。
  这三个占比没有「应该是多少」的标准——只做记录，不打分。</p>

  <h2>解读</h2>
  {take_html}

  <div class="note foot"><b>数据口径。</b>单摄像头、相机不动，用 MediaPipe 估骨架，
  这条线检出 {det_rate}。
  长度和速度都用<b>身长</b>（你肩中点到髋中点的距离）当单位，所以换手机、换机位、换人都能比。
  代价是它看的是相对趋势，不是实验室级的绝对测量。单目对深度不敏感，主要看画面内的运动。
  起攀时刻先用「手举过肩」定位上墙，再算重心——因为走向岩壁时人在往远处走，
  画面里重心会被透视抬高，看着像在爬。
  阈值都在 climb_report_v2.py 顶部，本次取值见 metrics_v2.json 的 params。
  画面是切面前 1 秒到后 2 秒的 3 秒片段，鼠标移上去就播。</div>
</div>

{HOVER_JS}'''

    out_html = os.path.join(A.out, "攀岩报告卡.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"✅ {A.base} 报告卡 → {out_html}")
    print(f"   完攀 {C['climb_time_s']:.1f}s（{C['start_s']:.1f}→{C['end_s']:.1f}）"
          f" · 净上升 {C['net_gain_bl']:.2f}bl · 检出 {det_rate}")
    print(f"   卡住型 {len(stuck)} 处 · 姿态极端 {len(power)} 处 · 弯臂 {len(bents)} 段"
          f" · 真休息 {v2['rests']['n']} 次")
    clips = cclips + bclips
    mb = sum(os.path.getsize(os.path.join(ASSET, x)) for x in clips if x) / 1048576
    print(f"   抽帧 {sum(1 for x in cfiles + bfiles if x)}/{len(cfiles) + len(bfiles)} 张"
          f" · 片段 {sum(1 for x in clips if x)}/{len(clips)} 个（{mb:.2f}MB）→ {ASSET}")


if __name__ == "__main__":
    main()

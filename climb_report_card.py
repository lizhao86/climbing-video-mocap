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
C_MOVE   = "#e08a42"   # 身体在动（重心位移段，不是出手；出手见 events）
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


def load_torso_m():
    """读项目根 账本配置.json → 躯干长（米）。

    ⚠️ 换算爬升要乘**躯干长**（肩中-髋中距），不是身高——body_scale 的定义就是
    肩中到髋中的距离。2026-07-20 之前误乘身高，把爬升放大了 3.5 倍。
    口径与 climb_journal.torso_len_m 保持一致（同一个 0.29 系数）。
    """
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "账本配置.json")
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
        t = cfg.get("躯干长_m")
        if t:
            return float(t)
        h = cfg.get("身高_m")
        return float(h) * 0.29 if h else None
    except (ValueError, OSError, TypeError):
        return None


def load_sidecar(out_dir):
    """读 <素材文件夹>/线路.json → dict。没有或坏了都返回 {}。"""
    path = os.path.join(out_dir, "线路.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def is_rope_route(sc):
    """这条线是不是绳索线（顶绳/先锋）。

    抱石一气呵成、不存在挂着歇，休息点指标恒为 0，报出来没有意义
    （老板 2026-07-20：「整个移动是不存在休息的，说这个有什么意思」）。
    绳索线（high wall）才会出现单臂打直甩手的真休息。
    类型没填时保守当抱石——宁可不显示，也不显示一个恒零的指标。
    """
    return (sc.get("类型") or "").strip() in ("顶绳", "先锋")


def sidecar_header(out_dir, base):
    """页眉：返回账本 + 视频文件名（文件名要留着，但它不是这条线的身份）。"""
    return ('<div class="cardhead">'
            '<a class="back" href="../../攀岩账本.html">← 返回账本</a>'
            f'<span class="fname mono">{base}</span></div>')


def group_head(num, title, sub):
    """主题组的分隔标题：大号编号 + 组名 + 一句话说这组回答什么问题。
    「总-分」结构里，概览之后每个组统领 2 个 h2 区块（老板 2026-07-20）。"""
    return (f'<div class="grp"><span class="grp-n mono">{num}</span>'
            f'<div class="grp-tx"><div class="grp-t">{title}</div>'
            f'<div class="grp-s">{sub}</div></div></div>')


def sec_h2(title, cnt="", tip="", minor=False):
    """区块标题。解释性文字收进标题右边的 i 图标，hover 才展开。

    定义、口径、怎么读图这些话每个区块都要一遍，摊在正文里比数据还占地方
    （老板 2026-07-20：「全是重复内容…不要浪费篇幅」）。正文只留数据和结论。
    """
    cls = ' class="minor"' if minor else ""
    cnt_html = f'<span class="cnt">{cnt}</span>' if cnt else ""
    tip_html = (f'<button class="info" type="button" aria-label="口径说明">'
                f'<span class="tip">{tip}</span></button>') if tip else ""
    return f'<h2{cls}><span class="h2t">{title}{tip_html}</span>{cnt_html}</h2>'


def hero_block(sc, base, tip=""):
    """标题区。

    标题用「这条线是什么」——野外用线路名，室内用岩馆名；难度做徽章。
    片名（IMG_6152）是文件名不是身份，退到页眉角落
    （老板 2026-07-20：「都告诉你时间地点难度了，不如写那些东西」）。
    sidecar 还没填时退回片名当标题，不至于无标题。
    """
    name = (sc.get("线路名") or "").strip()
    place = (sc.get("地点") or "").strip()
    title = name or place or base
    sub = place if (name and place) else ""

    meta = []
    d = (sc.get("日期") or "").strip()
    if d:
        meta.append(d)
    t = (sc.get("类型") or "").strip()
    if t:
        meta.append(t)
    if sc.get("完攀") is True:
        meta.append("完攀")
    elif sc.get("完攀") is False:
        meta.append("未完攀")
    if not meta:
        meta.append("这条线还没登记，跟 Claude 说一句就记上")

    grade = (sc.get("难度") or "").strip()
    badge = f'<div class="gbadge mono">{grade}</div>' if grade else ""
    subline = f'<div class="hsub">{sub}</div>' if sub else ""

    info = (f'<button class="info" type="button" aria-label="数据口径">'
            f'<span class="tip">{tip}</span></button>') if tip else ""
    return (f'<div class="eyebrow mono">{" · ".join(meta)}</div>'
            f'<div class="titlerow"><div class="titlebox">'
            f'<div class="h1row"><h1>{title}</h1>{info}</div>{subline}</div>'
            f'{badge}</div>')


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
                return dom, f"{LIMB_ZH[which]}挥到 {v_:.1f} 躯干/秒，全片最快的 {p}%"
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
                "power": c.get("driver", "发力点")}[c["kind"]]
        label = ("卡点 · " if c["source"] == "v2a" else "发力点 · ") + kind
        # 难点热区：覆盖高度曲线 + 分段条，不伸到肘角那一行（留给弯臂热区）
        hotspots += hotspot(c["t"], "stuck" if c["source"] == "v2a" else "power",
                            (f'{c["t"]:.1f}s', label), c.get("img"), c.get("clip"),
                            c.get("clip_t", 0.0), top_u=0, bot_u=SEG_TOP + SEG_H)
    # 弯臂段：热区横跨整个区间，只压在肘角那一行，不跟上面的难点竖线抢
    for b in bents:
        hotspots += hotspot(b["start_s"], "bentzone",
                            (f'{b["dur_s"]:.1f}s', f'锁臂耗力 · 最弯 {b["min_elbow_deg"]:.0f}°'),
                            b.get("img"), b.get("clip"), b.get("clip_t", 0.0),
                            width_s=b["end_s"] - b["start_s"],
                            top_u=E_TOP - 6, bot_u=E_BOT)

    timeline_svg = f'''<svg viewBox="0 0 {VW} {VH}" class="tl">
  <defs><linearGradient id="hg" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#e9ecf1" stop-opacity="0.16"/>
    <stop offset="1" stop-color="#e9ecf1" stop-opacity="0"/>
  </linearGradient></defs>
  <text x="{PADL-8}" y="{H_TOP-2}" fill="#6b7280" font-size="9" text-anchor="end">躯干</text>
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
            tag = "卡点 · " + {"hesitation": "起手前久停", "repeat": "原地磨"}[c["kind"]]
        else:
            # 不再叫「发力型 · 动作剧烈」——见上方 v1_terms 的拆解注释。
            # 也去掉了「占 X%」：那是公式内部的分量占比，对读者是黑话（老板看不懂）。
            tag = c["driver"]
        img = (shot(c.get("img"), c.get("clip"), c.get("clip_t", 0.0))
               or '<div class="ph">[抽帧失败]</div>')
        # 视觉判定（C 路线）：看过关键帧后的解读，替换几何 detail——眼睛比骨架准，
        # 且能纠正几何误报（IMG_6411@24.8 的「反复试探」实为连贯掛腳序列）
        vn = None
        if REC:
            for n in (REC.get("crux_notes") or []):
                if abs(n["t_s"] - c["t"]) < 0.5 and n.get("confidence") != "low":
                    vn = n["note"]
                    break
        detail_html = (f'<p>{vn} <span class="vtag">看过画面</span></p>' if vn
                       else f'<p>{c["detail"]}</p>')
        # 悬浮才播的东西必须自己说「我能播」，否则跟静态图长得一样，没人会去悬浮
        hint = '<span class="shot-hint"></span>' if c.get("clip") else ""
        # 结论当主体、时刻退成角标（老板 2026-07-20：「重点放在视频帧位置，
        # 这不是重点，重点应该结论才对」）。时刻仍要留——回看视频得知道跳到哪。
        return f'''<figure class="crux {cls}">{img}{hint}<figcaption>
  <div class="crux-top"><span class="ctag">{tag}</span>
    <span class="tm mono">{c["t"]:.1f}s</span></div>
  {detail_html}</figcaption></figure>'''

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
        for b in bents) or '<tr><td colspan="4" class="empty">全程没有持续锁臂，前臂省下来了</td></tr>'

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
    for lab, key, c_, ink in [("身体在动", "move_s", C_MOVE, "#0b0c0f"),
                              ("回血", "rest_s", C_REST, "#0b0c0f"),
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
    # 抱石一气呵成，挂着歇根本不会发生，rests 恒为 0——报「没有一次真休息」是拿
    # 恒零指标说事（老板 2026-07-20：「说这个有什么意思」）。抱石只讲「有没有憋着」，
    # 绳索线（high wall）两样都讲：单臂打直甩手的真休息 + 憋着的时间。
    SC = load_sidecar(A.out)
    IS_ROPE = is_rope_route(SC)
    # 标题得让没上下文的人也看懂。「憋着的时间」是老板自己的说法，搬来当标题就变味了
    # （老板 2026-07-20：「什么叫憋着的时间？是指两次移动间隙吗？你这个中文不行」）。
    # 这个指标测的是：较直那条手臂的肘角连续 2 秒以上低于 150°——不限于停顿，
    # 移动中一直弯着也算。
    n_bent = v2["bent_arm"]["n"]
    if IS_ROPE:
        arm_h2 = "锁臂与回血"
        arm_cnt = (f"锁臂 {n_bent} 段 · 回血 {v2['rests']['n']} 次"
                   if n_bent else f"回血 {v2['rests']['n']} 次")
    else:
        arm_h2 = "锁臂时间"
        arm_cnt = f"锁臂 {n_bent} 段" if n_bent else "全程没有持续锁臂"
    split_note = ("算一次<b>回血</b>要同时满足：直臂 + 重心低速 + 持续 &gt;2 秒。"
                  "其余停顿都算找点。"
                  if IS_ROPE else
                  "抱石线上<b>回血恒为 0</b>——一条线几十秒，不会有直臂甩手的机会，"
                  "这不是没做到。停顿都归在找点里。")

    # rest_head 只放**测到的事实**，不放概括。
    # 2026-07-20 删掉了「长停顿在憋，短停顿不」——那是个对仗病句（省了主谓，没人看得懂），
    # 而且代码从没比较过两组的时长，「长的在憋」是脑补的因果。同一个错误 2026-07-17
    # 犯过一次（把「没检测到直臂休息」外推成「停顿全在弯着扛」），CLAUDE.md 为此立了
    # 「聚合判定 ≠ 逐个都成立」这条规矩。要说相关性就得先算，不算就只陈列。
    rest_bullets = []
    if not IS_ROPE:
        # 抱石：只回答「停下来的时候有没有锁着」
        if bent_segs and straight_segs:
            longest = max(bent_segs, key=lambda s: s["dur_s"])
            sm = [s["elbow_open_med"] for s in straight_segs]
            rest_head = f"你一共停了 {len(stat_segs)} 次。"
            rest_bullets = [
                f"<b>{len(bent_segs)} 次锁着臂</b>——最长 {longest['dur_s']:.1f} 秒，"
                f"肘角 {longest['elbow_open_med']:.0f}°",
                f"<b>{len(straight_segs)} 次直臂</b>——"
                f"{min(sm):.0f}–{max(sm):.0f}°，那几次不吃前臂",
            ]
        elif bent_segs:
            longest = max(bent_segs, key=lambda s: s["dur_s"])
            rest_head = f"你停的 {len(bent_segs)} 次全在锁臂。"
            rest_bullets = [
                f"最长一次 <b>{longest['dur_s']:.1f} 秒</b>，肘角 {longest['elbow_open_med']:.0f}°",
                "想 beta 的时候先把手臂放直，重量落到骨头上，前臂能省下来",
            ]
        elif straight_segs:
            sm = [s["elbow_open_med"] for s in straight_segs]
            rest_head = f"你停的 {len(straight_segs)} 次都是直臂。"
            rest_bullets = [f"肘角都在 {min(sm):.0f}–{max(sm):.0f}°，全程没有持续锁臂"]
        else:
            rest_head = "没测到值得说的停顿。"
            rest_bullets = ["要么没停，要么停的那几次肘角不够可信，没参与判定"]
    elif v2["rests"]["n"] == 0 and bent_segs and straight_segs:
        # 「最长」必须从**锁着的那几次**里取，不能从所有停顿里取——否则会拿一个
        # 手臂其实是直的长停顿去佐证"在锁臂"
        longest = max(bent_segs, key=lambda s: s["dur_s"])
        sm = [s["elbow_open_med"] for s in straight_segs]
        rest_head = f"你一共停了 {len(stat_segs)} 次，一次回血都没有。"
        rest_bullets = [
            f"<b>{len(bent_segs)} 次锁着臂</b>——最长 {longest['dur_s']:.1f} 秒，"
            f"肘角 {longest['elbow_open_med']:.0f}°",
            f"<b>{len(straight_segs)} 次直臂</b>——{min(sm):.0f}–{max(sm):.0f}°，"
            f"但都不到 2 秒",
            "算一次回血要直臂挂满 2 秒",
        ]
    elif v2["rests"]["n"] == 0 and bent_segs:
        rest_head = f"你停的 {len(bent_segs)} 次全在锁臂。"
        rest_bullets = ["没有一次直臂挂满 2 秒，所以一次回血都没有"]
    elif v2["rests"]["n"] == 0:
        rest_head = "一次回血都没有。"
        rest_bullets = ["停顿都不到 2 秒，来不及放直手臂甩一甩"]
    else:
        rest_head = f"全程休息了 {v2['rests']['n']} 次。"
        # 光给「平均质量 60/100」不行——分数得能指回依据（老板的规矩：每句话都要能
        # 指回一个具体数字）。休息次数少（先锋以外通常 1-2 次），直接逐次把扣分原因说出来。
        if v2["rests"]["n"] <= 4:
            for r in v2["rests"]["items"]:
                why = "；".join(x.rstrip("(+−)").rstrip("(") for x in r["reasons"]) or "无明显加减分"
                rest_bullets.append(f"<b>{r['start_s']:.1f}–{r['end_s']:.1f} 秒</b>那次 "
                                    f"{r['quality']}/100——{why}")
        else:
            rest_bullets = [f"平均质量 {v2['rests']['mean_quality']}/100"]
    rest_facts = ("<ul class=\"facts\">"
                  + "".join(f"<li>{x}</li>" for x in rest_bullets)
                  + "</ul>") if rest_bullets else ""

    # 行文原则（老板 2026-07-17：「行文能不能简洁，用词简单」）：
    # 短句、常用词、一句话说一件事。不要「——」串下去，不要为了气势加修辞。
    # 页尾原有「下次记住这几件事」总结段，2026-07-20 整段删除——卡点、锁臂、流畅度、
    # 左右分布这四条结论各自的区块里都已经讲过一遍（老板：「这整段没看出来有啥意思，
    # 结论在其他 section 都说了，何必重新说一遍」）。信息层级重排后每个区块都有自己的
    # 结论行，总结段就成了纯冗余。
    # 唯一别处没有的是**左右偏向的建议**（其它区块只给了百分比），并进左右均衡区块。
    arm, leg = v1["left_arm_usage_pct"], v1["left_leg_usage_pct"]
    imb = max(abs(arm - 50), abs(leg - 50))
    balance_tip = ""
    if imb >= 10:   # 阈值 12 会漏掉 IMG_6152 的 61/39（偏差 11）——那已经是 1.6 倍差距了
        w_ = "手" if abs(arm - 50) >= abs(leg - 50) else "脚"
        p_ = arm if w_ == "手" else leg
        balance_tip = (f'<p class="lead">{w_}上偏{"左" if p_ > 50 else "右"}，{p_}%。'
                       f'多找{"右" if p_ > 50 else "左"}{w_}点，两边能匀一些。</p>')
    card_head = sidecar_header(A.out, A.base)

    # 全页口径挂在主标题旁边，不再在页尾摊一大段
    hero_html = hero_block(SC, A.base, (
        f"单摄像头、相机不动，用 MediaPipe 估骨架，这条线检出 {det_rate}。"
        f"长度和速度都用<b>躯干长</b>（肩中点到髋中点的距离）当单位，"
        f"所以换手机、换机位、换人都能比；代价是它看相对趋势，不是绝对测量。"
        f"单目对深度不敏感，主要看画面内的运动。"
        f"起攀时刻先用「手举过肩」定位上墙再算重心——走向岩壁时人在往远处走，"
        f"画面里重心会被透视抬高，看着像在爬。"
        f"阈值在 climb_report_v2.py 顶部，本次取值见 metrics_v2.json 的 params。"))

    h2_stuck = sec_h2(
        "卡点", f"{len(stuck)} 处",
        "两种情况会被标出来：起手前停顿超过中位数的 "
        f"{v2['params']['PREP_CRUX_K']} 倍，或者在同一高度反复动却没上升。"
        "<b>画面鼠标移上去会播</b>，是该时刻前 1 秒到后 2 秒的片段。")
    h2_rhythm = sec_h2(
        "整条线的节奏", f"起攀 {C['start_s']:.1f}s → 完攀 {C['end_s']:.1f}s",
        "白线是重心高度。下面窄条是较直那条手臂的肘角，粉底那段是弯着扛。"
        "<b>鼠标扫过顶部的三角能看到那一刻的画面。</b>")
    h2_arm = sec_h2(
        arm_h2, arm_cnt,
        "<b>直臂</b>时体重挂在骨头上，前臂几乎不出力；<b>锁臂</b>就得靠肌肉一直拉住，"
        "很吃前臂。两条臂只要有一条是直的就不算锁，所以只看比较直的那条。"
        "连续锁满 2 秒才记一段——<b>移动途中一直锁着也算</b>，不限于停下来的时候。"
        f"肘角靠单目猜 3D，不太准：只有 {elbow_valid_pct:.0f}% 的帧够可信，其余不参与判定。"
        "朝镜头方向弯的手臂，画面上看着也是直的，分不出来。")
    h2_balance = sec_h2(
        "左右均衡",
        f"手 {v1['left_arm_usage_pct']}/{100 - v1['left_arm_usage_pct']} · "
        f"脚 {v1['left_leg_usage_pct']}/{100 - v1['left_leg_usage_pct']}",
        "按左右肢的活动量分摊，不是真的测力。偏向一边不一定是毛病——"
        "线路本身可能就偏。同一条线多爬几次再比才有意义。")
    h2_prep = sec_h2(
        "出手前的停顿", f"中位数 {pmed:.2f}s · 最长 {v2['prep']['max_s']:.2f}s",
        "每根柱是一次出手前的停顿，柱下是出手时刻和主导肢体。"
        f"绿线是中位数 {pmed:.2f}s，青线是难点线（中位数的 "
        f"{v2['params']['PREP_CRUX_K']} 倍 = {plim:.2f}s），超过青线的算「卡点 · 起手前久停」。"
        "<b>停顿本身不是坏事</b>——高手停下来的时间反而更多，用来甩手恢复和看下一步。"
        "值得注意的只有超出青线那个量级的停。")
    h2_split = sec_h2(
        "时间构成", f"起攀 → 完攀 共 {C['climb_time_s']:.1f}s",
        split_note + "这几个占比没有「应该是多少」的标准，只做记录，不打分。")
    h2_fluency = sec_h2(
        "流畅度", "只跟自己比",
        "攀岩研究里流畅度是**四个指标**，不是一个数："
        "完攀用时、静止占比、几何熵（Cordier 1993）、归一化 jerk（Seifert 2014）。"
        "<b>路径绕度</b>是重心走过的路除以「套住这些路的橡皮筋周长」——完美直上等于 0，"
        "来回试探就升高。<b>轨迹抖动</b>看的是加速度的变化率，动作断续会升高。"
        "⚠️ <b>别拿这四个数比水平。</b>Orth 2017 的 21 项系统综述发现，"
        "高水平攀岩者的静止占比<b>反而更高</b>——停下来是在甩手回血和读线，"
        "不看意图就把停顿当毛病，是典型误读。难线本来也该停得多、走得绕。"
        "<b>唯一能比的是同一条线复爬的趋势</b>：四项一起降，说明这条线练顺了。")

    # 净上升换算成米：乘**躯干长**（肩中-髋中距），不是身高——曾误乘身高放大 3.5 倍。
    # ⚠️ 这个数已知偏保守：相机仰拍会压缩高处，IMG_6321 老板确认墙高 10m，骨架只推出
    # 4.7m。逐帧局部尺度积分与全局中位数数学上等价（实测差 1%），修不了。
    # 老板 2026-07-20 决定先留着，等 high wall 素材再评估，见 PLAN.md 待办。
    TORSO_M = load_torso_m()
    if TORSO_M:
        gain_val = f"{C['net_gain_bl'] * TORSO_M:.1f}"
        gain_unit = "米"
        gain_sub = "起攀点 → 最高点 · 偏保守"
    else:
        gain_val = f"{C['net_gain_bl']:.2f}"
        gain_unit = "躯干"
        gain_sub = "起攀点 → 最高点"

    # 开场白只讲这条线上真实发生的事，不外推到「你这个人怎么样」
    vd = [f"<b>{C['climb_time_s']:.1f} 秒</b>完攀，净上升 <b>{gain_val} {gain_unit}</b>。"]
    if stuck:
        sp = (f"{min(c['t'] for c in stuck):.0f}–{max(c['t'] for c in stuck):.0f} 秒"
              if len(stuck) > 1 else f"{stuck[0]['t']:.0f} 秒")
        vd.append(f"最值得回看 <b>{sp}</b>，你卡在同一个高度上不去")
        ov = [b for b in bents if b["end_s"] > min(c["t"] for c in stuck)
              and b["start_s"] < max(c["t"] for c in stuck)] if bents else []
        if ov:
            # 「其中 X 秒」而不是「一直」——弯臂只占卡住窗口的一部分，别夸大
            vd.append(f"，其中 <b>{sum(b['dur_s'] for b in ov):.1f} 秒</b>在锁臂。")
        else:
            vd.append("。")
    verdict = "".join(vd)
    # ── 流畅度：学界四指标（Seifert 2014 / Cordier 1993 一脉）────────────────
    # 完攀用时 + 静止占比(IR) + 几何熵(GIE) + 归一化 jerk，**四个都是越低越好**。
    # 2026-07-20 之前只把 GIE 一项叫「流畅度」摆进 KPI——四分之一冒充全部，
    # 而且挑的偏偏是最不直观、跨路线还不可比的那个（老板：「你确定 GIE Jerk
    # 又不用啦？」）。现在 KPI 放最直观的静止占比，四项另开区块并列。
    _fl = v2.get("fluency") or {}
    _rt = v2.get("ratios") or {}
    _g = _fl.get("gie")
    gie_str = f"{_g:.2f}" if _g is not None else "—"
    _j = _fl.get("log_norm_jerk")
    jerk_str = f"{_j:.1f}" if _j is not None else "—"
    _mv = _rt.get("move_pct")
    still_pct = round(100 - _mv, 1) if _mv is not None else None
    still_str = f"{still_pct:.0f}" if still_pct is not None else "—"

    fluency_tiles = "".join(
        f'<div class="mv-tile"><div class="mv-n mono">{v}</div>'
        f'<div class="mv-name">{lab}</div><div class="mv-side">{sub}</div></div>'
        for v, lab, sub in [
            (f"{C['climb_time_s']:.1f}<span class=\"fu\">秒</span>", "完攀用时", "起攀到最高点"),
            (f"{still_str}<span class=\"fu\">%</span>", "静止占比", "停着不动的时间"),
            (gie_str, "路径绕度", "重心走的路比外框长几倍"),
            (jerk_str, "轨迹抖动", "动作顺不顺"),
        ])

    # ── 动作记录（识别窄版）：只陈列 conf≥medium，不解读——判断留给人。
    # cross/heel_hook 是 low（左右标签/脚跟点不可靠，抽验有误报），刻意不上卡。
    moves_html = ""
    if REC and (REC.get("moves") or REC.get("hand_sequence")):
        ok_moves = [m for m in REC["moves"] if m["confidence"] in ("high", "medium")
                    and t0 <= m["t_s"] <= t1]
        hs = REC.get("hand_sequence") or {}
        seq_line = (f"出手 {hs.get('n_hand_moves', 0)} 次，左右轮流占 "
                    f"{hs.get('alternating_pct')}%。" if hs.get("n_hand_moves") else "")
        if ok_moves or seq_line:
            # 先给统计（每种几次、偏哪边），再给时序。原来只有一张时刻表，
            # 老板看完问「是不是还没有判断动作」——列表不等于统计。
            by_kind = {}
            for m in ok_moves:
                k = by_kind.setdefault(m["move_id"], {"name": m["name_zh"], "n": 0,
                                                      "limbs": {}, "ref": m.get("book_ref") or ""})
                k["n"] += 1
                k["limbs"][m["limb"]] = k["limbs"].get(m["limb"], 0) + 1

            tiles = []
            for k in sorted(by_kind.values(), key=lambda x: -x["n"]):
                side = ""
                if k["limbs"]:
                    top_limb, top_n = max(k["limbs"].items(), key=lambda kv: kv[1])
                    side = (f'<div class="mv-side">全是{top_limb}</div>' if top_n == k["n"]
                            else '<div class="mv-side">' +
                                 " · ".join(f"{l} {n}" for l, n in
                                            sorted(k["limbs"].items(), key=lambda kv: -kv[1])) +
                                 '</div>')
                ref = ('<div class="mv-ref mono">书 p.' +
                       str(k["ref"]).split("p.")[-1] + "</div>") if k["ref"] else ""
                tiles.append(f'<div class="mv-tile"><div class="mv-n mono">{k["n"]}</div>'
                             f'<div class="mv-name">{k["name"]}</div>{side}{ref}</div>')

            # 时序：动作落在攀爬窗口哪个位置。手/脚上色，不悬停也看得出分布；
            # 悬停出即时浮层（原来是浏览器原生 title——延迟慢、点击无反应、触屏没有，
            # 加上问号光标误导成可点，老板反馈是 bug）。
            span = max(t1 - t0, 0.001)
            dots = "".join(
                f'<span class="mv-dot{" foot" if "脚" in (m["limb"] or "") else ""}" '
                f'style="left:{100 * (m["t_s"] - t0) / span:.2f}%">'
                f'<span class="mv-tip mono">{m["t_s"]:.1f}s · {m["limb"]} · {m["name_zh"]}</span>'
                f'</span>'
                for m in ok_moves)
            seq = (f'<div class="mv-track"><div class="mv-line"></div>{dots}</div>'
                   f'<div class="mv-axis mono"><span>{t0:.0f}s</span>'
                   f'<span>起攀 → 完攀</span><span>{t1:.0f}s</span></div>'
                   f'<div class="mv-legend mono"><span class="ld"></span>手'
                   f'<span class="ld foot"></span>脚 · 悬停看动作</div>') if ok_moves else ""

            body = (f'<div class="mv-tiles">{"".join(tiles)}</div>{seq}' if ok_moves else
                    '<p class="sub">这条线上没识别出教材动作。</p>')
            head = sec_h2("动作记录", f"{len(ok_moves)} 个",
                          "只列骨架位置信号能可靠判定的动作：高抬脚、两手同点、换手。"
                          "侧身、掛旗这类要看身体朝向，骨架判不可靠，不硬猜。"
                          "<b>只记不评</b>——记录做过什么，不判断做得对不对。")
            lead = f'<p class="lead">{seq_line}</p>' if seq_line else ""
            moves_html = f'''
  {head}
  {lead}
  {body}'''

    HTML = f'''<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>攀岩报告卡 · {A.base}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
:root{{
  /* 与 攀岩账本.html 同一套令牌：深炭底 + 单一酸绿强调。
     强调色只给 UI（关键数字、当前态）；图表里的橙/绿/蓝是**数据编码**，
     各自有语义，不参与装饰。 */
  --bg:#0B0C0E; --surface:#131519; --surface2:#191C22; --line:#232733;
  --ink:#F2F4F7; --ink2:#9AA3B2; --ink3:#5D6675;
  --chip:#191C22; --ok:#4E9E6A;
  --accent:#AFD639; --acc-ink:#12160A;
  --move:{C_MOVE}; --rest:{C_REST}; --adjust:{C_ADJUST};
  --stuck:{C_STUCK}; --power:{C_POWER};
  --sans:"Space Grotesk","Segoe UI Variable Display","Microsoft YaHei",
         "PingFang SC",sans-serif;
  --mono:"Space Mono","Cascadia Mono",Consolas,ui-monospace,monospace;
  --ease:cubic-bezier(.2,.8,.2,1);
}}
*{{box-sizing:border-box}}
em,i,cite{{font-style:normal}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1200px;margin:0 auto;padding:56px 24px 96px}}
/* 字距只给拉丁文——中文加 letter-spacing 会被拉散成"标语体"，很丑 */
.eyebrow{{font-family:var(--mono);font-size:11px;color:var(--ink3)}}
.eyebrow .lat{{letter-spacing:.18em;text-transform:uppercase}}
/* 标题多是中文（岩馆名/线路名），不能用 mono——等宽排中文会散 */
h1{{font-size:clamp(30px,5vw,54px);font-weight:700;letter-spacing:-.03em;margin:0;
  line-height:1.05;word-break:break-word}}
/* 一句话结论是整页最该被读到的文字，字号仅次于标题，用主文字色 */
.verdict{{font-size:clamp(19px,2.3vw,26px);line-height:1.5;color:var(--ink2);
  max-width:34ch;margin:20px 0 0;text-wrap:pretty}}
.verdict b{{color:var(--ink);font-weight:700}}

/* 一级区块：大标题。原来 h2 只有 14px，比正文还小，层级是反的
   （老板 2026-07-20：「标题子标题正文字体大小差不多，有点看不明白」）。 */
/* 概览区（总）：标题 + 一句话结论 + KPI，视觉上成块，与下方细节拉开 */
.overview{{padding-bottom:clamp(30px,4vw,44px);
  border-bottom:1px solid var(--line);margin-bottom:8px}}
.detail-mark{{font-family:var(--mono);font-size:11px;letter-spacing:.3em;
  text-transform:uppercase;color:var(--ink3);margin:clamp(40px,5vw,60px) 0 0}}
/* 主题组分隔（分）：大号编号 + 组名，统领组内 2 个 h2 */
.grp{{display:flex;align-items:center;gap:16px;
  margin:clamp(38px,5vw,56px) 0 4px}}
.grp-n{{font-size:clamp(34px,5vw,54px);font-weight:700;line-height:1;
  letter-spacing:-.05em;color:var(--accent)}}
.grp-t{{font-size:clamp(20px,2.6vw,27px);font-weight:700;letter-spacing:-.02em;
  line-height:1.1}}
.grp-s{{font-size:12px;color:var(--ink3);margin-top:3px}}
/* 组内区块标题：比组标题小一档，靠组来分层 */
h2{{font-size:clamp(16px,1.9vw,20px);font-weight:700;color:var(--ink2);
  letter-spacing:-.01em;margin:clamp(28px,3.5vw,44px) 0 14px;
  padding-bottom:11px;border-bottom:1px solid var(--line);display:flex;
  justify-content:space-between;align-items:baseline;gap:16px;line-height:1.2}}
h2 .cnt{{font-family:var(--mono);font-size:11px;color:var(--ink3);font-weight:400;
  letter-spacing:.06em;white-space:nowrap;flex:none}}
.h2t{{display:inline-flex;align-items:center;gap:9px;min-width:0}}
/* 说明图标：CSS 画的圆圈 i，不用 emoji（各系统渲染不一，而且当 UI 图标很廉价） */
.info{{position:relative;flex:none;width:17px;height:17px;border-radius:50%;
  border:1px solid var(--ink3);background:none;color:var(--ink3);cursor:help;padding:0;
  font-family:var(--sans);font-size:11px;font-weight:600;line-height:1;
  display:inline-grid;place-items:center;letter-spacing:0;text-transform:none;
  transition:border-color .15s var(--ease),color .15s var(--ease)}}
.info::before{{content:"i"}}
.info:hover,.info:focus-visible{{border-color:var(--accent);color:var(--accent);outline:none}}
.tip{{position:absolute;left:0;top:calc(100% + 10px);
  width:min(360px,74vw);background:var(--surface2);border:1px solid var(--line);
  border-radius:4px;padding:13px 15px;text-align:left;
  font-family:var(--sans);font-size:13px;font-weight:400;line-height:1.7;
  color:var(--ink2);letter-spacing:0;text-transform:none;
  opacity:0;visibility:hidden;transition:opacity .15s var(--ease);
  z-index:40;box-shadow:0 10px 34px rgba(0,0,0,.55);pointer-events:none}}
.info:hover .tip,.info:focus-visible .tip{{opacity:1;visibility:visible}}
.tip b{{color:var(--ink);font-weight:700}}

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
.crux figcaption{{padding:16px 17px 17px}}
/* 结论是主角；分类做成 label、时刻缩成同行小字（老板 2026-07-20）。
   时刻不能删——回看视频得知道跳到哪一秒。 */
.crux-top{{display:flex;align-items:center;justify-content:space-between;gap:8px;
  margin-bottom:11px}}
.crux .ctag{{font-size:10px;font-weight:700;letter-spacing:.06em;padding:3px 8px;
  border-radius:2px;background:var(--surface2);color:var(--ink2);white-space:nowrap}}
.crux p{{font-size:15px;line-height:1.55;color:var(--ink);margin:0}}
.crux .tm{{font-family:var(--mono);font-size:10px;color:var(--ink3);flex:none;
  font-variant-numeric:tabular-nums}}
.vtag{{font-size:10px;font-weight:700;color:var(--accent);border:1px solid var(--accent);
  border-radius:3px;padding:1px 5px;margin-left:6px;white-space:nowrap;vertical-align:1px}}
.crux .tag{{font-size:11px;font-weight:700;margin-top:8px;display:inline-block;
  padding:3px 8px;border-radius:2px}}

/* ---- 动作记录：先统计后时序 ---- */
.mv-tiles{{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));
  gap:10px;margin-bottom:26px}}
.mv-tile{{background:var(--surface);border:1px solid var(--line);padding:16px 17px}}
.mv-n{{font-size:38px;font-weight:700;line-height:1;letter-spacing:-.04em;
  color:var(--accent);font-variant-numeric:tabular-nums}}
.mv-name{{font-size:14px;font-weight:600;margin-top:8px}}
.mv-side{{font-size:12px;color:var(--ink2);margin-top:3px}}
.mv-n .fu{{font-size:.42em;font-weight:500;color:var(--ink3);margin-left:.22em;
  letter-spacing:0}}
.mv-ref{{font-size:10px;color:var(--ink3);margin-top:5px}}
.mv-track{{position:relative;height:34px;margin-top:6px}}
.mv-line{{position:absolute;top:16px;left:0;right:0;height:1px;background:var(--line)}}
.mv-dot{{position:absolute;top:10px;width:11px;height:11px;margin-left:-5.5px;border-radius:50%;
  background:var(--accent);border:2px solid var(--bg);
  transition:transform .15s var(--ease)}}
.mv-dot.foot{{background:var(--ink3)}}
.mv-dot:hover{{transform:scale(1.35);z-index:21}}
/* 悬停即时浮层，替代原生 title */
.mv-tip{{position:absolute;bottom:calc(100% + 9px);left:50%;transform:translateX(-50%);
  white-space:nowrap;background:var(--surface2);border:1px solid var(--line);border-radius:3px;
  padding:5px 9px;font-size:11px;color:var(--ink);opacity:0;visibility:hidden;
  transition:opacity .12s var(--ease);pointer-events:none;z-index:22;
  box-shadow:0 6px 20px rgba(0,0,0,.5)}}
.mv-dot:hover .mv-tip{{opacity:1;visibility:visible}}
.mv-axis{{display:flex;justify-content:space-between;font-size:10px;color:var(--ink3);
  margin-top:2px}}
.mv-legend{{display:flex;align-items:center;gap:6px;font-size:10px;color:var(--ink3);
  margin-top:9px}}
.mv-legend .ld{{width:9px;height:9px;border-radius:50%;background:var(--accent);
  display:inline-block}}
.mv-legend .ld.foot{{background:var(--ink3);margin-left:8px}}
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
.lead{{font-size:18px;font-weight:700;color:var(--ink);margin:0 0 4px}}
/* 事实清单：一条一件事，不串成长句 */
.facts{{list-style:none;padding:0;margin:14px 0 0;max-width:70ch}}
.facts li{{position:relative;padding-left:19px;font-size:14.5px;color:var(--ink2);
  margin:9px 0;line-height:1.65}}
.facts li::before{{content:"";position:absolute;left:2px;top:8px;width:5px;height:5px;
  border-radius:50%;background:var(--accent)}}
.facts b{{color:var(--ink);font-weight:700}}
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

.cardhead{{display:flex;align-items:center;justify-content:space-between;gap:14px;
          flex-wrap:wrap;padding:0 0 14px;margin-bottom:26px;
          border-bottom:1px solid var(--line)}}
.fname{{font-size:11px;color:var(--ink3);letter-spacing:.08em}}
/* 标题区：线路名/岩馆当标题，难度做徽章，文件名不上标题 */
.titlerow{{display:flex;align-items:flex-start;justify-content:space-between;
          gap:20px;margin-top:10px}}
.titlebox{{min-width:0}}
.h1row{{display:flex;align-items:center;gap:11px;flex-wrap:wrap}}
.hsub{{font-size:15px;color:var(--ink2);margin-top:6px}}
.gbadge{{flex:none;background:var(--accent);color:var(--acc-ink);font-weight:700;
        font-size:clamp(22px,3.4vw,34px);line-height:1;letter-spacing:-.02em;
        padding:12px 16px;border-radius:3px;font-variant-numeric:tabular-nums}}
.back{{color:var(--ink3);text-decoration:none;font-size:13px}}
.back:hover{{color:var(--ink)}}
.hchips{{display:flex;gap:6px;flex-wrap:wrap}}
.hchip{{padding:2px 9px;border-radius:10px;font-size:12px;background:var(--chip);color:var(--ink2)}}
.hchip.sent{{background:var(--ok);color:#fff}}
.hchip.unsent{{color:var(--ink3)}}
</style>

<div class="wrap">
  {card_head}
  <section class="overview">
    {hero_html}
    <p class="verdict">{verdict}</p>
    <div class="kpis">
      <div class="kpi hi"><div class="n">{C['climb_time_s']:.1f}<span class="u">s</span></div>
        <div class="k">完攀用时</div><div class="s">{C['start_s']:.1f} → {C['end_s']:.1f}s</div></div>
      <div class="kpi"><div class="n">{gain_val}<span class="u">{gain_unit}</span></div>
        <div class="k">净上升</div><div class="s">{gain_sub}</div></div>
      <div class="kpi"><div class="n">{still_str}<span class="u">%</span></div>
        <div class="k">静止占比</div><div class="s">停着不动的时间</div></div>
      <div class="kpi"><div class="n">{len(stuck)}<span class="u">处</span></div>
        <div class="k">卡点</div><div class="s">最值得回看的时段</div></div>
    </div>
  </section>

  <div class="detail-mark">逐项拆解</div>

  {group_head("①", "卡在哪", "最该回看的时段，和整条线的节奏")}
  {h2_stuck}
  <div class="cruxes big">{stuck_cards}</div>
  {h2_rhythm}
  <div class="tlbox">
    <div class="tlwrap">{timeline_svg}{hotspots}</div>
    <div class="legend">
      <span><i style="background:{C_MOVE}"></i>身体在动</span>
      <span><i style="background:{C_REST}"></i>回血</span>
      <span><i style="background:{C_ADJUST}"></i>找点</span>
      <span><i style="background:{C_STUCK}"></i>卡点</span>
      <span><i style="background:{C_POWER}"></i>发力点 / 锁臂段</span>
    </div>
  </div>

  {group_head("②", "怎么爬的", "识别到的动作，和每次出手前的停顿")}
  {moves_html}
  {h2_prep}
  <div class="tlbox">{prep_svg}</div>

  {group_head("③", "省不省力", "锁臂时间，和左右两边的均衡")}
  {h2_arm}
  <p class="lead">{rest_head}</p>
  {rest_facts}
  <table>
    <tr><th>锁臂时段</th><th>持续</th><th>最弯</th><th>平均</th></tr>{bent_rows}
  </table>
  {h2_balance}
  {balance_tip}
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

  {group_head("④", "顺不顺", "流畅度四项，和时间都花在哪")}
  {h2_fluency}
  <div class="mv-tiles">{fluency_tiles}</div>
  {h2_split}
  <div class="tlbox">{split_svg}</div>

</div>

{HOVER_JS}'''

    out_html = os.path.join(A.out, "攀岩报告卡.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(HTML)
    print(f"✅ {A.base} 报告卡 → {out_html}")
    print(f"   完攀 {C['climb_time_s']:.1f}s（{C['start_s']:.1f}→{C['end_s']:.1f}）"
          f" · 净上升 {C['net_gain_bl']:.2f}bl · 检出 {det_rate}")
    print(f"   卡点 {len(stuck)} 处 · 发力点 {len(power)} 处 · 锁臂 {len(bents)} 段"
          f" · 真休息 {v2['rests']['n']} 次")
    clips = cclips + bclips
    mb = sum(os.path.getsize(os.path.join(ASSET, x)) for x in clips if x) / 1048576
    print(f"   抽帧 {sum(1 for x in cfiles + bfiles if x)}/{len(cfiles) + len(bfiles)} 张"
          f" · 片段 {sum(1 for x in clips if x)}/{len(clips)} 个（{mb:.2f}MB）→ {ASSET}")


if __name__ == "__main__":
    main()

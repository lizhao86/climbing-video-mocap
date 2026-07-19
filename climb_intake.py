#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
climb_intake.py —— 收件箱编排层（2026-07-20）

职责只有三件：算指纹判重、跑流水线、把产物落位到 素材/<片名>/。
**不算任何指标**——指标归 climb_analyze_report / climb_segments / climb_report_v2，
展示归 climb_report_card / climb_journal_card（分层硬约定见 CLAUDE.md）。

元数据（类型/难度/完攀/地点/线路名）不由本脚本采集——它由 Claude 在对话里
追问后直接写 素材/<片名>/线路.json。网页表单已于本次改版删除（7 条素材填了
零条，证伪了「让老板去网页填」）。

用法:
    python climb_intake.py scan                 # 列收件箱视频 + 判重结果（JSON）
    python climb_intake.py run <视频路径>        # 跑完整流水线并落位
    python climb_intake.py run <视频> --roi --seed X,Y [--seed-roi W,H] [--start-s S]
                                                # 远景素材走 ROI 取数

设计定案见 docs/superpowers/specs/2026-07-20-账本工作流重做-design.md。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

from climb_journal import SIDECAR_TEMPLATE

INBOX_DIR = "收件箱"
MATERIAL_DIR = "素材"
SIDECAR_NAME = "线路.json"
VIDEO_EXTS = (".mov", ".mp4")
HEAD_BYTES = 8 * 1024 * 1024      # 只哈希文件头，原片可达数百 MB

ROOT = os.path.dirname(os.path.abspath(__file__))

# Windows 三条铁律（来龙去脉见 CLAUDE.md）：
#   CLIMB_ROTATE=0 —— OpenCV 在 Windows 会自动应用旋转元数据，脚本再转一次
#     → 人躺着，但检出率仍 100%，重心高度量成水平方向，结果全错。
#   PYTHONUTF8 / PYTHONIOENCODING —— v1 脚本 open() 没指定编码，GBK 写不了 ▸。
#   venv 必须 ASCII 路径 —— mediapipe 无法从含中文的路径加载模型。
PIPELINE_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "CLIMB_MAX_W": "960",
    "CLIMB_ROTATE": "0",
}
DEFAULT_PY = r"C:\venvs\climb310\Scripts\python.exe"
DETECT_RATE_MIN = 50      # 低于这个百分比提示改走 ROI 流程


def _python():
    return os.environ.get("CLIMB_PY", DEFAULT_PY)


def run_step(args, label):
    """跑一条流水线命令，实时透传输出。→ (成功?, 完整 stdout)"""
    env = dict(os.environ)
    env.update(PIPELINE_ENV)
    print("\n=== %s ===" % label, flush=True)
    proc = subprocess.Popen([_python()] + args, cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    proc.wait()
    return proc.returncode == 0, "".join(lines)


def video_fingerprint(path, head_bytes=HEAD_BYTES):
    """→ "sha256:<32 位十六进制>"。

    哈希 = 文件大小 + 文件头 head_bytes。改文件名认得出是同一个视频；
    重新编码或裁剪认不出（那本来就是另一个文件，可接受）。
    大小必须入哈希，否则截断版与原版会撞。
    """
    h = hashlib.sha256()
    h.update(str(os.path.getsize(path)).encode())
    with open(path, "rb") as f:
        h.update(f.read(head_bytes))
    return "sha256:" + h.hexdigest()[:32]


def build_fingerprint_index(material_dir):
    """扫 <素材>/*/线路.json → {指纹: {base, dir, sidecar}}。

    指纹为空的条目跳过——否则空串会占位，让新视频全被误判成重复。
    """
    idx = {}
    if not os.path.isdir(material_dir):
        return idx
    for name in sorted(os.listdir(material_dir)):
        folder = os.path.join(material_dir, name)
        sc_path = os.path.join(folder, SIDECAR_NAME)
        if not os.path.isdir(folder) or not os.path.exists(sc_path):
            continue
        try:
            with open(sc_path, encoding="utf-8") as f:
                sc = json.load(f)
        except (ValueError, OSError):
            continue
        fp = (sc.get("视频指纹") or "").strip()
        if not fp:
            continue
        idx[fp] = {"base": name, "dir": folder, "sidecar": sc}
    return idx


def scan_inbox(inbox_dir, material_dir):
    """→ [{file, base, size_mb, fingerprint, duplicate_of, dup_sidecar}]。

    duplicate_of 是重复命中的素材文件夹名，没命中为 None。
    """
    idx = build_fingerprint_index(material_dir)
    out = []
    if not os.path.isdir(inbox_dir):
        return out
    for name in sorted(os.listdir(inbox_dir)):
        path = os.path.join(inbox_dir, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in VIDEO_EXTS:
            continue
        fp = video_fingerprint(path)
        hit = idx.get(fp)
        out.append({
            "file": path,
            "base": os.path.splitext(name)[0],
            "size_mb": round(os.path.getsize(path) / 1024 / 1024, 1),
            "fingerprint": fp,
            "duplicate_of": hit["base"] if hit else None,
            "dup_sidecar": hit["sidecar"] if hit else None,
        })
    return out


def _detect_rate(pose_stdout):
    """从 climb_pose 的输出里抓「检测到人体的帧: 123/456 (78%)」→ 78，抓不到返回 None。"""
    m = re.search(r"检测到人体的帧:\s*\d+/\d+\s*\((\d+)%\)", pose_stdout)
    return int(m.group(1)) if m else None


def run_pipeline(video_path, roi_args=None):
    """跑完整流水线并落位。→ {base, dir, ok, detect_rate, warnings}"""
    base = os.path.splitext(os.path.basename(video_path))[0]
    dest = os.path.join(ROOT, MATERIAL_DIR, base)
    data = os.path.join(dest, "数据")
    # 标注视频/ 这六步不写——它是审阅视频（climb_segments_review.py，未纳入本编排）的
    # 产物目录，这里先占位建好，免得后来人以为漏了一步。
    for d in (data, os.path.join(dest, "报告卡素材"), os.path.join(dest, "标注视频"),
              os.path.join(data, "v1原始")):
        os.makedirs(d, exist_ok=True)

    # 视频不在素材文件夹里就搬进去；已经在了（重跑场景）就原地用
    target_video = os.path.join(dest, os.path.basename(video_path))
    if os.path.abspath(video_path) != os.path.abspath(target_video):
        shutil.move(video_path, target_video)
    rel_video = os.path.relpath(target_video, ROOT)
    rel_data = os.path.relpath(data, ROOT)
    rel_dest = os.path.relpath(dest, ROOT)
    rel_v1 = os.path.relpath(os.path.join(data, "v1原始"), ROOT)

    warnings = []

    if roi_args:
        ok, out = run_step(["climb_pose_roi.py", rel_video, rel_data] + roi_args,
                           "1/6 骨架提取（ROI 远景版）")
    else:
        ok, out = run_step(["climb_pose.py", rel_video, rel_data], "1/6 骨架提取")
    if not ok:
        return {"base": base, "dir": rel_dest, "ok": False,
                "detect_rate": None, "warnings": ["骨架提取失败，后续步骤未执行"]}

    rate = _detect_rate(out)
    if rate is not None and rate < DETECT_RATE_MIN and not roi_args:
        warnings.append(
            "检出率只有 %d%%（低于 %d%%）。人在画面里可能太小，"
            "建议改走 ROI 流程重跑：run <视频> --roi --seed X,Y" % (rate, DETECT_RATE_MIN))

    steps = [
        (["climb_analyze_report.py", "--dir", rel_data, "--base", base,
          "--annotated", os.path.join(rel_data, base + "_annotated.mp4"),
          "--out", rel_v1], "2/6 v1 指标"),
        (["climb_segments.py", os.path.join(rel_data, base + "_pose2d.csv")], "3/6 动作分段"),
        (["climb_report_v2.py", "--dir", rel_data, "--base", base, "--out", rel_v1], "4/6 节奏指标"),
        (["climb_match.py", os.path.join(rel_data, base + "_segments.json")], "5/6 动作识别"),
        (["climb_report_card.py", "--dir", rel_data, "--base", base,
          "--video", rel_video, "--out", rel_dest], "6/6 报告卡"),
    ]
    for args, label in steps:
        ok, _ = run_step(args, label)
        if not ok:
            return {"base": base, "dir": rel_dest, "ok": False,
                    "detect_rate": rate, "warnings": warnings + ["%s 失败" % label]}

    # sidecar：不存在就建模板并写指纹；已存在（重跑）就只补指纹，不动老板填的内容
    sc_path = os.path.join(dest, SIDECAR_NAME)
    sc = {}
    if os.path.exists(sc_path):
        try:
            with open(sc_path, encoding="utf-8") as f:
                sc = json.load(f)
        except (ValueError, OSError):
            sc = {}
    for k, v in SIDECAR_TEMPLATE.items():
        sc.setdefault(k, v)
    sc["视频指纹"] = video_fingerprint(target_video)
    with open(sc_path, "w", encoding="utf-8") as f:
        json.dump(sc, f, ensure_ascii=False, indent=2)

    warnings.append("检出率高不代表跟对了人。开 数据/%s_annotated.mp4 抽看几帧，"
                    "确认骨架一直在攀岩者身上（有路人走过会跟错，检出率不会掉）。" % base)
    return {"base": base, "dir": rel_dest, "ok": True,
            "detect_rate": rate, "warnings": warnings}


def cmd_scan():
    items = scan_inbox(os.path.join(ROOT, INBOX_DIR),
                       os.path.join(ROOT, MATERIAL_DIR))
    print(json.dumps({"inbox": items}, ensure_ascii=False, indent=2))


def cmd_run(argv):
    video = argv[0]
    if not os.path.exists(video):
        print("找不到视频: %s" % video)
        sys.exit(1)
    roi_args = None
    if "--roi" in argv:
        roi_args = []
        for flag in ("--seed", "--seed-roi", "--start-s"):
            if flag in argv:
                i = argv.index(flag)
                if i + 1 >= len(argv):
                    print("%s 后面缺值" % flag)
                    sys.exit(1)
                roi_args += [flag, argv[i + 1]]
        if "--seed" not in argv:
            print("--roi 必须同时给 --seed X,Y（首帧攀岩者在全画幅的像素坐标）")
            sys.exit(1)
    result = run_pipeline(video, roi_args)
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("scan", "run"):
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "scan":
        cmd_scan()
    else:
        if len(sys.argv) < 3:
            print("用法: python climb_intake.py run <视频路径>")
            sys.exit(1)
        cmd_run(sys.argv[2:])


if __name__ == "__main__":
    main()

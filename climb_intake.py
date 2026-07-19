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
import sys

INBOX_DIR = "收件箱"
MATERIAL_DIR = "素材"
SIDECAR_NAME = "线路.json"
VIDEO_EXTS = (".mov", ".mp4")
HEAD_BYTES = 8 * 1024 * 1024      # 只哈希文件头，原片可达数百 MB

ROOT = os.path.dirname(os.path.abspath(__file__))


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

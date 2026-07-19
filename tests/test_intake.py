# -*- coding: utf-8 -*-
"""编排层单测：指纹与判重。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import climb_intake as ci
from climb_intake import video_fingerprint, build_fingerprint_index


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def test_fingerprint_stable(tmp_path):
    p = tmp_path / "a.mov"
    _write(p, b"climbing" * 100)
    assert video_fingerprint(str(p)) == video_fingerprint(str(p))


def test_fingerprint_survives_rename(tmp_path):
    """改文件名要认得出是同一个视频。"""
    a, b = tmp_path / "a.mov", tmp_path / "b.mov"
    _write(a, b"climbing" * 100)
    _write(b, b"climbing" * 100)
    assert video_fingerprint(str(a)) == video_fingerprint(str(b))


def test_fingerprint_differs_on_content(tmp_path):
    a, b = tmp_path / "a.mov", tmp_path / "b.mov"
    _write(a, b"climbing" * 100)
    _write(b, b"bouldering" * 100)
    assert video_fingerprint(str(a)) != video_fingerprint(str(b))


def test_fingerprint_differs_on_size_alone(tmp_path):
    """头部相同但长度不同（截断版）必须区分开。"""
    a, b = tmp_path / "a.mov", tmp_path / "b.mov"
    _write(a, b"x" * 1000)
    _write(b, b"x" * 2000)
    assert video_fingerprint(str(a)) != video_fingerprint(str(b))


def test_fingerprint_prefix(tmp_path):
    p = tmp_path / "a.mov"
    _write(p, b"x" * 10)
    assert video_fingerprint(str(p)).startswith("sha256:")


def test_index_maps_fingerprint_to_folder(tmp_path):
    mdir = tmp_path / "素材"
    for base, fp in [("IMG_1", "sha256:aaa"), ("IMG_2", "sha256:bbb")]:
        d = mdir / base
        d.mkdir(parents=True)
        with open(d / "线路.json", "w", encoding="utf-8") as f:
            json.dump({"视频指纹": fp, "难度": "V4"}, f, ensure_ascii=False)
    idx = build_fingerprint_index(str(mdir))
    assert idx["sha256:aaa"]["base"] == "IMG_1"
    assert idx["sha256:bbb"]["sidecar"]["难度"] == "V4"


def test_index_ignores_blank_fingerprint(tmp_path):
    """指纹为空的老条目不能占位，否则新视频会被误判成重复。"""
    mdir = tmp_path / "素材"
    d = mdir / "IMG_1"
    d.mkdir(parents=True)
    with open(d / "线路.json", "w", encoding="utf-8") as f:
        json.dump({"视频指纹": "", "难度": ""}, f, ensure_ascii=False)
    assert build_fingerprint_index(str(mdir)) == {}


from climb_intake import scan_inbox


def test_scan_flags_new_and_duplicate(tmp_path):
    inbox = tmp_path / "收件箱"
    inbox.mkdir()
    mdir = tmp_path / "素材"

    # 已入库的一条，指纹取自它的原片
    old_dir = mdir / "IMG_OLD"
    old_dir.mkdir(parents=True)
    _write(old_dir / "IMG_OLD.MOV", b"same content" * 50)
    fp = video_fingerprint(str(old_dir / "IMG_OLD.MOV"))
    with open(old_dir / "线路.json", "w", encoding="utf-8") as f:
        json.dump({"视频指纹": fp, "难度": "V4", "完攀": True,
                   "地点": "岩时", "日期": "2026-03-29"}, f, ensure_ascii=False)

    # 收件箱：一条重复（改了名）、一条全新
    _write(inbox / "renamed.MOV", b"same content" * 50)
    _write(inbox / "IMG_NEW.MOV", b"brand new" * 50)

    got = scan_inbox(str(inbox), str(mdir))
    by_name = {item["base"]: item for item in got}

    assert by_name["renamed"]["duplicate_of"] == "IMG_OLD"
    assert by_name["renamed"]["dup_sidecar"]["难度"] == "V4"
    assert by_name["IMG_NEW"]["duplicate_of"] is None


def test_scan_ignores_non_video(tmp_path):
    inbox = tmp_path / "收件箱"
    inbox.mkdir()
    _write(inbox / "readme.txt", b"hello")
    _write(inbox / ".gitkeep", b"")
    assert scan_inbox(str(inbox), str(tmp_path / "素材")) == []


def test_scan_empty_inbox(tmp_path):
    inbox = tmp_path / "收件箱"
    inbox.mkdir()
    assert scan_inbox(str(inbox), str(tmp_path / "素材")) == []


# ---- run_pipeline 的分支逻辑：不碰 mediapipe，把 run_step 换成假的 ----

def test_run_pipeline_stops_after_pose_extraction_failure(tmp_path, monkeypatch):
    """骨架提取失败要提前返回，后续五步不能被调用。"""
    monkeypatch.setattr(ci, "ROOT", str(tmp_path))
    calls = []

    def fake_run_step(args, label):
        calls.append(label)
        return False, "骨架提取炸了"

    monkeypatch.setattr(ci, "run_step", fake_run_step)
    video = tmp_path / "IMG_TEST.MOV"
    _write(video, b"fake video bytes")

    result = ci.run_pipeline(str(video))

    assert result["ok"] is False
    assert result["detect_rate"] is None
    assert calls == ["1/6 骨架提取"]
    assert "骨架提取失败" in result["warnings"][0]


def test_run_pipeline_warns_on_low_detect_rate(tmp_path, monkeypatch):
    """检出率低于 DETECT_RATE_MIN 且没走 ROI 时要给出改走 ROI 的建议。"""
    monkeypatch.setattr(ci, "ROOT", str(tmp_path))

    def fake_run_step(args, label):
        if label == "1/6 骨架提取":
            return True, "检测到人体的帧: 10/100 (10%)"
        return False, "后续步骤没跑，随便失败一下好提前结束"

    monkeypatch.setattr(ci, "run_step", fake_run_step)
    video = tmp_path / "IMG_TEST.MOV"
    _write(video, b"fake video bytes")

    result = ci.run_pipeline(str(video))

    assert result["detect_rate"] == 10
    assert any("建议改走 ROI 流程" in w for w in result["warnings"])


def test_run_pipeline_roi_skips_low_rate_warning(tmp_path, monkeypatch):
    """走 ROI 流程时，就算检出率低也不该再建议「改走 ROI」。"""
    monkeypatch.setattr(ci, "ROOT", str(tmp_path))

    def fake_run_step(args, label):
        if label == "1/6 骨架提取（ROI 远景版）":
            return True, "检测到人体的帧: 10/100 (10%)"
        return False, "后续步骤没跑，随便失败一下好提前结束"

    monkeypatch.setattr(ci, "run_step", fake_run_step)
    video = tmp_path / "IMG_TEST.MOV"
    _write(video, b"fake video bytes")

    result = ci.run_pipeline(str(video), roi_args=["--seed", "100,200"])

    assert result["detect_rate"] == 10
    assert not any("建议改走 ROI 流程" in w for w in result["warnings"])

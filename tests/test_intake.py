# -*- coding: utf-8 -*-
"""编排层单测：指纹与判重。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

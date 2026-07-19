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

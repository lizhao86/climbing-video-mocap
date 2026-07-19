# -*- coding: utf-8 -*-
"""聚合层单测：难度解析、荣誉榜、地点足迹。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from climb_journal import parse_grade


def test_v_scale():
    assert parse_grade("V4") == ("V", 4)
    assert parse_grade("v10") == ("V", 10)
    assert parse_grade(" V0 ") == ("V", 0)


def test_yds_scale():
    assert parse_grade("5.10b")[0] == "YDS"
    assert parse_grade("5.12A")[0] == "YDS"


def test_yds_ordering_5_9_easier_than_5_10a():
    """字符串排序会把 5.9 排在 5.10a 后面，rank 必须排对。"""
    _, r59 = parse_grade("5.9")
    _, r10a = parse_grade("5.10a")
    _, r10b = parse_grade("5.10b")
    assert r59 < r10a < r10b


def test_unrecognized():
    assert parse_grade("") == (None, None)
    assert parse_grade(None) == (None, None)
    assert parse_grade("紫色") == (None, None)
    assert parse_grade("V4/V5") == (None, None)


from climb_journal import honors, places


def _entry(grade, sent, place="", scale_from_grade=True):
    """构造一条最小 entry，只带 honors/places 关心的字段。"""
    scale, rank = parse_grade(grade) if scale_from_grade else (None, None)
    return {"grade": grade, "grade_scale": scale, "grade_rank": rank,
            "sent": sent, "place": place}


def test_honors_splits_two_scales():
    es = [_entry("V4", True), _entry("V5", True), _entry("5.10b", True)]
    h = honors(es)
    assert h["V"]["best_sent"] == "V5"
    assert h["YDS"]["best_sent"] == "5.10b"
    assert h["V"]["n_sent"] == 2


def test_honors_best_is_hardest_not_latest():
    """最高难度看 rank，不看出现顺序。"""
    es = [_entry("V7", True), _entry("V3", True)]
    assert honors(es)["V"]["best_sent"] == "V7"


def test_honors_unsent_counts_as_attempt_only():
    es = [_entry("V6", False), _entry("V4", True)]
    h = honors(es)
    assert h["V"]["best_sent"] == "V4"      # V6 没送顶，不进荣誉
    assert h["V"]["n_attempt"] == 2
    assert h["V"]["n_sent"] == 1
    assert h["V"]["by_grade"] == {"V4": 1}


def test_honors_yds_ordering():
    es = [_entry("5.9", True), _entry("5.10a", True)]
    assert honors(es)["YDS"]["best_sent"] == "5.10a"


def test_honors_skips_unrecognized_grade():
    es = [_entry("紫色", True), _entry("V4", True)]
    h = honors(es)
    assert list(h.keys()) == ["V"]


def test_places_dedupes_and_ignores_blank():
    es = [_entry("V4", True, "岩时"), _entry("V4", True, "岩时"),
          _entry("V4", True, "六盘水"), _entry("V4", True, "")]
    p = places(es)
    assert p["n"] == 2
    assert p["list"] == ["六盘水", "岩时"]

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

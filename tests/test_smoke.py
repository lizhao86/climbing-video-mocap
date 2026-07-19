# -*- coding: utf-8 -*-
"""冒烟测试：确认测试能从项目根 import 脚本模块。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_can_import_journal():
    import climb_journal
    assert hasattr(climb_journal, "aggregate")

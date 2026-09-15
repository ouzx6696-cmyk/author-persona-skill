# -*- coding: utf-8 -*-
"""数值展示：整数位绝不能被去尾零截断。

四个产物模块（report.renderer / persona.style_templates / scene_templates /
system_prompt）曾各自复制 ``f"{v:.{d}f}".rstrip("0")``，在 ``digits=0`` 时把
``100`` 渲染成 ``"1"``、``2400`` 渲染成 ``"24"``——整数计数直接进公开产物，
属数值保真缺陷。本用例把共享实现与四条委托路径一起钉死。
"""
from __future__ import annotations

import unittest

from author_persona_skill._numbers import trim_decimal
from author_persona_skill.persona.scene_templates import _fmt as scene_fmt
from author_persona_skill.persona.style_templates import _fmt as style_fmt
from author_persona_skill.persona.system_prompt import (
    _MISSING as _SYSTEM_PROMPT_MISSING,
)
from author_persona_skill.persona.system_prompt import _num_out
from author_persona_skill.report.renderer import _fmt_metric


class TrimDecimalTest(unittest.TestCase):

    def test_trailing_zeros_after_point_are_removed(self):
        self.assertEqual(trim_decimal(24.20, 2), "24.2")
        self.assertEqual(trim_decimal(10.0, 2), "10")
        self.assertEqual(trim_decimal(0.9309, 4), "0.9309")
        self.assertEqual(trim_decimal(0.0, 4), "0")

    def test_integer_places_are_never_truncated(self):
        for value, digits, expected in (
            (100, 0, "100"),
            (1000, 0, "1000"),
            (2400, 0, "2400"),
            (2916, 0, "2916"),
            (50, 0, "50"),
        ):
            self.assertEqual(trim_decimal(value, digits), expected,
                             f"{value} 的整数位被误去尾零")

    def test_rounding_is_applied_before_trimming(self):
        self.assertEqual(trim_decimal(1.998, 2), "2")
        self.assertEqual(trim_decimal(0.126, 2), "0.13")


class DelegationTest(unittest.TestCase):
    """四条渲染路径都必须委托共享实现。"""

    def test_renderer_metric(self):
        self.assertEqual(_fmt_metric(2400, 0), "2400")
        self.assertEqual(_fmt_metric(24.2, 2), "24.2")
        self.assertEqual(_fmt_metric(None), "—")

    def test_style_and_scene_formatters(self):
        self.assertEqual(style_fmt(120.0, 0), "120")
        self.assertEqual(scene_fmt(240.0, 0), "240")

    def test_system_prompt_formatter(self):
        self.assertEqual(_num_out(100.0, 0), "100")
        self.assertEqual(_num_out(None, 0), _SYSTEM_PROMPT_MISSING)


if __name__ == "__main__":
    unittest.main()

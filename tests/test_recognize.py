#!/usr/bin/env python3
"""手势识别器的单元测试。

主程序文件没有 .py 后缀(它是个可执行命令),所以用 SourceFileLoader 直接加载。
跑法: python3 -m unittest discover tests   或   python3 tests/test_recognize.py
"""

import importlib.machinery
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_main_module():
    loader = importlib.machinery.SourceFileLoader(
        "mouse_gestures", os.path.join(ROOT, "mouse-gestures"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


try:
    mg = load_main_module()
except SystemExit:                     # 主程序在 evdev 缺失时会 sys.exit
    print("跳过: 未安装 python3-evdev", file=sys.stderr)
    sys.exit(0)


def straight(dx, dy, steps=20):
    """生成一条从原点出发的直线轨迹。"""
    return [(dx * i / steps, dy * i / steps) for i in range(steps + 1)]


class TestRecognize(unittest.TestCase):
    MIN_SEG = 40

    def rec(self, path):
        return mg.recognize(path, self.MIN_SEG)

    def test_four_cardinal_directions(self):
        self.assertEqual(self.rec(straight(200, 0)), "R")
        self.assertEqual(self.rec(straight(-200, 0)), "L")
        self.assertEqual(self.rec(straight(0, 200)), "D")   # 屏幕坐标 y 轴向下
        self.assertEqual(self.rec(straight(0, -200)), "U")

    def test_four_diagonals(self):
        self.assertEqual(self.rec(straight(200, -200)), "9")   # 右上
        self.assertEqual(self.rec(straight(200, 200)), "3")    # 右下
        self.assertEqual(self.rec(straight(-200, 200)), "1")   # 左下
        self.assertEqual(self.rec(straight(-200, -200)), "7")  # 左上

    def test_l_shape_stays_two_segments(self):
        """先下后右的 L 形必须识别成 DR,不能被读成右下斜。"""
        path = straight(0, 200) + [(x, 200) for x in range(0, 201, 10)]
        self.assertEqual(self.rec(path), "DR")

    def test_jitter_returns_none(self):
        """手抖幅度小于 min_segment 时不产生任何方向 —— 调用方会补发普通右键。"""
        self.assertIsNone(self.rec([(0, 0), (3, 2), (1, -4), (0, 1)]))

    def test_too_few_points(self):
        self.assertIsNone(self.rec([]))
        self.assertIsNone(self.rec([(0, 0)]))

    def test_repeated_direction_collapses(self):
        """同方向的多段合并成一个字符,不会变成 'RRR'。"""
        self.assertEqual(self.rec(straight(600, 0, steps=60)), "R")

    def test_sector_boundaries(self):
        """每个扇区的中心角度都要落到对应方向上。"""
        import math
        expected = ["R", "3", "D", "1", "L", "7", "U", "9"]
        for i, want in enumerate(expected):
            angle = i * math.pi / 4
            dx, dy = 200 * math.cos(angle), 200 * math.sin(angle)
            self.assertEqual(self.rec(straight(dx, dy)), want,
                             f"扇区 {i} (角度 {math.degrees(angle):.0f}°)")


class TestParseCombo(unittest.TestCase):
    def test_single_key(self):
        mods, key = mg.parse_combo("f5")
        self.assertEqual(mods, [])
        self.assertEqual(key, mg.e.KEY_F5)

    def test_with_modifiers(self):
        mods, key = mg.parse_combo("ctrl+shift+t")
        self.assertEqual(mods, [mg.e.KEY_LEFTCTRL, mg.e.KEY_LEFTSHIFT])
        self.assertEqual(key, mg.e.KEY_T)

    def test_aliases(self):
        _, key = mg.parse_combo("alt+left")
        self.assertEqual(key, mg.e.KEY_LEFT)
        _, key = mg.parse_combo("super+h")
        self.assertEqual(key, mg.e.KEY_H)

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            mg.parse_combo("ctrl+nosuchkey")
        with self.assertRaises(ValueError):
            mg.parse_combo("")


if __name__ == "__main__":
    unittest.main(verbosity=2)

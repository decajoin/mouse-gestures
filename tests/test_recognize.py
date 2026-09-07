#!/usr/bin/env python3
"""手势识别器的单元测试。

主程序文件没有 .py 后缀(它是个可执行命令),所以用 SourceFileLoader 直接加载。
跑法: python3 -m unittest discover tests   或   python3 tests/test_recognize.py
"""

import importlib.machinery
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import time
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


class TestPathExtent(unittest.TestCase):
    """min_total 这道闸用的度量。

    回归点: 曾经用终点的净位移 max(|x|,|y|),导致所有终点回到起点附近的手势
    (UD/LR/画圈)被当成普通右键丢掉,而且回笔误差决定它偶尔又能通过 —— 时灵时不灵。
    """

    MIN_TOTAL = 60          # 配置默认值

    @staticmethod
    def stroke(corners, n=30):
        """按折点顺序生成一条轨迹。"""
        path = [corners[0]]
        for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
            path += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n)
                     for i in range(1, n + 1)]
        return path

    def test_round_trip_passes_the_gate(self):
        """往返手势必须过闸 —— 净位移接近 0,但这一笔确实画得很大。"""
        for name, corners in {
            "UD": [(0, 0), (0, -200), (0, 0)],
            "DU": [(0, 0), (0, 200), (0, 0)],
            "LR": [(0, 0), (-200, 0), (0, 0)],
            "RL": [(0, 0), (200, 0), (0, 0)],
            "画圈": [(0, 0), (150, 0), (150, 150), (0, 150), (0, 0)],
        }.items():
            path = self.stroke(corners)
            with self.subTest(name):
                end = path[-1]
                self.assertLess(max(abs(end[0]), abs(end[1])), self.MIN_TOTAL,
                                "前提: 这些手势的净位移确实小于阈值")
                self.assertGreaterEqual(mg.path_extent(path), self.MIN_TOTAL)

    def test_round_trip_recognizes(self):
        """识别器本身一直是对的,顺手钉住,防止以后改坏。"""
        self.assertEqual(mg.recognize(self.stroke([(0, 0), (0, -200), (0, 0)]), 40), "UD")
        self.assertEqual(mg.recognize(self.stroke([(0, 0), (200, 0), (0, 0)]), 40), "RL")

    def test_diagonal_measured_by_true_length(self):
        """斜向按欧氏长度算,不是切比雪夫距离 —— 否则斜向阈值被抬高 sqrt(2) 倍。"""
        d = 100 / math.sqrt(2)
        self.assertAlmostEqual(mg.path_extent([(0, 0), (d, -d)]), 100, places=6)

    def test_jitter_stays_below_gate(self):
        """手抖不能过闸,否则每次普通右键都变成误触发。"""
        jitter = [(0, 0), (3, 2), (1, -4), (0, 1), (-2, 3)]
        self.assertLess(mg.path_extent(jitter), self.MIN_TOTAL)

    def test_degenerate_paths(self):
        self.assertEqual(mg.path_extent([]), 0.0)
        self.assertEqual(mg.path_extent([(0, 0)]), 0.0)


class TestIsDaemonArgv(unittest.TestCase):
    """--doctor 靠它区分"设备被独占"是自己造成的,还是 keyd 之类抢的。

    判错的代价不对称: 漏判(该跳过却去 grab)会给出一大段"元凶是 keyd"的
    错误指引,把人指去改 /etc/keyd/default.conf。
    """

    DAEMON = [
        ["python3", "/home/u/.local/bin/mouse-gestures"],          # systemd 启动
        ["python3", "./mouse-gestures"],                           # 仓库里直接跑
        ["python3", "/home/u/.local/bin/mouse-gestures", "-c", "/tmp/x.json"],
        ["mouse-gestures"],                                        # 直接 exec
    ]
    NOT_DAEMON = [
        ["python3", "/home/u/.local/bin/mouse-gestures", "--doctor"],
        ["python3", "./mouse-gestures", "--list-devices"],
        ["journalctl", "--user", "-u", "mouse-gestures", "-f"],
        ["systemctl", "--user", "restart", "mouse-gestures"],
        ["nano", "mouse-gestures"],
        ["python3", "-c", "import time", "mouse-gestures"],
        ["bash", "./install.sh"],
        [],
    ]

    def test_daemon_shapes(self):
        for argv in self.DAEMON:
            with self.subTest(argv=argv):
                self.assertTrue(mg.is_daemon_argv(argv))

    def test_non_daemon_shapes(self):
        for argv in self.NOT_DAEMON:
            with self.subTest(argv=argv):
                self.assertFalse(mg.is_daemon_argv(argv))


class TestDaemonScan(unittest.TestCase):
    """daemon_already_running() 真的去扫 /proc。"""

    def test_detects_instance_run_from_repo(self):
        """从仓库里直接跑的实例也要认出来。若本机已有守护进程在跑,
        这条依然成立(只是不区分是谁),所以不需要基线。"""
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "mouse-gestures")
            with open(fake, "w", encoding="utf-8") as fh:
                fh.write("import time; time.sleep(30)\n")
            proc = subprocess.Popen([sys.executable, fake],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            deadline = time.time() + 5      # Popen 返回时 exec 可能还没发生
            while time.time() < deadline:
                if mg.daemon_already_running():
                    return
                time.sleep(0.02)
            self.fail("没能在 5 秒内检测到守护进程")

    def test_ignores_self(self):
        """跑 --doctor 的进程自己不算 —— 否则独占检查永远被跳过。"""
        self.assertTrue(mg.is_daemon_argv(["python3", "/x/mouse-gestures"]),
                        "前提: 这个形状本来是会被认成守护进程的")
        argv = ["python3", "/x/mouse-gestures", "--doctor"]
        self.assertFalse(mg.is_daemon_argv(argv))


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

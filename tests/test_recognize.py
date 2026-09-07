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


def rounded_corner(first, second, length=200, radius=0.3, step=4):
    """画一条带圆角的两段折线 —— 人画 L 形的真实样子。

    first/second 是 (dx, dy) 单位方向。圆角用二次贝塞尔,radius 是拐角
    吃掉的比例。真人画不出直角,这个圆弧就是 DR 被识别成 D3R 的根源。
    """
    p0 = (0.0, 0.0)
    p1 = (first[0] * length, first[1] * length)
    p2 = (p1[0] + second[0] * length, p1[1] + second[1] * length)
    a = (p1[0] + (p0[0] - p1[0]) * radius, p1[1] + (p0[1] - p1[1]) * radius)
    b = (p1[0] + (p2[0] - p1[0]) * radius, p1[1] + (p2[1] - p1[1]) * radius)
    knots = [p0, a]
    for i in range(1, 12):
        t = i / 12
        u = 1 - t
        knots.append((u * u * a[0] + 2 * u * t * p1[0] + t * t * b[0],
                      u * u * a[1] + 2 * u * t * p1[1] + t * t * b[1]))
    knots += [b, p2]
    path = [p0]
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        path += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n)
                 for k in range(1, n + 1)]
    return path


class TestSmoothing(unittest.TestCase):
    """圆角平滑。

    回归点: 人画 L 形不可能是直角,拐角那段圆弧被量化成一个斜向,"先下后右"
    实测 55% 的情况画出来是 D3R 而不是 DR —— 默认配置绑的 DR(Alt+F4)
    因此只有 31% 的命中率。
    """

    MIN_SEG = 40

    def test_rounded_l_shapes(self):
        """八种 L 形的圆角画法都要还原成两段。"""
        for want, (a, b) in {
            "DR": ((0, 1), (1, 0)),
            "DL": ((0, 1), (-1, 0)),
            "UR": ((0, -1), (1, 0)),
            "UL": ((0, -1), (-1, 0)),
            "RD": ((1, 0), (0, 1)),
            "RU": ((1, 0), (0, -1)),
            "LD": ((-1, 0), (0, 1)),
            "LU": ((-1, 0), (0, -1)),
        }.items():
            with self.subTest(want):
                self.assertEqual(
                    mg.recognize(rounded_corner(a, b), self.MIN_SEG), want)

    def test_sharp_corner_still_works(self):
        """没有圆角的理想 L 形不能被平滑改坏。"""
        path = [(0, y) for y in range(0, 201, 5)] + [(x, 200) for x in range(0, 201, 5)]
        self.assertEqual(mg.recognize(path, self.MIN_SEG), "DR")

    def test_only_interior_runs_are_dropped(self):
        """首尾的短段要留着 —— 抹掉会把 DR 变成 D 或 R,反而丢信息。"""
        runs = [["D", 30], ["R", 300], ["U", 30]]
        self.assertEqual(mg.smooth_runs([list(r) for r in runs], self.MIN_SEG), runs)

    def test_dropped_length_is_conserved(self):
        """被抹掉的长度要并给邻居,不能凭空丢 —— 否则反复平滑越削越短。"""
        out = mg.smooth_runs([["D", 200], ["3", 30], ["R", 200]], self.MIN_SEG)
        self.assertEqual([d for d, _ in out], ["D", "R"])
        self.assertEqual(sum(n for _, n in out), 430)

    def test_interior_short_run_is_dropped_and_merged(self):
        """抹掉中间段后左右同向的话要合并,不能留下 'RR'。"""
        self.assertEqual(
            mg.smooth_runs([["R", 200], ["9", 30], ["R", 200]], self.MIN_SEG),
            [["R", 430]])

    def test_long_interior_run_is_kept(self):
        """真的画了一段斜向就不能抹 —— 否则 D3R 这种真实手势没法表达。"""
        runs = [["D", 200], ["3", 200], ["R", 200]]
        self.assertEqual(mg.smooth_runs(list(runs), self.MIN_SEG), runs)


class TestEditDistance(unittest.TestCase):
    def test_basics(self):
        self.assertEqual(mg.edit_distance("", ""), 0)
        self.assertEqual(mg.edit_distance("L1D3", "L1D3"), 0)
        self.assertEqual(mg.edit_distance("L1D3", "L1D"), 1)      # 删一个
        self.assertEqual(mg.edit_distance("7L1D3", "L1D3"), 1)    # 加一个
        self.assertEqual(mg.edit_distance("L1D3", "L1D9"), 1)     # 换一个
        self.assertEqual(mg.edit_distance("L", "R"), 1)


class TestMatchGesture(unittest.TestCase):
    """模糊匹配。C 形这类曲线手势的起笔收笔位置每次都不同,同一个 C 能画出
    二十几种方向串,精确匹配只有 20% 命中。"""

    PATTERNS = ["L", "R", "U", "D", "DR", "9", "1", "7", "7L1D3R"]

    # 真机采集: 同一个人连画 17 笔 C,识别器吐出的全部写法。规范式 7L1D3R
    # 就是按这份分布选的 —— 起笔在左上(7)、收笔带 R,和仿真猜的 L1D3 不一样。
    REAL_C = ["7L1D3R", "71DR", "71D3R", "U1D3R", "L1D3R", "7LDR", "713R", "L1DR"]

    def match(self, observed):
        return mg.match_gesture(observed, self.PATTERNS)

    def test_exact_match_wins(self):
        for g in self.PATTERNS:
            with self.subTest(g):
                self.assertEqual(self.match(g), g)

    def test_real_c_shape_variants(self):
        """真机采集到的 8 种 C 形写法都要归到规范式。"""
        for observed in self.REAL_C:
            with self.subTest(observed):
                self.assertEqual(self.match(observed), "7L1D3R")

    def test_threshold_applies_before_ties(self):
        """够不着的模式不该有资格参与平局。

        回归点: '71DR' 到 'DR' 和到 '7L1D3R' 都是距离 2,原先任何平局一律
        否决,于是这一笔被丢掉。但 'DR' 长度 2、阈值只有 1,本就够不着。
        真机 17 笔里有 5 笔栽在这上面(71%)。
        """
        self.assertEqual(mg.edit_distance("71DR", "DR"), 2)
        self.assertEqual(mg.edit_distance("71DR", "7L1D3R"), 2)
        self.assertEqual(self.match("71DR"), "7L1D3R")

    def test_single_direction_requires_exact(self):
        """单向手势阈值为 0 —— 否则随便画一笔都会被吸到 L 上。"""
        self.assertIsNone(mg.match_gesture("L3", ["L"]))
        self.assertIsNone(mg.match_gesture("RD", ["R"]))

    def test_ties_are_rejected(self):
        """两个模式一样近时不猜 —— 宁可补发右键,也不要执行错的动作。"""
        self.assertIsNone(mg.match_gesture("L1", ["L", "1"]))

    def test_too_far_is_unbound(self):
        self.assertIsNone(self.match("RRRRRR"))
        self.assertIsNone(self.match("9U7L1D3R9U"))   # 离规范式 4 段
        self.assertIsNone(self.match("3R9U7L1D"))

    def test_two_extra_segments_still_match(self):
        """长手势允许差 2 段 —— C 形起笔多带一个小勾还是它。"""
        self.assertEqual(mg.edit_distance("9U7L1D3R", "7L1D3R"), 2)
        self.assertEqual(self.match("9U7L1D3R"), "7L1D3R")

    def test_l_shape_tolerates_one_slip(self):
        """DR 长度 2,阈值 1 —— 少画或多画一段还认得出。"""
        self.assertEqual(self.match("DR3"), "DR")

    def test_empty_patterns(self):
        self.assertIsNone(mg.match_gesture("L", []))

    def test_nearest_returns_all_ties(self):
        """并列的候选要全部返回,交给调用方按动作去歧义。"""
        self.assertEqual(sorted(mg.nearest_gestures("XY", ["XZ", "WY"])),
                         ["WY", "XZ"])


class TestConfigMatch(unittest.TestCase):
    """Config.match 在 nearest_gestures 之上按动作去歧义。"""

    class FakeConfig:
        fuzzy = True
        match = mg.Config.match

        def __init__(self, gestures):
            self.gestures = gestures

    def test_same_action_ties_are_not_ambiguous(self):
        """同一个动作绑多种写法时,并列不算歧义 —— 否则绑别名反而更差。"""
        cfg = self.FakeConfig({"XZ": "cmd:foo", "WY": "cmd:foo"})
        self.assertIn(cfg.match("XY"), ("XZ", "WY"))

    def test_different_action_ties_are_rejected(self):
        cfg = self.FakeConfig({"XZ": "cmd:foo", "WY": "cmd:bar"})
        self.assertIsNone(cfg.match("XY"))

    def test_fuzzy_can_be_disabled(self):
        cfg = self.FakeConfig({"7L1D3R": "cmd:foo"})
        cfg.fuzzy = False
        self.assertIsNone(cfg.match("71DR"))
        self.assertEqual(cfg.match("7L1D3R"), "7L1D3R")


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

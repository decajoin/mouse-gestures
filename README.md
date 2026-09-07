# mouse-gestures

Wayland 下**真正能用**的鼠标手势工具。按住右键画一笔，松手执行对应动作。

Linux 上的鼠标手势软件（easystroke、mouse-actions 等）在 Wayland 下几乎全部失效——
Wayland 协议不允许应用全局捕获鼠标事件。本工具绕开显示服务器，直接读内核的
evdev 输入设备，因此**在 Wayland 和 X11 下都能工作**。

约 570 行 Python，除 `python3-evdev` 外无依赖。

---

## 工作原理

```
物理鼠标 ──EVIOCGRAB 独占──> mouse-gestures ──uinput 虚拟设备──> 系统
                                    │
                                    └── 识别出手势 ──> 注入按键组合
```

1. **独占**物理鼠标（`EVIOCGRAB`），系统看不到它的原始事件
2. 建两个 uinput 虚拟设备：一个鼠标（转发所有事件）、一个键盘（注入快捷键）
3. 右键按下时**先吞掉不转发**，记录位移轨迹；松手时才决策：
   - 轨迹离起点的最远距离 < `min_total` → 判定普通右键，把吞掉的按下+抬起**原样补发** → 右键菜单照常弹出
   - 识别出已绑定的手势 → 执行动作，不补发右键
   - 识别失败或动作出错 → 也补发右键

第 3 步是关键：因为独占了设备，画手势时不会弹出上下文菜单；而失败路径总是补发，
所以**普通右键的行为完全不受影响**。

## 手势记号

轨迹被压缩成方向串。四正方向用字母，四斜方向用小键盘方位数字——
这样斜向不会和字母序列混淆（`9` 是一笔右上，`UR` 是先上后右两笔）：

```
    7  U  9        U 上   D 下   L 左   R 右
     ╲ │ ╱         9 右上  3 右下  1 左下  7 左上
  L ── ● ── R
     ╱ │ ╲         多笔按先后顺序拼接:
    1  D  3          DR = 先下后右的 L 形
                     7L1D3R = 开口朝右的 C 形
```

识别不要求画得一模一样，有两层容错：

- **圆角平滑**：人画 L 形不可能是直角，拐角那段圆弧会被量化成一个斜向，
  「先下后右」实测 55% 的情况画出来是 `D3R`。夹在中间且明显短于一笔的段
  会被抹掉，`D3R` → `DR`。
- **模糊匹配**：曲线手势的起笔收笔位置每次都不同——真机连画 17 笔 C，识别器
  吐出了 8 种不同的方向串。识别结果按编辑距离归到最近的已绑定手势，阈值随
  手势长度收紧（`len // 2`，上限 2；单向手势因此只接受精确匹配，不然随便
  画一笔都会被吸过去）。够不着阈值的手势不参与比较；剩下的候选若并列且绑的是
  **不同**动作才算歧义、不执行——绑同一个动作就不算，所以可以给一个动作绑多种写法。

规范式要按自己的手感挑，不是照搬默认值。画几笔看 `journalctl --user -u mouse-gestures -f`
里识别成了什么，把出现最多的那个串写进配置。**优先选长的**——长手势的阈值相对更严，
误触发更少。

## 默认手势

| 手势 | 动作 | 发送 |
|---|---|---|
| `←` 左 | 后退 | `Alt+Left` |
| `→` 右 | 前进 | `Alt+Right` |
| `↑` 上 | 新建标签页 | `Ctrl+T` |
| `↓` 下 | 关闭标签页 | `Ctrl+W` |
| `↓→` L 形 | 关闭窗口/软件 | `Alt+F4` |
| `↗` 右上斜 | 最大化/取消最大化 | `Alt+F10` |
| `↙` 左下斜 | 最小化 | `Super+H` |
| `↖` 左上斜 | 活动概览（看所有窗口） | `Super` |
| `C` 形（`7L1D3R`） | 新开 Chrome 窗口 | `google-chrome --new-window` |

C 形从右上起笔，向左划过去再兜到右下——开口朝右的那个 C。

最大化/最小化/活动概览用的是 GNOME 默认键位，无需改系统设置。其他桌面环境按需调整。

---

## 安装

```bash
# 1. 依赖（唯一需要 root 的两步）
sudo apt install -y python3-evdev
sudo usermod -aG input $USER
```

**然后注销重新登录**——组成员变更只在新会话生效，`newgrp` 只对单个 shell 有效。

```bash
# 2. 安装
git clone https://github.com/<your-name>/mouse-gestures.git
cd mouse-gestures
./install.sh
```

`install.sh` 会检查前提、安装三个文件、启用服务并设为开机自启：

| 文件 | 作用 |
|---|---|
| `~/.local/bin/mouse-gestures` | 主程序 |
| `~/.config/mouse-gestures.json` | 手势配置（已存在则不覆盖） |
| `~/.config/systemd/user/mouse-gestures.service` | 开机自启服务 |

卸载：`./uninstall.sh`（加 `--purge` 连配置一起删）

## 配置

编辑 `~/.config/mouse-gestures.json`，然后 `systemctl --user restart mouse-gestures`。

```json
{
  "device": "auto",
  "trigger_button": "BTN_RIGHT",
  "min_segment": 40,
  "min_total": 60,
  "gestures": {
    "L":  {"action": "key:alt+left", "desc": "后退"},
    "3":  {"action": "cmd:snipaste", "desc": "截图"}
  }
}
```

| 字段 | 说明 |
|---|---|
| `device` | `auto` 自动挑选，或填 `mouse-gestures --list-devices` 给出的路径。**优先用 `/dev/input/by-id/` 下的路径**——`event*` 编号会随插拔变化 |
| `trigger_button` | 触发键，evdev 名称。`BTN_RIGHT` / `BTN_MIDDLE` / `BTN_SIDE` / `BTN_EXTRA` |
| `min_segment` | 单段最小位移（px），小于此值的抖动被忽略 |
| `min_total` | 这一笔的**最远距离**阈值（离起点最远的那个点有多远），小于此值判定为普通点击并补发原按键。用最远距离而不是终点净位移，`UD`/`LR`/画圈这类终点回到起点的手势才不会被误当成普通右键 |
| `fuzzy_match` | 是否启用模糊匹配（默认 `true`）。绑了大量相似手势、希望严格区分时设 `false` |
| `gestures` | 手势串 → 动作。`key:<组合键>` 注入快捷键，`cmd:<命令>` 执行 shell 命令 |

组合键写法：`ctrl+shift+t`、`alt+f4`、`super+h`、`alt+left`。修饰键支持
`ctrl` / `alt` / `shift` / `super`。

## 命令行

```bash
mouse-gestures                    # 前台运行（调试用，Ctrl+C 退出）
mouse-gestures --list-devices     # 列出可用鼠标设备
mouse-gestures --doctor           # 检查运行前提，给出修复命令
mouse-gestures --config PATH      # 指定配置文件
```

---

## 排障

**先跑 `mouse-gestures --doctor`**，多数问题它会直接指出修复命令。

### 启动报 `Device or resource busy`（errno 16）

有别的程序抢先独占了鼠标。**最常见的元凶是 [keyd](https://github.com/rvaiya/keyd)**——
它的 `[ids]` 段若为 `*`，会连鼠标一起接管（很多人装它只是为了改键盘的
CapsLock/Esc，没意识到它把鼠标也抓了）。

查出鼠标的 vid:pid：

```bash
python3 -c "
import evdev
d = evdev.InputDevice('/dev/input/by-id/你的鼠标-event-mouse')
print('%04x:%04x' % (d.info.vendor, d.info.product))"
```

在 `/etc/keyd/default.conf` 的 `[ids]` 段加一行 `-` 前缀排除它：

```ini
[ids]
*
-046d:409f    # 排除这只鼠标，让 mouse-gestures 接管

[main]
capslock = esc
esc = capslock
```

然后 `sudo systemctl restart keyd`。

同类冲突源还有 input-remapper、interception-tools。

### 重启后手势失效

服务挂在 `graphical-session.target` 下，某些桌面环境不会可靠地激活这个 target。
确认：

```bash
systemctl --user is-active mouse-gestures
```

若为 `inactive`，把 service 文件的 `WantedBy` 改成 `default.target`，
然后 `systemctl --user daemon-reload && systemctl --user reenable mouse-gestures`。

### 右键菜单弹不出来 / 手势总被当成普通右键

调 `min_total`：画不动就调小，误触发就调大。看日志能知道每次识别成了什么：

```bash
journalctl --user -u mouse-gestures -f
```

### 手势画了没反应

日志会打出识别成了什么，以及模糊匹配把它归到了哪个手势：

```
[手势] 7L1D3 (左上左左下下右下) ≈ L1D3 -> C 形 —— 新开 Chrome 窗口 (cmd:google-chrome --new-window)
[手势] 9U7L1D3R (...) —— 未绑定
```

打「未绑定」说明画出来的串离所有已绑手势都太远。段数越多越不稳，
三段以上的手势（如 `DRU`）和闭合图形（画方框）实测命中率只有个位数，不建议绑。

### 鼠标彻底不响应了

守护进程崩溃时可能没释放独占。

```bash
systemctl --user stop mouse-gestures
```

程序有 `finally` 兜底会 `ungrab`，正常退出不会留下这种状态；真卡住了拔插一次鼠标也能恢复。

---

## 开发

```bash
python3 tests/test_recognize.py       # 单元测试，不需要真实设备
```

测试覆盖 8 方向扇区映射、L 形折线不被压成单段斜向、抖动返回 `None`、
同方向合并、往返手势（`UD`/`LR`/画圈）能过 `min_total` 这道闸、斜向按真实长度
而非切比雪夫距离度量、八种 L 形的圆角画法都还原成两段、平滑只动中间段且长度守恒、
模糊匹配的阈值先于平局生效、按动作去歧义、真机采集的 8 种 C 形写法都归到规范式、
按键组合解析、`--doctor` 的守护进程识别。
改识别逻辑前先跑一遍——扇区映射写错会让所有手势错乱。

## 兼容性

| 项 | 说明 |
|---|---|
| 显示服务器 | Wayland ✓ X11 ✓（不依赖显示服务器） |
| 桌面环境 | 任意。默认手势里的最大化/最小化键位是 GNOME 的，其他 DE 需改配置 |
| 发行版 | 任意有 `python3-evdev` 和 `/dev/uinput` 的 Linux |
| 开发环境 | Ubuntu 26.04 + GNOME/Wayland + Logitech G502 X |

## License

MIT

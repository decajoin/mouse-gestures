#!/usr/bin/env bash
# 安装 mouse-gestures 到当前用户。不需要 root,除了下面明确提示的两条命令。
set -euo pipefail

BIN_DIR="$HOME/.local/bin"
CONFIG="$HOME/.config/mouse-gestures.json"
UNIT_DIR="$HOME/.config/systemd/user"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }

say "==> 检查依赖"

if ! python3 -c 'import evdev' 2>/dev/null; then
    warn "缺少 python3-evdev。请先执行(需要 root):"
    echo "    sudo apt install -y python3-evdev"
    exit 1
fi
echo "  python3-evdev  ✓"

if ! id -nG | tr ' ' '\n' | grep -qx input; then
    warn "当前用户不在 input 组 —— 读 /dev/input/* 的前提。请执行:"
    echo "    sudo usermod -aG input \$USER"
    echo "  然后【注销重新登录】(组变更只在新会话生效),再跑一次本脚本。"
    exit 1
fi
echo "  input 组       ✓"

say "==> 安装文件"

install -Dm755 "$SRC/mouse-gestures" "$BIN_DIR/mouse-gestures"
echo "  $BIN_DIR/mouse-gestures"

if [[ -e "$CONFIG" ]]; then
    echo "  $CONFIG  (已存在,保留不覆盖)"
else
    install -Dm644 "$SRC/config/mouse-gestures.example.json" "$CONFIG"
    echo "  $CONFIG  (由示例创建)"
fi

install -Dm644 "$SRC/config/mouse-gestures.service" "$UNIT_DIR/mouse-gestures.service"
echo "  $UNIT_DIR/mouse-gestures.service"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "  注意: $BIN_DIR 不在 PATH 里,直接敲 mouse-gestures 会找不到命令" ;;
esac

say "==> 检查运行前提"
"$BIN_DIR/mouse-gestures" --doctor --config "$CONFIG" || true

say "==> 启用服务"
systemctl --user daemon-reload
systemctl --user enable mouse-gestures
# 用 restart 而不是 start —— 重复安装时要让新版本真正生效
systemctl --user restart mouse-gestures

sleep 2
if systemctl --user is-active --quiet mouse-gestures; then
    say "完成 —— 服务已运行并设为开机自启。按住右键画手势试试。"
    echo "  查看日志: journalctl --user -u mouse-gestures -f"
    echo "  临时停用: systemctl --user stop mouse-gestures"
else
    warn "服务启动失败,日志如下:"
    journalctl --user -u mouse-gestures --no-pager -n 20
    exit 1
fi

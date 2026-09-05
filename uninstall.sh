#!/usr/bin/env bash
# 卸载 mouse-gestures。默认保留配置文件,加 --purge 一并删除。
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

systemctl --user disable --now mouse-gestures 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/mouse-gestures.service"
systemctl --user daemon-reload
rm -f "$HOME/.local/bin/mouse-gestures"

if (( PURGE )); then
    rm -f "$HOME/.config/mouse-gestures.json"
    echo "已卸载(含配置文件)。"
else
    echo "已卸载。配置文件保留在 ~/.config/mouse-gestures.json,加 --purge 可一并删除。"
fi

#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
  unit_dir=/etc/systemd/system
  ctl() { systemctl "$@"; }
else
  unit_dir="$HOME/.config/systemd/user"
  ctl() { systemctl --user "$@"; }
fi
ctl disable --now proxylens-agent.service 2>/dev/null || true
rm -f "$unit_dir/proxylens-agent.service"
ctl daemon-reload
rm -rf "$HOME/.local/share/proxylens"
echo "ProxyLens Agent 已停止并卸载。"

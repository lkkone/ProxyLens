#!/bin/sh
set -eu
umask 077
command -v systemctl >/dev/null || { echo "此安装包需要用户级 systemd。"; exit 1; }
if [ "$(id -u)" = 0 ]; then
  unit_dir=/etc/systemd/system
  target=multi-user.target
  ctl() { systemctl "$@"; }
else
  unit_dir="$HOME/.config/systemd/user"
  target=default.target
  ctl() { systemctl --user "$@"; }
  ctl show-environment >/dev/null || { echo "当前用户的 systemd 未运行，请先登录该用户会话。"; exit 1; }
fi
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$source_dir/agent.json" ] && [ -f "$source_dir/proxylens-agent" ] || { echo "请先解压完整安装包。"; exit 1; }
install_dir="$HOME/.local/share/proxylens"
mkdir -p "$install_dir" "$unit_dir"
ctl stop proxylens-agent.service 2>/dev/null || true
cp "$source_dir/proxylens-agent" "$install_dir/proxylens-agent.new"
chmod 700 "$install_dir/proxylens-agent.new"
mv -f "$install_dir/proxylens-agent.new" "$install_dir/proxylens-agent"
cp "$source_dir/agent.json" "$install_dir/agent.json"
chmod 600 "$install_dir/agent.json"
cat > "$unit_dir/proxylens-agent.service" <<'SERVICE'
[Unit]
Description=ProxyLens local proxy agent
After=network-online.target
[Service]
ExecStart="%h/.local/share/proxylens/proxylens-agent" -config "%h/.local/share/proxylens/agent.json"
Restart=always
RestartSec=30
NoNewPrivileges=true
Environment=HOME=%h
[Install]
WantedBy=default.target
SERVICE
if [ "$(id -u)" = 0 ]; then
  sed -i "s/WantedBy=default.target/WantedBy=$target/" "$unit_dir/proxylens-agent.service"
fi
ctl daemon-reload
ctl enable --now proxylens-agent.service
if [ "$(id -u)" = 0 ]; then
  echo "安装完成：Agent 已在后台运行，服务器启动时自动运行。"
  echo "日志：journalctl -u proxylens-agent -f"
else
  echo "安装完成：Agent 已在后台运行，用户会话启动时自动运行。"
  echo "日志：journalctl --user -u proxylens-agent -f"
  echo "服务器需要退出登录后持续运行时，请管理员为此用户开启 systemd lingering。"
fi

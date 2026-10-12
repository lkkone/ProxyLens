#!/bin/bash
set -euo pipefail
[ "$(id -u)" != 0 ] || { echo "请以当前登录用户运行，不要使用 sudo。"; exit 1; }
launchctl bootout "gui/$(id -u)/com.proxylens.agent" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.proxylens.agent.plist"
rm -rf "$HOME/Library/Application Support/ProxyLens"
echo "ProxyLens Agent 已停止并卸载。"

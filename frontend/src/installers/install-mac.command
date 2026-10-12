#!/bin/bash
set -euo pipefail
umask 077
if [ "$(id -u)" = 0 ]; then
  echo "请以当前登录用户运行，不要使用 sudo。"
  exit 1
fi
source_dir="$(cd "$(dirname "$0")" && pwd)"
install_dir="$HOME/Library/Application Support/ProxyLens"
plist="$HOME/Library/LaunchAgents/com.proxylens.agent.plist"
label="com.proxylens.agent"
[ -f "$source_dir/agent.json" ] && [ -f "$source_dir/proxylens-agent" ] || { echo "请先解压完整安装包，再运行安装脚本。"; exit 1; }
mkdir -p "$install_dir" "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
cp "$source_dir/proxylens-agent" "$install_dir/proxylens-agent.new"
chmod 700 "$install_dir/proxylens-agent.new"
mv -f "$install_dir/proxylens-agent.new" "$install_dir/proxylens-agent"
cp "$source_dir/agent.json" "$install_dir/agent.json"
chmod 600 "$install_dir/agent.json"
# Only the downloaded agent needs execution permission; no system directories are used.
xattr -d com.apple.quarantine "$install_dir/proxylens-agent" 2>/dev/null || true
xml_escape() { printf '%s' "$1" | sed -e 's/\&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }
path_xml="$(xml_escape "$install_dir")"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$label</string>
<key>ProgramArguments</key><array><string>$path_xml/proxylens-agent</string><string>-config</string><string>$path_xml/agent.json</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>30</integer>
<key>StandardOutPath</key><string>$path_xml/agent.log</string>
<key>StandardErrorPath</key><string>$path_xml/agent.log</string>
</dict></plist>
PLIST
plutil -lint "$plist" >/dev/null
launchctl enable "gui/$(id -u)/$label"
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "安装完成：Agent 已静默运行，登录后自动启动；关闭终端不会停止上报。"
echo "日志：$install_dir/agent.log"

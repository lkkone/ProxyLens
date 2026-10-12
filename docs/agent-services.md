# 设备端后台启动

先前台运行确认面板收到上报，再设置后台启动。Agent 应以运行 Clash Verge 的同一用户启动，才能找到它的配置、Socket 或命名管道。

## macOS：LaunchAgent

将二进制与配置放在 `~/Library/Application Support/ProxyLens/`。下面以 Apple 芯片为例，Intel 把文件名里的 `arm64` 改成 `amd64`。

创建 `~/Library/LaunchAgents/com.proxylens.agent.plist`，将其中 `/Users/YOUR_USER` 替换为你的实际用户目录：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.proxylens.agent</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOUR_USER/Library/Application Support/ProxyLens/proxylens-agent-darwin-arm64</string>
    <string>-config</string>
    <string>/Users/YOUR_USER/Library/Application Support/ProxyLens/agent.json</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>/Users/YOUR_USER/Library/Application Support/ProxyLens/agent.log</string>
  <key>StandardErrorPath</key><string>/Users/YOUR_USER/Library/Application Support/ProxyLens/agent.log</string>
</dict></plist>
```

```sh
chmod 600 "$HOME/Library/Application Support/ProxyLens/agent.json"
chmod +x "$HOME/Library/Application Support/ProxyLens/proxylens-agent-darwin-arm64"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.proxylens.agent.plist"
```

停止并取消本次加载：

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.proxylens.agent.plist"
```

这是用户登录时的服务。设备睡眠或用户退出后不能保证采集，按“允许离线”策略处理。首次运行遇到系统安全拦截时，在“系统设置 → 隐私与安全性”允许打开你下载的 Agent，然后再配置自启动。

## Linux：用户级 systemd

将文件放在 `~/.local/share/proxylens/`，创建 `~/.config/systemd/user/proxylens-agent.service`：

```ini
[Unit]
Description=ProxyLens local proxy agent
After=network-online.target

[Service]
ExecStart=%h/.local/share/proxylens/proxylens-agent-linux-amd64 -config %h/.local/share/proxylens/agent.json
Restart=always
RestartSec=30
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

```sh
chmod 600 ~/.local/share/proxylens/agent.json
chmod +x ~/.local/share/proxylens/proxylens-agent-linux-amd64
systemctl --user daemon-reload
systemctl --user enable --now proxylens-agent
journalctl --user -u proxylens-agent -f
```

常驻服务器可由管理员为该用户开启 lingering：`sudo loginctl enable-linger YOUR_USER`。Mihomo 若使用其他用户或自定义路径，需明确配置 `clash_config_path` / `controller_url`，不要把控制接口改成公网监听。

停止：`systemctl --user disable --now proxylens-agent`。

## Windows：任务计划程序

把二进制与配置放在用户目录下，例如 `C:\Users\YOUR_USER\ProxyLens\`。打开“任务计划程序” → “创建任务”：

1. 名称：`ProxyLens Agent`，选择当前运行 Clash Verge 的用户。
2. 触发器：“登录时”。
3. 操作：“启动程序”，程序填写 Agent 的完整路径。
4. 参数：`-config "C:\Users\YOUR_USER\ProxyLens\agent.json"`。
5. 起始于：`C:\Users\YOUR_USER\ProxyLens`。
6. 设置：失败时每 1 分钟重启，取消“运行超过指定时间则停止”。办公笔记本按需求取消仅交流电启动的限制。

手动运行任务后在面板确认上报。任务结束即可停止采集。ARM Windows 下载 `windows-arm64.exe`；Windows 代理设置按运行 Agent 的用户读取。

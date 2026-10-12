# 设备端后台运行

在管理页选择设备平台，下载并解压安装包，按页面提示执行安装脚本。桌面安装无需管理员权限，不把 Agent 放到系统目录。脚本自动放好 Agent 与配置、注册后台服务并立即启动；重复安装会替换此用户原来的 Agent 与设备配置。

| 平台 | 安装 | 自动启动 | 安装位置与日志 |
| --- | --- | --- | --- |
| macOS | 页面的一条 `bash` 命令，或双击 `install.command` | LaunchAgent，登录时启动 | `~/Library/Application Support/ProxyLens/`；日志 `agent.log` |
| Windows | 双击 `install.cmd` | 当前用户的隐藏计划任务 | `%LOCALAPPDATA%\ProxyLens`；日志 `agent.log`、`agent-error.log` |
| Linux | `sh install.sh` | 用户级 systemd | `~/.local/share/proxylens/`；日志 `journalctl --user -u proxylens-agent -f` |

macOS 安装包默认解压到“下载”目录，页面命令使用这个位置；自定义下载位置时，将 `install.command` 的实际路径传给 `bash`。脚本会给 Agent 设置执行权限，配置文件仅当前用户可读写。安装完成后可删除下载的安装包，建议妥善保留卸载脚本。

Windows 安装脚本用当前用户注册任务，不需要输入账号密码；脚本仅在此次启动时使用 PowerShell 的 ExecutionPolicy Bypass，不修改系统策略。企业策略可能禁止注册计划任务。macOS 无图形登录会话、Linux 无用户级 systemd 时，安装脚本会显示明确错误。

## 查看与重启

macOS：

```sh
launchctl print "gui/$(id -u)/com.proxylens.agent"
launchctl kickstart -k "gui/$(id -u)/com.proxylens.agent"
tail -n 50 "$HOME/Library/Application Support/ProxyLens/agent.log"
```

Windows：在任务计划程序中找到 `ProxyLens Agent`，可停止或运行。

Linux：

```sh
systemctl --user status proxylens-agent
systemctl --user restart proxylens-agent
journalctl --user -u proxylens-agent -f
```

Linux 服务器若需退出登录后持续采集，由管理员执行 `sudo loginctl enable-linger YOUR_USER`。桌面系统在重启并登录后恢复采集，关机、休眠或用户退出期间不能保证上报。

## 卸载

运行安装包内的 `uninstall.command`（macOS，可用 `bash` 执行）、`uninstall.cmd`（Windows）或 `sh uninstall.sh`（Linux）。停止后台服务并删除本用户的 Agent、配置与日志。云端设备及历史保留，需在管理页另行删除。

Linux 已使用 root 登录的服务器可直接执行安装脚本，注册系统级服务并在开机时启动；无需另行使用 sudo。仍应与 Mihomo 使用同一运行用户。root 安装日志使用 `journalctl -u proxylens-agent -f`。

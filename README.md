# ProxyLens

多设备代理状态面板，支持 macOS、Windows、Linux 上的 Clash Verge / Mihomo。首页公开展示，`/admin` 登录管理；服务端为 Vue 3 + Python + SQLite，设备通过 Go Agent 主动上报。

## Docker Compose 部署

服务器安装 Docker 和 Compose，准备 `compose.deploy.yaml`、`.env` 和 amd64 镜像文件：

```sh
docker load -i proxylens-0.1.0-linux-amd64.tar.gz
cp .env.example .env
# 编辑 .env 后启动
docker compose -f compose.deploy.yaml up -d
```

`.env` 示例：

```dotenv
PROXYLENS_IMAGE=proxylens:0.1.0-amd64
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-this-password
PUBLIC_URL=https://proxy.example.com
BIND_ADDRESS=127.0.0.1
PORT=8080
COOKIE_SECURE=true
RETENTION_DAYS=30
```

将 HTTPS 反向代理指向 `http://127.0.0.1:8080`，访问域名首页或 `/admin`。`PUBLIC_URL` 用作设备配置中的默认上报地址；域名和 HTTPS 由自己的反向代理配置。

账号密码必须通过环境变量设置，密码至少 8 位。修改 `.env` 后重新执行 `up -d` 即生效，旧管理会话撤销，设备凭证保持有效。示例密码请自行替换。

本地 HTTP 调试使用 `PUBLIC_URL=http://localhost:8080`、`COOKIE_SECURE=false`。需要直接从其他机器访问时设置 `BIND_ADDRESS=0.0.0.0`；其他设备的上报地址应填服务器地址。

## 接入设备

1. 登录 `/admin`，点击“接入设备”，填写名称、分组及可选备注。偶尔在线的电脑可勾选“允许离线”。
2. 选择系统和架构，确认上报地址，下载并解压**安装包**。Agent、设备凭证和安装脚本已包含在内。
3. macOS 在终端执行页面给出的**一条命令**；Windows 双击 `install.cmd`；Linux 执行 `install.sh`。使用运行 Clash Verge 的同一用户，不需要 sudo，也不需要手动移动文件。

安装后 Agent 静默运行，关闭终端不会停止上报，重启并登录后自动启动。重新运行安装脚本可更新同一用户的 Agent 与配置；运行安装包里的 `uninstall` 脚本可停止并移除它。每个系统用户安装一个 Agent。

macOS 使用 LaunchAgent；Windows 使用当前用户的隐藏计划任务；Linux 使用用户级 systemd，root 安装时自动使用系统级服务。Linux 常驻服务器若需退出登录后继续运行，由管理员为该用户开启 lingering。电脑休眠和用户退出时，桌面代理客户端可能也停止运行。

Agent 自动识别 Clash Verge 本地控制接口，支持 Unix Socket、Windows 命名管道和本地 TCP。通常无需高级设置，也无需开放设备入站端口。远程上报使用 HTTPS；可信局域网 HTTP 调试需启用 `allow_http`。配置在浏览器内打包，本地控制接口密钥不提交到服务端。

具体安装位置和日志见 [设备端服务配置](docs/agent-services.md)。重新生成配置会撤销旧设备凭证，需下载新安装包并再次安装。

## 监测规则

- 默认每 30 秒上报、每 300 秒测试当前节点延迟，其他节点使用内核已有测速记录。策略修改在下一次上报后下发。
- 默认绿 ≤300 ms、黄 ≤1000 ms、红 >1000 ms 或代理异常；阈值可按设备调整。
- 历史条展示最近 5 小时内最多 60 个真实检测点，悬停显示检测时间；同一次节点延迟结果重复上报不会追加格子，检测结果生成后不改写，不合并时间段、不填充空格。在线但未获得有效延迟或直连为空心格。
- 超过 `max(90 秒, 3 × 上报间隔)` 无上报视为离线。“允许离线”的设备不触发总状态异常。
- 机场名称来自代理集合或当前订阅名称；流量和到期时间仅在内核提供时显示。规则模式下当前节点代表自动识别的主要策略组，负载均衡或链式代理可能没有唯一出口。

首页公开展示设备和节点信息；管理 API 需要登录。Agent 不上传订阅地址、节点密码或控制接口密钥。Windows 命名管道仍需真实 Windows 设备验证。

## 开发与构建

```sh
cp .env.example .env
# 编辑账号密码；本机开发镜像设置 PROXYLENS_IMAGE=proxylens:0.1.0
docker compose up -d --build

# 构建 amd64 镜像并导出
RELEASE_ARCH=amd64 docker compose -f compose.yaml -f compose.release.yaml build
mkdir -p dist
docker save proxylens:0.1.0-amd64 | gzip > dist/proxylens-0.1.0-linux-amd64.tar.gz
```

Docker 构建执行前端编译、Go 测试和静态检查，并包含六种系统/架构的 Agent。隔离集成测试：

```sh
docker compose -p proxylens-test -f compose.test.yaml run --rm test-api
docker compose -p proxylens-test -f compose.test.yaml run --rm test-storage
docker compose -p proxylens-test -f compose.test.yaml down -v
```

适配器与上报协议见 [架构说明](docs/architecture.md)。

## 维护

```sh
docker compose -f compose.deploy.yaml logs --tail=100 -f
docker compose -f compose.deploy.yaml down
```

数据保存在 `proxylens-data` 命名卷，重建容器不会丢失；部署环境不要执行 `down -v`。默认保留 30 天历史。

在线备份：

```sh
docker compose -f compose.deploy.yaml exec proxylens python -c "import sqlite3; a=sqlite3.connect('/data/proxylens.db'); b=sqlite3.connect('/data/backup.db'); a.backup(b); b.close(); a.close()"
docker compose -f compose.deploy.yaml cp proxylens:/data/backup.db ./proxylens-backup.db
```

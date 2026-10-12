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
2. 下载对应系统和架构的 Agent，以及 `agent.json`；确认上报地址，设备凭证自动生成。
3. 在运行 Clash Verge 的同一用户下启动 Agent。

```sh
# macOS Apple 芯片（Intel 使用 darwin-amd64）
chmod +x proxylens-agent-darwin-arm64
chmod 600 agent.json
./proxylens-agent-darwin-arm64 -config ./agent.json

# Linux x64
chmod +x proxylens-agent-linux-amd64
chmod 600 agent.json
./proxylens-agent-linux-amd64 -config ./agent.json
```

```powershell
# Windows x64
.\proxylens-agent-windows-amd64.exe -config .\agent.json
```

Agent 自动识别 Clash Verge 本地控制接口，支持 Unix Socket、Windows 命名管道和本地 TCP。未识别时在 `agent.json` 指定 `clash_config_path`，或设置 `controller_url` / `controller_secret`。无需开放设备入站端口。远程上报使用 HTTPS；可信局域网 HTTP 调试需启用 `allow_http`。

后台自启动见 [设备端服务配置](docs/agent-services.md)。重新生成配置会撤销旧设备凭证，需替换 `agent.json` 并重启 Agent。

## 监测规则

- 默认每 30 秒上报、每 300 秒测试当前节点延迟，其他节点使用内核已有测速记录。策略修改在下一次上报后下发。
- 默认绿 ≤300 ms、黄 ≤1000 ms、红 >1000 ms 或代理异常；阈值可按设备调整。
- 历史条覆盖最近 5 小时，每格 5 分钟取最差状态；无上报为灰色，在线但未获得有效延迟或直连为空心格。
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

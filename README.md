# ProxyLens

集中展示多台电脑与服务器上的 Clash Verge / Mihomo 代理状态。首页公开展示，管理操作只在 `/admin` 登录后开放。界面参考你自定义的 Uptime Kuma 状态页，采用 Vue 3、一行一台设备、柔和阴影和延迟历史条。

服务端运行在一个 Docker 镜像里，包含网页、API、SQLite 和六种平台的 Agent 下载。设备端是单文件 Agent，不需要 Docker、Python 或 Go。

## 本机开发运行

```sh
cp .env.example .env
docker compose up -d --build
```

默认访问 `http://localhost:8080`，管理入口 `http://localhost:8080/admin`。默认账号 `likaikai`，密码 `Aptech1!`。可用 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 设置首次初始化的账号密码；环境变量不会在每次重启时覆盖已有密码，后续修改使用下文的维护命令。后台左侧选择设备，右侧直接编辑或新增。

当前开发机的 8080 已有其他服务，因此已配置 `.env` 使用 **18790**。开发测试账号使用同样的默认值，管理员密码备份在 `.local/admin-password.txt`，测试 Agent 的配置、PID 和日志在 `.local/`，这些文件不进入镜像或 Git。

如果 Docker Hub 连接失败，可以使用构建参数指定镜像源，不用修改 Dockerfile：

```sh
docker compose build \
  --build-arg GO_IMAGE=docker.m.daocloud.io/library/golang:1.25-alpine \
  --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.13-alpine \
  --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
docker compose up -d --no-build
```

所有前端构建、Go 测试、静态检查和跨平台编译都在 Docker 构建阶段执行。

## 接入一台设备

1. 打开 `/admin`，点击“接入设备”，填写名称和分组。办公电脑勾选“允许离线”，常驻服务器不勾选。
2. 下载对应系统与 CPU 的 Agent，再下载 `agent.json`。通常只需确认**上报地址**；设备独立凭证已自动写入配置。
3. 将两个文件放在同一文件夹，运行面板给出的命令。

Apple Silicon Mac 示例：

```sh
chmod +x proxylens-agent-darwin-arm64
chmod 600 agent.json
./proxylens-agent-darwin-arm64 -config ./agent.json
```

Windows x64 示例（PowerShell）：

```powershell
.\proxylens-agent-windows-amd64.exe -config .\agent.json
```

Linux x64 示例：

```sh
chmod +x proxylens-agent-linux-amd64
chmod 600 agent.json
./proxylens-agent-linux-amd64 -config ./agent.json
```

Agent 自动读取当前用户的 Clash Verge 运行配置，支持 **本地 Unix Socket、Windows 命名管道和 TCP 控制接口**。不需要把 Clash 的 API 暴露到网络。若未识别，可在 `agent.json` 中指定 `clash_config_path`（运行中的 `clash-verge.yaml`），或填写 `controller_url` 与 `controller_secret`。自定义 Unix Socket / 命名管道分别使用 `controller_socket` / `controller_pipe`。

远程上报使用 HTTPS。本机 `localhost` 可使用 HTTP；可信局域网调试可在下载配置时勾选“允许 HTTP”，并将服务绑定到局域网可访问的地址。设备上的 `localhost` 指设备自身，其他设备不能使用本开发机的 localhost 地址。

后台自启动的 Linux systemd、macOS LaunchAgent 和 Windows 任务计划程序配置见 [设备端后台启动](docs/agent-services.md)。

## 首页和延迟历史

- `/`：公开展示设备名称、系统、模式、当前主要策略组节点、机场、延迟和历史。点击设备查看详情。不需要登录。
- `/admin`：管理员登录、添加/编辑/删除设备、下载 Agent、生成与撤销设备凭证、设置采样周期和颜色阈值。后台采用左侧设备列表、右侧编辑面板。
- 默认每 **30 秒**采集和上报，每 **300 秒**对当前节点执行一次 HTTPS 延迟测试。不会持续 Ping，不会主动对所有节点测速。
- 节点切换后清除旧延迟；最快每 60 秒测试一次，避免频繁切换造成探测风暴。关闭延迟探测后仍会继续采集设备、内核和策略组信息。
- **绿色**：延迟 ≤300 ms；**黄色**：301–1000 ms；**红色**：>1000 ms、探测失败或内核不可访问。阈值可按设备修改。
- **灰色**：该时间格没有设备上报。**空心格**：设备在线但缺少有效延迟，或直连模式。
- 每格 5 分钟，共最近 5 小时；有多次上报时取该格最差状态。没有历史的时间段也显示灰色，不会补造健康数据。
- 超过 `max(90 秒, 3 × 上报间隔)` 无上报，视为设备离线；仅凭失联无法判断是关机、休眠还是网络中断。“允许离线”设备不会导致总状态报异常。
- 规则模式中，主要策略组的节点不能代表所有应用出口；可手动指定主要策略组。负载均衡和链式代理可能没有唯一节点，此时不推测。
- 机场优先读取代理集合；没有集合时读取 Clash Verge 当前启用配置的名称。流量/到期仅在内核提供时显示，机场名称直接来自实际配置，不需要手动填写。
- 节点详情里的其他节点延迟来自 Mihomo 已有测速历史，标明采样时间，不代表 ProxyLens 刚刚测过。
- 系统代理读取 macOS 系统配置、Windows 当前用户代理设置或 GNOME 配置；无桌面的 Linux 可能为“未知”。它不是所有进程代理流量的证明。

## 云服务器部署：仅使用镜像

准备与服务器架构对应的镜像文件、`compose.deploy.yaml` 和 `.env`。服务器无需项目源码与编译环境。

```sh
# 普通 Intel/AMD 云服务器
docker load -i proxylens-0.1.0-linux-amd64.tar.gz
```

创建 `.env`：

```dotenv
PROXYLENS_IMAGE=proxylens:0.1.0-amd64
PUBLIC_URL=https://proxy.example.com
BIND_ADDRESS=127.0.0.1
PORT=8080
COOKIE_SECURE=true
ADMIN_USERNAME=likaikai
ADMIN_PASSWORD=Aptech1!
RETENTION_DAYS=30
```

```sh
docker compose -f compose.deploy.yaml up -d
```

将你的反向代理或服务器面板配置为：`https://proxy.example.com` → `http://127.0.0.1:8080`。设置好 HTTPS 后，打开 `/admin` 登录，再添加设备；设备只需要向该地址主动上报，不需要开放设备入站端口。

如果反向代理本身运行在另一个容器，`127.0.0.1` 是那个容器，不是宿主机。可将两者放到同一 Docker 网络，反代目标使用 `proxylens:8080`；或在宿主机运行反向代理。`PUBLIC_URL` 是配置下载时的默认上报地址，不会自动创建 DNS 或 HTTPS。

ARM64 服务器加载 `proxylens-0.1.0-linux-arm64.tar.gz`，将 `PROXYLENS_IMAGE` 改成 `proxylens:0.1.0-arm64`。

默认首页是公开的，因此设备与节点名称等展示信息可被访客读取。完整订阅地址、节点密码、控制接口密钥不在上报结构中，设备凭证只保存哈希，管理 API 和 Agent 下载需要管理员登录。

## 构建与导出云镜像

```sh
# amd64 云服务器镜像；前端与 Agent 构建使用本机架构，服务端为目标架构
RELEASE_ARCH=amd64 docker compose -f compose.yaml -f compose.release.yaml build
docker save proxylens:0.1.0-amd64 | gzip > proxylens-0.1.0-linux-amd64.tar.gz

# ARM64 云服务器镜像
RELEASE_ARCH=arm64 docker compose -f compose.yaml -f compose.release.yaml build
docker save proxylens:0.1.0-arm64 | gzip > proxylens-0.1.0-linux-arm64.tar.gz
```

## 运维

```sh
docker compose logs --tail=100 -f
docker compose restart
docker compose down
```

数据位于 `proxylens-data` 命名卷，普通重启/重建容器不会丢失。**不要使用 `down -v`，它会删除数据卷。** 默认保留 30 天历史，可设置 `RETENTION_DAYS`。

在线一致性备份（SQLite backup API，可同时继续上报）：

```sh
docker compose exec proxylens python -c "import sqlite3; a=sqlite3.connect('/data/proxylens.db'); b=sqlite3.connect('/data/backup.db'); a.backup(b); b.close(); a.close()"
docker compose cp proxylens:/data/backup.db ./proxylens-backup.db
```

忘记管理员密码时，在容器内交互重设：

```sh
docker compose exec proxylens python manage.py reset-password
```

重新生成设备配置会撤销旧凭证，需替换设备端 `agent.json` 并重启 Agent。编辑采集策略则在下次成功上报的回应里自动下发，无需替换配置。

## 验证与扩展

隔离的 API 集成测试不使用开发数据卷：

```sh
docker compose -p proxylens-test -f compose.test.yaml up -d --wait
docker compose -p proxylens-test -f compose.test.yaml run --rm test-api
docker compose -p proxylens-test -f compose.test.yaml run --rm test-storage
docker compose -p proxylens-test -f compose.test.yaml down -v
```

Agent 使用 `Adapter` 接口；当前注册 `mihomo`。新增适配器实现 `Collect`，输出统一、无凭证的 `Report`。上报协议为 `POST /api/v1/report`，Bearer 设备凭证，`schema_version=1`。服务端对字段做白名单处理，状态判定独立于适配器。协议说明见 [架构与上报](docs/architecture.md)。

第一版不包含远程切换节点、自动更新订阅或告警通知。macOS 已进行当前电脑的真实采集；Linux/Windows 已交叉编译并通过共享逻辑测试，Windows 命名管道仍需真实 Windows 设备验证。
# ProxyLens

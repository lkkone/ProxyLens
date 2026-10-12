# 架构与上报协议

```text
Clash Verge / Mihomo（设备本地）
  └─ Unix Socket / Windows Named Pipe / Loopback TCP
      └─ Go Agent · 30s 采集 · 300s 当前节点测试
          └─ HTTPS POST /api/v1/report（独立设备凭证）
              └─ Python HTTP API + SQLite（云服务器）
                  ├─ /api/status → Vue 公开展示页 /
                  └─ 管理 API → Vue 管理页 /admin（管理员会话）
```

## 模块

`frontend/src/App.vue` 管理公开/后台路由、设备操作与详情。`HeartbeatBar.vue` 展示时间格状态。样式与色彩独立，头像来自用户拥有的 Kuma 页面。

`server/app.py` 处理认证、版本化采集接口、设备生命周期、策略、历史与事件。SQLite 使用 WAL，事务保证首个管理员创建、凭证轮换与报告写入的原子性。所有历史保存在 Docker 命名卷，每小时清理超过保留期的数据。

`agent/main.go` 定义统一采集模型与适配器注册表。Mihomo 适配器递归解析策略组当前节点，从内核 API 的允许字段提取信息，不上传运行配置、订阅 URL、节点服务器地址或密码。

报告通过直接网络连接上报，不使用环境 HTTP_PROXY，防止代理故障导致监测递归。网络故障时指数退避，最长 5 分钟；设备后台服务负责异常退出重启。没有离线队列：断网期间不生成虚假的补报，历史为空灰格。

## 请求

```http
POST /api/v1/report
Authorization: Bearer <device-token>
Content-Type: application/json
```

```json
{
  "schema_version": 1,
  "adapter": "mihomo",
  "hostname": "my-computer",
  "os": "darwin",
  "arch": "arm64",
  "agent_version": "0.1.0",
  "core_version": "v1.x",
  "core_reachable": true,
  "mode": "rule",
  "tun_enabled": false,
  "system_proxy": "enabled",
  "primary_group": "节点选择",
  "selected_node": "香港 01",
  "airport": "订阅名称",
  "probe": {
    "ok": true,
    "delay_ms": 50,
    "at": 1791780000,
    "node": "香港 01",
    "target": "https://www.gstatic.com/generate_204",
    "error": ""
  },
  "groups": [],
  "providers": [],
  "nodes": []
}
```

设备身份由凭证决定，请求体中的 device_id 不被信任。报告最大 1MB，策略组最多 200 个、代理集合 100 个、节点 2000 个；凭证无效返回 401，协议或字段错误返回 400。服务器接收时间决定在线状态和历史归属；Agent 的 probe.at 标明真实测试时间。

回应包含 `policy`（上报周期、采样周期、启用状态、延迟阈值）。Agent 下次采集使用最新策略。HTTPS 探测目标当前固定为 gstatic generate_204，后续可独立扩展目标策略。

## 状态判定

先判设备是否失联，然后判内核、直连、采样有效性与延迟等级。采样必须与当前节点匹配，且时间不在未来 10 秒以外，也不能超过 `2 × probe_interval + 30 秒`。节点切换时 Agent 清除旧采样。

历史每格 5 分钟，记录该格已收到报告里的最差状态。无报告的格是灰色；失联判断有最多 3 个上报周期的宽限，不等同于精确的关机时间。延迟格基于最近一次有效测量，不会声称每个心跳都触发了网络测速。

公开 API 只提供已白名单化的展示数据，不包含凭证、设备备注或管理事件；管理 API 要求管理员 Cookie。账号密码登录，密码使用 scrypt，Cookie 为 HttpOnly/SameSite=Strict，云端 HTTPS 配置开启 Secure。写操作要求自定义请求头并验证 Origin，控制接口限定设备本地。

## 扩展边界

新的代理客户端通过适配器接入。新增适配器时同时扩展服务端的 adapter 允许列表；不把客户端原始配置直接塞进报告。若增加多租户、节点控制或大规模设备，需要独立授权模型、迁移机制和任务调度，不复用公开展示权限执行控制操作。

<script setup>
import { computed, onMounted, onUnmounted, ref, nextTick, watch } from "vue";
import { createFaviconBadge } from "./faviconBadge.js";
import HeartbeatBar from "./HeartbeatBar.vue";
import DeviceEditor from "./DeviceEditor.vue";
import { installFiles, zipFiles } from "./install-package.js";

const admin = location.pathname.replace(/\/$/, "") === "/admin";
document.title = admin ? "咸鱼的代理管理" : "咸鱼的代理状态";
const labels = {
  healthy: "低延迟",
  slow: "中等延迟",
  degraded: "高延迟",
  error: "代理异常",
  unknown: "待采样",
  direct: "直连",
  offline: "离线",
  pending: "待接入",
};
const devices = ref([]),
  now = ref(Date.now() / 1000),
  loading = ref(true),
  failure = ref(""),
  authenticated = ref(false),
  username = ref(""),
  password = ref(""),
  authError = ref(""),
  busy = ref(false),
  publicURL = ref("");
const dialog = ref(null),
  view = ref(""),
  active = ref(null),
  detailTab = ref("overview"),
  formError = ref(""),
  token = ref(""),
  enrollPolicy = ref({}),
  configURL = ref(""),
  controllerURL = ref(""),
  controllerSecret = ref(""),
  allowHTTP = ref(false),
  installTarget = ref("darwin-arm64"),
  notice = ref("");
const blank = () => ({
  name: "",
  group: "常驻设备",
  allow_offline: false,
  notes: "",
  report_interval: 30,
  probe_interval: 300,
  probe_enabled: true,
  green_delay_ms: 300,
  red_delay_ms: 1000,
});
const form = ref(blank());
document.documentElement.dataset.theme = matchMedia(
  "(prefers-color-scheme:dark)",
).matches
  ? "dark"
  : "light";
const editingId = ref(null);
const editingDevice = computed(
  () => devices.value.find((d) => d.id === editingId.value) || null,
);
async function api(path, method = "GET", data) {
  const r = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-ProxyLens-Request": "1" },
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(20000),
  });
  const b = await r.json();
  if (!r.ok) {
    if (r.status === 401 && admin && path != "/api/login")
      authenticated.value = false;
    throw new Error(b.error || "请求失败");
  }
  return b;
}
let refreshSequence = 0;
let appliedSequence = 0;
async function refresh() {
  const sequence = ++refreshSequence;
  try {
    const b = await api(
      admin && authenticated.value ? "/api/devices" : "/api/status",
    );
    if (sequence < appliedSequence) return;
    appliedSequence = sequence;
    devices.value = b.devices;
    now.value = b.server_time;
    publicURL.value = b.public_url || publicURL.value;
    if (view.value === "detail" && active.value) {
      active.value =
        devices.value.find((d) => d.id === active.value.id) || active.value;
    }
    failure.value = "";
  } catch (e) {
    if (sequence < appliedSequence) return;
    appliedSequence = sequence;
    failure.value = e.message;
    now.value = Date.now() / 1000;
  } finally {
    loading.value = false;
  }
}
async function init() {
  if (admin) {
    try {
      const a = await api("/api/auth");
      authenticated.value = a.authenticated;
    } catch (e) {
      authError.value = e.message;
    }
  }
  await refresh();
  if (admin && authenticated.value && devices.value.length)
    edit(devices.value[0]);
}
async function login() {
  busy.value = true;
  authError.value = "";
  try {
    await api("/api/login", "POST", {
      username: username.value,
      password: password.value,
    });
    password.value = "";
    authenticated.value = true;
    await refresh();
    if (devices.value.length) edit(devices.value[0]);
  } catch (e) {
    authError.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function logout() {
  await api("/api/logout", "POST");
  authenticated.value = false;
}
const groups = computed(() =>
  [...new Set(devices.value.map((d) => d.group))].map((name) => ({
    name,
    devices: devices.value.filter((d) => d.group === name),
  })),
);
function effectiveState(d) {
  return d.last_seen &&
    now.value - d.last_seen > Math.max(90, d.policy.report_interval * 3)
    ? "offline"
    : d.state;
}
const abnormalDevices = computed(() => devices.value.filter((d) =>
  ["error", "degraded"].includes(effectiveState(d)) ||
  (effectiveState(d) === "offline" && !d.allow_offline),
));
const faviconBadge = createFaviconBadge();
watch(() => abnormalDevices.value.length, (count) => faviconBadge.update(count), { immediate: true });
onUnmounted(() => faviconBadge.dispose());
const overall = computed(() => {
  if (!devices.value.length)
    return { state: "unknown", symbol: "○", text: "等待设备接入" };
  const errors = abnormalDevices.value;
  if (errors.length)
    return {
      state: "error",
      symbol: "!",
      text: `${errors.length} 台设备的代理需要关注`,
    };
  if (
    devices.value.some((d) =>
      ["slow", "unknown", "direct", "pending"].includes(effectiveState(d)),
    )
  )
    return { state: "slow", symbol: "!", text: "部分设备的代理状态待确认" };
  if (devices.value.some((d) => effectiveState(d) === "healthy"))
    return { state: "healthy", symbol: "✓", text: "在线设备的代理运行正常" };
  return { state: "offline", symbol: "○", text: "设备当前均已离线" };
});
const osName = (v) =>
  ({ darwin: "macOS", windows: "Windows", linux: "Linux" })[v] || "等待上报";
const modeName = (v) =>
  ({ rule: "规则", global: "全局", direct: "直连" })[v] || "—";
const time = (v) =>
  v ? new Date(v * 1000).toLocaleString("zh-CN", { hour12: false }) : "—";
const relative = (v) => {
  if (!v) return "尚未上报";
  const s = Math.max(0, Math.floor(now.value - v));
  return s < 60
    ? `${s} 秒前`
    : s < 3600
      ? `${Math.floor(s / 60)} 分钟前`
      : s < 86400
        ? `${Math.floor(s / 3600)} 小时前`
        : `${Math.floor(s / 86400)} 天前`;
};
const bytes = (v) =>
  v == null
    ? "未提供"
    : v >= 1073741824
      ? `${(v / 1073741824).toFixed(1)} GB`
      : `${(v / 1048576).toFixed(1)} MB`;
function delay(d) {
  const p = d.latest?.probe;
  return p?.ok &&
    p.node === d.latest.selected_node &&
    ["healthy", "slow", "degraded"].includes(effectiveState(d))
    ? `${p.delay_ms} ms`
    : "—";
}
function flash(s) {
  notice.value = s;
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => (notice.value = ""), 3000);
}
async function open(kind, d = null) {
  active.value = d;
  view.value = kind;
  formError.value = "";
  await nextTick();
  dialog.value.showModal();
}
function close() {
  dialog.value?.close();
  view.value = "";
  token.value = "";
  controllerSecret.value = "";
}
function details(d) {
  detailTab.value = "overview";
  open("detail", d);
}
function edit(d = null) {
  editingId.value = d?.id || null;
  form.value = d
    ? {
        ...blank(),
        ...d.policy,
        name: d.name,
        group: d.group,
        notes: d.notes || "",
        allow_offline: d.allow_offline,
      }
    : blank();
  formError.value = "";
}
async function saveDevice() {
  busy.value = true;
  formError.value = "";
  try {
    const d = editingDevice.value;
    const r = await api(
      d ? `/api/devices/${d.id}` : "/api/devices",
      d ? "PATCH" : "POST",
      form.value,
    );
    await refresh();
    if (d) {
      flash("设置已保存");
    } else {
      editingId.value = r.id;
      token.value = r.token;
      enrollPolicy.value = r.policy;
      configURL.value = publicURL.value || location.origin;
      controllerURL.value = "";
      controllerSecret.value = "";
      allowHTTP.value = false;
      await open("enroll", { id: r.id, name: form.value.name });
    }
  } catch (e) {
    formError.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function removeDevice() {
  if (
    !editingDevice.value ||
    !confirm(`删除 ${editingDevice.value.name} 及其全部历史数据？`)
  )
    return;
  try {
    await api(`/api/devices/${editingDevice.value.id}`, "DELETE");
    await refresh();
    edit(devices.value[0] || null);
  } catch (e) {
    formError.value = e.message;
  }
}
async function rotate() {
  if (!confirm("重新生成会立即撤销旧设备凭证。继续？")) return;
  try {
    const d = editingDevice.value || active.value;
    const r = await api(`/api/devices/${d.id}/token`, "POST");
    token.value = r.token;
    enrollPolicy.value = r.policy;
    configURL.value = publicURL.value || location.origin;
    controllerURL.value = "";
    controllerSecret.value = "";
    await open("enroll", d);
  } catch (e) {
    formError.value = e.message;
  }
}
const targets = [
  ["darwin-arm64", "Mac Apple 芯片"],
  ["darwin-amd64", "Mac Intel"],
  ["windows-amd64", "Windows x64"],
  ["windows-arm64", "Windows ARM"],
  ["linux-amd64", "Linux x64"],
  ["linux-arm64", "Linux ARM"],
];
const binary = (t) =>
  `proxylens-agent-${t}${t.startsWith("windows") ? ".exe" : ""}`;
const packageBusy = ref(false);
const runCommand = computed(() => {
  const directory = `proxylens-${installTarget.value}`;
  if (installTarget.value.startsWith("windows"))
    return "解压后双击 install.cmd";
  if (installTarget.value.startsWith("darwin"))
    return `bash "$HOME/Downloads/${directory}/install.command"`;
  return `sh "$HOME/Downloads/${directory}/install.sh"`;
});
function deviceConfig() {
  const raw = configURL.value.replace(/\/$/, "");
  const u = new URL(raw);
  if (
    !["http:", "https:"].includes(u.protocol) ||
    u.username ||
    u.password ||
    u.search ||
    u.hash ||
    u.pathname !== "/"
  )
    throw new Error("请输入完整的服务根地址");
  if (
    u.protocol === "http:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(u.hostname) &&
    !allowHTTP.value
  )
    throw new Error("远程地址使用 HTTPS；局域网调试需勾选允许 HTTP");
  return {
    server_url: raw,
    token: token.value,
    adapter: "mihomo",
    controller_url: controllerURL.value.trim(),
    controller_secret: controllerSecret.value,
    allow_http: allowHTTP.value,
    ...enrollPolicy.value,
  };
}
function saveDownload(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function downloadConfig() {
  try {
    saveDownload(
      new Blob([JSON.stringify(deviceConfig(), null, 2) + "\n"], {
        type: "application/json",
      }),
      "agent.json",
    );
    flash("配置已下载");
    formError.value = "";
  } catch (e) {
    formError.value = e.message;
  }
}
async function downloadPackage() {
  packageBusy.value = true;
  formError.value = "";
  try {
    const config = deviceConfig();
    const target = installTarget.value;
    const response = await fetch("/downloads/" + binary(target), {
      signal: AbortSignal.timeout(120000),
    });
    if (!response.ok) throw new Error("Agent 下载失败，请重新登录后重试");
    const bytes = new Uint8Array(await response.arrayBuffer());
    saveDownload(
      zipFiles(installFiles(target, config, bytes)),
      `proxylens-${target}.zip`,
    );
    flash("安装包已下载，解压后即可安装");
  } catch (e) {
    formError.value = e.message;
  } finally {
    packageBusy.value = false;
  }
}
async function copyInstallCommand() {
  try {
    await navigator.clipboard.writeText(runCommand.value);
    flash("安装命令已复制");
  } catch {
    flash("请选中并复制安装命令");
  }
}

let timer;
onMounted(() => {
  init();
  // Keep the tab badge current even when the dashboard is in the background.
  timer = setInterval(refresh, 10000);
});
onUnmounted(() => clearInterval(timer));
</script>

<template>
  <main v-if="admin && !authenticated" class="login panel">
    <img src="/rocket-avatar.png" alt="" class="avatar" />
    <h1>咸鱼的代理管理</h1>
    <form @submit.prevent="login">
      <label
        >账号<input
          v-model="username"
          type="text"
          autocomplete="username"
          maxlength="200"
          required
          placeholder="账号" /></label
      ><label
        >密码<input
          v-model="password"
          type="password"
          autocomplete="current-password"
          maxlength="1024"
          required
          placeholder="密码" /></label
      ><button class="btn primary" :disabled="busy">
        {{ busy ? "正在登录…" : "登录" }}
      </button>
      <p class="form-error" role="alert">{{ authError }}</p>
    </form>
    <a href="/">返回展示页</a>
  </main>
  <main v-else class="page" :class="{ 'admin-page': admin }">
    <div v-if="admin" class="admin-toolbar">
      <a href="/">← 展示页</a><button class="btn" @click="logout">退出</button>
    </div>
    <header class="page-title">
      <img src="/rocket-avatar.png" class="avatar" alt="" />
      <h1>{{ admin ? "咸鱼的代理管理" : "咸鱼的代理状态" }}</h1>
    </header>
    <div v-if="failure" class="connection-error" role="alert">
      连接中断，正在展示上次收到的数据。
    </div>
    <template v-if="admin"
      ><div class="admin-layout">
        <aside class="device-sidebar panel">
          <div class="sidebar-inner">
            <button class="btn add-device" @click="edit()">＋ 接入设备</button>
            <div class="sidebar-scroll">
              <section
                v-for="group in groups"
                :key="group.name"
                class="sidebar-group"
              >
                <h3>{{ group.name }}</h3>
                <button
                  v-for="d in group.devices"
                  :key="d.id"
                  class="sidebar-device"
                  :class="[effectiveState(d), { selected: editingId === d.id }]"
                  @click="edit(d)"
                >
                  <span class="status-dot"></span
                  ><span class="sidebar-name"
                    >{{ d.name
                    }}<small>{{ labels[effectiveState(d)] }}</small></span
                  ><span class="sidebar-delay">{{ delay(d) }}</span>
                </button>
              </section>
              <p v-if="!devices.length" class="hint sidebar-empty">暂无设备</p>
            </div>
          </div>
        </aside>
        <DeviceEditor
          :form="form"
          :device="editingDevice"
          :busy="busy"
          :error="formError"
          @save="saveDevice"
          @delete="removeDevice"
          @config="rotate"
          @detail="details(editingDevice)"
        /></div
    ></template>
    <template v-else
      ><section class="overall panel" :class="overall.state" aria-live="polite">
        <span class="overall-icon">{{ overall.symbol }}</span>
        <h2>{{ loading ? "正在获取设备状态…" : overall.text }}</h2>
      </section>
      <section v-if="!loading && !devices.length" class="empty panel">
        <p>尚未接入设备。</p>
      </section>
      <section v-for="group in groups" :key="group.name" class="group">
        <h2 class="group-title">{{ group.name }}</h2>
        <div class="device-list panel">
          <article
            v-for="d in group.devices"
            :key="d.id"
            class="device"
            :class="effectiveState(d)"
          >
            <div class="device-info">
              <div class="device-name-row">
                <span
                  class="status-dot"
                  :title="labels[effectiveState(d)]"
                ></span
                ><button class="device-name" @click="details(d)">
                  {{ d.name }}
                </button>
              </div>
              <div class="device-tags">
                <span class="tag">{{ osName(d.latest?.os) }}</span
                ><span v-if="d.latest?.arch" class="tag">{{
                  d.latest.arch
                }}</span
                ><span class="tag status-tag">{{
                  labels[effectiveState(d)]
                }}</span>
              </div>
              <div class="last-seen">
                {{ d.last_seen ? relative(d.last_seen) + "上报" : "尚未上报" }}
              </div>
            </div>
            <div class="device-values">
              <div class="value-node">
                <small>当前节点</small
                ><strong>{{ d.latest?.selected_node || "未确定" }}</strong>
              </div>
              <div>
                <small>机场</small
                ><strong>{{ d.latest?.airport || "未提供" }}</strong>
              </div>
              <div>
                <small>延迟</small
                ><strong class="latency">{{ delay(d) }}</strong>
              </div>
              <div>
                <small>代理模式</small
                ><strong
                  >{{ modeName(d.latest?.mode)
                  }}<span v-if="d.latest?.tun_enabled"> · TUN</span></strong
                >
              </div>
            </div>
            <HeartbeatBar :history="d.history" :policy="d.policy" />
          </article>
        </div></section
    ></template>
  </main>

  <dialog
    ref="dialog"
    @cancel="close"
    @close="
      view = '';
      token = '';
      controllerSecret = '';
    "
  >
    <div class="dialog-head">
      <div>
        <h2>{{ view === "enroll" ? "设备配置" : active?.name }}</h2>
        <p v-if="view === 'enroll'">
          {{ active?.name }} · 设备凭证仅在此次显示，请保存配置。
        </p>
      </div>
      <button class="btn icon" @click="close" aria-label="关闭">✕</button>
    </div>
    <template v-if="view === 'enroll'"
      ><section class="step">
        <h3>1. 选择设备</h3>
        <select v-model="installTarget" aria-label="设备平台">
          <option v-for="[t, label] in targets" :key="t" :value="t">
            {{ label }}
          </option>
        </select>
      </section>
      <section class="step">
        <h3>2. 下载安装包</h3>
        <label
          >设备能访问的上报地址<input
            v-model="configURL"
            placeholder="https://proxy.example.com"
        /></label>
        <details>
          <summary>高级设置（通常无需修改）</summary>
          <label
            >本地控制接口地址<input
              v-model="controllerURL"
              placeholder="自动识别 Socket、命名管道或 TCP" /></label
          ><label
            >本地控制接口密钥<input
              v-model="controllerSecret"
              type="password"
              autocomplete="off"
              placeholder="自动读取 Clash Verge 运行配置" /></label
          ><label class="checkbox"
            ><input v-model="allowHTTP" type="checkbox" />允许局域网 HTTP
            调试</label
          >
          <p class="hint">控制接口密钥仅写入下载的文件，不提交到服务端。</p>
        </details>
        <button
          class="btn primary"
          :disabled="packageBusy"
          @click="downloadPackage"
        >
          {{ packageBusy ? "正在准备安装包…" : "下载安装包" }}
        </button>
        <p class="hint">
          包含
          Agent、设备配置、安装与卸载脚本，无需手动移动文件或输入管理员密码。
        </p>
        <details>
          <summary>手动接入</summary>
          <div class="download-links">
            <a class="btn" :href="'/downloads/' + binary(installTarget)"
              >仅下载 Agent</a
            >
            <button class="btn" @click="downloadConfig">下载 agent.json</button>
          </div>
        </details>
        <p class="form-error" role="alert">{{ formError }}</p>
      </section>
      <section class="step">
        <h3>3. 安装并后台运行</h3>
        <p v-if="installTarget.startsWith('windows')">
          解压安装包，双击 install.cmd。使用当前用户安装，无需管理员权限。
        </p>
        <p v-else-if="installTarget.startsWith('darwin')">
          在“下载”目录解压安装包，然后在终端执行下面这一条命令。不要使用 sudo。
        </p>
        <p v-else>
          在下载目录解压安装包，用当前用户执行下面的命令。需要用户级 systemd。
        </p>
        <pre>{{ runCommand }}</pre>
        <button
          v-if="!installTarget.startsWith('windows')"
          class="btn"
          @click="copyInstallCommand"
        >
          复制安装命令
        </button>
        <p class="hint">
          安装后静默运行，关闭终端不影响上报；重启电脑并登录后自动启动。电脑休眠时暂停上报。
        </p>
        <p class="hint">
          再次运行安装脚本可更新配置。卸载时运行安装包内的 uninstall 脚本。
        </p>
      </section>
      <div class="actions">
        <button class="btn" @click="close">完成</button>
      </div></template
    >
    <template v-if="view === 'detail' && active"
      ><div class="tabs" role="tablist">
        <button
          v-for="[t, label] in [
            ['overview', '概览'],
            ['groups', '策略组'],
            ['providers', '机场'],
            ['nodes', '节点'],
            ...(admin ? [['events', '事件']] : []),
          ]"
          :key="t"
          class="tab"
          :class="{ selected: detailTab === t }"
          role="tab"
          :aria-selected="detailTab === t"
          @click="detailTab = t"
        >
          {{ label }}
        </button>
      </div>
      <div role="tabpanel">
        <template v-if="detailTab === 'overview'"
          ><dl class="facts">
            <div>
              <dt>状态</dt>
              <dd>{{ labels[effectiveState(active)] }}</dd>
            </div>
            <div>
              <dt>最后上报</dt>
              <dd>{{ time(active.last_seen) }}</dd>
            </div>
            <div>
              <dt>系统</dt>
              <dd>
                {{ osName(active.latest?.os) }} /
                {{ active.latest?.arch || "—" }}
              </dd>
            </div>
            <div>
              <dt>内核</dt>
              <dd>{{ active.latest?.core_version || "—" }}</dd>
            </div>
            <div>
              <dt>模式 / TUN</dt>
              <dd>
                {{ modeName(active.latest?.mode) }} /
                {{ active.latest?.tun_enabled ? "开启" : "未开启" }}
              </dd>
            </div>
            <div>
              <dt>系统代理设置</dt>
              <dd>
                {{
                  { enabled: "已开启", disabled: "未开启", unknown: "未知" }[
                    active.latest?.system_proxy
                  ] || "未知"
                }}
              </dd>
            </div>
            <div>
              <dt>主要策略组</dt>
              <dd>{{ active.latest?.primary_group || "未确定" }}</dd>
            </div>
            <div>
              <dt>当前节点</dt>
              <dd>{{ active.latest?.selected_node || "未确定" }}</dd>
            </div>
            <div>
              <dt>机场</dt>
              <dd>{{ active.latest?.airport || "未提供" }}</dd>
            </div>
            <div>
              <dt>延迟 / 采样时间</dt>
              <dd>
                {{ delay(active) }} / {{ relative(active.latest?.probe?.at) }}
              </dd>
            </div>
          </dl>
          <p v-if="active.latest?.core_error" class="form-error">
            {{ active.latest.core_error }}
          </p>
          <p v-if="active.latest?.probe?.error" class="form-error">
            {{ active.latest.probe.error }}
          </p>
          <HeartbeatBar
            :history="active.history"
            :policy="active.policy" /></template
        ><template v-if="detailTab === 'groups'"
          ><div
            v-for="g in active.latest?.groups || []"
            :key="g.name"
            class="detail-row"
          >
            <div>
              <strong>{{ g.name }}</strong
              ><small>{{ g.type }}</small>
            </div>
            <div>
              {{ g.selected || "未确定"
              }}<small>{{ g.leaf || "无唯一出口" }}</small>
            </div>
          </div>
          <p v-if="!active.latest?.groups?.length" class="hint">
            尚未获取策略组。
          </p></template
        ><template v-if="detailTab === 'providers'"
          ><div
            v-for="p in active.latest?.providers || []"
            :key="p.name"
            class="provider"
          >
            <h3>{{ p.name }}</h3>
            <p>{{ p.node_count }} 个节点 · {{ p.type }}</p>
            <dl class="facts">
              <div>
                <dt>流量</dt>
                <dd>
                  {{
                    p.usage?.total
                      ? `${bytes((p.usage.upload || 0) + (p.usage.download || 0))} / ${bytes(p.usage.total)}`
                      : "未提供"
                  }}
                </dd>
              </div>
              <div>
                <dt>到期</dt>
                <dd>{{ p.usage?.expire ? time(p.usage.expire) : "未提供" }}</dd>
              </div>
              <div>
                <dt>更新时间</dt>
                <dd>
                  {{
                    p.updated_at
                      ? new Date(p.updated_at).toLocaleString("zh-CN")
                      : "未提供"
                  }}
                </dd>
              </div>
            </dl>
          </div>
          <p v-if="!active.latest?.providers?.length" class="hint">
            当前配置没有提供代理集合信息。
          </p></template
        ><template v-if="detailTab === 'nodes'"
          ><div
            v-for="n in active.latest?.nodes || []"
            :key="n.name"
            class="detail-row"
          >
            <div>
              <strong>{{ n.name }}</strong
              ><small>{{ n.type }}</small>
            </div>
            <div>
              {{ n.delay_ms == null ? "未测速" : `${n.delay_ms} ms`
              }}<small>{{
                n.delay_at ? new Date(n.delay_at).toLocaleString("zh-CN") : "—"
              }}</small>
            </div>
          </div></template
        ><template v-if="detailTab === 'events'"
          ><div v-for="(e, i) in active.events || []" :key="i" class="event">
            <small>{{ time(e.at) }}</small>
            <p>{{ e.message }}</p>
          </div></template
        >
      </div>
      <p class="form-error" role="alert">{{ formError }}</p></template
    >
  </dialog>
  <div v-if="notice" class="notice" role="status">{{ notice }}</div>
</template>

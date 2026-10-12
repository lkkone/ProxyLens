/* Browser QA uses the isolated test server; it never adds fixture devices to the real dashboard. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const base = process.env.TEST_URL || "http://localhost:18791";
const password =
  process.env.TEST_PASSWORD || "ProxyLens-isolated-test-password";
if (!password) throw Error("TEST_PASSWORD is required");
const artifacts = process.env.QA_ARTIFACTS || "artifacts";
fs.mkdirSync(artifacts, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    channel: process.env.CHROME_CHANNEL || "chrome",
    headless: true,
  });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const created = [];
  try {
    await page.goto(base + "/");
    await page.locator(".overall").waitFor();
    assert.equal(
      await page.locator("input[type=password]").count(),
      0,
      "public page asks for password",
    );
    assert.equal(
      await page.locator("input").count(),
      0,
      "public page must not have a search",
    );
    assert.equal(await page.locator(".admin-toolbar").count(), 0);
    await page.goto(base + "/admin");
    await page.locator(".login").waitFor();
    await page.getByLabel("账号", { exact: true }).fill("likaikai");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await page.locator(".admin-toolbar").waitFor();
    const authRequest = context.request;
    const mutate = async (path, data) => {
      const r = await authRequest.post(base + path, {
        headers: { "X-ProxyLens-Request": "1" },
        data,
      });
      assert(r.ok(), await r.text());
      return r.json();
    };
    const samples = [
      ["Mac mini", "常驻设备", "darwin", 45],
      ["Cloud Server", "常驻设备", "linux", 560],
      ["Windows PC", "办公设备", "windows", 1400],
      ["<script>no-execution</script>", "办公设备", "darwin", null],
    ];
    for (const [name, group, os, delay] of samples) {
      const d = await mutate("/api/devices", {
        name,
        group,
        allow_offline: group === "办公设备",
      });
      created.push(d.id);
      if (delay !== null) {
        const r = await authRequest.post(base + "/api/v1/report", {
          headers: { Authorization: "Bearer " + d.token },
          data: {
            schema_version: 1,
            adapter: "mihomo",
            hostname: "fixture",
            os,
            arch: "amd64",
            core_reachable: true,
            mode: "rule",
            primary_group: "Proxy",
            selected_node: "香港 · 测试节点",
            airport: "测试机场",
            system_proxy: "enabled",
            probe: {
              ok: true,
              at: Math.floor(Date.now() / 1000),
              node: "香港 · 测试节点",
              delay_ms: delay,
            },
            groups: [
              {
                name: "Proxy",
                type: "Selector",
                selected: "香港 · 测试节点",
                leaf: "香港 · 测试节点",
              },
            ],
            providers: [],
            nodes: [],
          },
        });
        assert(r.ok());
      }
    }
    await page.goto(base + "/");
    await page.locator(".device").first().waitFor();
    assert.equal(await page.locator(".device").count(), 4);
    assert.equal(await page.locator(".device.healthy").count(), 1);
    assert.equal(await page.locator(".device.slow").count(), 1);
    assert.equal(await page.locator(".device.degraded").count(), 1);
    for (const width of [320, 375, 414, 768, 1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      const overflow = await page.evaluate(() => ({
        root: document.documentElement.scrollWidth,
        body: document.body.scrollWidth,
        width: innerWidth,
      }));
      assert(
        overflow.root <= width && overflow.body <= width,
        JSON.stringify(overflow),
      );
      const wrapped = await page.locator("button,a").evaluateAll((items) =>
        items
          .filter((e) => {
            const r = e.getBoundingClientRect();
            return (
              r.width > 0 &&
              e.scrollWidth > e.clientWidth + 1 &&
              !e.classList.contains("device-name")
            );
          })
          .map((e) => e.textContent),
      );
      assert.equal(wrapped.length, 0, "button overflow: " + wrapped.join(","));
      await page.screenshot({
        path: `${artifacts}/public-${width}.png`,
        fullPage: true,
      });
    }
    await page.getByRole("button", { name: "Mac mini", exact: true }).click();
    await page.locator("dialog[open]").waitFor();
    await page.getByRole("tab", { name: "策略组" }).click();
    await page.getByText("Selector", { exact: true }).waitFor();
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    assert.equal(await page.locator(".theme-toggle,.legend").count(), 0);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await page.locator(".device").first().waitFor();
    await page.screenshot({
      path: `${artifacts}/public-dark.png`,
      fullPage: true,
    });
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto(base + "/admin");
    await page.locator(".admin-toolbar").waitFor();
    await page.locator(".add-device").click();
    await page
      .getByLabel("设备名称", { exact: true })
      .fill("UI-created device");
    await page.getByRole("button", { name: "创建并获取配置" }).click();
    await page
      .getByRole("heading", { name: "设备配置", exact: true })
      .waitFor();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载 agent.json" }).click();
    const download = await downloadPromise;
    const path = await download.path();
    const config = JSON.parse(fs.readFileSync(path, "utf8"));
    assert.equal(config.adapter, "mihomo");
    assert(config.token);
    assert.equal(config.server_url, base);
    assert.equal(config.probe_interval, 300);
    await page.getByRole("button", { name: "完成", exact: true }).click();
    const snapshot = await (
      await authRequest.get(base + "/api/devices")
    ).json();
    created.push(
      snapshot.devices.find((d) => d.name === "UI-created device").id,
    );
    assert.equal(await page.getByLabel("机场名称", { exact: true }).count(), 0);
    await page
      .locator(".sidebar-device")
      .filter({ hasText: "Mac mini" })
      .click();
    await page.getByLabel("设备名称", { exact: true }).fill("Mac mini edited");
    await page.getByRole("button", { name: "保存", exact: true }).click();
    await page
      .locator(".sidebar-device")
      .filter({ hasText: "Mac mini edited" })
      .waitFor();
    for (const width of [320, 375, 414, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      await page.screenshot({
        path: `${artifacts}/admin-${width}.png`,
        fullPage: true,
      });
    }

    // Offline state is tested by backdating only this isolated test database from the runner.
    const unauthorized = await browser.newContext();
    const p = await unauthorized.newPage();
    await p.goto(base + "/admin");
    await p.locator(".login").waitFor();
    await unauthorized.close();
    assert.deepEqual(errors, []);
    console.log(
      "Browser QA passed: public/admin split, device creation, config download, XSS escaping, responsive widths, details and dark theme.",
    );
  } finally {
    for (const id of created)
      await context.request.delete(base + "/api/devices/" + id, {
        headers: { "X-ProxyLens-Request": "1" },
      });
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});

<script setup>
import { computed } from "vue";
const props = defineProps({
  history: { type: Array, default: () => [] },
  policy: { type: Object, default: () => ({}) },
});
const label = {
  healthy: "低延迟",
  slow: "中等延迟",
  degraded: "高延迟",
  error: "探测失败 / 内核不可访问",
  unknown: "在线，尚无有效延迟",
  direct: "在线，直连模式",
  offline: "离线 / 无上报",
};
const bars = computed(() =>
  props.history.map((h) => ({
    ...h,
    title: h.sample_at != null
      ? `${new Date(h.sample_at * 1000).toLocaleString("zh-CN", { hour12: false })} · ${label[h.state] || h.state}${h.delay_ms != null ? ` · ${h.delay_ms} ms` : ""}`
      : `${new Date(h.at * 1000).toLocaleString("zh-CN", { hour12: false })} – ${new Date((h.at + 300) * 1000).toLocaleTimeString("zh-CN", { hour12: false })} · 无记录`,
  })),
);
</script>
<template>
  <div class="history">
    <div class="beats" aria-label="最近 5 小时，按延迟分色的代理历史">
      <span
        v-for="h in bars"
        :key="h.at"
        class="beat"
        :class="h.state"
        :title="h.title"
      ></span>
    </div>
    <div class="beat-time"><span>5 小时前</span><span>现在</span></div>
  </div>
</template>

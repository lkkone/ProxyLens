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
    title: `${new Date(h.at * 1000).toLocaleString("zh-CN", { hour12: false })} · ${label[h.state] || h.state}${h.delay_ms != null ? ` · ${h.delay_ms} ms` : ""}`,
  })),
);
</script>
<template>
  <div class="history">
    <div class="beats" aria-label="最近 5 小时，按延迟分色的代理历史">
      <span
        v-for="(h, index) in bars"
        :key="h.at"
        class="beat"
        :class="h.state"
        :style="index === 0 ? { gridColumn: 61 - bars.length } : undefined"
        :title="h.title"
      ></span>
    </div>
    <div class="beat-time"><span>{{ history.length ? new Date(history[0].at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "暂无检测记录" }}</span><span>最近检测</span></div>
  </div>
</template>

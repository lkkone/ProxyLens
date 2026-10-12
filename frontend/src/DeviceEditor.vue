<script setup>
defineProps({ form: Object, device: Object, busy: Boolean, error: String });
defineEmits(["save", "delete", "config", "detail"]);
</script>
<template>
  <section class="editor panel">
    <div class="editor-heading">
      <h2>{{ device ? device.name : "接入设备" }}</h2>
      <div v-if="device" class="editor-tools">
        <button class="btn" @click="$emit('detail')">查看状态</button
        ><button class="btn" @click="$emit('config')">获取配置</button>
      </div>
    </div>
    <form @submit.prevent="$emit('save')">
      <h3>基本信息</h3>
      <div class="form-grid">
        <label
          >设备名称<input
            v-model="form.name"
            maxlength="200"
            placeholder="例如：Mac mini"
            required /></label
        ><label
          >分组<input v-model="form.group" maxlength="200" required
        /></label>
      </div>
      <label
        >设备备注<input
          v-model="form.notes"
          maxlength="500"
          placeholder="例如：家中 Mac mini，日常办公使用"
      /></label>
      <h3>采集设置</h3>
      <div class="form-grid">
        <label
          >上报间隔（秒）<input
            v-model.number="form.report_interval"
            type="number"
            min="15"
            max="300"
            required /></label
        ><label
          >延迟采样间隔（秒）<input
            v-model.number="form.probe_interval"
            type="number"
            min="60"
            max="86400"
            required /></label
        ><label
          >绿色延迟上限（ms）<input
            v-model.number="form.green_delay_ms"
            type="number"
            min="1"
            max="9999"
            required /></label
        ><label
          >黄色延迟上限（ms）<input
            v-model.number="form.red_delay_ms"
            type="number"
            min="2"
            max="10000"
            required
        /></label>
      </div>
      <label class="checkbox"
        ><input
          v-model="form.probe_enabled"
          type="checkbox"
        />启用节点延迟采样</label
      ><label class="checkbox"
        ><input v-model="form.allow_offline" type="checkbox" />允许离线</label
      >
      <p class="form-error" role="alert">{{ error }}</p>
      <div class="actions">
        <button
          v-if="device"
          type="button"
          class="btn danger"
          @click="$emit('delete')"
        >
          删除设备</button
        ><button class="btn primary" :disabled="busy">
          {{ busy ? "正在保存…" : device ? "保存" : "创建并获取配置" }}
        </button>
      </div>
    </form>
  </section>
</template>

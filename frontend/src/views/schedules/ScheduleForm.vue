<template>
  <a-form :model="form" layout="vertical">
    <a-form-item label="任务名称" required>
      <a-input v-model:value="form.name" placeholder="例如：晨间简报" />
    </a-form-item>
    <a-form-item label="描述">
      <a-input v-model:value="form.description" placeholder="可选" />
    </a-form-item>
    <a-form-item label="绑定 Agent" required>
      <a-select v-model:value="form.agent_id" placeholder="请选择已发布 Agent">
        <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
          {{ a.name }}
        </a-select-option>
      </a-select>
    </a-form-item>
    <a-form-item label="Cron 表达式" required>
      <a-input v-model:value="form.cron_expression" placeholder="0 8 * * *" />
      <div class="field-hint">标准 5 段 cron（分 时 日 月 周）</div>
    </a-form-item>
    <a-form-item label="时区">
      <a-select v-model:value="form.timezone">
        <a-select-option value="Asia/Shanghai">Asia/Shanghai</a-select-option>
        <a-select-option value="UTC">UTC</a-select-option>
      </a-select>
    </a-form-item>
    <a-form-item label="提示词模板">
      <a-textarea v-model:value="form.prompt_template" :rows="4" />
      <div class="field-hint" v-pre>支持变量：{{date}} {{time}} {{weekday}} {{datetime}} {{schedule_name}} {{agent_name}}</div>
    </a-form-item>
    <a-form-item label="执行选项">
      <a-space direction="vertical" style="width: 100%">
        <a-switch v-model:checked="form.enabled" checked-children="启用" un-checked-children="停用" />
        <a-switch v-model:checked="form.skip_if_running" checked-children="重叠跳过" un-checked-children="允许重叠" />
      </a-space>
    </a-form-item>
    <a-form-item label="超时(秒)">
      <a-input-number v-model:value="form.timeout_seconds" :min="5" :max="3600" style="width: 100%" />
    </a-form-item>
    <a-form-item>
      <a-button @click="handlePreview" :loading="previewLoading">预览下次触发时间</a-button>
      <div v-if="preview.length" class="preview-box">
        <div v-for="(x, idx) in preview" :key="idx">{{ x }}</div>
      </div>
    </a-form-item>
    <a-space>
      <a-button type="primary" @click="onSubmit">保存</a-button>
      <a-button @click="$emit('cancel')">取消</a-button>
    </a-space>
  </a-form>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { scheduleApi } from '../../api'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  agents: { type: Array, default: () => [] },
})

const emit = defineEmits(['submit', 'cancel'])
const form = reactive({
  name: '',
  description: '',
  agent_id: '',
  cron_expression: '0 8 * * *',
  timezone: 'Asia/Shanghai',
  prompt_template: '{{schedule_name}}：请基于今日信息生成晨间简报。',
  enabled: true,
  skip_if_running: true,
  timeout_seconds: null,
})
const preview = ref([])
const previewLoading = ref(false)

watch(
  () => props.modelValue,
  (v) => {
    Object.assign(form, {
      name: v?.name || '',
      description: v?.description || '',
      agent_id: v?.agent_id || '',
      cron_expression: v?.cron_expression || '0 8 * * *',
      timezone: v?.timezone || 'Asia/Shanghai',
      prompt_template: v?.prompt_template || '{{schedule_name}}：请基于今日信息生成晨间简报。',
      enabled: v?.enabled ?? true,
      skip_if_running: v?.skip_if_running ?? true,
      timeout_seconds: v?.timeout_seconds ?? null,
    })
  },
  { immediate: true, deep: true },
)

async function handlePreview() {
  previewLoading.value = true
  try {
    const res = await scheduleApi.previewCron({
      cron_expression: form.cron_expression,
      timezone: form.timezone,
      count: 5,
    })
    preview.value = res.next_runs || []
  } catch (e) {
    message.error(e.message)
  } finally {
    previewLoading.value = false
  }
}

function onSubmit() {
  if (!form.name || !form.agent_id || !form.cron_expression) {
    message.warning('请填写必填项')
    return
  }
  emit('submit', { ...form })
}
</script>

<style scoped>
.field-hint { color: #9e9590; margin-top: 4px; font-size: 12px; }
.preview-box { margin-top: 8px; padding: 8px; background: #f3f0e8; border-radius: 6px; font-size: 12px; }
</style>

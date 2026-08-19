<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ detail?.name || '定时任务详情' }}</h2>
      <a-space>
        <a-button @click="$router.push('/schedules')">返回列表</a-button>
        <a-button type="primary" @click="triggerNow">立即执行</a-button>
      </a-space>
    </div>

    <a-row :gutter="16">
      <a-col :span="12">
        <a-card title="任务配置">
          <a-descriptions :column="1" size="small">
            <a-descriptions-item label="名称">{{ detail?.name }}</a-descriptions-item>
            <a-descriptions-item label="描述">{{ detail?.description || '-' }}</a-descriptions-item>
            <a-descriptions-item label="Agent">{{ detail?.agent_name || '-' }}</a-descriptions-item>
            <a-descriptions-item label="Cron">{{ detail?.cron_expression }}</a-descriptions-item>
            <a-descriptions-item label="时区">{{ detail?.timezone }}</a-descriptions-item>
            <a-descriptions-item label="启用">
              <a-tag :color="detail?.enabled ? 'green' : 'default'">{{ detail?.enabled ? '是' : '否' }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="上次状态">{{ detail?.last_status || '-' }}</a-descriptions-item>
            <a-descriptions-item label="下次执行">{{ formatScheduleTime(detail?.next_run_at) }}</a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card title="提示词模板">
          <pre class="prompt-pre">{{ detail?.prompt_template || '-' }}</pre>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="运行历史" style="margin-top: 16px">
      <a-table :columns="runColumns" :data-source="runs" row-key="run_id" :loading="loadingRuns">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'scheduled_for'">{{ formatScheduleTime(record.scheduled_for) }}</template>
          <template v-if="column.key === 'started_at'">{{ formatScheduleTime(record.started_at) }}</template>
          <template v-if="column.key === 'finished_at'">{{ formatScheduleTime(record.finished_at) }}</template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="showRun(record)">查看</a>
              <a
                v-if="record.session_id && record.agent_id"
                @click="$router.push(`/agents/${record.agent_id}/chat?session_id=${record.session_id}`)"
              >打开会话</a>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-drawer v-model:open="drawerOpen" title="运行详情" width="640">
      <a-descriptions :column="1" size="small" v-if="activeRun">
        <a-descriptions-item label="状态">{{ activeRun.status }}</a-descriptions-item>
        <a-descriptions-item label="触发方式">{{ activeRun.trigger_type }}</a-descriptions-item>
        <a-descriptions-item label="计划时间">{{ formatScheduleTime(activeRun.scheduled_for) }}</a-descriptions-item>
        <a-descriptions-item label="开始时间">{{ formatScheduleTime(activeRun.started_at) }}</a-descriptions-item>
        <a-descriptions-item label="结束时间">{{ formatScheduleTime(activeRun.finished_at) }}</a-descriptions-item>
        <a-descriptions-item label="Token">{{ activeRun.token_used || 0 }}</a-descriptions-item>
      </a-descriptions>
      <a-divider />
      <h4>摘要</h4>
      <pre class="prompt-pre">{{ activeRun?.summary || '-' }}</pre>
      <h4>错误</h4>
      <pre class="prompt-pre">{{ activeRun?.error_message || '-' }}</pre>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { scheduleApi } from '../../api'

const route = useRoute()
const id = route.params.id
const detail = ref(null)
const runs = ref([])
const loadingRuns = ref(false)
const drawerOpen = ref(false)
const activeRun = ref(null)

const runColumns = [
  { title: '状态', key: 'status', width: 120 },
  { title: '触发', dataIndex: 'trigger_type', width: 100 },
  { title: '计划时间', key: 'scheduled_for' },
  { title: '开始时间', key: 'started_at' },
  { title: '结束时间', key: 'finished_at' },
  { title: '操作', key: 'action', width: 160 },
]

function statusColor(status) {
  if (status === 'SUCCESS') return 'green'
  if (status === 'ERROR') return 'red'
  if (status === 'HITL_WAIT') return 'orange'
  if (status === 'SKIPPED') return 'default'
  return 'blue'
}

function formatScheduleTime(t) {
  if (!t) return '-'
  const s = String(t).trim().replace(' ', 'T')
  const hasTz = /Z$/i.test(s) || /[+-]\d{2}:\d{2}$/.test(s)
  const d = new Date(hasTz ? s : `${s}Z`)
  if (Number.isNaN(d.getTime())) return String(t)
  return d.toLocaleString('zh-CN', {
    timeZone: detail.value?.timezone || 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

async function fetchDetail() {
  try {
    detail.value = await scheduleApi.get(id)
  } catch (e) {
    message.error(e.message)
  }
}

async function fetchRuns() {
  loadingRuns.value = true
  try {
    const res = await scheduleApi.listRuns(id, { page_size: 100 })
    runs.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loadingRuns.value = false
  }
}

async function triggerNow() {
  try {
    await scheduleApi.trigger(id)
    message.success('已触发执行')
    await fetchRuns()
  } catch (e) {
    message.error(e.message)
  }
}

function showRun(run) {
  activeRun.value = run
  drawerOpen.value = true
}

onMounted(async () => {
  await fetchDetail()
  await fetchRuns()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.prompt-pre { white-space: pre-wrap; font-size: 12px; color: #3a342e; background: #f3f0e8; padding: 12px; border-radius: 6px; max-height: 280px; overflow-y: auto; }
</style>

<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">定时任务</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 新建任务
      </a-button>
    </div>

    <a-card>
      <a-table :columns="columns" :data-source="items" row-key="schedule_id" :loading="loading">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/schedules/${record.schedule_id}`)">{{ record.name }}</a>
          </template>
          <template v-if="column.key === 'enabled'">
            <a-switch :checked="record.enabled" @change="(v) => toggleEnabled(record, v)" />
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.last_status)">{{ record.last_status || '-' }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="$router.push(`/schedules/${record.schedule_id}`)">详情</a>
              <a @click="openEdit(record)">编辑</a>
              <a @click="triggerNow(record.schedule_id)">立即执行</a>
              <a-popconfirm title="确认删除?" @confirm="remove(record.schedule_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="modalOpen"
      :title="editing ? '编辑定时任务' : '新建定时任务'"
      :footer="null"
      width="720px"
      destroy-on-close
    >
      <ScheduleForm :model-value="editing" :agents="publishedAgents" @submit="save" @cancel="modalOpen = false" />
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { agentApi, scheduleApi } from '../../api'
import ScheduleForm from './ScheduleForm.vue'

const loading = ref(false)
const items = ref([])
const agents = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const columns = [
  { title: '任务名称', key: 'name' },
  { title: 'Agent', dataIndex: 'agent_name' },
  { title: 'Cron', dataIndex: 'cron_expression' },
  { title: '时区', dataIndex: 'timezone', width: 140 },
  { title: '启用', key: 'enabled', width: 90 },
  { title: '上次状态', key: 'status', width: 120 },
  { title: '操作', key: 'action', width: 240 },
]

const publishedAgents = computed(() => agents.value.filter((x) => x.status === 'PUBLISHED'))

function statusColor(status) {
  if (status === 'SUCCESS') return 'green'
  if (status === 'ERROR') return 'red'
  if (status === 'HITL_WAIT') return 'orange'
  if (status === 'SKIPPED') return 'default'
  return 'blue'
}

async function fetchData() {
  loading.value = true
  try {
    const [schedules, list] = await Promise.all([
      scheduleApi.list({ page_size: 100 }),
      agentApi.list({ page_size: 100 }),
    ])
    items.value = schedules.items || []
    agents.value = list.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(row) {
  editing.value = { ...row }
  modalOpen.value = true
}

async function save(payload) {
  try {
    if (editing.value?.schedule_id) {
      await scheduleApi.update(editing.value.schedule_id, payload)
      message.success('更新成功')
    } else {
      await scheduleApi.create(payload)
      message.success('创建成功')
    }
    modalOpen.value = false
    await fetchData()
  } catch (e) {
    message.error(e.message)
  }
}

async function triggerNow(id) {
  try {
    await scheduleApi.trigger(id)
    message.success('已触发执行')
    await fetchData()
  } catch (e) {
    message.error(e.message)
  }
}

async function toggleEnabled(row, enabled) {
  try {
    if (enabled) {
      await scheduleApi.enable(row.schedule_id)
    } else {
      await scheduleApi.disable(row.schedule_id)
    }
    row.enabled = enabled
    message.success('状态已更新')
  } catch (e) {
    message.error(e.message)
  }
}

async function remove(id) {
  try {
    await scheduleApi.delete(id)
    message.success('删除成功')
    await fetchData()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(fetchData)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>

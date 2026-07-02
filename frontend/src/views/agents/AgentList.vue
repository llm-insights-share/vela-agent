<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">Agent 列表</h2>
      <a-button type="primary" @click="$router.push('/agents/create')">
        <PlusOutlined /> 创建 Agent
      </a-button>
    </div>
    <a-card>
      <a-table
        :columns="columns"
        :data-source="agents"
        :loading="loading"
        :pagination="pagination"
        row-key="agent_id"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/agents/${record.agent_id}`)">{{ record.name }}</a>
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-if="column.key === 'model_name'">
            <a-tag v-if="record.model_name" color="blue">{{ record.model_name }}</a-tag>
            <span v-else style="color: #9e9590">-</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="$router.push(`/agents/${record.agent_id}`)">详情</a>
              <a v-if="record.status !== 'PUBLISHED'" @click="$router.push(`/agents/${record.agent_id}/edit`)">编辑</a>
              <a v-if="record.status === 'DEPRECATED'" @click="handleRepublish(record.agent_id)">重新上架</a>
              <a @click="$router.push(`/agents/${record.agent_id}/chat`)" v-if="record.status === 'PUBLISHED'">对话</a>
              <a-popconfirm title="确认删除?" @confirm="handleDelete(record.agent_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { agentApi } from '../../api'
import { message } from 'ant-design-vue'

const loading = ref(false)
const agents = ref([])
const pagination = reactive({ current: 1, pageSize: 20, total: 0 })

const columns = [
  { title: '名称', key: 'name', dataIndex: 'name' },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '模型', key: 'model_name' },
  { title: '版本', dataIndex: 'current_version' },
  { title: '自主级别', dataIndex: 'autonomy_level', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 180 },
]

function statusColor(s) {
  const m = { DRAFT: 'default', PUBLISHED: 'green', DEPRECATED: 'orange', DELETED: 'red' }
  return m[s] || 'default'
}
function statusLabel(s) {
  const m = { DRAFT: '草稿', VALIDATING: '验证中', PUBLISHED: '已发布', DEPRECATED: '已下架', DELETED: '已删除' }
  return m[s] || s
}

async function fetchAgents() {
  loading.value = true
  try {
    const res = await agentApi.list({ page: pagination.current, page_size: pagination.pageSize })
    agents.value = res.items
    pagination.total = res.total
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function onTableChange(pag) {
  pagination.current = pag.current
  pagination.pageSize = pag.pageSize
  fetchAgents()
}

async function handleDelete(id) {
  try {
    await agentApi.delete(id)
    message.success('已删除')
    fetchAgents()
  } catch (e) {
    message.error(e.message)
  }
}

async function handleRepublish(id) {
  try {
    await agentApi.republish(id)
    message.success('已重新上架')
    fetchAgents()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(fetchAgents)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>
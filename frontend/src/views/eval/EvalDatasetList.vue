<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">Eval 数据集</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 新建数据集
      </a-button>
    </div>

    <a-card>
      <a-space style="margin-bottom: 16px">
        <a-select
          v-model:value="filterAgentId"
          allow-clear
          placeholder="按 Agent 筛选"
          style="width: 280px"
          @change="fetchData"
        >
          <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
            {{ a.name }}
          </a-select-option>
        </a-select>
        <a-button @click="fetchData">刷新</a-button>
      </a-space>

      <a-table :columns="columns" :data-source="items" row-key="dataset_id" :loading="loading">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'name'">
            <a @click="$router.push(`/eval/datasets/${record.dataset_id}`)">{{ record.name }}</a>
          </template>
          <template v-if="column.key === 'agent'">
            {{ agentName(record.agent_id) }}
          </template>
          <template v-if="column.key === 'tags'">
            <a-tag v-for="t in record.tags || []" :key="t">{{ t }}</a-tag>
            <span v-if="!(record.tags || []).length">—</span>
          </template>
          <template v-if="column.key === 'created_at'">
            {{ formatDateTime(record.created_at) }}
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="$router.push(`/eval/datasets/${record.dataset_id}`)">管理用例</a>
              <a @click="runEvalJob(record)">运行 Job</a>
              <a @click="openEdit(record)">编辑</a>
              <a-popconfirm title="删除数据集及其用例与 Job 历史？" @confirm="remove(record.dataset_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="modalOpen"
      :title="editing ? '编辑数据集' : '新建数据集'"
      ok-text="保存"
      cancel-text="取消"
      :confirm-loading="saving"
      @ok="save"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="唯一名称，如 agent-foo-regression" />
        </a-form-item>
        <a-form-item label="关联 Agent">
          <a-select v-model:value="form.agent_id" allow-clear placeholder="可选">
            <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
              {{ a.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="3" />
        </a-form-item>
        <a-form-item label="标签（逗号分隔）">
          <a-input v-model:value="form.tagsText" placeholder="regression, smoke" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { agentApi, evalApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()
const loading = ref(false)
const saving = ref(false)
const items = ref([])
const agents = ref([])
const filterAgentId = ref(undefined)
const modalOpen = ref(false)
const editing = ref(null)
const form = ref({ name: '', agent_id: undefined, description: '', tagsText: '' })

const columns = [
  { title: '名称', key: 'name' },
  { title: 'Agent', key: 'agent', width: 160, ellipsis: true },
  { title: '用例数', dataIndex: 'case_count', width: 80 },
  { title: '标签', key: 'tags', width: 160 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'action', width: 280 },
]

function agentName(agentId) {
  if (!agentId) return '—'
  const a = agents.value.find((x) => x.agent_id === agentId)
  return a ? a.name : agentId.slice(0, 8)
}

function resetForm() {
  form.value = { name: '', agent_id: undefined, description: '', tagsText: '' }
}

function openCreate() {
  editing.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  form.value = {
    name: record.name,
    agent_id: record.agent_id || undefined,
    description: record.description || '',
    tagsText: (record.tags || []).join(', '),
  }
  modalOpen.value = true
}

async function fetchData() {
  loading.value = true
  try {
    const params = { page_size: 100 }
    if (filterAgentId.value) params.agent_id = filterAgentId.value
    const [ds, list] = await Promise.all([
      evalApi.listDatasets(params),
      agentApi.list({ page_size: 100 }),
    ])
    items.value = ds.items || []
    agents.value = list.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function save() {
  const name = (form.value.name || '').trim()
  if (!name) {
    message.warning('请填写名称')
    return
  }
  const tags = (form.value.tagsText || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = {
    name,
    agent_id: form.value.agent_id || '',
    description: form.value.description || '',
    tags,
  }
  saving.value = true
  try {
    if (editing.value?.dataset_id) {
      await evalApi.updateDataset(editing.value.dataset_id, payload)
      message.success('更新成功')
    } else {
      await evalApi.createDataset(payload)
      message.success('创建成功')
    }
    modalOpen.value = false
    await fetchData()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function remove(datasetId) {
  try {
    await evalApi.deleteDataset(datasetId)
    message.success('已删除')
    await fetchData()
  } catch (e) {
    message.error(e.message)
  }
}

async function runEvalJob(record) {
  try {
    const job = await evalApi.createJob({
      dataset_id: record.dataset_id,
      agent_id: record.agent_id || '',
    })
    const result = await evalApi.runJob(job.job_id)
    const rate = result.summary?.pass_rate
    message.info(
      rate != null ? `Eval 完成: ${Math.round(rate * 100)}%` : `Eval 完成: ${result.status}`,
    )
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  await fetchData()
  if (route.query.create === '1') openCreate()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin: 0;
}
</style>

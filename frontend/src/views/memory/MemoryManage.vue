<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">记忆管理</h2>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
      <a-tab-pane key="records" tab="语义记忆">
        <div class="filters">
          <a-select
            v-model:value="recordFilters.agent_id"
            allow-clear
            placeholder="按 Agent 筛选"
            style="width: 200px"
            :options="agentOptions"
            @change="fetchRecords"
          />
          <a-select
            v-model:value="recordFilters.memory_type"
            allow-clear
            placeholder="记忆类型"
            style="width: 160px"
            :options="typeOptions"
            @change="fetchRecords"
          />
          <a-select
            v-model:value="recordFilters.status"
            style="width: 120px"
            :options="statusOptions"
            @change="fetchRecords"
          />
          <a-input-search
            v-model:value="recordFilters.keyword"
            placeholder="关键词"
            style="width: 220px"
            allow-clear
            @search="fetchRecords"
          />
        </div>

        <a-table
          :columns="recordColumns"
          :data-source="records"
          :loading="recordsLoading"
          row-key="record_id"
          :pagination="recordPagination"
          @change="onRecordTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'memory_type'">
              <a-tag>{{ typeLabel(record.memory_type) }}</a-tag>
            </template>
            <template v-else-if="column.key === 'content'">
              <span class="content-cell">{{ record.content }}</span>
            </template>
            <template v-else-if="column.key === 'agent_id'">
              {{ agentName(record.agent_id) }}
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag :color="record.status === 'active' ? 'green' : 'default'">
                {{ record.status === 'active' ? '有效' : '已失效' }}
              </a-tag>
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-space>
                <a-button type="link" size="small" @click="openDetail(record)">详情</a-button>
                <a-button
                  type="link"
                  size="small"
                  :disabled="record.status !== 'active'"
                  @click="openEdit(record)"
                >修改</a-button>
                <a-popconfirm
                  title="确认失效该记忆？（不会物理删除）"
                  :disabled="record.status !== 'active'"
                  @confirm="invalidateRecord(record)"
                >
                  <a-button type="link" size="small" danger :disabled="record.status !== 'active'">
                    失效
                  </a-button>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="episodes" tab="情景事件">
        <div class="filters">
          <a-select
            v-model:value="episodeFilters.agent_id"
            allow-clear
            placeholder="按 Agent 筛选"
            style="width: 200px"
            :options="agentOptions"
            @change="fetchEpisodes"
          />
          <a-select
            v-model:value="episodeFilters.event_type"
            allow-clear
            placeholder="事件类型"
            style="width: 180px"
            :options="eventTypeOptions"
            @change="fetchEpisodes"
          />
          <a-input
            v-model:value="episodeFilters.session_id"
            placeholder="Session ID"
            style="width: 260px"
            allow-clear
            @pressEnter="fetchEpisodes"
          />
          <a-button @click="fetchEpisodes">查询</a-button>
        </div>

        <a-table
          :columns="episodeColumns"
          :data-source="episodes"
          :loading="episodesLoading"
          row-key="episode_id"
          :pagination="episodePagination"
          @change="onEpisodeTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'agent_id'">
              {{ agentName(record.agent_id) }}
            </template>
            <template v-else-if="column.key === 'payload'">
              <a-button type="link" size="small" @click="openEpisode(record)">查看</a-button>
            </template>
          </template>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <a-drawer
      v-model:open="detailOpen"
      title="记忆详情"
      width="520"
      :destroy-on-close="true"
    >
      <template v-if="currentRecord">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="ID">{{ currentRecord.record_id }}</a-descriptions-item>
          <a-descriptions-item label="类型">{{ typeLabel(currentRecord.memory_type) }}</a-descriptions-item>
          <a-descriptions-item label="Agent">{{ agentName(currentRecord.agent_id) }}</a-descriptions-item>
          <a-descriptions-item label="状态">{{ currentRecord.status }}</a-descriptions-item>
          <a-descriptions-item label="创建者">{{ currentRecord.created_by }}</a-descriptions-item>
          <a-descriptions-item label="内容">{{ currentRecord.content }}</a-descriptions-item>
          <a-descriptions-item label="元数据">
            <pre class="json-block">{{ JSON.stringify(currentRecord.metadata || {}, null, 2) }}</pre>
          </a-descriptions-item>
          <a-descriptions-item label="溯源 Episode">
            {{ (currentRecord.source_episode_ids || []).join(', ') || '—' }}
          </a-descriptions-item>
        </a-descriptions>
      </template>
    </a-drawer>

    <a-modal
      v-model:open="editOpen"
      title="修改记忆"
      ok-text="保存（旧记录失效）"
      :confirm-loading="editSaving"
      @ok="saveEdit"
    >
      <a-form layout="vertical">
        <a-form-item label="内容">
          <a-textarea v-model:value="editForm.content" :rows="5" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-drawer
      v-model:open="episodeOpen"
      title="情景事件详情"
      width="560"
      :destroy-on-close="true"
    >
      <template v-if="currentEpisode">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="ID">{{ currentEpisode.episode_id }}</a-descriptions-item>
          <a-descriptions-item label="事件">{{ currentEpisode.event_type }}</a-descriptions-item>
          <a-descriptions-item label="Session">{{ currentEpisode.session_id }}</a-descriptions-item>
          <a-descriptions-item label="Payload">
            <pre class="json-block">{{ JSON.stringify(currentEpisode.payload || {}, null, 2) }}</pre>
          </a-descriptions-item>
        </a-descriptions>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { memoryApi, agentApi } from '../../api'

const activeTab = ref('records')
const agents = ref([])
const agentOptions = computed(() =>
  agents.value.map((a) => ({ label: a.name, value: a.agent_id }))
)

const typeOptions = [
  { label: '用户偏好', value: 'user_pref' },
  { label: '任务摘要', value: 'task_summary' },
  { label: '经验', value: 'experience' },
  { label: '工具画像', value: 'tool_profile' },
  { label: '溯源', value: 'provenance' },
]
const statusOptions = [
  { label: '有效', value: 'active' },
  { label: '已失效', value: 'superseded' },
  { label: '全部', value: 'all' },
]
const eventTypeOptions = [
  { label: '消息轮次', value: 'MESSAGE_TURN' },
  { label: '工具完成', value: 'TOOL_COMPLETED' },
  { label: '异常', value: 'EXCEPTION_RAISED' },
  { label: '会话关闭', value: 'SESSION_CLOSED' },
]

const TYPE_MAP = Object.fromEntries(typeOptions.map((o) => [o.value, o.label]))
function typeLabel(t) {
  return TYPE_MAP[t] || t
}
function agentName(id) {
  return agents.value.find((a) => a.agent_id === id)?.name || id
}

const records = ref([])
const recordsLoading = ref(false)
const recordFilters = reactive({
  agent_id: undefined,
  memory_type: undefined,
  status: 'active',
  keyword: '',
})
const recordPagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })

const recordColumns = [
  { title: '类型', key: 'memory_type', dataIndex: 'memory_type', width: 110 },
  { title: '内容', key: 'content', dataIndex: 'content', ellipsis: true },
  { title: 'Agent', key: 'agent_id', dataIndex: 'agent_id', width: 160 },
  { title: '状态', key: 'status', dataIndex: 'status', width: 90 },
  { title: '创建时间', dataIndex: 'created_at', width: 180 },
  { title: '操作', key: 'actions', width: 200 },
]

const episodes = ref([])
const episodesLoading = ref(false)
const episodeFilters = reactive({
  agent_id: undefined,
  event_type: undefined,
  session_id: '',
})
const episodePagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })
const episodeColumns = [
  { title: '事件类型', dataIndex: 'event_type', width: 160 },
  { title: 'Agent', key: 'agent_id', dataIndex: 'agent_id', width: 160 },
  { title: 'Session', dataIndex: 'session_id', ellipsis: true },
  { title: '时间', dataIndex: 'created_at', width: 180 },
  { title: '详情', key: 'payload', width: 80 },
]

const detailOpen = ref(false)
const currentRecord = ref(null)
const editOpen = ref(false)
const editSaving = ref(false)
const editForm = reactive({ record_id: '', content: '' })
const episodeOpen = ref(false)
const currentEpisode = ref(null)

async function loadAgents() {
  try {
    const res = await agentApi.list({ page: 1, page_size: 200 })
    agents.value = res.items || []
  } catch (e) {
    // ignore
  }
}

async function fetchRecords() {
  recordsLoading.value = true
  try {
    const res = await memoryApi.listRecords({
      agent_id: recordFilters.agent_id || undefined,
      memory_type: recordFilters.memory_type || undefined,
      status: recordFilters.status || 'active',
      keyword: recordFilters.keyword || undefined,
      page: recordPagination.current,
      page_size: recordPagination.pageSize,
    })
    records.value = res.items || []
    recordPagination.total = res.total || 0
  } catch (e) {
    message.error(e.message)
  } finally {
    recordsLoading.value = false
  }
}

async function fetchEpisodes() {
  episodesLoading.value = true
  try {
    const res = await memoryApi.listEpisodes({
      agent_id: episodeFilters.agent_id || undefined,
      event_type: episodeFilters.event_type || undefined,
      session_id: episodeFilters.session_id || undefined,
      page: episodePagination.current,
      page_size: episodePagination.pageSize,
    })
    episodes.value = res.items || []
    episodePagination.total = res.total || 0
  } catch (e) {
    message.error(e.message)
  } finally {
    episodesLoading.value = false
  }
}

function onTabChange(key) {
  if (key === 'records') fetchRecords()
  else fetchEpisodes()
}

function onRecordTableChange(pag) {
  recordPagination.current = pag.current
  recordPagination.pageSize = pag.pageSize
  fetchRecords()
}

function onEpisodeTableChange(pag) {
  episodePagination.current = pag.current
  episodePagination.pageSize = pag.pageSize
  fetchEpisodes()
}

function openDetail(record) {
  currentRecord.value = record
  detailOpen.value = true
}

function openEdit(record) {
  editForm.record_id = record.record_id
  editForm.content = record.content
  editOpen.value = true
}

async function saveEdit() {
  if (!editForm.content?.trim()) {
    message.warning('内容不能为空')
    return
  }
  editSaving.value = true
  try {
    await memoryApi.updateRecord(editForm.record_id, { content: editForm.content.trim() })
    message.success('已保存：旧记录失效，新记录已写入')
    editOpen.value = false
    await fetchRecords()
  } catch (e) {
    message.error(e.message)
  } finally {
    editSaving.value = false
  }
}

async function invalidateRecord(record) {
  try {
    await memoryApi.deleteRecord(record.record_id)
    message.success('记忆已失效')
    await fetchRecords()
  } catch (e) {
    message.error(e.message)
  }
}

function openEpisode(ep) {
  currentEpisode.value = ep
  episodeOpen.value = true
}

onMounted(async () => {
  await loadAgents()
  await fetchRecords()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.content-cell { display: inline-block; max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.json-block {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 360px;
  overflow: auto;
}
</style>

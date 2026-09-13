<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">记忆管理</h2>
    </div>

    <div class="filters scope-bar">
      <a-select
        v-model:value="scope.agent_id"
        allow-clear
        placeholder="选择 Agent"
        style="width: 240px"
        :options="agentOptions"
        @change="onScopeChange"
      />
      <a-select
        v-model:value="scope.user_id"
        allow-clear
        placeholder="按用户筛选（可空=匿名/agent 级）"
        style="width: 220px"
        :options="userOptions"
        @change="onScopeChange"
      />
      <a-tag v-if="lettaHealthy === true" color="green">Letta 正常</a-tag>
      <a-tag v-else-if="lettaHealthy === false" color="red">Letta 不可用</a-tag>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
      <!-- 核心记忆 -->
      <a-tab-pane key="blocks" tab="核心记忆">
        <a-spin :spinning="blocksLoading">
          <div v-if="!scope.agent_id" class="empty-hint">请先选择 Agent</div>
          <div v-else-if="!blocks.length" class="empty-hint">暂无记忆块（开启记忆并对话后自动创建）</div>
          <div v-else class="block-grid">
            <a-card v-for="b in blocks" :key="b.label" size="small" class="block-card">
              <template #title>
                <span>{{ blockLabelZh(b.label) }}</span>
                <a-tag v-if="b.read_only" style="margin-left: 8px">只读</a-tag>
              </template>
              <template #extra>
                <a-button
                  type="link"
                  size="small"
                  :disabled="b.read_only"
                  @click="openBlockEdit(b)"
                >编辑</a-button>
              </template>
              <div class="field-hint" v-if="b.description">{{ b.description }}</div>
              <pre class="block-value">{{ b.value || '（空）' }}</pre>
              <a-progress
                :percent="blockUsage(b)"
                size="small"
                :status="blockUsage(b) > 90 ? 'exception' : 'normal'"
              />
              <div class="field-hint">{{ (b.value || '').length }} / {{ b.limit || 2000 }} 字符</div>
            </a-card>
          </div>
        </a-spin>
      </a-tab-pane>

      <!-- 归档记忆 -->
      <a-tab-pane key="passages" tab="归档记忆">
        <div class="filters">
          <a-input-search
            v-model:value="passageQuery"
            placeholder="按语义检索，例如：用户对报告格式的要求"
            style="width: 360px"
            allow-clear
            @search="fetchPassages"
          />
          <a-select
            v-model:value="passageTags"
            mode="tags"
            placeholder="tags 过滤"
            style="width: 220px"
            :options="tagOptions"
            @change="fetchPassages"
          />
          <a-button type="primary" :disabled="!scope.agent_id" @click="openPassageCreate">新增记忆</a-button>
          <a-button :disabled="!scope.agent_id" @click="fetchPassages">刷新</a-button>
        </div>
        <a-table
          :columns="passageColumns"
          :data-source="passages"
          :loading="passagesLoading"
          row-key="id"
          :pagination="passagePagination"
          @change="onPassageTableChange"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'content'">
              <span class="content-cell" :title="record.content">{{ record.content }}</span>
            </template>
            <template v-else-if="column.key === 'tags'">
              <a-tag v-for="t in (record.tags || [])" :key="t">{{ t }}</a-tag>
            </template>
            <template v-else-if="column.key === 'rank'">
              {{ record.rank || '—' }}
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ formatDateTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-popconfirm title="确认删除该归档记忆？" @confirm="removePassage(record)">
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </template>
          </template>
        </a-table>
      </a-tab-pane>

      <!-- 情景事件 -->
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
            style="width: 220px"
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
            <template v-if="column.key === 'event_type'">
              <a-tag>{{ eventTypeLabel(record.event_type) }}</a-tag>
            </template>
            <template v-else-if="column.key === 'agent_id'">
              {{ agentName(record.agent_id) }}
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ formatDateTime(record.created_at) }}
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-button type="link" size="small" @click="openEpisode(record)">查看</a-button>
            </template>
          </template>
        </a-table>
      </a-tab-pane>

      <!-- 服务状态 -->
      <a-tab-pane key="status" tab="服务状态">
        <a-descriptions bordered size="small" :column="1" style="max-width: 720px; margin-bottom: 24px;">
          <a-descriptions-item label="连通性">
            <a-tag :color="lettaStatus.healthy ? 'green' : 'red'">
              {{ lettaStatus.healthy ? 'healthy' : 'unavailable' }}
            </a-tag>
            <span v-if="lettaStatus.error" class="field-hint" style="margin-left: 8px;">{{ lettaStatus.error }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="服务地址">{{ lettaStatus.base_url || '—' }}</a-descriptions-item>
          <a-descriptions-item label="Embedding">
            {{ lettaStatus.embedding_model }} · {{ lettaStatus.embedding_dim }} 维
          </a-descriptions-item>
          <a-descriptions-item label="映射数量">{{ lettaStatus.mapping_count ?? 0 }}</a-descriptions-item>
        </a-descriptions>

        <h3 class="section-title">记忆 Agent 映射</h3>
        <a-table
          :columns="scopeColumns"
          :data-source="scopes"
          :loading="scopesLoading"
          row-key="mapping_id"
          :pagination="false"
          size="middle"
          style="margin-bottom: 24px;"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'agent_id'">
              {{ agentName(record.agent_id) }}
            </template>
            <template v-else-if="column.key === 'user'">
              {{ record.username || record.user_id || '—' }}
            </template>
            <template v-else-if="column.key === 'created_at'">
              {{ formatDateTime(record.created_at) }}
            </template>
          </template>
        </a-table>

        <h3 class="section-title">手动触发蒸馏</h3>
        <div class="filters">
          <a-input v-model:value="processSessionId" placeholder="Session ID" style="width: 320px" />
          <a-button type="primary" :loading="processing" @click="triggerProcess">触发处理</a-button>
          <a-button @click="refreshStatus">刷新状态</a-button>
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 编辑 block -->
    <a-modal
      v-model:open="blockEditOpen"
      title="编辑核心记忆"
      ok-text="保存"
      :confirm-loading="blockSaving"
      @ok="saveBlock"
    >
      <a-form layout="vertical">
        <a-form-item :label="blockLabelZh(blockEdit.label)">
          <a-textarea v-model:value="blockEdit.value" :rows="8" :maxlength="blockEdit.limit || 2000" show-count />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 新增 passage -->
    <a-modal
      v-model:open="passageCreateOpen"
      title="新增归档记忆"
      ok-text="写入"
      :confirm-loading="passageSaving"
      @ok="savePassage"
    >
      <a-form layout="vertical">
        <a-form-item label="内容" required>
          <a-textarea v-model:value="passageForm.text" :rows="5" />
        </a-form-item>
        <a-form-item label="Tags">
          <a-select v-model:value="passageForm.tags" mode="tags" style="width: 100%" :options="tagOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- episode 详情 -->
    <a-drawer v-model:open="episodeOpen" title="情景事件详情" width="560" :destroy-on-close="true">
      <template v-if="currentEpisode">
        <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="ID">{{ currentEpisode.episode_id }}</a-descriptions-item>
          <a-descriptions-item label="类型">{{ currentEpisode.event_type }}</a-descriptions-item>
          <a-descriptions-item label="Session">{{ currentEpisode.session_id || '—' }}</a-descriptions-item>
          <a-descriptions-item label="Payload">
            <pre class="json-block">{{ JSON.stringify(currentEpisode.payload || {}, null, 2) }}</pre>
          </a-descriptions-item>
        </a-descriptions>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { agentApi, memoryApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()

const activeTab = ref('blocks')
const agentOptions = ref([])
const agentMap = ref({})
const scope = reactive({ agent_id: undefined, user_id: undefined })
const scopes = ref([])
const scopesLoading = ref(false)
const lettaHealthy = ref(null)
const lettaStatus = reactive({
  healthy: false,
  base_url: '',
  embedding_model: 'vela-embedding',
  embedding_dim: 1024,
  error: null,
  mapping_count: 0,
})

const blocks = ref([])
const blocksLoading = ref(false)
const blockEditOpen = ref(false)
const blockSaving = ref(false)
const blockEdit = reactive({ label: '', value: '', limit: 2000 })

const passages = ref([])
const passagesLoading = ref(false)
const passageQuery = ref('')
const passageTags = ref([])
const passagePagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })
const passageCreateOpen = ref(false)
const passageSaving = ref(false)
const passageForm = reactive({ text: '', tags: ['experience'] })

const episodes = ref([])
const episodesLoading = ref(false)
const episodeFilters = reactive({ agent_id: undefined, event_type: undefined, session_id: '' })
const episodePagination = reactive({ current: 1, pageSize: 20, total: 0, showSizeChanger: true })
const episodeOpen = ref(false)
const currentEpisode = ref(null)

const processSessionId = ref('')
const processing = ref(false)

const tagOptions = [
  { label: 'experience', value: 'experience' },
  { label: 'task_summary', value: 'task_summary' },
  { label: 'user_pref', value: 'user_pref' },
]

const eventTypeOptions = [
  { label: '消息轮次', value: 'MESSAGE_TURN' },
  { label: '工具完成', value: 'TOOL_COMPLETED' },
  { label: '异常', value: 'EXCEPTION_RAISED' },
  { label: '会话关闭', value: 'SESSION_CLOSED' },
]

const userOptions = computed(() => {
  const byId = new Map()
  for (const s of scopes.value) {
    const uid = s.user_id
    if (!uid) continue
    if (!byId.has(uid)) {
      byId.set(uid, { label: s.username || uid, value: uid })
    }
  }
  return Array.from(byId.values())
})

const passageColumns = computed(() => {
  const cols = [
    { title: '内容', key: 'content', dataIndex: 'content' },
    { title: 'Tags', key: 'tags', width: 180 },
    { title: '创建时间', key: 'created_at', dataIndex: 'created_at', width: 180 },
    { title: '操作', key: 'actions', width: 100 },
  ]
  if (passageQuery.value) {
    cols.splice(2, 0, { title: '排序', key: 'rank', width: 70 })
  }
  return cols
})

const episodeColumns = [
  { title: '事件类型', key: 'event_type', width: 140 },
  { title: 'Agent', key: 'agent_id', width: 160 },
  { title: 'Session', dataIndex: 'session_id', ellipsis: true },
  { title: '时间', key: 'created_at', dataIndex: 'created_at', width: 180 },
  { title: '详情', key: 'actions', width: 80 },
]

const scopeColumns = [
  { title: 'Agent', key: 'agent_id', width: 180 },
  { title: '用户', key: 'user', width: 160 },
  { title: 'Letta Agent ID', dataIndex: 'letta_agent_id' },
  { title: '创建时间', key: 'created_at', dataIndex: 'created_at', width: 180 },
]

function blockLabelZh(label) {
  return ({ user_pref: '用户偏好', task_context: '任务上下文', tool_profile: '工具画像' })[label] || label
}

function blockUsage(b) {
  const limit = b.limit || 2000
  return Math.min(100, Math.round(((b.value || '').length / limit) * 100))
}

function agentName(id) {
  return agentMap.value[id] || id
}

function eventTypeLabel(t) {
  const m = Object.fromEntries(eventTypeOptions.map((o) => [o.value, o.label]))
  return m[t] || t
}

async function loadAgents() {
  try {
    const res = await agentApi.list({ page: 1, page_size: 100 })
    const items = res.items || []
    agentOptions.value = items.map((a) => ({ label: a.name, value: a.agent_id }))
    const map = {}
    for (const a of items) map[a.agent_id] = a.name
    agentMap.value = map
  } catch (e) {
    message.error(e.message)
  }
}

async function refreshStatus() {
  try {
    const s = await memoryApi.lettaStatus()
    Object.assign(lettaStatus, s)
    lettaHealthy.value = !!s.healthy
  } catch (e) {
    lettaHealthy.value = false
    lettaStatus.healthy = false
    lettaStatus.error = e.message
  }
  scopesLoading.value = true
  try {
    scopes.value = await memoryApi.listScopes()
  } catch (e) {
    scopes.value = []
  } finally {
    scopesLoading.value = false
  }
}

async function fetchBlocks() {
  if (!scope.agent_id) {
    blocks.value = []
    return
  }
  blocksLoading.value = true
  try {
    blocks.value = await memoryApi.listBlocks({
      agent_id: scope.agent_id,
      user_id: scope.user_id || '',
    })
  } catch (e) {
    message.error(e.message)
    blocks.value = []
  } finally {
    blocksLoading.value = false
  }
}

function openBlockEdit(b) {
  blockEdit.label = b.label
  blockEdit.value = b.value || ''
  blockEdit.limit = b.limit || 2000
  blockEditOpen.value = true
}

async function saveBlock() {
  blockSaving.value = true
  try {
    await memoryApi.updateBlock(blockEdit.label, {
      agent_id: scope.agent_id,
      user_id: scope.user_id || '',
      value: blockEdit.value,
    })
    message.success('已保存')
    blockEditOpen.value = false
    await fetchBlocks()
  } catch (e) {
    message.error(e.message)
  } finally {
    blockSaving.value = false
  }
}

async function fetchPassages() {
  if (!scope.agent_id) {
    passages.value = []
    return
  }
  passagesLoading.value = true
  try {
    const params = {
      agent_id: scope.agent_id,
      user_id: scope.user_id || '',
      page: passagePagination.current,
      page_size: passagePagination.pageSize,
    }
    if (passageQuery.value) params.query = passageQuery.value
    if (passageTags.value?.length) params.tags = passageTags.value.join(',')
    const res = await memoryApi.listPassages(params)
    passages.value = res.items || []
    passagePagination.total = res.total || 0
    // #region agent log
    fetch('http://127.0.0.1:7619/ingest/e4abc09e-cca5-4895-80e3-3c1a600bc5af',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'5cb12e'},body:JSON.stringify({sessionId:'5cb12e',runId:'pre-fix',hypothesisId:'H5',location:'MemoryManage.vue:fetchPassages',message:'frontend passages',data:{user_id:(scope.user_id||'').slice(0,12)||'empty',n:(res.items||[]).length,total:res.total||0},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
  } catch (e) {
    message.error(e.message)
    passages.value = []
  } finally {
    passagesLoading.value = false
  }
}

function onPassageTableChange(pag) {
  passagePagination.current = pag.current
  passagePagination.pageSize = pag.pageSize
  fetchPassages()
}

function openPassageCreate() {
  passageForm.text = ''
  passageForm.tags = ['experience']
  passageCreateOpen.value = true
}

async function savePassage() {
  if (!passageForm.text.trim()) {
    message.warning('请填写内容')
    return
  }
  passageSaving.value = true
  try {
    await memoryApi.createPassage({
      agent_id: scope.agent_id,
      user_id: scope.user_id || '',
      text: passageForm.text,
      tags: passageForm.tags || [],
    })
    message.success('已写入')
    passageCreateOpen.value = false
    await fetchPassages()
  } catch (e) {
    message.error(e.message)
  } finally {
    passageSaving.value = false
  }
}

async function removePassage(record) {
  try {
    await memoryApi.deletePassage(record.id, {
      agent_id: scope.agent_id,
      user_id: scope.user_id || '',
    })
    message.success('已删除')
    await fetchPassages()
  } catch (e) {
    message.error(e.message)
  }
}

async function fetchEpisodes() {
  episodesLoading.value = true
  try {
    const params = {
      page: episodePagination.current,
      page_size: episodePagination.pageSize,
    }
    if (episodeFilters.agent_id) params.agent_id = episodeFilters.agent_id
    if (episodeFilters.event_type) params.event_type = episodeFilters.event_type
    if (episodeFilters.session_id) params.session_id = episodeFilters.session_id
    const res = await memoryApi.listEpisodes(params)
    episodes.value = res.items || []
    episodePagination.total = res.total || 0
  } catch (e) {
    message.error(e.message)
  } finally {
    episodesLoading.value = false
  }
}

function onEpisodeTableChange(pag) {
  episodePagination.current = pag.current
  episodePagination.pageSize = pag.pageSize
  fetchEpisodes()
}

function openEpisode(record) {
  currentEpisode.value = record
  episodeOpen.value = true
}

async function triggerProcess() {
  if (!processSessionId.value.trim()) {
    message.warning('请输入 Session ID')
    return
  }
  processing.value = true
  try {
    const res = await memoryApi.processSession(processSessionId.value.trim())
    // #region agent log
    fetch('http://127.0.0.1:7619/ingest/e4abc09e-cca5-4895-80e3-3c1a600bc5af',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'5cb12e'},body:JSON.stringify({sessionId:'5cb12e',runId:'pre-fix',hypothesisId:'H1',location:'MemoryManage.vue:triggerProcess',message:'manual distill triggered',data:{session_id:(processSessionId.value||'').slice(0,12),msg:res.message||''},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    message.success(res.message || '已触发')
  } catch (e) {
    message.error(e.message)
  } finally {
    processing.value = false
  }
}

function onScopeChange() {
  if (activeTab.value === 'blocks') fetchBlocks()
  if (activeTab.value === 'passages') fetchPassages()
}

function onTabChange(key) {
  if (key === 'blocks') fetchBlocks()
  else if (key === 'passages') fetchPassages()
  else if (key === 'episodes') fetchEpisodes()
  else if (key === 'status') refreshStatus()
}

onMounted(async () => {
  await loadAgents()
  await refreshStatus()
  const qAgent = route.query.agent_id
  const qUser = route.query.user_id
  const qTab = route.query.tab
  if (qAgent) {
    scope.agent_id = String(qAgent)
    scope.user_id = qUser != null && qUser !== '' ? String(qUser) : undefined
  } else if (scopes.value.length) {
    scope.agent_id = scopes.value[0].agent_id
    scope.user_id = scopes.value[0].user_id || undefined
  }
  if (qTab === 'passages' || qTab === 'blocks' || qTab === 'episodes' || qTab === 'status') {
    activeTab.value = String(qTab)
  } else if (qAgent) {
    activeTab.value = 'passages'
  }
  if (activeTab.value === 'blocks') await fetchBlocks()
  else if (activeTab.value === 'passages') await fetchPassages()
  else if (activeTab.value === 'episodes') await fetchEpisodes()
  else await fetchBlocks()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.filters { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; align-items: center; }
.scope-bar { margin-bottom: 12px; }
.field-hint { font-size: 11px; color: #9e9590; line-height: 1.5; margin-bottom: 8px; }
.empty-hint { color: #9e9590; padding: 24px 0; }
.block-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.block-card { background: #fff; }
.block-value {
  margin: 0 0 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  max-height: 180px;
  overflow: auto;
  background: #f7f4ee;
  padding: 8px;
  border-radius: 6px;
}
.content-cell { white-space: pre-wrap; word-break: break-word; }
.json-block {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
}
.section-title { font-size: 15px; margin: 0 0 12px; }
</style>

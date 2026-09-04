<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">监控</h2>
        <p class="page-subtitle">Observability · Traces / Observations / Sessions</p>
      </div>
      <a-space wrap>
        <a-input-search
          v-model:value="searchQ"
          placeholder="搜索摘要 / Trace ID"
          style="width: 200px"
          allow-clear
          @search="refreshAll"
        />
        <a-select
          v-model:value="currentAgentId"
          allow-clear
          style="width: 220px"
          placeholder="全部 Agent"
          @change="refreshAll"
        >
          <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
            {{ a.name }}
          </a-select-option>
        </a-select>
        <a-select v-model:value="days" style="width: 110px" @change="refreshAll">
          <a-select-option :value="1">近 1 天</a-select-option>
          <a-select-option :value="7">近 7 天</a-select-option>
          <a-select-option :value="30">近 30 天</a-select-option>
        </a-select>
        <a-button @click="refreshAll">刷新</a-button>
        <a-button @click="saveCurrentView">保存视图</a-button>
      </a-space>
    </div>

    <a-row :gutter="[12, 12]" style="margin-bottom: 16px">
      <a-col :xs="12" :sm="8" :md="6" :lg="4" v-for="kpi in kpiItems" :key="kpi.title">
        <a-card size="small" class="kpi-card">
          <a-statistic
            :title="kpi.title"
            :value="kpi.value"
            :suffix="kpi.suffix"
            :value-style="kpi.style"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-card v-if="timeseries.length" size="small" title="Pulse · 错误率 / 延迟趋势" style="margin-bottom: 12px">
      <div class="pulse-chart">
        <div v-for="pt in timeseries" :key="pt.date" class="pulse-bar">
          <div
            class="pulse-fill error"
            :style="{ height: `${Math.max(4, pt.error_rate * 100)}px` }"
            :title="`${pt.date}: 错误率 ${Math.round(pt.error_rate * 100)}%`"
          />
          <div
            class="pulse-fill latency"
            :style="{ height: `${Math.min(60, Math.max(4, pt.avg_elapsed_ms / 50))}px` }"
            :title="`${pt.date}: P95≈${pt.avg_elapsed_ms}ms`"
          />
          <span class="pulse-label">{{ pt.date.slice(5) }}</span>
        </div>
      </div>
    </a-card>

    <a-alert
      v-for="alert in alerts"
      :key="alert.alert_id"
      :type="alert.severity === 'critical' ? 'error' : 'warning'"
      :message="alert.message"
      show-icon
      closable
      style="margin-bottom: 8px"
      @close="ackAlert(alert.alert_id)"
    />

    <a-tabs v-model:activeKey="mainTab" @change="onMainTabChange">
      <a-tab-pane key="traces" tab="Traces">
        <a-select
          v-model:value="statusFilter"
          allow-clear
          style="width: 140px; margin-bottom: 12px"
          placeholder="全部状态"
          @change="refreshRuns"
        >
          <a-select-option value="SUCCESS">SUCCESS</a-select-option>
          <a-select-option value="ERROR">ERROR</a-select-option>
          <a-select-option value="HITL_WAIT">HITL_WAIT</a-select-option>
          <a-select-option value="TIMEOUT">TIMEOUT</a-select-option>
          <a-select-option value="ABORT">ABORT</a-select-option>
        </a-select>
        <a-table
          :data-source="runs"
          row-key="run_id"
          size="small"
          :loading="loading"
          :pagination="{ pageSize: 15, showSizeChanger: false }"
        >
          <a-table-column title="时间" key="started_at" width="170">
            <template #default="{ record }">{{ formatDateTime(record.started_at) }}</template>
          </a-table-column>
          <a-table-column title="Agent" data-index="agent_name" width="120" ellipsis />
          <a-table-column title="状态" key="status" width="100">
            <template #default="{ record }">
              <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="耗时(ms)" data-index="elapsed_ms" width="90" />
          <a-table-column title="Token" key="tokens" width="90">
            <template #default="{ record }">{{ (record.token_in || 0) + (record.token_out || 0) }}</template>
          </a-table-column>
          <a-table-column title="摘要" data-index="summary" ellipsis />
          <a-table-column title="操作" key="action" width="100">
            <template #default="{ record }">
              <a @click="openDetail(record)">详情</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="observations" tab="Observations">
        <a-space style="margin-bottom: 12px">
          <a-select v-model:value="obsKind" allow-clear placeholder="类型" style="width: 160px" @change="fetchObservations">
            <a-select-option value="chat">chat / LLM</a-select-option>
            <a-select-option value="execute_tool">execute_tool / TOOL</a-select-option>
            <a-select-option value="guard_decision">guard_decision / GUARDRAIL</a-select-option>
            <a-select-option value="agent">agent / AGENT</a-select-option>
            <a-select-option value="retriever">retriever / RETRIEVER</a-select-option>
            <a-select-option value="evaluator">evaluator / EVALUATOR</a-select-option>
            <a-select-option value="internal">internal / CHAIN</a-select-option>
          </a-select>
          <a-button @click="fetchObservations">刷新</a-button>
        </a-space>
        <a-table
          :data-source="observations"
          row-key="span_id"
          size="small"
          :loading="obsLoading"
          :pagination="{ pageSize: 20 }"
        >
          <a-table-column title="名称" data-index="name" ellipsis />
          <a-table-column title="类型" data-index="kind" width="110" />
          <a-table-column title="耗时" data-index="duration_ms" width="80" />
          <a-table-column title="Run 状态" data-index="run_status" width="100" />
          <a-table-column title="操作" key="action" width="80">
            <template #default="{ record }">
              <a @click="openDetail({ run_id: record.run_id })">Trace</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="sessions" tab="Sessions">
        <a-table
          :data-source="sessions"
          row-key="session_id"
          size="small"
          :loading="sessionsLoading"
          :pagination="{ pageSize: 15 }"
        >
          <a-table-column title="标题" data-index="title" ellipsis />
          <a-table-column title="状态" data-index="status" width="100" />
          <a-table-column title="Runs" data-index="run_count" width="70" />
          <a-table-column title="Token" data-index="token_used" width="80" />
          <a-table-column title="成本(USD)" key="cost" width="100">
            <template #default="{ record }">{{ (record.estimated_cost_usd || 0).toFixed(4) }}</template>
          </a-table-column>
          <a-table-column title="最近活跃" key="last" width="170">
            <template #default="{ record }">{{ formatDateTime(record.last_active_at) }}</template>
          </a-table-column>
          <a-table-column title="操作" key="action" width="80">
            <template #default="{ record }">
              <a @click="goChat(record)">Chat</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="users" tab="Users">
        <a-table :data-source="userUsage" row-key="user_id" size="small" :loading="usersLoading" :pagination="false">
          <a-table-column title="用户 ID" data-index="user_id" ellipsis />
          <a-table-column title="Runs" data-index="run_count" width="80" />
          <a-table-column title="Token" data-index="total_tokens" width="100" />
          <a-table-column title="成本(USD)" key="cost" width="100">
            <template #default="{ record }">{{ (record.estimated_cost_usd || 0).toFixed(4) }}</template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="alerts" tab="告警设置">
        <a-button type="primary" style="margin-bottom: 12px" @click="openAlertRuleModal">新建规则</a-button>
        <a-table :data-source="alertRules" row-key="rule_id" size="small" :pagination="false">
          <a-table-column title="名称" data-index="name" />
          <a-table-column title="指标" data-index="metric" width="120" />
          <a-table-column title="Warning" data-index="threshold_warning" width="90" />
          <a-table-column title="Alert" data-index="threshold_alert" width="90" />
          <a-table-column title="Webhook" data-index="webhook_url" ellipsis />
          <a-table-column title="启用" key="enabled" width="70">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'default'">{{ record.enabled ? '是' : '否' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="操作" key="action" width="80">
            <template #default="{ record }">
              <a-popconfirm title="删除规则？" @confirm="removeAlertRule(record.rule_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <a-drawer v-model:open="drawerOpen" title="Trace 详情" width="780" destroy-on-close>
      <template v-if="detailRun">
        <a-descriptions :column="2" size="small" bordered>
          <a-descriptions-item label="Run ID" :span="2">{{ detailRun.run_id }}</a-descriptions-item>
          <a-descriptions-item label="Session">{{ detailRun.session_id }}</a-descriptions-item>
          <a-descriptions-item label="Version">{{ detailRun.version_id || '—' }}</a-descriptions-item>
          <a-descriptions-item label="Caller">{{ detailRun.caller_id || '—' }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusColor(detailRun.status)">{{ detailRun.status }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="耗时">{{ detailRun.elapsed_ms ?? 0 }} ms</a-descriptions-item>
          <a-descriptions-item label="Token">
            in {{ detailRun.token_in || 0 }} / out {{ detailRun.token_out || 0 }}
          </a-descriptions-item>
          <a-descriptions-item label="摘要" :span="2">{{ detailRun.summary || '—' }}</a-descriptions-item>
        </a-descriptions>

        <a-tabs v-model:activeKey="detailTab" style="margin-top: 12px">
          <a-tab-pane key="tree" tab="Span 树">
            <a-tree
              v-if="spanTree.length"
              :tree-data="spanTreeData"
              default-expand-all
              block-node
              @select="onSpanSelect"
            />
            <a-empty v-else description="无 Spans" :image-style="{ height: '40px' }" />
          </a-tab-pane>
          <a-tab-pane key="graph" tab="执行图谱">
            <div class="span-graph">
              <div v-for="node in graphNodes" :key="node.span_id" class="graph-node" :class="node.kind">
                <div class="graph-name">{{ node.name }}</div>
                <div class="graph-meta">{{ node.kind }} · {{ node.duration_ms }}ms</div>
              </div>
            </div>
          </a-tab-pane>
          <a-tab-pane key="flat" tab="列表">
            <a-table :data-source="detailRun.spans || []" row-key="span_id" size="small" :pagination="false">
              <a-table-column title="名称" data-index="name" ellipsis />
              <a-table-column title="类型" data-index="kind" width="110" />
              <a-table-column title="耗时" data-index="duration_ms" width="80" />
            </a-table>
          </a-tab-pane>
        </a-tabs>

        <a-card v-if="selectedSpan" size="small" title="Span I/O" style="margin-top: 12px">
          <a-tabs>
            <a-tab-pane key="in" tab="Input">
              <pre class="io-block">{{ formatJson(selectedSpan.input) }}</pre>
            </a-tab-pane>
            <a-tab-pane key="out" tab="Output">
              <pre class="io-block">{{ formatJson(selectedSpan.output) }}</pre>
            </a-tab-pane>
          </a-tabs>
        </a-card>

        <a-divider>Scores</a-divider>
        <a-table
          v-if="(detailRun.scores || []).length"
          :data-source="detailRun.scores"
          row-key="score_name"
          size="small"
          :pagination="false"
        >
          <a-table-column title="名称" data-index="score_name" />
          <a-table-column title="类型" data-index="data_type" width="100" />
          <a-table-column title="分值" data-index="value" width="80" />
          <a-table-column title="来源" data-index="source" width="90" />
        </a-table>
        <a-empty v-else description="暂无评分" :image-style="{ height: '40px' }" />

        <a-divider v-if="(detailRun.feedback || []).length">用户反馈</a-divider>
        <a-table
          v-if="(detailRun.feedback || []).length"
          :data-source="detailRun.feedback"
          row-key="feedback_id"
          size="small"
          :pagination="false"
        >
          <a-table-column title="评分" data-index="rating" width="70" />
          <a-table-column title="原因" data-index="reason" ellipsis />
        </a-table>

        <a-space style="margin-top: 16px" wrap>
          <a-button type="primary" @click="openImportModal">加入数据集</a-button>
          <a-button @click="goChat(detailRun)">跳转 Chat</a-button>
          <a-button @click="exportOtel">导出 OTel</a-button>
        </a-space>
      </template>
    </a-drawer>

    <a-modal
      v-model:open="importModalOpen"
      title="加入评测数据集"
      ok-text="导入"
      :confirm-loading="importing"
      @ok="importToDataset"
    >
      <a-select v-model:value="importDatasetId" placeholder="选择数据集" style="width: 100%">
        <a-select-option v-for="d in datasets" :key="d.dataset_id" :value="d.dataset_id">
          {{ d.name }} ({{ d.case_count }})
        </a-select-option>
      </a-select>
    </a-modal>

    <a-modal v-model:open="alertRuleModalOpen" title="告警规则" ok-text="保存" @ok="saveAlertRule">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="alertRuleForm.name" />
        </a-form-item>
        <a-form-item label="指标" required>
          <a-select v-model:value="alertRuleForm.metric">
            <a-select-option value="error_rate">error_rate</a-select-option>
            <a-select-option value="success_rate">success_rate</a-select-option>
            <a-select-option value="avg_tokens">avg_tokens</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="Warning 阈值">
          <a-input-number v-model:value="alertRuleForm.threshold_warning" :step="0.05" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Alert 阈值">
          <a-input-number v-model:value="alertRuleForm.threshold_alert" :step="0.05" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Webhook URL">
          <a-input v-model:value="alertRuleForm.webhook_url" placeholder="https://..." />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { agentApi, monitorApi, evalApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()
const router = useRouter()
const agents = ref([])
const currentAgentId = ref(undefined)
const days = ref(7)
const statusFilter = ref(undefined)
const searchQ = ref('')
const summary = ref({})
const runs = ref([])
const alerts = ref([])
const datasets = ref([])
const loading = ref(false)
const drawerOpen = ref(false)
const detailRun = ref(null)
const detailTab = ref('tree')
const selectedSpan = ref(null)
const mainTab = ref('traces')
const observations = ref([])
const obsLoading = ref(false)
const obsKind = ref(undefined)
const sessions = ref([])
const sessionsLoading = ref(false)
const userUsage = ref([])
const usersLoading = ref(false)
const alertRules = ref([])
const alertRuleModalOpen = ref(false)
const alertRuleForm = ref({ name: '', metric: 'error_rate', threshold_warning: 0.2, threshold_alert: 0.3, webhook_url: '' })
const importModalOpen = ref(false)
const importDatasetId = ref(undefined)
const importing = ref(false)

const timeseries = computed(() => summary.value?.timeseries || [])

const kpiItems = computed(() => {
  const s = summary.value || {}
  return [
    { title: 'Traces', value: s.total_runs || 0 },
    { title: '成功率', value: Math.round((s.success_rate || 0) * 100), suffix: '%' },
    { title: '错误率', value: Math.round((s.error_rate || 0) * 100), suffix: '%', style: { color: '#b5341c' } },
    { title: 'P95 延迟', value: s.p95_elapsed_ms || 0, suffix: 'ms' },
    { title: 'Token', value: s.total_tokens || 0 },
    { title: '成本(USD)', value: s.estimated_cost_usd || 0 },
    { title: '负反馈率', value: Math.round((s.negative_feedback_rate || 0) * 100), suffix: '%' },
  ]
})

const spanTree = computed(() => detailRun.value?.span_tree || [])

const spanTreeData = computed(() => {
  function mapNode(n) {
    return {
      key: n.span_id,
      title: `${n.name} (${n.kind}, ${n.duration_ms}ms)`,
      span: n,
      children: (n.children || []).map(mapNode),
    }
  }
  return spanTree.value.map(mapNode)
})

const graphNodes = computed(() => detailRun.value?.spans || [])

function formatJson(val) {
  if (val == null) return '—'
  try {
    return JSON.stringify(val, null, 2)
  } catch {
    return String(val)
  }
}

function onSpanSelect(keys, { node }) {
  selectedSpan.value = node?.span || null
}

function statusColor(s) {
  if (s === 'SUCCESS') return 'green'
  if (s === 'ERROR' || s === 'TIMEOUT') return 'red'
  if (s === 'HITL_WAIT') return 'orange'
  return 'default'
}

async function loadAgents() {
  const res = await agentApi.list({ page_size: 100 })
  agents.value = res.items || []
}

async function refreshRuns() {
  const params = { days: days.value, page_size: 50, q: searchQ.value || undefined }
  if (currentAgentId.value) params.agent_id = currentAgentId.value
  if (statusFilter.value) params.status = statusFilter.value
  const r = await monitorApi.listRuns(params)
  runs.value = r.items || []
}

async function fetchObservations() {
  obsLoading.value = true
  try {
    const params = { page_size: 50 }
    if (currentAgentId.value) params.agent_id = currentAgentId.value
    if (obsKind.value) params.kind = obsKind.value
    if (searchQ.value) params.q = searchQ.value
    const res = await monitorApi.listObservations(params)
    observations.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    obsLoading.value = false
  }
}

async function fetchSessions() {
  sessionsLoading.value = true
  try {
    const params = { page_size: 30 }
    if (currentAgentId.value) params.agent_id = currentAgentId.value
    const res = await monitorApi.listSessions(params)
    sessions.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    sessionsLoading.value = false
  }
}

async function fetchUsers() {
  usersLoading.value = true
  try {
    const params = { days: days.value }
    if (currentAgentId.value) params.agent_id = currentAgentId.value
    const res = await monitorApi.listUsers(params)
    userUsage.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    usersLoading.value = false
  }
}

async function fetchAlertRules() {
  try {
    const res = await monitorApi.listAlertRules()
    alertRules.value = res.items || []
  } catch (e) {
    message.error(e.message)
  }
}

async function refreshAll() {
  loading.value = true
  try {
    const params = { days: days.value }
    if (currentAgentId.value) params.agent_id = currentAgentId.value
    const [s, a] = await Promise.all([
      monitorApi.summary(params),
      monitorApi.listAlerts({ acknowledged: false }),
    ])
    summary.value = s || {}
    alerts.value = a.items || []
    await refreshRuns()
    if (mainTab.value === 'observations') await fetchObservations()
    if (mainTab.value === 'sessions') await fetchSessions()
    if (mainTab.value === 'users') await fetchUsers()
    if (mainTab.value === 'alerts') await fetchAlertRules()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function onMainTabChange(key) {
  if (key === 'observations') fetchObservations()
  if (key === 'sessions') fetchSessions()
  if (key === 'users') fetchUsers()
  if (key === 'alerts') fetchAlertRules()
}

async function ackAlert(alertId) {
  await monitorApi.ackAlert(alertId)
  alerts.value = alerts.value.filter((x) => x.alert_id !== alertId)
}

async function openDetail(record) {
  detailRun.value = await monitorApi.getRun(record.run_id || record)
  selectedSpan.value = (detailRun.value.spans || [])[0] || null
  detailTab.value = 'tree'
  drawerOpen.value = true
}

function goChat(record) {
  router.push(`/agents/${record.agent_id}/chat?session=${record.session_id}`)
}

async function openImportModal() {
  const params = { page_size: 100 }
  if (detailRun.value?.agent_id) params.agent_id = detailRun.value.agent_id
  const ds = await evalApi.listDatasets(params)
  datasets.value = ds.items || []
  importDatasetId.value = datasets.value[0]?.dataset_id
  importModalOpen.value = true
}

async function importToDataset() {
  if (!importDatasetId.value || !detailRun.value) return
  importing.value = true
  try {
    await evalApi.importRun(importDatasetId.value, detailRun.value.run_id)
    message.success('已加入评测数据集')
    importModalOpen.value = false
  } catch (e) {
    message.error(e.message)
  } finally {
    importing.value = false
  }
}

async function exportOtel() {
  if (!detailRun.value) return
  const res = await monitorApi.exportOtel(detailRun.value.run_id)
  const blob = new Blob([res.payload], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `run-${detailRun.value.run_id}-otel.json`
  a.click()
  URL.revokeObjectURL(url)
}

function openAlertRuleModal() {
  alertRuleForm.value = { name: '', metric: 'error_rate', threshold_warning: 0.2, threshold_alert: 0.3, webhook_url: '' }
  alertRuleModalOpen.value = true
}

async function saveAlertRule() {
  try {
    await monitorApi.createAlertRule({ ...alertRuleForm.value, enabled: true, agent_id: currentAgentId.value || '' })
    message.success('规则已创建')
    alertRuleModalOpen.value = false
    await fetchAlertRules()
  } catch (e) {
    message.error(e.message)
  }
}

async function removeAlertRule(ruleId) {
  await monitorApi.deleteAlertRule(ruleId)
  await fetchAlertRules()
}

async function saveCurrentView() {
  try {
    await monitorApi.createSavedView({
      name: `视图 ${new Date().toLocaleString()}`,
      path: mainTab.value,
      filters_json: {
        agent_id: currentAgentId.value,
        days: days.value,
        status: statusFilter.value,
        q: searchQ.value,
      },
    })
    message.success('视图已保存')
  } catch (e) {
    message.error(e.message)
  }
}

async function openDeepLink() {
  const runId = route.query.run_id
  if (!runId || typeof runId !== 'string') return
  await openDetail({ run_id: runId })
}

onMounted(async () => {
  await loadAgents()
  await refreshAll()
  await openDeepLink()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 12px;
  flex-wrap: wrap;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin: 0;
}
.page-subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: #8a847c;
}
.kpi-card { height: 100%; }
.io-block {
  background: #f7f5f2;
  padding: 8px;
  border-radius: 4px;
  font-size: 11px;
  max-height: 240px;
  overflow: auto;
}
.pulse-chart {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  min-height: 72px;
}
.pulse-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.pulse-fill {
  width: 12px;
  border-radius: 2px 2px 0 0;
}
.pulse-fill.error { background: #b5341c; }
.pulse-fill.latency { background: #4a6741; opacity: 0.7; }
.pulse-label { font-size: 10px; color: #8a847c; }
.span-graph {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.graph-node {
  border: 1px solid #d4cfc6;
  border-radius: 4px;
  padding: 8px 10px;
  min-width: 120px;
}
.graph-node.chat { border-left: 3px solid #4a6741; }
.graph-node.execute_tool { border-left: 3px solid #c45c26; }
.graph-node.guard_decision { border-left: 3px solid #b5341c; }
.graph-node.agent { border-left: 3px solid #2c5f8a; }
.graph-node.retriever { border-left: 3px solid #6b5b95; }
.graph-node.evaluator { border-left: 3px solid #7a8b5a; }
.graph-name { font-size: 12px; font-weight: 600; }
.graph-meta { font-size: 10px; color: #8a847c; }
</style>

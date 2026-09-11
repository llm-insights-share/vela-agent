<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">自优化 SelfOpt</h2>
      <a-space>
        <a-select
          v-model:value="agentId"
          allow-clear
          show-search
          placeholder="选择白名单内 Agent"
          style="width: 240px"
          :options="agentOptions"
          :filter-option="filterAgent"
          @change="onAgentChange"
        />
        <a-select
          v-model:value="jobReflectProviderId"
          allow-clear
          show-search
          placeholder="反思供应商（可选）"
          style="width: 180px"
          :options="providerOptions"
          :filter-option="filterAgent"
          :disabled="!status.enabled"
          @change="onJobProviderChange"
        />
        <a-select
          v-model:value="jobReflectModelId"
          allow-clear
          show-search
          placeholder="反思模型（可选）"
          style="width: 220px"
          :options="modelOptions"
          :filter-option="filterAgent"
          :disabled="!status.enabled || !jobReflectProviderId"
        />
        <a-button type="primary" :disabled="!canRunJob" :loading="jobLoading" @click="runJob">
          运行反思 Job
        </a-button>
      </a-space>
    </div>

    <a-alert
      v-if="!status.enabled"
      type="warning"
      show-icon
      style="margin-bottom: 16px"
      message="自优化已关闭"
      description="请在「系统配置 → 自优化」中开启，并勾选目标 Agent。关闭时不参与会话分流。"
    />
    <a-alert
      v-else-if="!(status.agent_ids || []).length"
      type="info"
      show-icon
      style="margin-bottom: 16px"
      message="尚未勾选目标 Agent"
      description="请在系统配置中选择可参与自优化的 Agent（白名单为空时 Job / 调度 / A/B 均不生效）。"
    />

    <!-- 全局总览（不绑具体 Job） -->
    <a-card size="small" style="margin-bottom: 16px" title="总览">
      <a-row :gutter="12">
        <a-col :span="6"><a-statistic title="白名单 Agent" :value="overview.allowlist_count || 0" /></a-col>
        <a-col :span="6"><a-statistic title="待审阅提案" :value="overview.pending_review || 0" /></a-col>
        <a-col :span="6"><a-statistic title="运行中 A/B" :value="overview.running_experiments || 0" /></a-col>
        <a-col :span="6"><a-statistic title="本周 Jobs" :value="overview.jobs_week || 0" /></a-col>
      </a-row>
    </a-card>

    <!-- Job 历史选择 -->
    <a-card size="small" style="margin-bottom: 16px" title="Job 历史">
      <a-space wrap>
        <span class="field-label">当前 Agent</span>
        <a-select
          v-model:value="agentId"
          allow-clear
          show-search
          placeholder="必选白名单 Agent"
          style="width: 240px"
          :options="agentOptions"
          :filter-option="filterAgent"
          @change="onAgentChange"
        />
        <span class="field-label">Job</span>
        <a-select
          v-model:value="selectedJobId"
          show-search
          placeholder="选择 Job"
          style="width: 320px"
          :options="jobOptions"
          :filter-option="filterAgent"
          :disabled="!agentId || !jobOptions.length"
          :loading="jobsLoading"
          @change="onJobSelect"
        />
      </a-space>
      <div v-if="agentId && !jobsLoading && !jobOptions.length" class="meta-line">
        该 Agent 暂无 Job，可点击「运行反思 Job」创建。
      </div>
    </a-card>

    <!-- 选定 Job 详情 -->
    <a-card
      v-if="selectedJobId && jobDetail"
      size="small"
      style="margin-bottom: 16px"
      :loading="detailLoading"
    >
      <template #title>
        <span>{{ jobDetail.job?.job_label || selectedJobId }}</span>
        <a-tag style="margin-left: 8px">{{ jobDetail.job?.status || '-' }}</a-tag>
      </template>
      <div class="meta-line" style="margin-top: 0; margin-bottom: 12px">
        反思模型
        {{
          jobDetail.job?.stats_json?.reflect_model_name
            || jobDetail.job?.stats_json?.reflect_model_service_id
            || '-'
        }}
        · 轨迹 {{ jobDetail.job?.stats_json?.trajectory_count ?? '-' }}
        · 提案 {{ jobDetail.job?.stats_json?.proposal_count ?? (jobDetail.proposals || []).length }}
      </div>

      <a-steps
        :current="stageIndex"
        size="small"
        type="navigation"
        class="clickable-steps"
        style="margin-bottom: 16px"
        @change="onStageClick"
      >
        <a-step
          v-for="(s, idx) in displayStages"
          :key="s.key"
          :status="stepStatus(idx)"
        >
          <template #title>
            <span class="step-title" @click.stop="activeStage = s.key">{{ s.label }}</span>
          </template>
        </a-step>
      </a-steps>

      <!-- 环节内容卡片 -->
      <a-card size="small" class="stage-card" :title="activeStageLabel">
        <template v-if="activeStage === 'collect'">
          <a-descriptions size="small" :column="2">
            <a-descriptions-item label="轨迹数">
              {{ stagePayload.trajectory_count ?? '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="Job 状态">{{ stagePayload.status || '-' }}</a-descriptions-item>
            <a-descriptions-item label="窗口开始">{{ formatTs(stagePayload.window_start) }}</a-descriptions-item>
            <a-descriptions-item label="窗口结束">{{ formatTs(stagePayload.window_end) }}</a-descriptions-item>
          </a-descriptions>
        </template>
        <template v-else-if="activeStage === 'reflect'">
          <a-descriptions size="small" :column="2">
            <a-descriptions-item label="Findings">{{ stagePayload.finding_count ?? '-' }}</a-descriptions-item>
            <a-descriptions-item label="提案数">{{ stagePayload.proposal_count ?? '-' }}</a-descriptions-item>
            <a-descriptions-item label="反思模型">
              {{ stagePayload.reflect_model_name || stagePayload.reflect_model_service_id || '-' }}
            </a-descriptions-item>
            <a-descriptions-item label="状态">{{ stagePayload.status || '-' }}</a-descriptions-item>
          </a-descriptions>
          <a-alert
            v-if="stagePayload.error"
            type="error"
            show-icon
            style="margin-top: 8px"
            :message="String(stagePayload.error)"
          />
        </template>
        <template v-else-if="activeStage === 'gate'">
          <div v-if="!(stagePayload.reports || []).length" class="meta-line">暂无评测报告</div>
          <div v-for="r in (stagePayload.reports || [])" :key="r.proposal_id" class="gate-item">
            <a-tag>{{ r.status }}</a-tag>
            <span class="mono">{{ shortId(r.proposal_id) }}</span>
            <span v-if="r.passed != null">· passed={{ r.passed }}</span>
            <pre v-if="r.summary" class="report-pre small">{{ formatJson(r.summary) }}</pre>
          </div>
        </template>
        <template v-else-if="activeStage === 'review'">
          <div class="meta-line" style="margin-top: 0">待审阅 {{ stagePayload.pending_review ?? 0 }}</div>
          <a-list
            size="small"
            :data-source="stagePayload.proposals || []"
            :locale="{ emptyText: '暂无提案' }"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space>
                  <a-tag>{{ item.status }}</a-tag>
                  <a-tag>{{ item.risk_tier }}</a-tag>
                  <span>{{ item.change_kind }}</span>
                  <span class="clamp">{{ item.rationale || '-' }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </template>
        <template v-else-if="activeStage === 'ab'">
          <div class="meta-line" style="margin-top: 0">运行中 {{ stagePayload.running_count ?? 0 }}</div>
          <a-list
            size="small"
            :data-source="stagePayload.experiments || []"
            :locale="{ emptyText: '暂无关联实验' }"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space>
                  <a-tag>{{ item.status }}</a-tag>
                  <span>rr={{ item.rr_counter }}</span>
                  <span>decision={{ item.decision || '-' }}</span>
                  <span class="mono">{{ shortId(item.experiment_id) }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </template>
        <template v-else-if="activeStage === 'decide'">
          <a-descriptions size="small" :column="2" style="margin-bottom: 8px">
            <a-descriptions-item label="已上线">{{ stagePayload.promoted ?? 0 }}</a-descriptions-item>
            <a-descriptions-item label="拒绝/终止">{{ stagePayload.rejected ?? 0 }}</a-descriptions-item>
          </a-descriptions>
          <a-list
            size="small"
            :data-source="stagePayload.decisions || []"
            :locale="{ emptyText: '尚无 promote / keep_control 决策' }"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <a-space>
                  <a-tag color="blue">{{ item.decision }}</a-tag>
                  <span>{{ item.decided_by || '-' }}</span>
                  <span>{{ formatTs(item.decided_at) }}</span>
                  <span>{{ item.decision_note || '' }}</span>
                </a-space>
              </a-list-item>
            </template>
          </a-list>
        </template>
      </a-card>

      <!-- Job 级 Tabs -->
      <a-tabs v-model:activeKey="tab" style="margin-top: 16px">
        <a-tab-pane key="proposals" tab="提案审阅">
          <a-table
            :columns="proposalColumns"
            :data-source="proposals"
            :loading="detailLoading"
            row-key="proposal_id"
            :pagination="{ pageSize: 10 }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'risk'">
                <a-tag>{{ record.risk_tier }}</a-tag>
                <span style="margin-left: 6px; color: #888">{{ record.change_kind }}</span>
              </template>
              <template v-else-if="column.key === 'rationale'">
                <div class="clamp">{{ record.rationale || '-' }}</div>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a @click="showProposal(record)">详情</a>
                  <a
                    v-if="['pending_review', 'evaluated', 'approved'].includes(record.status) && status.enabled && status.ab_enabled"
                    @click="startAb(record)"
                  >启动 A/B</a>
                  <a-popconfirm
                    v-if="canIgnoreProposal(record)"
                    title="确认忽略并放弃该优化提案？"
                    ok-text="忽略"
                    cancel-text="取消"
                    @confirm="ignoreProposal(record)"
                  >
                    <a style="color: #b5341c">忽略</a>
                  </a-popconfirm>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-tab-pane>

        <a-tab-pane key="ab" tab="A/B 实验">
          <a-table
            :columns="abColumns"
            :data-source="experiments"
            :loading="detailLoading"
            row-key="experiment_id"
            :pagination="{ pageSize: 10 }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'versions'">
                <div>C: {{ shortId(record.control_version_id) }}</div>
                <div>T: {{ shortId(record.treatment_version_id) }}</div>
              </template>
              <template v-else-if="column.key === 'action'">
                <a-space>
                  <a @click="loadReport(record)">效果对比</a>
                  <a-popconfirm
                    v-if="record.status === 'running' && status.enabled"
                    title="确认将自优化版本正式上线？"
                    @confirm="promote(record)"
                  >
                    <a style="color: #52c41a">正式上线</a>
                  </a-popconfirm>
                  <a-popconfirm
                    v-if="record.status === 'running' && status.enabled"
                    title="保持当前生产版本并结束实验？"
                    @confirm="keepControl(record)"
                  >
                    <a>保持当前</a>
                  </a-popconfirm>
                  <a
                    v-if="record.status === 'running' && status.enabled"
                    style="color: #b5341c"
                    @click="abortExp(record)"
                  >终止</a>
                </a-space>
              </template>
            </template>
          </a-table>

          <a-card v-if="report" title="效果对比报告" style="margin-top: 16px">
            <a-alert
              type="info"
              show-icon
              style="margin-bottom: 16px"
              :message="abAssignTitle"
              :description="abAssignDescription"
            />
            <a-row :gutter="16">
              <a-col :span="12">
                <h4>Control（当前）</h4>
                <a-list size="small" bordered :data-source="armMetricItems(report.control)">
                  <template #renderItem="{ item }">
                    <a-list-item>
                      <span class="metric-label">{{ item.label }}</span>
                      <span class="metric-value">{{ item.value }}</span>
                    </a-list-item>
                  </template>
                </a-list>
              </a-col>
              <a-col :span="12">
                <h4>Treatment（自优化）</h4>
                <a-list size="small" bordered :data-source="armMetricItems(report.treatment)">
                  <template #renderItem="{ item }">
                    <a-list-item>
                      <span class="metric-label">{{ item.label }}</span>
                      <span class="metric-value">{{ item.value }}</span>
                    </a-list-item>
                  </template>
                </a-list>
              </a-col>
            </a-row>
            <div class="compare-narrative">
              <h4>文字比较说明</h4>
              <p v-for="(line, i) in abCompareNarrative" :key="i">{{ line }}</p>
            </div>
          </a-card>
        </a-tab-pane>
      </a-tabs>
    </a-card>

    <a-drawer v-model:open="drawerOpen" title="提案详情" width="520">
      <template v-if="currentProposal">
        <p><strong>状态</strong>：{{ currentProposal.status }}</p>
        <p><strong>风险</strong>：{{ currentProposal.risk_tier }} / {{ currentProposal.change_kind }}</p>
        <p><strong>理由</strong>：{{ currentProposal.rationale }}</p>
        <p><strong>证据 Run</strong>：{{ (currentProposal.evidence_run_ids || []).join(', ') || '-' }}</p>
        <h4>diff_json</h4>
        <pre class="report-pre">{{ JSON.stringify(currentProposal.diff_json, null, 2) }}</pre>
        <h4>eval_report</h4>
        <pre class="report-pre">{{ JSON.stringify(currentProposal.eval_report_json, null, 2) }}</pre>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { selfoptApi, agentApi, configApi, serviceApi, providerApi } from '../../api'

const tab = ref('proposals')
const agentId = ref(undefined)
const selectedJobId = ref(undefined)
const jobReflectProviderId = ref(undefined)
const jobReflectModelId = ref(undefined)
const agentOptions = ref([])
const providerOptions = ref([])
const allServices = ref([])
const modelOptions = ref([])
const status = ref({ enabled: false, schedule_enabled: false, ab_enabled: true, agent_ids: [] })
const overview = ref({ allowlist_count: 0, pending_review: 0, running_experiments: 0, jobs_week: 0 })

const defaultStages = [
  { key: 'collect', label: '轨迹采集' },
  { key: 'reflect', label: '反思提案' },
  { key: 'gate', label: '离线评测' },
  { key: 'review', label: '人工审阅' },
  { key: 'ab', label: '轮询 A/B' },
  { key: 'decide', label: '正式上线 / 保持当前' },
]

const jobs = ref([])
const jobsLoading = ref(false)
const jobLoading = ref(false)
const detailLoading = ref(false)
const jobDetail = ref(null)
const activeStage = ref('collect')
const report = ref(null)
const drawerOpen = ref(false)
const currentProposal = ref(null)

const proposals = computed(() => jobDetail.value?.proposals || [])
const experiments = computed(() => jobDetail.value?.experiments || [])

function formatRate(v) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return `${(Number(v) * 100).toFixed(1)}%`
}

function formatNum(v, digits = 1) {
  if (v == null || Number.isNaN(Number(v))) return '-'
  return Number(v).toFixed(digits)
}

function armMetricItems(arm) {
  const a = arm || {}
  return [
    { label: '有效会话数', value: a.session_count ?? 0 },
    { label: '空会话数', value: a.empty_session_count ?? 0 },
    { label: '运行数', value: a.run_count ?? 0 },
    { label: '成功数', value: a.success_count ?? 0 },
    { label: '错误数', value: a.error_count ?? 0 },
    { label: 'HITL 数', value: a.hitl_count ?? 0 },
    { label: '成功率', value: formatRate(a.success_rate) },
    { label: '平均耗时 (ms)', value: formatNum(a.avg_elapsed_ms) },
    { label: '平均 Token', value: formatNum(a.avg_tokens) },
    { label: '点赞', value: a.thumbs_up ?? 0 },
    { label: '点踩', value: a.thumbs_down ?? 0 },
  ]
}

const abAssignTitle = computed(() => {
  if (!report.value) return ''
  const strategy = report.value.strategy || 'round_robin'
  const rr = report.value.rr_counter ?? 0
  return `分流策略：${strategy} · 已分配会话轮次 rr_counter=${rr}`
})

const abAssignDescription = computed(() => {
  if (!report.value) return ''
  const asg = report.value.assignment || {}
  const rr = report.value.rr_counter ?? asg.rr_counter ?? 0
  const expectedT = asg.expected_treatment_sessions ?? Math.ceil(rr / 2)
  const expectedC = asg.expected_control_sessions ?? Math.floor(rr / 2)
  const c = asg.actual_control_sessions ?? report.value.control?.assigned_session_count ?? 0
  const t = asg.actual_treatment_sessions ?? report.value.treatment?.assigned_session_count ?? 0
  const emptyC = asg.control_empty_sessions ?? report.value.control?.empty_session_count ?? 0
  const emptyT = asg.treatment_empty_sessions ?? report.value.treatment?.empty_session_count ?? 0
  const ok = asg.balanced ?? (c === expectedC && t === expectedT)
  const base = ok
    ? `新建会话按奇数轮→自优化、偶数轮→当前 轮流分配。分配会话：控制版 ${c} / 自优化 ${t}，与轮询计数一致。`
    : `新建会话按奇数轮→自优化、偶数轮→当前。轮询计数=${rr}（期望控制 ${expectedC} / 自优化 ${expectedT}），实际分配控制 ${c} / 自优化 ${t}。`
  if (emptyC || emptyT) {
    return `${base} 其中空会话（未发消息）控制 ${emptyC} / 自优化 ${emptyT}，不计入效果指标。`
  }
  return base
})

const abCompareNarrative = computed(() => {
  if (!report.value) return []
  const c = report.value.control || {}
  const t = report.value.treatment || {}
  const d = report.value.delta || {}
  const lines = []

  lines.push(
    `样本量：当前版 ${c.session_count ?? 0} 会话 / ${c.run_count ?? 0} 次运行；自优化版 ${t.session_count ?? 0} 会话 / ${t.run_count ?? 0} 次运行。`,
  )

  if (c.success_rate == null && t.success_rate == null) {
    lines.push('成功率：两侧暂无足够运行数据，暂无法比较。')
  } else if (c.success_rate == null) {
    lines.push(`成功率：当前版暂无运行数据；自优化版为 ${formatRate(t.success_rate)}。`)
  } else if (t.success_rate == null) {
    lines.push(`成功率：自优化版暂无运行数据；当前版为 ${formatRate(c.success_rate)}。`)
  } else {
    const diff = Number(d.success_rate)
    if (diff > 0.02) {
      lines.push(`成功率：自优化版更高（${formatRate(t.success_rate)} vs ${formatRate(c.success_rate)}，+${formatRate(diff)}）。`)
    } else if (diff < -0.02) {
      lines.push(`成功率：当前版更高（${formatRate(c.success_rate)} vs ${formatRate(t.success_rate)}，自优化相对 ${formatRate(diff)}）。`)
    } else {
      lines.push(`成功率：两侧接近（当前 ${formatRate(c.success_rate)}，自优化 ${formatRate(t.success_rate)}）。`)
    }
  }

  if (d.avg_elapsed_ms != null) {
    const ms = Number(d.avg_elapsed_ms)
    if (ms < -50) {
      lines.push(`平均耗时：自优化更快约 ${formatNum(Math.abs(ms))} ms。`)
    } else if (ms > 50) {
      lines.push(`平均耗时：自优化更慢约 ${formatNum(ms)} ms。`)
    } else {
      lines.push(`平均耗时：两侧接近（差值 ${formatNum(ms)} ms）。`)
    }
  }

  if (d.avg_tokens != null) {
    const tok = Number(d.avg_tokens)
    if (Math.abs(tok) < 1) {
      lines.push('平均 Token：两侧接近。')
    } else if (tok > 0) {
      lines.push(`平均 Token：自优化多消耗约 ${formatNum(tok)}。`)
    } else {
      lines.push(`平均 Token：自优化少消耗约 ${formatNum(Math.abs(tok))}。`)
    }
  }

  const errDiff = (t.error_count ?? 0) - (c.error_count ?? 0)
  const hitlDiff = (t.hitl_count ?? 0) - (c.hitl_count ?? 0)
  lines.push(
    `稳定性：错误数差值（自优化−当前）=${errDiff}，HITL 差值=${hitlDiff}；反馈 👍 ${t.thumbs_up ?? 0}/${c.thumbs_up ?? 0}（自优化/当前），👎 ${t.thumbs_down ?? 0}/${c.thumbs_down ?? 0}。`,
  )

  if ((c.run_count ?? 0) === 0 && (t.run_count ?? 0) > 0) {
    lines.push('提示：当前版会话尚无产生运行记录，对比时请结合轮询是否刚开始、或控制版会话未继续对话。')
  }

  return lines
})

const jobOptions = computed(() =>
  (jobs.value || []).map((j) => ({
    label: j.job_label || j.job_id,
    value: j.job_id,
  })),
)

const displayStages = computed(() => jobDetail.value?.stages || defaultStages)

const stageIndex = computed(() => {
  const idx = displayStages.value.findIndex((s) => s.key === activeStage.value)
  return idx >= 0 ? idx : 0
})

const progressStageIndex = computed(() => {
  const stages = displayStages.value
  const cur = jobDetail.value?.current_stage
  const idx = stages.findIndex((s) => s.key === cur || s.active)
  return idx >= 0 ? idx : 0
})

const activeStageLabel = computed(() => {
  const s = displayStages.value.find((x) => x.key === activeStage.value)
  return s?.label || '环节详情'
})

const stagePayload = computed(() => {
  const payloads = jobDetail.value?.stage_payloads || {}
  return payloads[activeStage.value] || {}
})

const canRunJob = computed(() => {
  return !!(
    agentId.value &&
    status.value.enabled &&
    (status.value.agent_ids || []).includes(agentId.value)
  )
})

const proposalColumns = [
  { title: '状态', dataIndex: 'status', width: 120 },
  { title: '风险/类型', key: 'risk', width: 180 },
  { title: '理由', key: 'rationale' },
  { title: '操作', key: 'action', width: 200 },
]
const abColumns = [
  { title: '状态', dataIndex: 'status', width: 100 },
  { title: '策略', dataIndex: 'strategy', width: 110 },
  { title: '轮询计数', dataIndex: 'rr_counter', width: 90 },
  { title: '版本', key: 'versions' },
  { title: '决策', dataIndex: 'decision', width: 110 },
  { title: '操作', key: 'action', width: 260 },
]

function shortId(id) {
  if (!id) return '-'
  return String(id).slice(0, 8)
}

function filterAgent(input, option) {
  return (option?.label || '').toLowerCase().includes((input || '').toLowerCase())
}

function formatTs(v) {
  if (!v) return '-'
  try {
    return new Date(v).toLocaleString()
  } catch {
    return String(v)
  }
}

function formatJson(v) {
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

function stepStatus(idx) {
  const progress = progressStageIndex.value
  if (idx < progress) return 'finish'
  if (idx === progress) return 'process'
  return 'wait'
}

function onStageClick(idx) {
  const s = displayStages.value[idx]
  if (s) activeStage.value = s.key
}

async function loadStatus() {
  try {
    status.value = await configApi.getSelfopt()
  } catch {
    status.value = { enabled: false, schedule_enabled: false, ab_enabled: true, agent_ids: [] }
  }
}

async function loadAgents() {
  try {
    const res = await agentApi.list({ page: 1, page_size: 100 })
    const allow = new Set(status.value.agent_ids || [])
    const all = (res.items || []).map((a) => ({
      label: a.name,
      value: a.agent_id,
    }))
    agentOptions.value = allow.size ? all.filter((o) => allow.has(o.value)) : []
  } catch (e) {
    message.error(e.message)
  }
}

function syncJobModelOptions(providerId) {
  const pid = providerId || jobReflectProviderId.value
  if (!pid) {
    modelOptions.value = []
    return
  }
  modelOptions.value = (allServices.value || [])
    .filter((s) => s.provider_id === pid)
    .map((s) => ({
      label: `${s.display_name || s.model_name} (${s.model_name})`,
      value: s.model_service_id,
    }))
}

function onJobProviderChange(providerId) {
  jobReflectModelId.value = undefined
  syncJobModelOptions(providerId)
}

async function loadModels() {
  try {
    const [provRes, svcRes] = await Promise.all([
      providerApi.list({ page: 1, page_size: 100 }),
      serviceApi.list({ page: 1, page_size: 100 }),
    ])
    providerOptions.value = (provRes.items || []).map((p) => ({
      label: p.display_name || p.provider_code,
      value: p.provider_id,
    }))
    allServices.value = svcRes.items || []
    syncJobModelOptions(jobReflectProviderId.value)
  } catch {
    providerOptions.value = []
    allServices.value = []
    modelOptions.value = []
  }
}

async function loadOverview() {
  try {
    overview.value = await selfoptApi.overview({})
  } catch {
    overview.value = { allowlist_count: 0, pending_review: 0, running_experiments: 0, jobs_week: 0 }
  }
}

async function loadJobs() {
  if (!agentId.value) {
    jobs.value = []
    selectedJobId.value = undefined
    jobDetail.value = null
    return
  }
  jobsLoading.value = true
  try {
    const res = await selfoptApi.listJobs({
      agent_id: agentId.value,
      page: 1,
      page_size: 50,
    })
    jobs.value = res.items || []
    if (jobs.value.length) {
      const stillValid = jobs.value.some((j) => j.job_id === selectedJobId.value)
      if (!stillValid) {
        selectedJobId.value = jobs.value[0].job_id
      }
      await loadJobDetail(selectedJobId.value)
    } else {
      selectedJobId.value = undefined
      jobDetail.value = null
    }
  } catch (e) {
    message.error(e.message)
    jobs.value = []
  } finally {
    jobsLoading.value = false
  }
}

async function loadJobDetail(jobId) {
  if (!jobId) {
    jobDetail.value = null
    return
  }
  detailLoading.value = true
  report.value = null
  try {
    const detail = await selfoptApi.getJobDetail(jobId)
    jobDetail.value = detail
    const cur = detail.current_stage || detail.stages?.find((s) => s.active)?.key || 'collect'
    activeStage.value = cur
  } catch (e) {
    message.error(e.message)
    jobDetail.value = null
  } finally {
    detailLoading.value = false
  }
}

async function onAgentChange() {
  selectedJobId.value = undefined
  jobDetail.value = null
  report.value = null
  await loadJobs()
}

async function onJobSelect(jobId) {
  await loadJobDetail(jobId)
}

async function runJob() {
  if (!agentId.value) return
  jobLoading.value = true
  try {
    const payload = { agent_id: agentId.value, window_days: 7 }
    if (jobReflectModelId.value) {
      payload.reflect_model_service_id = jobReflectModelId.value
    }
    const job = await selfoptApi.createJob(payload)
    message.success(`反思 Job 已完成：${job.job_label || job.job_id}`)
    tab.value = 'proposals'
    await loadOverview()
    await loadJobs()
    if (job.job_id) {
      selectedJobId.value = job.job_id
      await loadJobDetail(job.job_id)
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    jobLoading.value = false
  }
}

function showProposal(record) {
  currentProposal.value = record
  drawerOpen.value = true
}

function canIgnoreProposal(record) {
  return (
    status.value.enabled &&
    ['pending_review', 'evaluated', 'approved', 'drafted'].includes(record.status)
  )
}

async function ignoreProposal(record) {
  try {
    await selfoptApi.rejectProposal(record.proposal_id, { note: 'ui ignore' })
    message.success('已忽略该优化提案')
    await loadOverview()
    if (selectedJobId.value) await loadJobDetail(selectedJobId.value)
  } catch (e) {
    message.error(e.message)
  }
}

async function startAb(record) {
  try {
    await selfoptApi.startAb(record.proposal_id, {})
    message.success('A/B 已启动（轮询分流）')
    tab.value = 'ab'
    await loadOverview()
    if (selectedJobId.value) await loadJobDetail(selectedJobId.value)
  } catch (e) {
    message.error(e.message)
  }
}

async function loadReport(record) {
  try {
    report.value = await selfoptApi.abReport(record.experiment_id)
  } catch (e) {
    message.error(e.message)
  }
}

async function promote(record) {
  try {
    await selfoptApi.promote(record.experiment_id, { note: 'ui promote' })
    message.success('已正式上线自优化版本')
    await loadOverview()
    if (selectedJobId.value) await loadJobDetail(selectedJobId.value)
  } catch (e) {
    message.error(e.message)
  }
}

async function keepControl(record) {
  try {
    await selfoptApi.keepControl(record.experiment_id, { note: 'ui keep' })
    message.success('已保持当前版本并结束实验')
    await loadOverview()
    if (selectedJobId.value) await loadJobDetail(selectedJobId.value)
  } catch (e) {
    message.error(e.message)
  }
}

async function abortExp(record) {
  try {
    await selfoptApi.abort(record.experiment_id, { note: 'ui abort' })
    message.success('实验已终止')
    await loadOverview()
    if (selectedJobId.value) await loadJobDetail(selectedJobId.value)
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  await loadStatus()
  await Promise.all([loadAgents(), loadModels(), loadOverview()])
  if (agentOptions.value.length === 1) {
    agentId.value = agentOptions.value[0].value
    await loadJobs()
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  color: #1a1714;
}
.clamp {
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.report-pre {
  background: #f5f2ea;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  max-height: 280px;
  overflow: auto;
}
.report-pre.small {
  max-height: 120px;
  margin-top: 6px;
}
.meta-line {
  margin-top: 10px;
  font-size: 13px;
  color: #666;
}
.field-label {
  color: #666;
  font-size: 13px;
}
.stage-card {
  background: #faf9f6;
}
.gate-item {
  margin-bottom: 10px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.clickable-steps :deep(.ant-steps-item) {
  cursor: pointer;
}
.step-title {
  cursor: pointer;
}
.metric-label {
  color: #666;
}
.metric-value {
  margin-left: auto;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
:deep(.ant-list-item) {
  display: flex;
  justify-content: space-between;
  width: 100%;
}
.compare-narrative {
  margin-top: 16px;
  padding: 12px 14px;
  background: #faf9f6;
  border-radius: 6px;
  border: 1px solid #eee9df;
}
.compare-narrative h4 {
  margin: 0 0 8px;
}
.compare-narrative p {
  margin: 0 0 6px;
  color: #444;
  line-height: 1.6;
}
.compare-narrative p:last-child {
  margin-bottom: 0;
}
</style>

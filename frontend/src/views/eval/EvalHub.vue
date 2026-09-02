<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">评测</h2>
        <p class="page-subtitle">Evaluation · Datasets / Experiments / Scores</p>
      </div>
      <a-space>
        <a-button v-if="activeTab === 'datasets'" type="primary" @click="openCreateDataset">
          <PlusOutlined /> 新建数据集
        </a-button>
        <a-button v-if="activeTab === 'experiments'" type="primary" @click="openCreateExperiment">
          <PlusOutlined /> 新建 Experiment
        </a-button>
        <a-button v-if="activeTab === 'evaluators'" type="primary" @click="openEvaluatorModal">
          <PlusOutlined /> 新建 Evaluator
        </a-button>
        <a-button v-if="activeTab === 'annotation'" type="primary" @click="openQueueModal">
          <PlusOutlined /> 新建标注队列
        </a-button>
      </a-space>
    </div>

    <a-tabs v-model:activeKey="activeTab" @change="onTabChange">
      <a-tab-pane key="datasets" tab="Datasets">
        <a-space style="margin-bottom: 16px">
          <a-select
            v-model:value="filterAgentId"
            allow-clear
            placeholder="按 Agent 筛选"
            style="width: 260px"
            @change="fetchDatasets"
          >
            <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
              {{ a.name }}
            </a-select-option>
          </a-select>
          <a-button @click="fetchDatasets">刷新</a-button>
        </a-space>
        <a-table
          :columns="datasetColumns"
          :data-source="datasets"
          row-key="dataset_id"
          :loading="datasetsLoading"
          size="small"
        >
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
                <a @click="$router.push(`/eval/datasets/${record.dataset_id}`)">打开 Items</a>
                <a @click="quickRunExperiment(record)">运行 Experiment</a>
                <a @click="openEditDataset(record)">编辑</a>
                <a-popconfirm title="删除数据集及其 Items 与 Experiment 历史？" @confirm="removeDataset(record.dataset_id)">
                  <a style="color: #b5341c">删除</a>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="experiments" tab="Experiments">
        <a-space style="margin-bottom: 16px" wrap>
          <a-select
            v-model:value="jobDatasetFilter"
            allow-clear
            placeholder="按 Dataset 筛选"
            style="width: 260px"
            @change="fetchJobs"
          >
            <a-select-option v-for="d in datasets" :key="d.dataset_id" :value="d.dataset_id">
              {{ d.name }}
            </a-select-option>
          </a-select>
          <a-button @click="fetchJobs">刷新</a-button>
        </a-space>

        <a-card
          v-if="compareRows.length >= 2"
          size="small"
          title="Experiment 对比"
          style="margin-bottom: 12px"
        >
          <a-space wrap style="margin-bottom: 8px">
            <a-select v-model:value="compareJobA" style="width: 220px" placeholder="Job A">
              <a-select-option v-for="row in compareRows" :key="row.job_id" :value="row.job_id">
                {{ formatDateTime(row.created_at) }} · {{ row.status }}
              </a-select-option>
            </a-select>
            <a-select v-model:value="compareJobB" style="width: 220px" placeholder="Job B">
              <a-select-option v-for="row in compareRows" :key="'b-' + row.job_id" :value="row.job_id">
                {{ formatDateTime(row.created_at) }} · {{ row.status }}
              </a-select-option>
            </a-select>
            <a-button :disabled="!compareJobA || !compareJobB" @click="loadCompare">对比</a-button>
          </a-space>
          <a-table
            v-if="compareResult?.rows?.length"
            :data-source="compareResult.rows"
            row-key="case_id"
            size="small"
            :pagination="false"
          >
            <a-table-column title="Item" data-index="input_preview" ellipsis />
            <a-table-column title="Job A" key="a" width="80">
              <template #default="{ record }">
                <a-tag :color="record.job_a_passed ? 'green' : 'red'">{{ record.job_a_passed ? '✓' : '✗' }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column title="Job B" key="b" width="80">
              <template #default="{ record }">
                <a-tag :color="record.job_b_passed ? 'green' : 'red'">{{ record.job_b_passed ? '✓' : '✗' }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column title="回归" key="reg" width="70">
              <template #default="{ record }">
                <a-tag v-if="record.regression" color="red">是</a-tag>
                <span v-else>—</span>
              </template>
            </a-table-column>
          </a-table>
        </a-card>

        <a-table :data-source="jobs" row-key="job_id" size="small" :loading="jobsLoading">
          <a-table-column title="时间" key="created_at" width="170">
            <template #default="{ record }">{{ formatDateTime(record.created_at) }}</template>
          </a-table-column>
          <a-table-column title="Dataset" key="dataset" width="160" ellipsis>
            <template #default="{ record }">{{ datasetName(record.dataset_id) }}</template>
          </a-table-column>
          <a-table-column title="Agent" key="agent" width="140" ellipsis>
            <template #default="{ record }">{{ agentName(record.agent_id) }}</template>
          </a-table-column>
          <a-table-column title="状态" key="status" width="100">
            <template #default="{ record }">
              <a-tag :color="record.status === 'SUCCESS' ? 'green' : record.status === 'FAILED' ? 'red' : 'default'">
                {{ record.status }}
              </a-tag>
            </template>
          </a-table-column>
          <a-table-column title="通过率" key="pass_rate" width="100">
            <template #default="{ record }">
              {{
                record.summary?.pass_rate != null
                  ? `${Math.round(record.summary.pass_rate * 100)}%`
                  : '—'
              }}
            </template>
          </a-table-column>
          <a-table-column title="阈值" key="threshold" width="80">
            <template #default="{ record }">
              {{ record.pass_threshold != null ? Math.round(record.pass_threshold * 100) + '%' : '—' }}
            </template>
          </a-table-column>
          <a-table-column title="操作" key="action" width="80">
            <template #default="{ record }">
              <a @click="viewJob(record.job_id)">详情</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="scores" tab="Scores / Feedback">
        <a-space style="margin-bottom: 16px" wrap>
          <a-select
            v-model:value="scoresAgentId"
            allow-clear
            placeholder="选择 Agent"
            style="width: 260px"
            @change="fetchEffect"
          >
            <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
              {{ a.name }}
            </a-select-option>
          </a-select>
          <a-select v-model:value="scoresDays" style="width: 120px" @change="fetchEffect">
            <a-select-option :value="1">近 1 天</a-select-option>
            <a-select-option :value="7">近 7 天</a-select-option>
            <a-select-option :value="30">近 30 天</a-select-option>
          </a-select>
          <a-button @click="fetchEffect">刷新</a-button>
        </a-space>

        <template v-if="effectReport">
          <a-alert
            type="info"
            show-icon
            style="margin-bottom: 16px"
            :message="effectReport.recommendation"
            description="用生产负反馈与 Badcase 回流 Dataset，形成评测闭环（对齐 Langfuse Evaluation loop）。"
          />
          <a-row :gutter="12" style="margin-bottom: 16px">
            <a-col :span="6">
              <a-statistic title="Badcase 数" :value="effectReport.badcase_count || 0" />
            </a-col>
            <a-col :span="6">
              <a-statistic title="负反馈" :value="effectReport.negative_feedback_count || 0" />
            </a-col>
            <a-col :span="6">
              <a-statistic title="规则评分条数" :value="effectReport.rule_score_count || 0" />
            </a-col>
            <a-col :span="6">
              <a-statistic title="近期 Experiments" :value="(effectReport.eval_jobs_recent || []).length" />
            </a-col>
          </a-row>
          <a-card title="Badcase Traces" size="small" style="margin-bottom: 12px">
            <a-space wrap v-if="(effectReport.badcase_run_ids || []).length">
              <a
                v-for="rid in effectReport.badcase_run_ids"
                :key="rid"
                @click="$router.push({ path: '/monitor', query: { run_id: rid } })"
              >
                {{ rid.slice(0, 8) }}…
              </a>
            </a-space>
            <a-empty v-else description="暂无 Badcase" :image-style="{ height: '40px' }" />
          </a-card>
          <a-card title="近期 Experiments" size="small">
            <a-table
              :data-source="effectReport.eval_jobs_recent || []"
              row-key="job_id"
              size="small"
              :pagination="false"
            >
              <a-table-column title="Job" data-index="job_id" ellipsis />
              <a-table-column title="状态" data-index="status" width="100" />
              <a-table-column title="通过率" key="rate" width="100">
                <template #default="{ record }">
                  {{
                    record.summary?.pass_rate != null
                      ? `${Math.round(record.summary.pass_rate * 100)}%`
                      : '—'
                  }}
                </template>
              </a-table-column>
              <a-table-column title="操作" key="action" width="80">
                <template #default="{ record }">
                  <a @click="viewJob(record.job_id)">详情</a>
                </template>
              </a-table-column>
            </a-table>
          </a-card>
        </template>
        <a-empty v-else description="选择 Agent 后查看生产质量信号" />
      </a-tab-pane>

      <a-tab-pane key="evaluators" tab="Evaluators">
        <a-table :data-source="evaluators" row-key="evaluator_id" size="small" :loading="evaluatorsLoading">
          <a-table-column title="名称" data-index="name" />
          <a-table-column title="Agent" key="agent" width="140">
            <template #default="{ record }">{{ agentName(record.agent_id) }}</template>
          </a-table-column>
          <a-table-column title="启用" key="enabled" width="70">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'default'">{{ record.enabled ? '是' : '否' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="规则" key="rules" ellipsis>
            <template #default="{ record }">
              {{ JSON.stringify(record.rules_json || {}) }}
            </template>
          </a-table-column>
          <a-table-column title="操作" key="action" width="80">
            <template #default="{ record }">
              <a-popconfirm title="删除？" @confirm="removeEvaluator(record.evaluator_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </template>
          </a-table-column>
        </a-table>
        <a-divider>LLM Judge（采样）</a-divider>
        <a-table :data-source="judgeEvaluators" row-key="evaluator_id" size="small">
          <a-table-column title="名称" data-index="name" />
          <a-table-column title="采样率" key="rate" width="90">
            <template #default="{ record }">{{ Math.round((record.sample_rate || 0) * 100) }}%</template>
          </a-table-column>
          <a-table-column title="启用" key="enabled" width="70">
            <template #default="{ record }">
              <a-tag :color="record.enabled ? 'green' : 'default'">{{ record.enabled ? '是' : '否' }}</a-tag>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>

      <a-tab-pane key="annotation" tab="Annotation">
        <a-table :data-source="annotationQueues" row-key="queue_id" size="small">
          <a-table-column title="队列" data-index="name" />
          <a-table-column title="待标注" data-index="pending_count" width="90" />
          <a-table-column title="操作" key="action" width="100">
            <template #default="{ record }">
              <a @click="openQueueItems(record)">打开</a>
            </template>
          </a-table-column>
        </a-table>
      </a-tab-pane>
    </a-tabs>

    <a-modal
      v-model:open="datasetModalOpen"
      :title="editingDataset ? '编辑数据集' : '新建数据集'"
      ok-text="保存"
      cancel-text="取消"
      :confirm-loading="datasetSaving"
      @ok="saveDataset"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="datasetForm.name" placeholder="唯一名称，如 agent-foo-regression" />
        </a-form-item>
        <a-form-item label="关联 Agent">
          <a-select v-model:value="datasetForm.agent_id" allow-clear placeholder="可选">
            <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">
              {{ a.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="datasetForm.description" :rows="3" />
        </a-form-item>
        <a-form-item label="标签（逗号分隔）">
          <a-input v-model:value="datasetForm.tagsText" placeholder="regression, smoke" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="experimentModalOpen"
      title="新建 Experiment"
      ok-text="运行"
      cancel-text="取消"
      :confirm-loading="experimentRunning"
      @ok="createAndRunExperiment"
    >
      <a-form layout="vertical">
        <a-form-item label="Dataset" required>
          <a-select v-model:value="experimentForm.dataset_id" placeholder="选择数据集" style="width: 100%">
            <a-select-option v-for="d in datasets" :key="d.dataset_id" :value="d.dataset_id">
              {{ d.name }} ({{ d.case_count }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="通过率阈值">
          <a-input-number
            v-model:value="experimentForm.pass_threshold"
            :min="0"
            :max="1"
            :step="0.05"
            style="width: 100%"
          />
        </a-form-item>
        <a-form-item label="运行模式">
          <a-select v-model:value="experimentForm.run_mode" style="width: 100%">
            <a-select-option value="replay">回放打分（默认）</a-select-option>
            <a-select-option value="rerun">真实重跑 Agent</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="规则 Evaluator">
          <a-select v-model:value="experimentForm.evaluator_id" allow-clear placeholder="可选，使用内置规则" style="width: 100%">
            <a-select-option v-for="ev in evaluators" :key="ev.evaluator_id" :value="ev.evaluator_id">
              {{ ev.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-drawer v-model:open="jobDrawerOpen" title="Experiment 详情" width="560">
      <template v-if="jobDetail">
        <a-descriptions :column="1" size="small" bordered>
          <a-descriptions-item label="Job ID">{{ jobDetail.job_id }}</a-descriptions-item>
          <a-descriptions-item label="状态">{{ jobDetail.status }}</a-descriptions-item>
          <a-descriptions-item label="通过率">
            {{
              jobDetail.summary?.pass_rate != null
                ? `${Math.round(jobDetail.summary.pass_rate * 100)}%`
                : '—'
            }}
          </a-descriptions-item>
          <a-descriptions-item label="阈值">
            {{
              jobDetail.pass_threshold != null
                ? `${Math.round(jobDetail.pass_threshold * 100)}%`
                : '—'
            }}
          </a-descriptions-item>
        </a-descriptions>
        <a-divider>逐条结果</a-divider>
        <a-table
          :data-source="jobDetail.results || []"
          row-key="result_id"
          size="small"
          :pagination="false"
        >
          <a-table-column title="Item" data-index="case_id" ellipsis />
          <a-table-column title="通过" key="passed" width="70">
            <template #default="{ record }">
              <a-tag :color="record.passed ? 'green' : 'red'">{{ record.passed ? '是' : '否' }}</a-tag>
            </template>
          </a-table-column>
          <a-table-column title="详情" key="details" ellipsis>
            <template #default="{ record }">
              {{ (record.details?.messages || []).join('; ') || '—' }}
            </template>
          </a-table-column>
        </a-table>
      </template>
    </a-drawer>

    <a-modal v-model:open="evaluatorModalOpen" title="规则 Evaluator" ok-text="保存" @ok="saveEvaluator">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="evaluatorForm.name" />
        </a-form-item>
        <a-form-item label="Agent">
          <a-select v-model:value="evaluatorForm.agent_id" allow-clear style="width: 100%">
            <a-select-option v-for="a in agents" :key="a.agent_id" :value="a.agent_id">{{ a.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="禁止词（逗号分隔）">
          <a-input v-model:value="evaluatorForm.forbiddenText" placeholder="虚构,placeholder" />
        </a-form-item>
        <a-form-item label="最大耗时(ms)">
          <a-input-number v-model:value="evaluatorForm.max_duration_ms" :min="1000" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="queueModalOpen" title="标注队列" ok-text="创建" @ok="saveQueue">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="queueForm.name" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="queueForm.description" :rows="2" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-drawer v-model:open="queueDrawerOpen" title="标注队列 Items" width="560">
      <a-table :data-source="queueItems" row-key="item_id" size="small" :pagination="false">
        <a-table-column title="Run" data-index="run_id" ellipsis />
        <a-table-column title="状态" data-index="status" width="90" />
        <a-table-column title="操作" key="action" width="80">
          <template #default="{ record }">
            <a @click="markItemDone(record)">完成</a>
          </template>
        </a-table-column>
      </a-table>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { agentApi, evalApi, monitorApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()
const router = useRouter()

const activeTab = ref('datasets')
const agents = ref([])
const datasets = ref([])
const jobs = ref([])
const filterAgentId = ref(undefined)
const jobDatasetFilter = ref(undefined)
const datasetsLoading = ref(false)
const jobsLoading = ref(false)

const datasetModalOpen = ref(false)
const datasetSaving = ref(false)
const editingDataset = ref(null)
const datasetForm = ref({ name: '', agent_id: undefined, description: '', tagsText: '' })

const experimentModalOpen = ref(false)
const experimentRunning = ref(false)
const experimentForm = ref({ dataset_id: undefined, pass_threshold: 0.8, run_mode: 'replay', evaluator_id: undefined })

const scoresAgentId = ref(undefined)
const scoresDays = ref(7)
const effectReport = ref(null)

const evaluators = ref([])
const evaluatorsLoading = ref(false)
const judgeEvaluators = ref([])
const evaluatorModalOpen = ref(false)
const evaluatorForm = ref({ name: '', agent_id: undefined, forbiddenText: '虚构,placeholder,TODO:', max_duration_ms: 120000 })

const annotationQueues = ref([])
const queueModalOpen = ref(false)
const queueForm = ref({ name: '', description: '' })
const queueDrawerOpen = ref(false)
const queueItems = ref([])
const activeQueueId = ref('')

const compareJobA = ref(undefined)
const compareJobB = ref(undefined)
const compareResult = ref(null)

const jobDrawerOpen = ref(false)
const jobDetail = ref(null)

const datasetColumns = [
  { title: '名称', key: 'name' },
  { title: 'Agent', key: 'agent', width: 140, ellipsis: true },
  { title: 'Items', dataIndex: 'case_count', width: 80 },
  { title: '标签', key: 'tags', width: 160 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'action', width: 300 },
]

const compareRows = computed(() => {
  if (!jobDatasetFilter.value) return []
  return (jobs.value || []).slice(0, 5)
})

function agentName(agentId) {
  if (!agentId) return '—'
  const a = agents.value.find((x) => x.agent_id === agentId)
  return a ? a.name : String(agentId).slice(0, 8)
}

function datasetName(datasetId) {
  const d = datasets.value.find((x) => x.dataset_id === datasetId)
  return d ? d.name : String(datasetId || '').slice(0, 8)
}

function syncTabFromRoute() {
  const tab = route.query.tab
  if (['experiments', 'scores', 'datasets', 'evaluators', 'annotation'].includes(tab)) {
    activeTab.value = tab
  }
}

function onTabChange(key) {
  router.replace({ path: '/eval', query: { ...route.query, tab: key } })
  if (key === 'experiments') fetchJobs()
  if (key === 'scores') fetchEffect()
  if (key === 'evaluators') fetchEvaluators()
  if (key === 'annotation') fetchAnnotationQueues()
}

async function loadAgents() {
  const list = await agentApi.list({ page_size: 100 })
  agents.value = list.items || []
}

async function fetchDatasets() {
  datasetsLoading.value = true
  try {
    const params = { page_size: 100 }
    if (filterAgentId.value) params.agent_id = filterAgentId.value
    const ds = await evalApi.listDatasets(params)
    datasets.value = ds.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    datasetsLoading.value = false
  }
}

async function fetchJobs() {
  jobsLoading.value = true
  try {
    const params = { page_size: 50 }
    if (jobDatasetFilter.value) params.dataset_id = jobDatasetFilter.value
    const res = await evalApi.listJobs(params)
    jobs.value = res.items || []
    compareResult.value = null
  } catch (e) {
    message.error(e.message)
  } finally {
    jobsLoading.value = false
  }
}

async function fetchEvaluators() {
  evaluatorsLoading.value = true
  try {
    const params = {}
    if (filterAgentId.value) params.agent_id = filterAgentId.value
    const res = await evalApi.listEvaluators(params)
    evaluators.value = res.items || []
    const jres = await evalApi.listJudgeEvaluators()
    judgeEvaluators.value = jres.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    evaluatorsLoading.value = false
  }
}

async function fetchAnnotationQueues() {
  try {
    const res = await evalApi.listAnnotationQueues()
    annotationQueues.value = res.items || []
  } catch (e) {
    message.error(e.message)
  }
}

async function loadCompare() {
  if (!compareJobA.value || !compareJobB.value) return
  try {
    compareResult.value = await evalApi.compareJobs({ job_a: compareJobA.value, job_b: compareJobB.value })
  } catch (e) {
    message.error(e.message)
  }
}

function openEvaluatorModal() {
  evaluatorForm.value = { name: '', agent_id: filterAgentId.value, forbiddenText: '虚构,placeholder,TODO:', max_duration_ms: 120000 }
  evaluatorModalOpen.value = true
}

async function saveEvaluator() {
  const name = (evaluatorForm.value.name || '').trim()
  if (!name) {
    message.warning('请填写名称')
    return
  }
  const forbidden = (evaluatorForm.value.forbiddenText || '').split(',').map((s) => s.trim()).filter(Boolean)
  try {
    await evalApi.createEvaluator({
      name,
      agent_id: evaluatorForm.value.agent_id || '',
      enabled: true,
      rules_json: {
        forbidden_patterns: forbidden,
        max_duration_ms: evaluatorForm.value.max_duration_ms || 120000,
        pass_threshold: 0.8,
      },
    })
    evaluatorModalOpen.value = false
    await fetchEvaluators()
  } catch (e) {
    message.error(e.message)
  }
}

async function removeEvaluator(id) {
  await evalApi.deleteEvaluator(id)
  await fetchEvaluators()
}

function openQueueModal() {
  queueForm.value = { name: '', description: '' }
  queueModalOpen.value = true
}

async function saveQueue() {
  const name = (queueForm.value.name || '').trim()
  if (!name) return
  await evalApi.createAnnotationQueue(queueForm.value)
  queueModalOpen.value = false
  await fetchAnnotationQueues()
}

async function openQueueItems(queue) {
  activeQueueId.value = queue.queue_id
  queueItems.value = (await evalApi.listAnnotationItems(queue.queue_id)).items || []
  queueDrawerOpen.value = true
}

async function markItemDone(item) {
  await evalApi.updateAnnotationItem(activeQueueId.value, item.item_id, { status: 'done' })
  queueItems.value = (await evalApi.listAnnotationItems(activeQueueId.value)).items || []
  await fetchAnnotationQueues()
}

async function fetchEffect() {
  if (!scoresAgentId.value) {
    effectReport.value = null
    return
  }
  try {
    effectReport.value = await monitorApi.effectReport({
      agent_id: scoresAgentId.value,
      days: scoresDays.value,
    })
  } catch (e) {
    message.error(e.message)
  }
}

function openCreateDataset() {
  editingDataset.value = null
  datasetForm.value = { name: '', agent_id: undefined, description: '', tagsText: '' }
  datasetModalOpen.value = true
}

function openEditDataset(record) {
  editingDataset.value = record
  datasetForm.value = {
    name: record.name,
    agent_id: record.agent_id || undefined,
    description: record.description || '',
    tagsText: (record.tags || []).join(', '),
  }
  datasetModalOpen.value = true
}

async function saveDataset() {
  const name = (datasetForm.value.name || '').trim()
  if (!name) {
    message.warning('请填写名称')
    return
  }
  const tags = (datasetForm.value.tagsText || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const payload = {
    name,
    agent_id: datasetForm.value.agent_id || '',
    description: datasetForm.value.description || '',
    tags,
  }
  datasetSaving.value = true
  try {
    if (editingDataset.value?.dataset_id) {
      await evalApi.updateDataset(editingDataset.value.dataset_id, payload)
      message.success('更新成功')
    } else {
      await evalApi.createDataset(payload)
      message.success('创建成功')
    }
    datasetModalOpen.value = false
    await fetchDatasets()
  } catch (e) {
    message.error(e.message)
  } finally {
    datasetSaving.value = false
  }
}

async function removeDataset(datasetId) {
  try {
    await evalApi.deleteDataset(datasetId)
    message.success('已删除')
    await fetchDatasets()
  } catch (e) {
    message.error(e.message)
  }
}

function openCreateExperiment() {
  experimentForm.value = {
    dataset_id: jobDatasetFilter.value || datasets.value[0]?.dataset_id,
    pass_threshold: 0.8,
  }
  experimentModalOpen.value = true
}

async function createAndRunExperiment() {
  if (!experimentForm.value.dataset_id) {
    message.warning('请选择 Dataset')
    return
  }
  const ds = datasets.value.find((d) => d.dataset_id === experimentForm.value.dataset_id)
  experimentRunning.value = true
  try {
    const job = await evalApi.createJob({
      dataset_id: experimentForm.value.dataset_id,
      agent_id: ds?.agent_id || '',
      pass_threshold: experimentForm.value.pass_threshold ?? 0.8,
      run_mode: experimentForm.value.run_mode || 'replay',
      evaluator_id: experimentForm.value.evaluator_id || '',
    })
    const result = await evalApi.runJob(job.job_id)
    const rate = result.summary?.pass_rate
    message.info(rate != null ? `Experiment 完成: ${Math.round(rate * 100)}%` : `完成: ${result.status}`)
    experimentModalOpen.value = false
    activeTab.value = 'experiments'
    jobDatasetFilter.value = experimentForm.value.dataset_id
    await fetchJobs()
  } catch (e) {
    message.error(e.message)
  } finally {
    experimentRunning.value = false
  }
}

async function quickRunExperiment(record) {
  experimentForm.value = {
    dataset_id: record.dataset_id,
    pass_threshold: 0.8,
  }
  experimentModalOpen.value = true
}

async function viewJob(jobId) {
  try {
    jobDetail.value = await evalApi.getJob(jobId)
    jobDrawerOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

watch(
  () => route.query,
  () => {
    syncTabFromRoute()
    if (route.query.create === '1' && activeTab.value === 'datasets') {
      openCreateDataset()
      const q = { ...route.query }
      delete q.create
      router.replace({ path: '/eval', query: { ...q, tab: 'datasets' } })
    }
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    await loadAgents()
    await fetchDatasets()
    syncTabFromRoute()
    if (activeTab.value === 'experiments') await fetchJobs()
    if (activeTab.value === 'scores') await fetchEffect()
    if (activeTab.value === 'evaluators') await fetchEvaluators()
    if (activeTab.value === 'annotation') await fetchAnnotationQueues()
    if (route.query.create === '1') {
      openCreateDataset()
      const q = { ...route.query }
      delete q.create
      router.replace({ path: '/eval', query: { ...q, tab: 'datasets' } })
    }
  } catch (e) {
    message.error(e.message)
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
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
</style>

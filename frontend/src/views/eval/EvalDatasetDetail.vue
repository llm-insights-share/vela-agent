<template>
  <div>
    <div class="page-header">
      <a-space>
        <a-button @click="$router.push('/eval?tab=datasets')">← 返回评测</a-button>
        <h2 class="page-title">{{ dataset.name || 'Dataset 详情' }}</h2>
      </a-space>
      <a-space>
        <a-button type="primary" @click="openRunExperiment">运行 Experiment</a-button>
        <a-button @click="openCaseModal()">新增 Item</a-button>
      </a-space>
    </div>

    <a-descriptions bordered size="small" :column="2" style="margin-bottom: 16px">
      <a-descriptions-item label="Agent">{{ agentName(dataset.agent_id) }}</a-descriptions-item>
      <a-descriptions-item label="Items">{{ cases.length }}</a-descriptions-item>
      <a-descriptions-item label="描述" :span="2">{{ dataset.description || '—' }}</a-descriptions-item>
    </a-descriptions>

    <a-card title="Dataset Items" style="margin-bottom: 16px">
      <template #extra>
        <a-space>
          <a-input
            v-model:value="importRunId"
            placeholder="Trace Run ID 导入"
            style="width: 220px"
          />
          <a-button :disabled="!importRunId" @click="importFromRun">导入</a-button>
        </a-space>
      </template>
      <a-table :data-source="cases" row-key="case_id" size="small" :loading="loading">
        <a-table-column title="输入" data-index="input_text" ellipsis />
        <a-table-column title="期望工具" key="expected_tools" width="140">
          <template #default="{ record }">
            <a-tag v-for="t in record.expected_tools || []" :key="t">{{ t }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="期望关键词" key="expected_keywords" width="120">
          <template #default="{ record }">
            <a-tag v-for="k in record.expected_keywords || []" :key="k">{{ k }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="期望输出" data-index="expected_output" width="140" ellipsis />
        <a-table-column title="Rubric" data-index="rubric" width="140" ellipsis />
        <a-table-column title="来源 Trace" key="source_run_id" width="120">
          <template #default="{ record }">
            <a v-if="record.source_run_id" @click="goMonitor(record.source_run_id)">
              {{ record.source_run_id.slice(0, 8) }}…
            </a>
            <span v-else>—</span>
          </template>
        </a-table-column>
        <a-table-column title="操作" key="action" width="120">
          <template #default="{ record }">
            <a-space>
              <a @click="openCaseModal(record)">编辑</a>
              <a-popconfirm title="确认删除 Item？" @confirm="removeCase(record.case_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </a-table-column>
      </a-table>
    </a-card>

    <a-card title="Experiments">
      <a-table :data-source="jobs" row-key="job_id" size="small" :loading="jobsLoading">
        <a-table-column title="时间" key="created_at" width="170">
          <template #default="{ record }">{{ formatDateTime(record.created_at) }}</template>
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
    </a-card>

    <a-modal
      v-model:open="caseModalOpen"
      :title="editingCase ? '编辑 Item' : '新增 Item'"
      ok-text="保存"
      cancel-text="取消"
      :confirm-loading="caseSaving"
      width="640px"
      @ok="saveCase"
    >
      <a-form layout="vertical">
        <a-form-item label="输入文本">
          <a-textarea v-model:value="caseForm.input_text" :rows="3" />
        </a-form-item>
        <a-form-item label="期望工具（逗号分隔）">
          <a-input v-model:value="caseForm.expectedToolsText" placeholder="get_forecast, search" />
        </a-form-item>
        <a-form-item label="期望关键词（逗号分隔）">
          <a-input v-model:value="caseForm.expectedKeywordsText" placeholder="温度, 结果" />
        </a-form-item>
        <a-form-item label="期望输出 (expected_output)">
          <a-textarea v-model:value="caseForm.expected_output" :rows="2" placeholder="期望助手回复内容" />
        </a-form-item>
        <a-form-item label="Rubric">
          <a-textarea v-model:value="caseForm.rubric" :rows="2" />
        </a-form-item>
        <a-form-item label="来源 Trace Run ID">
          <a-input v-model:value="caseForm.source_run_id" placeholder="可选，关联监控 Trace" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="experimentModalOpen"
      title="运行 Experiment"
      ok-text="运行"
      cancel-text="取消"
      :confirm-loading="experimentRunning"
      @ok="runEvalJob"
    >
      <a-form layout="vertical">
        <a-form-item label="通过率阈值">
          <a-input-number
            v-model:value="passThreshold"
            :min="0"
            :max="1"
            :step="0.05"
            style="width: 100%"
          />
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
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { agentApi, evalApi } from '../../api'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()
const router = useRouter()
const datasetId = route.params.id

const loading = ref(false)
const jobsLoading = ref(false)
const dataset = ref({})
const cases = ref([])
const jobs = ref([])
const agents = ref([])
const importRunId = ref('')
const caseModalOpen = ref(false)
const caseSaving = ref(false)
const editingCase = ref(null)
const caseForm = ref({
  input_text: '',
  expected_output: '',
  expectedToolsText: '',
  expectedKeywordsText: '',
  rubric: '',
  source_run_id: '',
})
const jobDrawerOpen = ref(false)
const jobDetail = ref(null)
const experimentModalOpen = ref(false)
const experimentRunning = ref(false)
const passThreshold = ref(0.8)

function agentName(agentId) {
  if (!agentId) return '—'
  const a = agents.value.find((x) => x.agent_id === agentId)
  return a ? a.name : agentId
}

function splitCsv(text) {
  return (text || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function resetCaseForm() {
  caseForm.value = {
    input_text: '',
    expected_output: '',
    expectedToolsText: '',
    expectedKeywordsText: '',
    rubric: '',
    source_run_id: '',
  }
}

function openCaseModal(record = null) {
  editingCase.value = record
  if (record) {
    caseForm.value = {
      input_text: record.input_text || '',
      expected_output: record.expected_output || '',
      expectedToolsText: (record.expected_tools || []).join(', '),
      expectedKeywordsText: (record.expected_keywords || []).join(', '),
      rubric: record.rubric || '',
      source_run_id: record.source_run_id || '',
    }
  } else {
    resetCaseForm()
  }
  caseModalOpen.value = true
}

function openRunExperiment() {
  passThreshold.value = 0.8
  experimentModalOpen.value = true
}

async function fetchAll() {
  loading.value = true
  jobsLoading.value = true
  try {
    const [ds, cs, js, ag] = await Promise.all([
      evalApi.getDataset(datasetId),
      evalApi.listCases(datasetId),
      evalApi.listJobs({ dataset_id: datasetId, page_size: 50 }),
      agentApi.list({ page_size: 100 }),
    ])
    dataset.value = ds || {}
    cases.value = cs.items || []
    jobs.value = js.items || []
    agents.value = ag.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
    jobsLoading.value = false
  }
}

async function saveCase() {
  const payload = {
    input_text: caseForm.value.input_text || '',
    expected_output: caseForm.value.expected_output || '',
    expected_tools: splitCsv(caseForm.value.expectedToolsText),
    expected_keywords: splitCsv(caseForm.value.expectedKeywordsText),
    rubric: caseForm.value.rubric || '',
    source_run_id: caseForm.value.source_run_id || '',
  }
  caseSaving.value = true
  try {
    if (editingCase.value?.case_id) {
      await evalApi.updateCase(datasetId, editingCase.value.case_id, payload)
      message.success('Item 已更新')
    } else {
      await evalApi.createCase(datasetId, payload)
      message.success('Item 已添加')
    }
    caseModalOpen.value = false
    await fetchAll()
  } catch (e) {
    message.error(e.message)
  } finally {
    caseSaving.value = false
  }
}

async function removeCase(caseId) {
  try {
    await evalApi.deleteCase(datasetId, caseId)
    message.success('已删除')
    await fetchAll()
  } catch (e) {
    message.error(e.message)
  }
}

async function importFromRun() {
  const runId = (importRunId.value || '').trim()
  if (!runId) return
  try {
    await evalApi.importRun(datasetId, runId)
    message.success('已从 Trace 导入')
    importRunId.value = ''
    await fetchAll()
  } catch (e) {
    message.error(e.message)
  }
}

async function runEvalJob() {
  experimentRunning.value = true
  try {
    const job = await evalApi.createJob({
      dataset_id: datasetId,
      agent_id: dataset.value.agent_id || '',
      pass_threshold: passThreshold.value ?? 0.8,
    })
    const result = await evalApi.runJob(job.job_id)
    const rate = result.summary?.pass_rate
    message.info(
      rate != null ? `Experiment 完成: ${Math.round(rate * 100)}%` : `完成: ${result.status}`,
    )
    experimentModalOpen.value = false
    await fetchAll()
  } catch (e) {
    message.error(e.message)
  } finally {
    experimentRunning.value = false
  }
}

async function viewJob(jobId) {
  try {
    jobDetail.value = await evalApi.getJob(jobId)
    jobDrawerOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

function goMonitor(runId) {
  router.push({ path: '/monitor', query: { run_id: runId } })
}

onMounted(fetchAll)
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

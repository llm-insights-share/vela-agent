<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">系统配置</h2>
    </div>

    <a-card title="工具配置" style="margin-bottom: 24px;">
      <a-collapse v-model:activeKey="activeKeys">
        <a-collapse-panel key="tavily" header="Tavily Web Search">
          <template #extra>
            <a-tag v-if="tavilyStatus.configured" color="green">已配置</a-tag>
            <a-tag v-else color="orange">未配置</a-tag>
          </template>
          <a-form :model="tavilyForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
            <a-form-item label="API Key">
              <a-input-password
                v-model:value="tavilyForm.api_key"
                placeholder="输入 Tavily API Key"
              />
              <div class="field-hint">
                在 <a href="https://tavily.com/" target="_blank">tavily.com</a> 注册获取 API Key。
                配置后，Agent 可使用内置的 <code>tavily_web_search</code> 工具进行网络搜索。
              </div>
            </a-form-item>
            <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
              <a-button type="primary" :loading="tavilySaving" @click="saveTavily">保存</a-button>
              <a-button style="margin-left: 12px;" @click="testTavily" :loading="tavilyTesting">测试连接</a-button>
            </a-form-item>
          </a-form>
          <div v-if="tavilyTestResult" style="margin-top: 12px;">
            <a-alert
              :type="tavilyTestResult.success ? 'success' : 'error'"
              :message="tavilyTestResult.message"
              show-icon
            />
          </div>
        </a-collapse-panel>
      </a-collapse>
    </a-card>

    <a-card title="记忆模块" style="margin-bottom: 24px;">
      <div class="field-hint" style="margin-bottom: 16px;">
        为各 Agent 开关记忆闭环（自我记录 / 自我处理 / 自我检索）。开启后，对话过程会自动写入情景事件，会话关闭时蒸馏语义记忆，并在后续对话中自动召回。
      </div>
      <a-table
        :columns="memoryColumns"
        :data-source="memoryAgents"
        :loading="memoryLoading"
        row-key="agent_id"
        :pagination="false"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag>{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'memory_enabled'">
            <a-switch
              :checked="record.memory_enabled"
              @change="(checked) => onMemoryToggle(record, checked)"
            />
          </template>
        </template>
      </a-table>
      <div style="margin-top: 16px;">
        <a-button type="primary" :loading="memorySaving" @click="saveMemoryMounts">
          保存挂载配置
        </a-button>
        <a-button style="margin-left: 12px;" @click="fetchMemoryAgents">刷新</a-button>
      </div>
    </a-card>

    <a-card title="Query 改写引擎" style="margin-bottom: 24px;">
      <div class="field-hint" style="margin-bottom: 16px;">
        为各 Agent 开关 Query 改写引擎。开启后，对话进入检索 / 工具前会自动判断是否需要改写，并按 T0 透传 / T1 规则 / T2 LLM 路由执行。
      </div>
      <a-table
        :columns="rewriteColumns"
        :data-source="rewriteAgents"
        :loading="rewriteLoading"
        row-key="agent_id"
        :pagination="false"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag>{{ record.status }}</a-tag>
          </template>
          <template v-else-if="column.key === 'query_rewrite_enabled'">
            <a-switch
              :checked="record.query_rewrite_enabled"
              @change="(checked) => onRewriteToggle(record, checked)"
            />
          </template>
        </template>
      </a-table>
      <div style="margin-top: 16px;">
        <a-button type="primary" :loading="rewriteSaving" @click="saveRewriteMounts">
          保存挂载配置
        </a-button>
        <a-button style="margin-left: 12px;" @click="fetchRewriteAgents">刷新</a-button>
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { configApi } from '../../api'
import { message } from 'ant-design-vue'

const activeKeys = ref(['tavily'])
const tavilySaving = ref(false)
const tavilyTesting = ref(false)
const tavilyTestResult = ref(null)

const tavilyStatus = reactive({
  configured: false,
})

const tavilyForm = reactive({
  api_key: '',
})

const memoryAgents = ref([])
const memoryLoading = ref(false)
const memorySaving = ref(false)
const memoryColumns = [
  { title: 'Agent', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status', width: 120 },
  { title: '挂载记忆', key: 'memory_enabled', width: 120 },
]

const rewriteAgents = ref([])
const rewriteLoading = ref(false)
const rewriteSaving = ref(false)
const rewriteColumns = [
  { title: 'Agent', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status', width: 120 },
  { title: '挂载改写', key: 'query_rewrite_enabled', width: 120 },
]

async function fetchConfig() {
  try {
    const res = await configApi.getToolConfig()
    const tavily = res.tavily || {}
    tavilyStatus.configured = !!tavily.api_key
  } catch (e) {
    // ignore
  }
  try {
    const status = await configApi.getTavilyStatus()
    tavilyStatus.configured = status.configured
  } catch (e) {
    // ignore
  }
}

async function saveTavily() {
  if (!tavilyForm.api_key) {
    message.warning('请输入 API Key')
    return
  }
  tavilySaving.value = true
  try {
    await configApi.updateTavily({ api_key: tavilyForm.api_key })
    message.success('Tavily 配置已保存')
    tavilyForm.api_key = ''
    await fetchConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    tavilySaving.value = false
  }
}

async function testTavily() {
  tavilyTesting.value = true
  tavilyTestResult.value = null
  try {
    const status = await configApi.getTavilyStatus()
    if (status.configured) {
      tavilyTestResult.value = { success: true, message: 'API Key 已配置，Tavily Web Search 工具可用' }
    } else {
      tavilyTestResult.value = { success: false, message: 'API Key 未配置，请先保存 API Key' }
    }
  } catch (e) {
    tavilyTestResult.value = { success: false, message: '检查失败: ' + e.message }
  } finally {
    tavilyTesting.value = false
  }
}

async function fetchMemoryAgents() {
  memoryLoading.value = true
  try {
    memoryAgents.value = await configApi.listMemoryAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    memoryLoading.value = false
  }
}

function onMemoryToggle(record, checked) {
  record.memory_enabled = checked
}

async function saveMemoryMounts() {
  memorySaving.value = true
  try {
    const items = memoryAgents.value.map((a) => ({
      agent_id: a.agent_id,
      memory_enabled: !!a.memory_enabled,
    }))
    const res = await configApi.updateMemoryAgents(items)
    message.success(res.message || '记忆模块挂载配置已保存')
    await fetchMemoryAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    memorySaving.value = false
  }
}

async function fetchRewriteAgents() {
  rewriteLoading.value = true
  try {
    rewriteAgents.value = await configApi.listQueryRewriteAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    rewriteLoading.value = false
  }
}

function onRewriteToggle(record, checked) {
  record.query_rewrite_enabled = checked
}

async function saveRewriteMounts() {
  rewriteSaving.value = true
  try {
    const items = rewriteAgents.value.map((a) => ({
      agent_id: a.agent_id,
      query_rewrite_enabled: !!a.query_rewrite_enabled,
    }))
    const res = await configApi.updateQueryRewriteAgents(items)
    message.success(res.message || 'Query改写引擎挂载配置已保存')
    await fetchRewriteAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    rewriteSaving.value = false
  }
}

onMounted(async () => {
  await fetchConfig()
  await fetchMemoryAgents()
  await fetchRewriteAgents()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.field-hint {
  font-size: 11px;
  color: #9e9590;
  margin-top: 4px;
  line-height: 1.5;
}
.field-hint code {
  font-size: 11px;
  background: #f3f0e8;
  padding: 1px 5px;
  border-radius: 3px;
  color: #5c5650;
}
</style>

<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">系统配置</h2>
    </div>

    <a-card style="margin-bottom: 24px;">
      <template #title>工具配置</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.tools ? '展开' : '收起'"
          :aria-label="cardCollapsed.tools ? '展开' : '收起'"
          @click.stop="cardCollapsed.tools = !cardCollapsed.tools"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.tools" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.tools">
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
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>代码执行沙箱 (Code Interpreter)</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.codeExec ? '展开' : '收起'"
          @click.stop="cardCollapsed.codeExec = !cardCollapsed.codeExec"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.codeExec" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.codeExec">
        <div class="field-hint" style="margin-bottom: 16px;">
          控制 Agent 内置 <code>execute_code</code> 工具的加固沙箱：独立 venv、资源限制、产物捕获与跨调用变量状态。
        </div>
        <a-form :model="codeExecForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="启用">
            <a-switch v-model:checked="codeExecForm.enabled" />
          </a-form-item>
          <a-form-item label="超时 (秒)">
            <a-input-number v-model:value="codeExecForm.wall_timeout" :min="10" :max="600" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="CPU 限制 (秒)">
            <a-input-number v-model:value="codeExecForm.cpu_seconds" :min="5" :max="300" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="内存 (MB)">
            <a-input-number v-model:value="codeExecForm.memory_mb" :min="256" :max="8192" style="width: 160px;" />
            <div class="field-hint">macOS 上内存限制可能不生效</div>
          </a-form-item>
          <a-form-item label="允许网络">
            <a-switch v-model:checked="codeExecForm.allow_network" />
          </a-form-item>
          <a-form-item label="允许安装包">
            <a-switch v-model:checked="codeExecForm.allow_install" />
          </a-form-item>
          <a-form-item label="状态持久化">
            <a-switch v-model:checked="codeExecForm.state_persist" />
          </a-form-item>
          <a-form-item label="包白名单">
            <a-select
              v-model:value="codeExecForm.package_allowlist"
              mode="tags"
              style="width: 100%;"
              placeholder="pandas, numpy, matplotlib..."
            />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="codeExecSaving" @click="saveCodeExec">保存</a-button>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>知识库 · 上下文感知检索</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.contextual ? '展开' : '收起'"
          @click.stop="cardCollapsed.contextual = !cardCollapsed.contextual"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.contextual" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.contextual">
        <div class="field-hint" style="margin-bottom: 16px;">
          在向量化前为每个分块生成 LLM 上下文前缀（Anthropic Contextual Retrieval），提升检索召回质量。
          索引时使用「前缀 + 原文」，检索返回仍为原始分块。
        </div>
        <a-form :model="contextualForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="全局启用">
            <a-switch v-model:checked="contextualForm.enabled" />
          </a-form-item>
          <a-form-item label="前缀生成模型">
            <a-select
              v-model:value="contextualForm.model_service_id"
              allow-clear
              placeholder="默认使用第一个可用模型服务"
              :options="modelServiceOptions"
              style="width: 100%"
            />
          </a-form-item>
          <a-form-item label="并发数">
            <a-input-number v-model:value="contextualForm.max_concurrency" :min="1" :max="32" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="单块超时 (秒)">
            <a-input-number v-model:value="contextualForm.chunk_timeout_seconds" :min="5" :max="120" style="width: 160px;" />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="contextualSaving" @click="saveContextual">保存</a-button>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>打开驭屏系统</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.screenpilot ? '展开' : '收起'"
          :aria-label="cardCollapsed.screenpilot ? '展开' : '收起'"
          @click.stop="cardCollapsed.screenpilot = !cardCollapsed.screenpilot"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.screenpilot" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.screenpilot">
        <div class="screenpilot-card">
          <div class="screenpilot-card-main">
            <div>
              <div class="field-hint" style="margin-bottom: 8px;">
                打开后自动注册 {{ screenpilot.tools.length || 10 }} 个 <code>cu_*</code> MCP 工具（导航 / 观测 / 动作 / 提取 / 技能重放 / 技能编译 / 技能搜索 / 任务执行 / OTP / Vision）。关闭则移除这些工具并解除 Agent 绑定。
                可在 <a href="/tools">工具管理</a> 中查看。
              </div>
              <div v-if="screenpilot.tools.length" class="sp-tools">
                <a-tag v-for="t in screenpilot.tools" :key="t.tool_id" color="blue">
                  {{ t.name }}
                </a-tag>
              </div>
              <div v-else class="field-hint">当前未注册驭屏 MCP 工具</div>
            </div>
            <a-switch
              :checked="screenpilot.enabled"
              :loading="screenpilotSaving"
              checked-children="已打开"
              un-checked-children="已关闭"
              @change="onScreenpilotToggle"
            />
          </div>
        </div>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>Letta 记忆服务</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.letta ? '展开' : '收起'"
          :aria-label="cardCollapsed.letta ? '展开' : '收起'"
          @click.stop="cardCollapsed.letta = !cardCollapsed.letta"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.letta" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.letta">
        <div class="field-hint" style="margin-bottom: 16px;">
          自托管 Letta 提供核心记忆（blocks）与归档记忆（语义检索）。LLM / Embedding 通过 vela 网关回连本系统的模型服务与知识库同款嵌入模型，无需外部 API Key。
        </div>
        <a-form :model="lettaForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="启用">
            <a-switch v-model:checked="lettaForm.enabled" />
          </a-form-item>
          <a-form-item label="服务地址">
            <a-input v-model:value="lettaForm.base_url" placeholder="http://127.0.0.1:8283" />
          </a-form-item>
          <a-form-item label="访问密码">
            <a-input-password v-model:value="lettaForm.password" placeholder="留空或保持掩码表示不修改" />
          </a-form-item>
          <a-form-item label="网关地址">
            <a-input v-model:value="lettaForm.gateway_base" placeholder="http://127.0.0.1:8000" />
          </a-form-item>
          <a-form-item label="网关密钥">
            <a-input-password v-model:value="lettaForm.gateway_token" placeholder="留空或保持掩码表示不修改" />
          </a-form-item>
          <a-form-item label="蒸馏模型服务">
            <a-select
              v-model:value="lettaForm.distill_model_service_id"
              allow-clear
              placeholder="默认使用各 Agent 自己的模型服务"
              :options="modelServiceOptions"
              style="width: 100%"
            />
            <div class="field-hint">须支持 function calling（如 DeepSeek-chat / qwen-max）</div>
          </a-form-item>
          <a-form-item label="Embedding">
            <a-input
              :value="`${lettaMeta.embedding_model} · ${lettaMeta.embedding_dim} 维`"
              disabled
            />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="lettaSaving" @click="saveLetta">保存</a-button>
            <a-button style="margin-left: 12px;" :loading="lettaTesting" @click="testLetta">测试连接</a-button>
          </a-form-item>
        </a-form>
        <div v-if="lettaTestResult" style="margin-top: 12px;">
          <a-alert
            :type="lettaTestResult.success ? 'success' : 'error'"
            :message="lettaTestResult.message"
            show-icon
          />
        </div>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>记忆模块</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.memory ? '展开' : '收起'"
          :aria-label="cardCollapsed.memory ? '展开' : '收起'"
          @click.stop="cardCollapsed.memory = !cardCollapsed.memory"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.memory" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.memory">
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
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>Query 改写引擎</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.rewrite ? '展开' : '收起'"
          :aria-label="cardCollapsed.rewrite ? '展开' : '收起'"
          @click.stop="cardCollapsed.rewrite = !cardCollapsed.rewrite"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.rewrite" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.rewrite">
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
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { UpOutlined, DownOutlined } from '@ant-design/icons-vue'
import { configApi, serviceApi, memoryApi } from '../../api'
import { message } from 'ant-design-vue'

const cardCollapsed = reactive({
  tools: true,
  codeExec: true,
  contextual: true,
  screenpilot: true,
  letta: true,
  memory: true,
  rewrite: true,
})

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

const codeExecForm = reactive({
  enabled: true,
  wall_timeout: 60,
  cpu_seconds: 30,
  memory_mb: 2048,
  allow_network: false,
  allow_install: true,
  state_persist: true,
  package_allowlist: ['pandas', 'numpy', 'matplotlib'],
})
const codeExecSaving = ref(false)

const contextualForm = reactive({
  enabled: false,
  model_service_id: undefined,
  max_concurrency: 12,
  chunk_timeout_seconds: 30,
})
const contextualSaving = ref(false)

const lettaForm = reactive({
  enabled: true,
  base_url: 'http://127.0.0.1:8283',
  password: '',
  gateway_base: 'http://127.0.0.1:8000',
  gateway_token: '',
  distill_model_service_id: undefined,
})
const lettaMeta = reactive({
  embedding_model: 'vela-embedding',
  embedding_dim: 1024,
})
const lettaSaving = ref(false)
const lettaTesting = ref(false)
const lettaTestResult = ref(null)
const modelServiceOptions = ref([])

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

const screenpilotSaving = ref(false)
const screenpilot = reactive({
  enabled: false,
  tools: [],
})

async function fetchCodeExecConfig() {
  try {
    const cfg = await configApi.getCodeExec()
    codeExecForm.enabled = !!cfg.enabled
    codeExecForm.wall_timeout = cfg.wall_timeout ?? 60
    codeExecForm.cpu_seconds = cfg.cpu_seconds ?? 30
    codeExecForm.memory_mb = cfg.memory_mb ?? 2048
    codeExecForm.allow_network = !!cfg.allow_network
    codeExecForm.allow_install = cfg.allow_install !== false
    codeExecForm.state_persist = cfg.state_persist !== false
    codeExecForm.package_allowlist = cfg.package_allowlist || []
  } catch (e) {
    // ignore
  }
}

async function saveCodeExec() {
  codeExecSaving.value = true
  try {
    const res = await configApi.updateCodeExec({ ...codeExecForm })
    message.success(res.message || '代码执行沙箱配置已保存')
  } catch (e) {
    message.error(e.message)
  } finally {
    codeExecSaving.value = false
  }
}

async function fetchContextualConfig() {
  try {
    const cfg = await configApi.getContextualRetrieval()
    contextualForm.enabled = !!cfg.enabled
    contextualForm.model_service_id = cfg.model_service_id || undefined
    contextualForm.max_concurrency = cfg.max_concurrency ?? 12
    contextualForm.chunk_timeout_seconds = cfg.chunk_timeout_seconds ?? 30
  } catch (e) {
    // ignore
  }
}

async function saveContextual() {
  contextualSaving.value = true
  try {
    await configApi.updateContextualRetrieval({
      enabled: !!contextualForm.enabled,
      model_service_id: contextualForm.model_service_id || '',
      max_concurrency: contextualForm.max_concurrency,
      chunk_timeout_seconds: contextualForm.chunk_timeout_seconds,
    })
    message.success('上下文感知检索配置已保存')
    await fetchContextualConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    contextualSaving.value = false
  }
}

async function fetchScreenpilot() {
  try {
    const res = await configApi.getScreenpilot()
    screenpilot.enabled = !!res.enabled
    screenpilot.tools = res.tools || []
  } catch (e) {
    // ignore
  }
}

async function onScreenpilotToggle(checked) {
  screenpilotSaving.value = true
  try {
    const res = await configApi.updateScreenpilot({ enabled: !!checked })
    screenpilot.enabled = !!res.enabled
    screenpilot.tools = res.tools || []
    message.success(res.message || (checked ? '驭屏系统已打开' : '驭屏系统已关闭'))
  } catch (e) {
    message.error(e.message)
    await fetchScreenpilot()
  } finally {
    screenpilotSaving.value = false
  }
}

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

async function fetchLettaConfig() {
  try {
    const cfg = await configApi.getLetta()
    lettaForm.enabled = !!cfg.enabled
    lettaForm.base_url = cfg.base_url || ''
    lettaForm.password = cfg.password || ''
    lettaForm.gateway_base = cfg.gateway_base || ''
    lettaForm.gateway_token = cfg.gateway_token || ''
    lettaForm.distill_model_service_id = cfg.distill_model_service_id || undefined
    lettaMeta.embedding_model = cfg.embedding_model || 'vela-embedding'
    lettaMeta.embedding_dim = cfg.embedding_dim || 1024
  } catch (e) {
    // ignore
  }
}

async function fetchModelServices() {
  try {
    const res = await serviceApi.list({ page: 1, page_size: 100 })
    modelServiceOptions.value = (res.items || []).map((s) => ({
      label: `${s.display_name || s.model_name} (${s.model_name})`,
      value: s.model_service_id,
    }))
  } catch (e) {
    modelServiceOptions.value = []
  }
}

async function saveLetta() {
  lettaSaving.value = true
  try {
    const payload = {
      enabled: !!lettaForm.enabled,
      base_url: lettaForm.base_url,
      gateway_base: lettaForm.gateway_base,
      distill_model_service_id: lettaForm.distill_model_service_id || '',
    }
    if (lettaForm.password && !String(lettaForm.password).includes('*')) {
      payload.password = lettaForm.password
    }
    if (lettaForm.gateway_token && !String(lettaForm.gateway_token).includes('*')) {
      payload.gateway_token = lettaForm.gateway_token
    }
    const res = await configApi.updateLetta(payload)
    message.success(res.message || 'Letta 配置已保存')
    await fetchLettaConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    lettaSaving.value = false
  }
}

async function testLetta() {
  lettaTesting.value = true
  lettaTestResult.value = null
  try {
    const s = await memoryApi.lettaStatus()
    if (s.healthy) {
      lettaTestResult.value = {
        success: true,
        message: `连接成功 · embedding ${s.embedding_model} (${s.embedding_dim}维) · 映射 ${s.mapping_count || 0}`,
      }
    } else {
      lettaTestResult.value = {
        success: false,
        message: `不可用: ${s.error || 'unknown'}（请确认已启动 backend/letta/start_letta.sh）`,
      }
    }
  } catch (e) {
    lettaTestResult.value = { success: false, message: e.message }
  } finally {
    lettaTesting.value = false
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
  await fetchCodeExecConfig()
  await fetchContextualConfig()
  await fetchScreenpilot()
  await fetchLettaConfig()
  await fetchModelServices()
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
.screenpilot-card-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}
.sp-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
</style>

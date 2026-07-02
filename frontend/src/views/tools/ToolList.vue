<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">工具管理</h2>
      <a-space>
        <a-button type="primary" @click="openCreate">
          <PlusOutlined /> 创建工具
        </a-button>
      </a-space>
    </div>
    <a-card>
      <a-table :columns="columns" :data-source="allTools" :loading="loading" row-key="tool_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'tool_type'">
            <a-tag :color="typeColor(record.tool_type)">{{ typeLabel(record.tool_type) }}</a-tag>
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'default'">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <template v-if="record.tool_type === 'builtin'">
              <a-tag color="default">系统内置</a-tag>
            </template>
            <template v-else>
              <a-space>
                <a @click="openEdit(record)">编辑</a>
                <a @click="openTest(record)">测试</a>
                <a-popconfirm title="确认删除?" @confirm="handleDelete(record.tool_id)">
                  <a style="color: #b5341c">删除</a>
                </a-popconfirm>
              </a-space>
            </template>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑工具' : '创建工具'" @ok="handleSave" :confirm-loading="saving" width="860px">
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 17 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="工具唯一标识名，如 weather_query" />
          <div class="field-hint">仅允许英文、数字和下划线，如：weather_query、search_docs</div>
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="form.display_name" placeholder="如：天气查询" />
          <div class="field-hint">用户可见的名称，如：天气查询、文档搜索</div>
        </a-form-item>
        <a-form-item label="类型" required>
          <a-select v-model:value="form.tool_type" @change="onTypeChange">
            <a-select-option value="mcp">MCP 调用</a-select-option>
            <a-select-option value="restful">RESTful 服务</a-select-option>
            <a-select-option value="local_python">本地 Python 代码</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="2" placeholder="工具功能描述" />
          <div class="field-hint">描述工具的功能和用途，Agent 会根据此描述决定何时调用该工具</div>
        </a-form-item>

        <a-divider orientation="left">配置</a-divider>

        <template v-if="form.tool_type === 'mcp'">
          <a-form-item label="MCP 命令">
            <a-input v-model:value="config.mcp_command" placeholder="如 npx" />
            <div class="field-hint">
              MCP 运行命令，如：<code>npx</code>、<code>python</code>、<code>node</code>、<code>uvx</code>
            </div>
          </a-form-item>
          <a-form-item label="MCP 参数">
            <a-textarea v-model:value="config.mcp_args_text" :rows="2" :placeholder="mcpArgsExample" />
            <div class="field-hint">
              JSON 数组格式，样例：<code>["-y", "@modelcontextprotocol/server-weather"]</code>
            </div>
          </a-form-item>
          <a-form-item label="环境变量">
            <a-textarea v-model:value="config.mcp_env_text" :rows="2" placeholder='{"API_KEY": "your-api-key"}' />
            <div class="field-hint">
              JSON 对象格式，可选，如：<code>{"API_KEY": "sk-xxx", "BASE_URL": "https://..."}</code>
            </div>
          </a-form-item>
          <a-form-item label="工具名称">
            <a-space direction="vertical" style="width: 100%;">
              <a-input v-model:value="config.mcp_tool_name" placeholder="单个工具如 get_weather，多个用逗号分隔如 read_query,write_query" />
              <a-space>
                <a-button size="small" :loading="discovering" @click="discoverTools">发现可用工具</a-button>
                <a-button
                  v-if="selectedDiscoveredNames.length > 0"
                  size="small"
                  type="primary"
                  ghost
                  @click="fillSelectedToolNames"
                >
                  填入已选 ({{ selectedDiscoveredNames.length }})
                </a-button>
                <a-button
                  v-if="discoveredTools.length > 0"
                  size="small"
                  type="primary"
                  @click="batchCreateTools"
                >
                  批量创建全部工具
                </a-button>
              </a-space>
            </a-space>
            <div class="field-hint">
              要调用的 MCP 工具名称，支持逗号分隔多个。多工具时 Agent 会通过 <code>tool_name</code> 参数自动选择。
            </div>
          </a-form-item>
          <div v-if="discoveredTools.length > 0" style="margin-top: 8px;">
            <div class="field-hint" style="margin-bottom: 6px;">已发现 {{ discoveredTools.length }} 个工具，点击可选中/取消：</div>
            <a-space wrap>
              <a-tag
                v-for="dt in discoveredTools"
                :key="dt.name"
                :color="selectedDiscoveredNames.includes(dt.name) ? 'blue' : 'default'"
                style="cursor: pointer;"
                @click="toggleDiscoveredTool(dt.name)"
              >
                <component :is="selectedDiscoveredNames.includes(dt.name) ? 'CheckCircleOutlined' : 'span'" />
                {{ dt.name }}
              </a-tag>
            </a-space>
            <div v-if="selectedDiscoveredNames.length > 0" class="field-hint" style="margin-top: 6px; color: #5c5650;">
              已选: {{ selectedDiscoveredNames.join(', ') }}
            </div>
          </div>
          <div v-if="discoverError" style="margin-top: 8px;">
            <a-alert type="error" :message="discoverError" closable @close="discoverError = ''" />
          </div>
        </template>

        <template v-if="form.tool_type === 'restful'">
          <a-form-item label="请求方法">
            <a-select v-model:value="config.restful_method">
              <a-select-option value="GET">GET</a-select-option>
              <a-select-option value="POST">POST</a-select-option>
              <a-select-option value="PUT">PUT</a-select-option>
              <a-select-option value="DELETE">DELETE</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="URL">
            <a-input v-model:value="config.restful_url" placeholder="https://api.example.com/v1/endpoint" />
            <div class="field-hint">
              完整 API 地址，可使用 <code>{参数名}</code> 占位，如：<code>https://api.weather.com/v1/{city}</code>
            </div>
          </a-form-item>
          <a-form-item label="请求头">
            <a-textarea v-model:value="config.restful_headers_text" :rows="2" placeholder='{"Authorization": "Bearer sk-xxx", "Content-Type": "application/json"}' />
            <div class="field-hint">
              JSON 对象格式，如：<code>{"Authorization": "Bearer xxx", "X-API-Key": "xxx"}</code>
            </div>
          </a-form-item>
          <a-form-item label="请求体模板">
            <a-textarea v-model:value="config.restful_body_template" :rows="3" placeholder='{"query": "{{query}}", "limit": 10}' />
            <div class="field-hint">
              使用 <code>&#123;&#123;参数名&#125;&#125;</code> 作为占位符，如：<code>{"city": "&#123;&#123;city&#125;&#125;", "lang": "zh"}</code>
            </div>
          </a-form-item>
        </template>

        <template v-if="form.tool_type === 'local_python'">
          <a-form-item label="Python 代码">
            <a-textarea v-model:value="config.python_code" :rows="10" :placeholder="pythonCodeExample" />
            <div class="field-hint">
              必须定义一个 <code>execute(params)</code> 函数，接收参数字典，返回结果字典。
              可用内置模块：<code>json</code>、<code>re</code>、<code>datetime</code>、<code>math</code>、<code>urllib</code> 等。
            </div>
          </a-form-item>
        </template>

        <a-divider orientation="left">
          参数定义
          <a-button size="small" type="link" @click="fillExampleSchema" style="margin-left: 8px;">填入示例</a-button>
        </a-divider>
        <a-form-item label="参数 Schema">
          <a-textarea v-model:value="paramsSchemaText" :rows="6" :placeholder="schemaExample" />
          <div class="field-hint">
            JSON Schema 格式定义工具参数。Agent 会根据此 Schema 生成正确的工具调用参数。
          </div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="testOpen" title="测试工具" :footer="null" width="700px">
      <a-form :label-col="{ span: 4 }" :wrapper-col="{ span: 18 }">
        <a-form-item v-if="testMcpToolNames.length > 1" label="选择工具">
          <a-select
            v-model:value="selectedTestMcpTool"
            placeholder="选择要测试的 MCP 工具"
            @change="onTestMcpToolChange"
          >
            <a-select-option v-for="name in testMcpToolNames" :key="name" :value="name">
              {{ name }}
            </a-select-option>
          </a-select>
          <div class="field-hint">该工具条目包含多个 MCP 子工具，请选择要测试的具体工具</div>
        </a-form-item>
        <a-form-item label="参数">
          <a-textarea v-model:value="testParams" :rows="6" placeholder='{"query": "test"}' />
        </a-form-item>
        <a-form-item :wrapper-col="{ offset: 4, span: 18 }">
          <a-button type="primary" :loading="testing" @click="handleTest">执行测试</a-button>
        </a-form-item>
      </a-form>
      <div v-if="testResult" style="margin-top: 16px">
        <a-divider />
        <h4>测试结果：</h4>
        <pre class="result-pre">{{ testResult }}</pre>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { PlusOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
import { toolApi } from '../../api'
import { message } from 'ant-design-vue'

const router = useRouter()
const loading = ref(false)
const tools = ref([])
const builtinTools = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const paramsSchemaText = ref('{}')

const testOpen = ref(false)
const testing = ref(false)
const testParams = ref('{}')
const testResult = ref(null)
let testToolId = null
const testToolRecord = ref(null)
const selectedTestMcpTool = ref('')

const discovering = ref(false)
const discoveredTools = ref([])
const discoverError = ref('')
const selectedDiscoveredNames = ref([])

const columns = [
  { title: '名称', dataIndex: 'name', width: 160 },
  { title: '显示名称', dataIndex: 'display_name', width: 150 },
  { title: '类型', key: 'tool_type', width: 120 },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '状态', key: 'status', width: 80 },
  { title: '操作', key: 'action', width: 150 },
]

const config = reactive({
  mcp_command: '',
  mcp_args_text: '[]',
  mcp_env_text: '{}',
  mcp_tool_name: '',
  restful_method: 'GET',
  restful_url: '',
  restful_headers_text: '{}',
  restful_body_template: '',
  python_code: '',
})

const form = reactive({
  name: '',
  display_name: '',
  tool_type: 'restful',
  description: '',
})

const mcpArgsExample = computed(() =>
  '["-y", "@modelcontextprotocol/server-weather"]'
)

const pythonCodeExample = computed(() =>
`def execute(params):
    """
    参数说明：
    - params: dict, 包含 schema 中定义的参数
    返回值: dict, 必须包含 success 字段
    """
    import json

    query = params.get("query", "")
    limit = params.get("limit", 10)

    # 在此编写工具逻辑
    result = f"处理查询: {query}, 限制: {limit}"

    return {"success": True, "result": result}`
)

const schemaExample = computed(() => {
  if (form.tool_type === 'mcp') {
    return `{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "查询关键词"
    },
    "limit": {
      "type": "integer",
      "description": "返回结果数量上限",
      "default": 10
    }
  },
  "required": ["query"]
}`
  }
  if (form.tool_type === 'restful') {
    return `{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "城市名称"
    },
    "lang": {
      "type": "string",
      "description": "语言代码",
      "enum": ["zh", "en"],
      "default": "zh"
    }
  },
  "required": ["city"]
}`
  }
  return `{
  "type": "object",
  "properties": {
    "input_text": {
      "type": "string",
      "description": "输入文本"
    },
    "max_length": {
      "type": "integer",
      "description": "最大长度限制",
      "default": 100
    }
  },
  "required": ["input_text"]
}`
})

const selectedDiscoveredToolDesc = computed(() => {
  if (selectedDiscoveredNames.value.length === 0) return ''
  const descs = selectedDiscoveredNames.value.map(name => {
    const found = discoveredTools.value.find(t => t.name === name)
    return found ? `${name}: ${found.description}` : name
  })
  return descs.join('; ')
})

const testMcpToolNames = computed(() => {
  if (!testToolRecord.value || testToolRecord.value.tool_type !== 'mcp') return []
  const cfg = testToolRecord.value.config || {}
  const raw = cfg.mcp_tool_name || ''
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string' && raw.includes(',')) {
    return raw.split(',').map(n => n.trim()).filter(Boolean)
  }
  if (typeof raw === 'string' && raw.trim()) return [raw.trim()]
  return []
})

function toggleDiscoveredTool(name) {
  const idx = selectedDiscoveredNames.value.indexOf(name)
  if (idx >= 0) {
    selectedDiscoveredNames.value.splice(idx, 1)
  } else {
    selectedDiscoveredNames.value.push(name)
  }
}

function fillSelectedToolNames() {
  config.mcp_tool_name = selectedDiscoveredNames.value.join(', ')
}

function typeColor(t) {
  const m = { mcp: 'purple', restful: 'blue', local_python: 'orange', builtin: 'cyan' }
  return m[t] || 'default'
}
function typeLabel(t) {
  const m = { mcp: 'MCP', restful: 'RESTful', local_python: '本地 Python', builtin: '系统内置' }
  return m[t] || t
}

const allTools = computed(() => {
  return [...builtinTools.value, ...tools.value]
})

async function fetchTools() {
  loading.value = true
  try {
    const [dbRes, builtinRes] = await Promise.all([
      toolApi.list({ page_size: 100 }),
      toolApi.listBuiltin(),
    ])
    tools.value = dbRes.items
    builtinTools.value = builtinRes.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function resetConfig() {
  Object.assign(config, {
    mcp_command: '',
    mcp_args_text: '[]',
    mcp_env_text: '{}',
    mcp_tool_name: '',
    restful_method: 'GET',
    restful_url: '',
    restful_headers_text: '{}',
    restful_body_template: '',
    python_code: '',
  })
}

function buildConfig() {
  const c = {}
  if (form.tool_type === 'mcp') {
    c.mcp_command = config.mcp_command
    try { c.mcp_args = JSON.parse(config.mcp_args_text) } catch { c.mcp_args = [] }
    try { c.mcp_env = JSON.parse(config.mcp_env_text) } catch { c.mcp_env = {} }
    c.mcp_tool_name = config.mcp_tool_name
  } else if (form.tool_type === 'restful') {
    c.restful_method = config.restful_method
    c.restful_url = config.restful_url
    try { c.restful_headers = JSON.parse(config.restful_headers_text) } catch { c.restful_headers = {} }
    c.restful_body_template = config.restful_body_template
  } else if (form.tool_type === 'local_python') {
    c.python_code = config.python_code
  }
  return c
}

function loadConfig(toolConfig) {
  const c = toolConfig || {}
  if (form.tool_type === 'mcp') {
    config.mcp_command = c.mcp_command || ''
    config.mcp_args_text = JSON.stringify(c.mcp_args || [], null, 2)
    config.mcp_env_text = JSON.stringify(c.mcp_env || {}, null, 2)
    config.mcp_tool_name = c.mcp_tool_name || ''
  } else if (form.tool_type === 'restful') {
    config.restful_method = c.restful_method || 'GET'
    config.restful_url = c.restful_url || ''
    config.restful_headers_text = JSON.stringify(c.restful_headers || {}, null, 2)
    config.restful_body_template = c.restful_body_template || ''
  } else if (form.tool_type === 'local_python') {
    config.python_code = c.python_code || ''
  }
}

function onTypeChange() {
  discoveredTools.value = []
  discoverError.value = ''
  selectedDiscoveredNames.value = []
  if (!editing.value) {
    fillExampleSchema()
  }
}

function fillExampleSchema() {
  paramsSchemaText.value = JSON.stringify(JSON.parse(schemaExample.value), null, 2)
}

async function discoverTools() {
  if (!config.mcp_command) {
    message.warning('请先填写 MCP 命令')
    return
  }

  let args = []
  try { args = JSON.parse(config.mcp_args_text) } catch {
    message.warning('MCP 参数格式错误，请使用 JSON 数组格式')
    return
  }

  let env = {}
  if (config.mcp_env_text) {
    try { env = JSON.parse(config.mcp_env_text) } catch { env = {} }
  }

  discovering.value = true
  discoverError.value = ''
  discoveredTools.value = []
  selectedDiscoveredNames.value = []
  try {
    const res = await toolApi.discoverMcp({
      command: config.mcp_command,
      args,
      env,
      timeout_seconds: 30,
    })
    if (res.success) {
      discoveredTools.value = res.tools || []
      if (discoveredTools.value.length === 0) {
        message.info('该 MCP Server 未提供任何工具')
      } else {
        message.success(`发现 ${discoveredTools.value.length} 个工具`)
      }
    } else {
      discoverError.value = res.error || '获取工具列表失败'
    }
  } catch (e) {
    discoverError.value = e.message
  } finally {
    discovering.value = false
  }
}

async function batchCreateTools() {
  if (discoveredTools.value.length === 0) return

  const baseName = form.name || 'mcp_tool'
  let created = 0
  let failed = 0

  for (const dt of discoveredTools.value) {
    try {
      const toolName = `${baseName}_${dt.name}`
      let paramsSchema = {}
      if (dt.inputSchema && Object.keys(dt.inputSchema).length > 0) {
        paramsSchema = dt.inputSchema
      } else {
        paramsSchema = { type: 'object', properties: {}, required: [] }
      }
      await toolApi.create({
        name: toolName,
        display_name: dt.name,
        tool_type: 'mcp',
        description: dt.description || `MCP 工具: ${dt.name}`,
        config: {
          mcp_command: config.mcp_command,
          mcp_args: (() => { try { return JSON.parse(config.mcp_args_text) } catch { return [] } })(),
          mcp_env: (() => { try { return JSON.parse(config.mcp_env_text) } catch { return {} } })(),
          mcp_tool_name: dt.name,
        },
        parameters_schema: paramsSchema,
      })
      created++
    } catch (e) {
      failed++
    }
  }

  if (created > 0) {
    message.success(`批量创建成功: ${created} 个工具`)
    fetchTools()
  }
  if (failed > 0) {
    message.warning(`${failed} 个工具创建失败，可能是名称重复`)
  }
}

function openCreate() {
  editing.value = null
  resetConfig()
  Object.assign(form, { name: '', display_name: '', tool_type: 'restful', description: '' })
  paramsSchemaText.value = '{}'
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  resetConfig()
  Object.assign(form, {
    name: record.name,
    display_name: record.display_name,
    tool_type: record.tool_type,
    description: record.description,
  })
  loadConfig(record.config)
  paramsSchemaText.value = JSON.stringify(record.parameters_schema || {}, null, 2)
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    let paramsSchema = {}
    try {
      paramsSchema = JSON.parse(paramsSchemaText.value)
    } catch {
      message.error('参数 Schema JSON 格式错误')
      saving.value = false
      return
    }
    const data = {
      name: form.name,
      display_name: form.display_name || form.name,
      tool_type: form.tool_type,
      description: form.description,
      config: buildConfig(),
      parameters_schema: paramsSchema,
    }
    if (editing.value) {
      await toolApi.update(editing.value.tool_id, data)
      message.success('更新成功')
    } else {
      await toolApi.create(data)
      message.success('创建成功')
    }
    modalOpen.value = false
    fetchTools()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  try {
    await toolApi.delete(id)
    message.success('已删除')
    fetchTools()
  } catch (e) {
    message.error(e.message)
  }
}

function openTest(record) {
  testToolId = record.tool_id
  testToolRecord.value = record
  testParams.value = '{}'
  testResult.value = null
  selectedTestMcpTool.value = ''
  testOpen.value = true
}

function onTestMcpToolChange(toolName) {
  try {
    const params = JSON.parse(testParams.value)
    params.tool_name = toolName
    testParams.value = JSON.stringify(params, null, 2)
  } catch {
    testParams.value = JSON.stringify({ tool_name: toolName }, null, 2)
  }
}

async function handleTest() {
  testing.value = true
  try {
    let params = {}
    try {
      params = JSON.parse(testParams.value)
    } catch {
      message.error('参数 JSON 格式错误')
      testing.value = false
      return
    }
    if (testMcpToolNames.value.length > 1 && selectedTestMcpTool.value) {
      params.tool_name = selectedTestMcpTool.value
    }
    const res = await toolApi.test(testToolId, { parameters: params })
    testResult.value = JSON.stringify(res, null, 2)
  } catch (e) {
    testResult.value = '测试失败: ' + e.message
  } finally {
    testing.value = false
  }
}

onMounted(fetchTools)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.result-pre { white-space: pre-wrap; font-size: 12px; color: #3a342e; background: #f3f0e8; padding: 12px; border-radius: 6px; max-height: 300px; overflow-y: auto; }
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
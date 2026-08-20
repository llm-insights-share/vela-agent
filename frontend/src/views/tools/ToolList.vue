<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">工具管理</h2>
      <a-space>
        <a-button v-if="activeTab === 'tools'" type="primary" @click="openCreate">
          <PlusOutlined /> 创建工具
        </a-button>
        <a-button v-else type="primary" @click="openServerCreate">
          <PlusOutlined /> 添加 MCP Server
        </a-button>
      </a-space>
    </div>

    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="tools" tab="工具" />
      <a-tab-pane key="servers" tab="MCP 服务器" />
    </a-tabs>

    <a-card v-show="activeTab === 'tools'">
      <a-table :columns="columns" :data-source="allTools" :loading="loading" row-key="tool_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'tool_type'">
            <a-tag :color="typeColor(record.tool_type)">{{ typeLabel(record.tool_type) }}</a-tag>
          </template>
          <template v-if="column.key === 'source'">
            <div v-if="record.tool_type === 'mcp'">
              <a-tag>{{ transportLabel(record.config) }}</a-tag>
              <span class="source-text">{{ mcpSource(record) }}</span>
            </div>
            <span v-else class="source-text">—</span>
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

    <a-card v-show="activeTab === 'servers'">
      <a-alert
        v-if="oauthNotice"
        :type="oauthNotice.type"
        :message="oauthNotice.message"
        show-icon
        closable
        style="margin-bottom: 16px"
        @close="oauthNotice = null"
      />
      <a-table :columns="serverColumns" :data-source="servers" :loading="serversLoading" row-key="server_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'transport'">
            <a-tag color="purple">{{ transportLabelFromValue(record.transport) }}</a-tag>
          </template>
          <template v-if="column.key === 'auth'">
            <a-tag :color="oauthTagColor(record)">{{ oauthLabel(record) }}</a-tag>
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : (record.status === 'ERROR' ? 'red' : 'default')">
              {{ record.status }}
            </a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openServerEdit(record)">编辑</a>
              <a @click="discoverServer(record)">发现</a>
              <a @click="syncServer(record)">同步工具</a>
              <a v-if="isRemoteTransport(record.transport)" @click="startOauth(record)">连接授权</a>
              <a-popconfirm title="删除 Server 不会删除已同步工具，仅解除关联。确认？" @confirm="deleteServer(record.server_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑工具' : '创建工具'" @ok="handleSave" :confirm-loading="saving" width="920px">
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 17 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="工具唯一标识名，如 weather_query" />
          <div class="field-hint">仅允许英文、数字和下划线，如：weather_query、search_docs</div>
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="form.display_name" placeholder="如：天气查询" />
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
        </a-form-item>

        <a-divider orientation="left">配置</a-divider>

        <template v-if="form.tool_type === 'mcp'">
          <a-form-item label="MCP Server">
            <a-select v-model:value="config.mcp_server_id" allow-clear placeholder="可选：归属已保存的 Server" @change="onBindServerChange">
              <a-select-option v-for="s in servers" :key="s.server_id" :value="s.server_id">
                {{ s.display_name || s.name }} ({{ transportLabelFromValue(s.transport) }})
              </a-select-option>
            </a-select>
            <div class="field-hint">绑定后使用 Server 的传输与认证；也可在下方单独填写连接信息。</div>
          </a-form-item>
          <a-form-item label="传输方式" required>
            <a-radio-group v-model:value="config.transport" :disabled="!!config.mcp_server_id" @change="onTransportChange">
              <a-radio-button value="stdio">stdio（本地命令）</a-radio-button>
              <a-radio-button value="sse">SSE</a-radio-button>
              <a-radio-button value="streamable_http">Streamable HTTP</a-radio-button>
            </a-radio-group>
            <div class="field-hint">stdio 由本机拉起进程；SSE / Streamable HTTP 连接远程或本地 HTTP 端点。</div>
          </a-form-item>
          <a-form-item v-if="config.transport === 'stdio' && !config.mcp_server_id" label="常用预设">
            <a-select placeholder="选择预设填入命令" allow-clear @change="applyPreset">
              <a-select-option v-for="p in mcpPresets" :key="p.key" :value="p.key">{{ p.label }}</a-select-option>
            </a-select>
          </a-form-item>

          <template v-if="config.transport === 'stdio'">
            <a-form-item label="MCP 命令">
              <a-input v-model:value="config.mcp_command" placeholder="如 npx" :disabled="!!config.mcp_server_id" />
            </a-form-item>
            <a-form-item label="MCP 参数">
              <div class="kv-list">
                <a-space v-for="(arg, idx) in config.mcp_args_list" :key="'arg-'+idx" style="margin-bottom: 6px; width: 100%;">
                  <a-input v-model:value="config.mcp_args_list[idx]" placeholder="参数" :disabled="!!config.mcp_server_id" />
                  <a v-if="!config.mcp_server_id" @click="config.mcp_args_list.splice(idx, 1)">删除</a>
                </a-space>
                <a-button v-if="!config.mcp_server_id" size="small" @click="config.mcp_args_list.push('')">添加参数</a-button>
              </div>
            </a-form-item>
            <a-form-item label="环境变量">
              <div class="kv-list">
                <a-space v-for="(row, idx) in config.mcp_env_rows" :key="'env-'+idx" style="margin-bottom: 6px; width: 100%;">
                  <a-input v-model:value="row.key" placeholder="KEY" :disabled="!!config.mcp_server_id" />
                  <a-input v-model:value="row.value" placeholder="value" :disabled="!!config.mcp_server_id" />
                  <a v-if="!config.mcp_server_id" @click="config.mcp_env_rows.splice(idx, 1)">删除</a>
                </a-space>
                <a-button v-if="!config.mcp_server_id" size="small" @click="config.mcp_env_rows.push({ key: '', value: '' })">添加变量</a-button>
              </div>
            </a-form-item>
          </template>

          <template v-else>
            <a-form-item :label="config.transport === 'sse' ? 'SSE 端点 URL' : 'HTTP 端点 URL'">
              <a-input v-model:value="config.mcp_url" placeholder="https://mcp.example.com/mcp" :disabled="!!config.mcp_server_id" />
            </a-form-item>
            <a-form-item label="认证">
              <a-select v-model:value="config.auth_type" :disabled="!!config.mcp_server_id">
                <a-select-option value="none">无</a-select-option>
                <a-select-option value="bearer">Bearer Token</a-select-option>
                <a-select-option value="oauth" disabled>OAuth（请在 MCP 服务器页授权）</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item v-if="config.auth_type === 'bearer'" label="Bearer Token">
              <a-input-password v-model:value="config.auth_token" placeholder="访问令牌" :disabled="!!config.mcp_server_id" />
            </a-form-item>
            <a-form-item label="请求头">
              <a-textarea v-model:value="config.mcp_headers_text" :rows="2" placeholder='{"X-Custom": "value"}' :disabled="!!config.mcp_server_id" />
            </a-form-item>
          </template>

          <a-form-item label="工具名称">
            <a-input v-model:value="config.mcp_tool_name" placeholder="单个工具如 get_weather，多个用逗号分隔" />
            <a-space style="margin-top: 8px;">
              <a-button size="small" :loading="discovering" @click="discoverTools">发现可用工具</a-button>
              <a-button v-if="selectedDiscoveredNames.length > 0" size="small" type="primary" ghost @click="fillSelectedToolNames">
                填入已选 ({{ selectedDiscoveredNames.length }})
              </a-button>
              <a-button v-if="selectedDiscoveredNames.length > 0" size="small" type="primary" @click="batchCreateTools(true)">
                批量创建已选
              </a-button>
              <a-button v-if="discoveredTools.length > 0" size="small" @click="batchCreateTools(false)">
                批量创建全部
              </a-button>
            </a-space>
            <div class="field-hint">多选填入同一记录时，Agent 通过 <code>tool_name</code> 参数选择；更推荐批量创建为独立工具。</div>
          </a-form-item>
          <div v-if="discoveredTools.length > 0" class="discover-box">
            <div class="field-hint" style="margin-bottom: 8px;">已发现 {{ discoveredTools.length }} 个工具，点击行可选中：</div>
            <a-table
              :data-source="discoveredTools"
              :columns="discoverColumns"
              row-key="name"
              size="small"
              :pagination="false"
              :row-selection="{ selectedRowKeys: selectedDiscoveredNames, onChange: onDiscoverSelect }"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'schema'">
                  <a @click="previewSchema(record)">查看 schema</a>
                </template>
              </template>
            </a-table>
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
          </a-form-item>
          <a-form-item label="请求头">
            <a-textarea v-model:value="config.restful_headers_text" :rows="2" placeholder='{"Authorization": "Bearer sk-xxx"}' />
          </a-form-item>
          <a-form-item label="请求体模板">
            <a-textarea v-model:value="config.restful_body_template" :rows="3" placeholder='{"query": "{{query}}"}' />
          </a-form-item>
        </template>

        <template v-if="form.tool_type === 'local_python'">
          <a-form-item label="Python 代码">
            <a-textarea v-model:value="config.python_code" :rows="10" :placeholder="pythonCodeExample" />
          </a-form-item>
        </template>

        <a-divider orientation="left">
          参数定义
          <a-button size="small" type="link" @click="fillExampleSchema" style="margin-left: 8px;">填入示例</a-button>
        </a-divider>
        <a-form-item label="参数 Schema">
          <a-textarea v-model:value="paramsSchemaText" :rows="6" :placeholder="schemaExample" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="serverModalOpen" :title="editingServer ? '编辑 MCP Server' : '添加 MCP Server'" @ok="saveServer" :confirm-loading="serverSaving" width="720px">
      <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="serverForm.name" placeholder="唯一标识，如 github_mcp" :disabled="!!editingServer" />
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="serverForm.display_name" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="serverForm.description" :rows="2" />
        </a-form-item>
        <a-form-item label="传输方式" required>
          <a-radio-group v-model:value="serverForm.transport">
            <a-radio-button value="stdio">stdio</a-radio-button>
            <a-radio-button value="sse">SSE</a-radio-button>
            <a-radio-button value="streamable_http">Streamable HTTP</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <template v-if="serverForm.transport === 'stdio'">
          <a-form-item label="命令">
            <a-input v-model:value="serverForm.command" placeholder="npx" />
          </a-form-item>
          <a-form-item label="参数 JSON">
            <a-textarea v-model:value="serverForm.args_text" :rows="2" placeholder='["-y", "@modelcontextprotocol/server-fetch"]' />
          </a-form-item>
          <a-form-item label="环境变量 JSON">
            <a-textarea v-model:value="serverForm.env_text" :rows="2" placeholder="{}" />
          </a-form-item>
        </template>
        <template v-else>
          <a-form-item :label="serverForm.transport === 'sse' ? 'SSE URL' : 'HTTP URL'">
            <a-input v-model:value="serverForm.url" placeholder="https://mcp.example.com/mcp" />
          </a-form-item>
          <a-form-item label="认证">
            <a-select v-model:value="serverForm.auth_type">
              <a-select-option value="none">无</a-select-option>
              <a-select-option value="bearer">Bearer Token</a-select-option>
              <a-select-option value="oauth">OAuth 2.1</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="serverForm.auth_type === 'bearer'" label="Bearer Token">
            <a-input-password v-model:value="serverForm.auth_token" />
            <div class="field-hint">将写入自定义请求头 Authorization。</div>
          </a-form-item>
          <a-form-item label="请求头 JSON">
            <a-textarea v-model:value="serverForm.headers_text" :rows="2" placeholder="{}" />
          </a-form-item>
        </template>
      </a-form>
    </a-modal>

    <a-modal v-model:open="schemaPreviewOpen" title="inputSchema" :footer="null">
      <pre class="result-pre">{{ schemaPreview }}</pre>
    </a-modal>

    <a-modal v-model:open="testOpen" :title="testModalTitle" :footer="null" width="700px">
      <a-form :label-col="{ span: 4 }" :wrapper-col="{ span: 18 }">
        <a-form-item v-if="testMcpToolNames.length > 1" label="选择工具">
          <a-select v-model:value="selectedTestMcpTool" placeholder="选择要测试的 MCP 工具" @change="onTestMcpToolChange">
            <a-select-option v-for="name in testMcpToolNames" :key="name" :value="name">{{ name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="参数">
          <a-textarea v-model:value="testParams" :rows="10" placeholder='{"query": "test"}' />
          <div class="field-hint">已按该工具参数 Schema 预填示例，可直接修改后执行。</div>
        </a-form-item>
        <a-form-item :wrapper-col="{ offset: 4, span: 18 }">
          <a-button type="primary" :loading="testing" @click="handleTest">执行测试</a-button>
        </a-form-item>
      </a-form>
      <div v-if="testResult" style="margin-top: 16px">
        <a-divider />
        <pre class="result-pre">{{ testResult }}</pre>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'
import { toolApi, mcpServerApi } from '../../api'
import { message } from 'ant-design-vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref(route.query.tab === 'servers' ? 'servers' : 'tools')
const loading = ref(false)
const tools = ref([])
const builtinTools = ref([])
const servers = ref([])
const serversLoading = ref(false)
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const paramsSchemaText = ref('{}')
const oauthNotice = ref(null)

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
const schemaPreviewOpen = ref(false)
const schemaPreview = ref('')

const serverModalOpen = ref(false)
const editingServer = ref(null)
const serverSaving = ref(false)
const serverForm = reactive({
  name: '',
  display_name: '',
  description: '',
  transport: 'stdio',
  command: '',
  args_text: '[]',
  env_text: '{}',
  url: '',
  headers_text: '{}',
  auth_type: 'none',
  auth_token: '',
})

const mcpPresets = [
  { key: 'filesystem', label: 'Filesystem', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '/tmp'] },
  { key: 'fetch', label: 'Fetch', command: 'npx', args: ['-y', '@modelcontextprotocol/server-fetch'] },
  { key: 'sqlite', label: 'SQLite', command: 'uvx', args: ['--with', 'mcp<2', 'mcp-server-sqlite', '--db-path', './data.db'] },
  { key: 'github', label: 'GitHub', command: 'npx', args: ['-y', '@modelcontextprotocol/server-github'] },
]

const columns = [
  { title: '名称', dataIndex: 'name', width: 150 },
  { title: '显示名称', dataIndex: 'display_name', width: 140 },
  { title: '类型', key: 'tool_type', width: 100 },
  { title: '来源', key: 'source', width: 240 },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '状态', key: 'status', width: 80 },
  { title: '操作', key: 'action', width: 150 },
]

const serverColumns = [
  { title: '名称', dataIndex: 'name', width: 140 },
  { title: '显示名称', dataIndex: 'display_name', width: 140 },
  { title: '传输', key: 'transport', width: 150 },
  { title: '来源', dataIndex: 'source', ellipsis: true },
  { title: '认证', key: 'auth', width: 120 },
  { title: '工具数', dataIndex: 'tool_count', width: 80 },
  { title: '状态', key: 'status', width: 90 },
  { title: '操作', key: 'action', width: 280 },
]

const discoverColumns = [
  { title: '名称', dataIndex: 'name', width: 180 },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: 'Schema', key: 'schema', width: 110 },
]

const config = reactive({
  transport: 'stdio',
  mcp_server_id: undefined,
  mcp_command: '',
  mcp_args_list: [],
  mcp_env_rows: [],
  mcp_tool_name: '',
  mcp_url: '',
  mcp_headers_text: '{}',
  auth_type: 'none',
  auth_token: '',
  restful_method: 'GET',
  restful_url: '',
  restful_headers_text: '{}',
  restful_body_template: '',
  python_code: '',
})

const form = reactive({
  name: '',
  display_name: '',
  tool_type: 'mcp',
  description: '',
})

const pythonCodeExample = computed(() =>
`def execute(params):
    import json
    query = params.get("query", "")
    return {"success": True, "result": query}`
)

const schemaExample = computed(() => {
  return `{
  "type": "object",
  "properties": {
    "query": { "type": "string", "description": "查询关键词" }
  },
  "required": ["query"]
}`
})

const testMcpToolNames = computed(() => {
  if (!testToolRecord.value || testToolRecord.value.tool_type !== 'mcp') return []
  const raw = (testToolRecord.value.config || {}).mcp_tool_name || ''
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string' && raw.includes(',')) {
    return raw.split(',').map(n => n.trim()).filter(Boolean)
  }
  if (typeof raw === 'string' && raw.trim()) return [raw.trim()]
  return []
})

const testModalTitle = computed(() => {
  const rec = testToolRecord.value
  if (!rec) return '测试工具'
  const name = rec.display_name || rec.name
  return name ? `测试工具 · ${name}` : '测试工具'
})

const TOOL_MOCK_PARAMS = {
  nl2sql_query: {
    question: '查询最近一个月的订单数量',
    top_k: 200,
    strict_mode: true,
    return_sql_only: false,
  },
  query_sqlite: {
    query: "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20",
  },
  query: {
    query: "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20",
  },
  read_query: {
    query: "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20",
  },
  write_query: {
    query: 'INSERT INTO example_table (id, name) VALUES (1, \'demo\')',
  },
  create_table: {
    query: 'CREATE TABLE IF NOT EXISTS example_table (id INTEGER PRIMARY KEY, name TEXT)',
  },
  describe_table: {
    table_name: 'example_table',
  },
  list_tables: {},
  append_insight: {
    insight: '示例分析：最近一个月订单量呈上升趋势',
  },
  cu_extract: { screen_session_id: 'sess_demo' },
  cu_observe: { screen_session_id: 'sess_demo' },
  cu_act: { screen_session_id: 'sess_demo', action: 'click', target_ref: '[1]' },
  cu_navigate: { system_id: '示例系统', auto_login: true },
  cu_vision: { screen_session_id: 'sess_demo', question: '登录按钮在哪里', use_som: false },
  cu_search_skills: { query: '登录系统', scope: 'default', top_k: 5 },
  cu_compile_skill: { screen_session_id: 'sess_demo', name: '登录流程', description: '编译当前登录轨迹', scope: 'default' },
  cu_replay_skill: { skill_id: 'skill_demo', screen_session_id: 'sess_demo', params: {} },
  cu_wait_for_otp: { screen_session_id: 'sess_demo', selector: 'input[name="otp"]', prompt: '请输入短信验证码' },
  cu_run_task: { system_id: '示例系统', goal: '打开首页并提取页面标题', max_steps: 6 },
  tavily_web_search: { query: '今天北京天气', max_results: 5, search_depth: 'basic', include_answer: true },
  web_extract: { url: 'https://example.com', max_length: 10000 },
  kb_search: { query: '检索示例问题', top_k: 5 },
  bash: { command: 'ls -la', timeout: 30 },
  execute_code: { code: 'print("hello")', language: 'python', timeout: 60, reset_state: false },
  read_file: { file_path: '/tmp/example.txt', offset: 1, limit: 50 },
}

function unwrapParamSchema(schema) {
  if (!schema) return null
  if (typeof schema === 'string') {
    try { schema = JSON.parse(schema) } catch { return null }
  }
  if (typeof schema !== 'object') return null
  if (schema.properties || schema.type === 'object' || schema.items) return schema
  if (schema.parameters && typeof schema.parameters === 'object') return unwrapParamSchema(schema.parameters)
  if (schema.inputSchema && typeof schema.inputSchema === 'object') return unwrapParamSchema(schema.inputSchema)
  return schema
}

function mockStringValue(key, schema) {
  const format = schema.format || ''
  if (format === 'uri' || format === 'url' || /(^|_)url$/i.test(key) || key === 'url') return 'https://example.com'
  if (format === 'email' || /email/i.test(key)) return 'user@example.com'
  if (format === 'uuid') return '00000000-0000-0000-0000-000000000000'
  if (format === 'date') return '2026-08-19'
  if (format === 'date-time') return '2026-08-19T12:00:00Z'
  if (/sql/i.test(key)) return 'SELECT 1'
  if (key === 'query' || key === 'question' || key === 'goal') return '查询示例'
  if (/path/i.test(key) || key === 'file_path') return '/tmp/example.txt'
  if (key === 'command') return 'ls -la'
  if (key === 'code') return 'print("hello")'
  if (/selector/i.test(key)) return '#example'
  if (key === 'action') return 'click'
  if (key === 'target_ref') return '[1]'
  if (/session_id$/i.test(key)) return 'sess_demo'
  if (/_id$/i.test(key) || key.endsWith('Id')) return 'demo-id'
  if (key === 'content' || key === 'value' || key === 'text' || key === 'prompt') return '示例文本'
  return `example_${key}`
}

function mockFromJsonSchema(schema, fieldName = '', depth = 0) {
  if (depth > 6 || schema == null) return {}
  const unwrapped = unwrapParamSchema(schema) || schema
  if (typeof unwrapped !== 'object') return unwrapped
  if (unwrapped.example !== undefined) return unwrapped.example
  if (Array.isArray(unwrapped.examples) && unwrapped.examples.length) return unwrapped.examples[0]
  if (unwrapped.default !== undefined) return unwrapped.default
  if (Array.isArray(unwrapped.enum) && unwrapped.enum.length) return unwrapped.enum[0]
  const rawType = unwrapped.type
  const type = Array.isArray(rawType) ? rawType.find((t) => t !== 'null') : rawType
  if (type === 'array' || unwrapped.items) {
    return [mockFromJsonSchema(unwrapped.items || { type: 'string' }, fieldName, depth + 1)]
  }
  if (type === 'object' || unwrapped.properties) {
    const obj = {}
    const props = unwrapped.properties || {}
    const required = new Set(unwrapped.required || [])
    for (const [key, prop] of Object.entries(props)) {
      const p = (prop && typeof prop === 'object') ? prop : {}
      const include = depth > 0
        || required.has(key)
        || p.default !== undefined
        || p.example !== undefined
        || (Array.isArray(p.examples) && p.examples.length)
        || (Array.isArray(p.enum) && p.enum.length)
      if (!include) continue
      obj[key] = mockFromJsonSchema(prop, key, depth + 1)
    }
    return obj
  }
  if (type === 'integer') return Number.isFinite(unwrapped.minimum) ? unwrapped.minimum : 1
  if (type === 'number') return Number.isFinite(unwrapped.minimum) ? unwrapped.minimum : 1
  if (type === 'boolean') return false
  if (type === 'null') return null
  if (type === 'string' || fieldName) return mockStringValue(fieldName, unwrapped)
  return {}
}

function catalogKeyForTool(record, mcpToolName = '') {
  if (mcpToolName) {
    return TOOL_MOCK_PARAMS[mcpToolName] ? mcpToolName : ''
  }
  if ((record?.config || {}).adapter === 'dataquery_agent') return 'nl2sql_query'
  if (typeof record?.name === 'string' && (record.name === 'nl2sql_query' || record.name.startsWith('nl2sql_'))) {
    return 'nl2sql_query'
  }
  const keys = [record?.name, record?.config?.mcp_tool_name]
  for (const key of keys) {
    if (typeof key === 'string' && TOOL_MOCK_PARAMS[key]) return key
    if (Array.isArray(key)) {
      const hit = key.find((n) => TOOL_MOCK_PARAMS[n])
      if (hit) return hit
    }
  }
  return ''
}

function buildTestParams(record, mcpToolName = '') {
  const catalogKey = catalogKeyForTool(record, mcpToolName)
  const catalogMock = catalogKey ? { ...TOOL_MOCK_PARAMS[catalogKey] } : {}
  const isSubTool = mcpToolName && mcpToolName !== record?.name && catalogKey === mcpToolName
  if (isSubTool) return catalogMock
  const schemaMock = mockFromJsonSchema(record?.parameters_schema || {})
  return { ...schemaMock, ...catalogMock }
}

watch(activeTab, (val) => {
  router.replace({ query: { ...route.query, tab: val } })
})

function isRemoteTransport(t) {
  return t === 'sse' || t === 'streamable_http'
}
function typeColor(t) {
  const m = { mcp: 'purple', restful: 'blue', local_python: 'orange', builtin: 'cyan' }
  return m[t] || 'default'
}
function typeLabel(t) {
  const m = { mcp: 'MCP', restful: 'RESTful', local_python: '本地 Python', builtin: '系统内置' }
  return m[t] || t
}
function transportLabelFromValue(t) {
  const m = { stdio: 'stdio', sse: 'SSE', streamable_http: 'Streamable HTTP', http: 'Streamable HTTP' }
  return m[t] || t || 'stdio'
}
function transportLabel(cfg) {
  return transportLabelFromValue((cfg || {}).transport || 'stdio')
}
function mcpSource(record) {
  if (record.mcp_server_name) return record.mcp_server_name
  const cfg = record.config || {}
  if (cfg.mcp_url) {
    try { return new URL(cfg.mcp_url).host } catch { return cfg.mcp_url }
  }
  const parts = [cfg.mcp_command, ...(cfg.mcp_args || [])].filter(Boolean)
  return parts.join(' ') || '—'
}
function oauthLabel(record) {
  if (record.auth_type === 'oauth') {
    return record.oauth_status === 'authorized' ? 'OAuth 已授权' : 'OAuth 未授权'
  }
  if (record.auth_type === 'bearer') return 'Bearer'
  return '无'
}
function oauthTagColor(record) {
  if (record.auth_type === 'oauth') return record.oauth_status === 'authorized' ? 'green' : 'orange'
  if (record.auth_type === 'bearer') return 'blue'
  return 'default'
}

const allTools = computed(() => [...builtinTools.value, ...tools.value])

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

async function fetchServers() {
  serversLoading.value = true
  try {
    const res = await mcpServerApi.list()
    servers.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    serversLoading.value = false
  }
}

function envRowsToObject(rows) {
  const obj = {}
  for (const row of rows || []) {
    if (row.key) obj[row.key] = row.value
  }
  return obj
}
function objectToEnvRows(obj) {
  return Object.entries(obj || {}).map(([key, value]) => ({ key, value: String(value ?? '') }))
}

function resetConfig() {
  Object.assign(config, {
    transport: 'stdio',
    mcp_server_id: undefined,
    mcp_command: '',
    mcp_args_list: [],
    mcp_env_rows: [],
    mcp_tool_name: '',
    mcp_url: '',
    mcp_headers_text: '{}',
    auth_type: 'none',
    auth_token: '',
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
    c.transport = config.transport || 'stdio'
    c.mcp_tool_name = config.mcp_tool_name
    if (config.mcp_server_id) c.mcp_server_id = config.mcp_server_id
    if (c.transport === 'stdio') {
      c.mcp_command = config.mcp_command
      c.mcp_args = (config.mcp_args_list || []).filter(Boolean)
      c.mcp_env = envRowsToObject(config.mcp_env_rows)
    } else {
      c.mcp_url = config.mcp_url
      try { c.mcp_headers = JSON.parse(config.mcp_headers_text || '{}') } catch { c.mcp_headers = {} }
      c.auth_type = config.auth_type || 'none'
      if (config.auth_type === 'bearer') {
        c.auth_token = config.auth_token
        c.mcp_headers = { ...(c.mcp_headers || {}), Authorization: `Bearer ${config.auth_token}` }
      }
    }
  } else if (form.tool_type === 'restful') {
    c.restful_method = config.restful_method
    c.restful_url = config.restful_url
    try { c.restful_headers = JSON.parse(config.restful_headers_text) } catch { c.restful_headers = {} }
    c.restful_body_template = config.restful_body_template
    const prev = (editing.value && editing.value.config) || {}
    if (prev.adapter) c.adapter = prev.adapter
    if (prev.dq_agent_id) c.dq_agent_id = prev.dq_agent_id
    if (prev.adapter === 'dataquery_agent' || form.name === 'nl2sql_query' || String(form.name || '').startsWith('nl2sql_')) {
      c.adapter = c.adapter || 'dataquery_agent'
      if (prev.dq_agent_id) c.dq_agent_id = prev.dq_agent_id
    }
  } else if (form.tool_type === 'local_python') {
    c.python_code = config.python_code
  }
  return c
}

function loadConfig(toolConfig) {
  const c = toolConfig || {}
  if (form.tool_type === 'mcp') {
    config.transport = c.transport || 'stdio'
    config.mcp_server_id = c.mcp_server_id || undefined
    config.mcp_command = c.mcp_command || ''
    config.mcp_args_list = [...(c.mcp_args || [])]
    config.mcp_env_rows = objectToEnvRows(c.mcp_env || {})
    config.mcp_tool_name = c.mcp_tool_name || ''
    config.mcp_url = c.mcp_url || ''
    const headers = { ...(c.mcp_headers || {}) }
    config.auth_type = c.auth_type || (headers.Authorization ? 'bearer' : 'none')
    config.auth_token = c.auth_token || ''
    config.mcp_headers_text = JSON.stringify(headers, null, 2)
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
  if (!editing.value) fillExampleSchema()
}
function onTransportChange() {
  discoveredTools.value = []
}
function applyPreset(key) {
  const p = mcpPresets.find(x => x.key === key)
  if (!p) return
  config.transport = 'stdio'
  config.mcp_command = p.command
  config.mcp_args_list = [...p.args]
}
function onBindServerChange(serverId) {
  const s = servers.value.find(x => x.server_id === serverId)
  if (!s) return
  config.transport = s.transport || 'stdio'
  config.mcp_command = s.command || ''
  config.mcp_args_list = [...(s.args || [])]
  config.mcp_env_rows = objectToEnvRows(s.env || {})
  config.mcp_url = s.url || ''
  config.auth_type = s.auth_type || 'none'
  config.mcp_headers_text = JSON.stringify(s.headers || {}, null, 2)
}

function fillExampleSchema() {
  paramsSchemaText.value = JSON.stringify(JSON.parse(schemaExample.value), null, 2)
}

function onDiscoverSelect(keys) {
  selectedDiscoveredNames.value = keys
}
function previewSchema(record) {
  schemaPreview.value = JSON.stringify(record.inputSchema || {}, null, 2)
  schemaPreviewOpen.value = true
}

function discoverPayload() {
  if (config.mcp_server_id) {
    return { mcp_server_id: config.mcp_server_id, timeout_seconds: 30 }
  }
  const payload = {
    transport: config.transport || 'stdio',
    timeout_seconds: 30,
  }
  if (config.transport === 'stdio') {
    payload.command = config.mcp_command
    payload.args = (config.mcp_args_list || []).filter(Boolean)
    payload.env = envRowsToObject(config.mcp_env_rows)
  } else {
    payload.url = config.mcp_url
    try { payload.headers = JSON.parse(config.mcp_headers_text || '{}') } catch { payload.headers = {} }
    payload.auth_type = config.auth_type
    payload.auth_token = config.auth_token
  }
  return payload
}

async function discoverTools() {
  if (!config.mcp_server_id) {
    if (config.transport === 'stdio' && !config.mcp_command) {
      message.warning('请先填写 MCP 命令')
      return
    }
    if (config.transport !== 'stdio' && !config.mcp_url) {
      message.warning('请先填写 MCP URL')
      return
    }
  }
  discovering.value = true
  discoverError.value = ''
  discoveredTools.value = []
  selectedDiscoveredNames.value = []
  try {
    const res = await toolApi.discoverMcp(discoverPayload())
    if (res.success) {
      discoveredTools.value = res.tools || []
      if (discoveredTools.value.length === 0) message.info('该 MCP Server 未提供任何工具')
      else message.success(`发现 ${discoveredTools.value.length} 个工具`)
    } else {
      discoverError.value = res.error || '获取工具列表失败'
    }
  } catch (e) {
    discoverError.value = e.message
  } finally {
    discovering.value = false
  }
}

function fillSelectedToolNames() {
  const selected = discoveredTools.value.filter(t => selectedDiscoveredNames.value.includes(t.name))
  config.mcp_tool_name = selected.map(t => t.name).join(', ')
  if (selected.length === 1) {
    form.description = selected[0].description || form.description
    if (selected[0].inputSchema) {
      paramsSchemaText.value = JSON.stringify(selected[0].inputSchema, null, 2)
    }
  } else if (selected.length > 1) {
    message.info('已填入多个工具名。多工具共用一条记录时，建议改用「批量创建已选」。')
  }
}

async function batchCreateTools(selectedOnly) {
  const list = selectedOnly
    ? discoveredTools.value.filter(t => selectedDiscoveredNames.value.includes(t.name))
    : discoveredTools.value
  if (list.length === 0) return
  const existing = new Set(tools.value.map(t => t.name))
  const baseName = form.name || 'mcp_tool'
  const conn = buildConfig()
  let created = 0
  let skipped = 0
  let failed = 0
  for (const dt of list) {
    const toolName = `${baseName}_${dt.name}`
    if (existing.has(toolName)) {
      skipped++
      continue
    }
    try {
      await toolApi.create({
        name: toolName,
        display_name: dt.name,
        tool_type: 'mcp',
        description: dt.description || `MCP 工具: ${dt.name}`,
        mcp_server_id: config.mcp_server_id || undefined,
        config: { ...conn, mcp_tool_name: dt.name },
        parameters_schema: dt.inputSchema && Object.keys(dt.inputSchema).length ? dt.inputSchema : { type: 'object', properties: {}, required: [] },
      })
      created++
      existing.add(toolName)
    } catch {
      failed++
    }
  }
  if (created) {
    message.success(`批量创建成功: ${created} 个工具`)
    fetchTools()
  }
  if (skipped) message.info(`${skipped} 个因名称已存在而跳过`)
  if (failed) message.warning(`${failed} 个工具创建失败`)
}

function openCreate() {
  editing.value = null
  resetConfig()
  Object.assign(form, { name: '', display_name: '', tool_type: 'mcp', description: '' })
  paramsSchemaText.value = '{}'
  discoveredTools.value = []
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
  loadConfig({ ...(record.config || {}), mcp_server_id: record.mcp_server_id || (record.config || {}).mcp_server_id })
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
    const built = buildConfig()
    const data = {
      name: form.name,
      display_name: form.display_name || form.name,
      tool_type: form.tool_type,
      description: form.description,
      config: built,
      parameters_schema: paramsSchema,
      mcp_server_id: built.mcp_server_id || null,
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

function fillTestParams(mcpToolName = '') {
  const params = buildTestParams(testToolRecord.value, mcpToolName)
  if (testMcpToolNames.value.length > 1 && mcpToolName) {
    params.tool_name = mcpToolName
  }
  testParams.value = JSON.stringify(params, null, 2)
}

function openTest(record) {
  testToolId = record.tool_id
  testToolRecord.value = record
  testResult.value = null
  const names = testMcpToolNames.value
  selectedTestMcpTool.value = names.length > 1 ? names[0] : (names[0] || '')
  fillTestParams(selectedTestMcpTool.value)
  testOpen.value = true
}
function onTestMcpToolChange(toolName) {
  fillTestParams(toolName)
}
async function handleTest() {
  testing.value = true
  try {
    let params = {}
    try { params = JSON.parse(testParams.value) } catch {
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

function resetServerForm() {
  Object.assign(serverForm, {
    name: '',
    display_name: '',
    description: '',
    transport: 'stdio',
    command: '',
    args_text: '[]',
    env_text: '{}',
    url: '',
    headers_text: '{}',
    auth_type: 'none',
    auth_token: '',
  })
}
function openServerCreate() {
  editingServer.value = null
  resetServerForm()
  serverModalOpen.value = true
}
function openServerEdit(record) {
  editingServer.value = record
  Object.assign(serverForm, {
    name: record.name,
    display_name: record.display_name,
    description: record.description,
    transport: record.transport || 'stdio',
    command: record.command || '',
    args_text: JSON.stringify(record.args || [], null, 2),
    env_text: JSON.stringify(record.env || {}, null, 2),
    url: record.url || '',
    headers_text: JSON.stringify(record.headers || {}, null, 2),
    auth_type: record.auth_type || 'none',
    auth_token: '',
  })
  serverModalOpen.value = true
}
function parseServerPayload() {
  let args = []
  let env = {}
  let headers = {}
  try { args = JSON.parse(serverForm.args_text || '[]') } catch { args = [] }
  try { env = JSON.parse(serverForm.env_text || '{}') } catch { env = {} }
  try { headers = JSON.parse(serverForm.headers_text || '{}') } catch { headers = {} }
  if (serverForm.auth_type === 'bearer' && serverForm.auth_token) {
    headers.Authorization = `Bearer ${serverForm.auth_token}`
  }
  return {
    name: serverForm.name,
    display_name: serverForm.display_name || serverForm.name,
    description: serverForm.description,
    transport: serverForm.transport,
    command: serverForm.command,
    args,
    env,
    url: serverForm.url,
    headers,
    auth_type: serverForm.auth_type,
  }
}
async function saveServer() {
  serverSaving.value = true
  try {
    const data = parseServerPayload()
    if (editingServer.value) {
      await mcpServerApi.update(editingServer.value.server_id, data)
      message.success('Server 已更新')
    } else {
      await mcpServerApi.create(data)
      message.success('Server 已创建')
    }
    serverModalOpen.value = false
    fetchServers()
  } catch (e) {
    message.error(e.message)
  } finally {
    serverSaving.value = false
  }
}
async function deleteServer(id) {
  try {
    await mcpServerApi.delete(id)
    message.success('已删除')
    fetchServers()
    fetchTools()
  } catch (e) {
    message.error(e.message)
  }
}
async function discoverServer(record) {
  try {
    const res = await mcpServerApi.discover(record.server_id)
    if (res.success) message.success(`发现 ${res.total || (res.tools || []).length} 个工具`)
    else message.error(res.error || '发现失败')
  } catch (e) {
    message.error(e.message)
  }
}
async function syncServer(record) {
  try {
    const res = await mcpServerApi.sync(record.server_id)
    if (res.success) {
      message.success(`同步完成：新增 ${res.created}，更新 ${res.updated}，停用 ${res.deactivated}`)
      fetchServers()
      fetchTools()
    } else {
      message.error(res.error || '同步失败')
    }
  } catch (e) {
    message.error(e.message)
  }
}
async function startOauth(record) {
  try {
    const frontend = `${window.location.origin}/tools?tab=servers&mcp_oauth=ok&server_id=${record.server_id}`
    const res = await mcpServerApi.startOauth(record.server_id, { frontend_redirect: frontend })
    if (res.authorization_url) {
      window.location.href = res.authorization_url
    } else {
      message.error('未返回授权地址')
    }
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(() => {
  fetchTools()
  fetchServers()
  if (route.query.mcp_oauth === 'ok') {
    oauthNotice.value = { type: 'success', message: 'OAuth 授权成功，可以同步工具了' }
    activeTab.value = 'servers'
  } else if (route.query.mcp_oauth === 'error') {
    oauthNotice.value = { type: 'error', message: route.query.message || 'OAuth 授权失败' }
    activeTab.value = 'servers'
  }
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.result-pre { white-space: pre-wrap; font-size: 12px; color: #3a342e; background: #f3f0e8; padding: 12px; border-radius: 6px; max-height: 300px; overflow-y: auto; }
.field-hint { font-size: 11px; color: #9e9590; margin-top: 4px; line-height: 1.5; }
.field-hint code { font-size: 11px; background: #f3f0e8; padding: 1px 5px; border-radius: 3px; color: #5c5650; }
.source-text { font-size: 12px; color: #5c5650; }
.discover-box { margin: 8px 0 0 0; padding: 8px; background: #faf8f4; border-radius: 6px; }
.kv-list { width: 100%; }
</style>

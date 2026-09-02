<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">连接器</h2>
      <a-space>
        <a-button type="primary" @click="openMcpCreate">
          <PlusOutlined /> 添加 MCP Server
        </a-button>
      </a-space>
    </div>

    <a-alert
      v-if="oauthNotice"
      :type="oauthNotice.type"
      :message="oauthNotice.message"
      show-icon
      closable
      style="margin-bottom: 16px"
      @close="oauthNotice = null"
    />

    <a-card title="目录模板" style="margin-bottom: 16px">
      <a-row :gutter="[16, 16]">
        <a-col v-for="item in catalog" :key="item.catalog_key" :xs="24" :sm="12" :md="8" :lg="6">
          <a-card hoverable class="catalog-card" @click="openCatalogModal(item)">
            <div class="catalog-title">{{ item.display_name }}</div>
            <div class="catalog-desc">{{ item.description }}</div>
            <a v-if="item.help_url" :href="item.help_url" target="_blank" rel="noopener" @click.stop>文档</a>
          </a-card>
        </a-col>
      </a-row>
    </a-card>

    <a-card title="连接器与 MCP 服务器">
      <a-table
        :columns="columns"
        :data-source="listItems"
        :loading="loading"
        row-key="row_id"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'kind'">
            <a-tag :color="record.kind === 'platform_mcp' ? 'purple' : 'blue'">
              {{ record.kind === 'platform_mcp' ? 'MCP Server' : catalogLabel(record.catalog_key) }}
            </a-tag>
          </template>
          <template v-if="column.key === 'transport'">
            <a-tag v-if="record.transport">{{ transportLabel(record.transport) }}</a-tag>
            <span v-else>—</span>
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'oauth_status'">
            <a-tag :color="oauthTagColor(record)">{{ record.oauth_status || '—' }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space wrap>
              <template v-if="record.kind === 'platform_mcp'">
                <a @click="openMcpEdit(record)">编辑</a>
                <a @click="openToolTest(record)" :class="{ disabled: actionLoading }">测试</a>
                <a @click="discoverMcp(record)" :class="{ disabled: actionLoading }">发现</a>
                <a @click="syncMcp(record)" :class="{ disabled: actionLoading }">同步工具</a>
                <a v-if="isRemoteTransport(record.transport)" @click="startMcpOauth(record)">连接授权</a>
                <a-popconfirm
                  title="删除 Server 不会删除已同步工具，仅解除关联。确认？"
                  @confirm="removeMcp(record.server_id)"
                >
                  <a style="color: #b5341c">删除</a>
                </a-popconfirm>
              </template>
              <template v-else>
                <a @click="openEditModal(record)">编辑</a>
                <a @click="openToolTest(record)" :class="{ disabled: actionLoading }">测试</a>
                <a @click="syncConn(record)" :class="{ disabled: actionLoading }">同步</a>
                <a
                  v-if="isRemoteTransport(record.transport) && record.oauth_status !== 'not_required'"
                  @click="startConnectorOauth(record)"
                >连接授权</a>
                <a @click="disconnectConn(record)">断开</a>
                <a-popconfirm title="确认删除?" @confirm="removeConn(record.connector_id)">
                  <a style="color: #b5341c">删除</a>
                </a-popconfirm>
              </template>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="catalogModalOpen"
      :title="`添加 ${selectedCatalog?.display_name || ''}`"
      @ok="submitCatalog"
      :confirm-loading="saving"
      width="640px"
    >
      <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="catalogForm.name" placeholder="如 my-github" />
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="catalogForm.display_name" />
        </a-form-item>

        <template v-if="selectedCatalog?.catalog_key === 'email'">
          <a-form-item label="服务商">
            <a-select v-model:value="emailProvider" @change="applyEmailPreset">
              <a-select-option v-for="(preset, key) in emailPresets" :key="key" :value="key">
                {{ preset.label }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-alert
            v-if="emailPresets[emailProvider]?.auth_hint"
            type="info"
            show-icon
            :message="emailPresets[emailProvider].auth_hint"
            style="margin-bottom: 16px"
          />
        </template>

        <a-form-item
          v-for="field in selectedCatalog?.required_fields || []"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <a-input-password v-if="field.type === 'password'" v-model:value="catalogForm.credentials[field.key]" />
          <a-input-number v-else-if="field.type === 'number'" v-model:value="catalogForm.credentials[field.key]" style="width: 100%" />
          <a-switch v-else-if="field.type === 'boolean'" v-model:checked="catalogForm.credentials[field.key]" />
          <a-input v-else v-model:value="catalogForm.credentials[field.key]" />
        </a-form-item>

        <a-form-item v-if="selectedCatalog?.catalog_key === 'github'" label="只读模式">
          <a-switch v-model:checked="catalogForm.connector_config.readonly" />
        </a-form-item>
        <a-form-item v-if="selectedCatalog?.catalog_key === 'feishu_group'" label="默认群 chat_id">
          <a-input v-model:value="catalogForm.connector_config.default_chat_id" />
        </a-form-item>
        <a-form-item v-if="selectedCatalog?.catalog_key === 'dingtalk_group'" label="默认群 ID">
          <a-input v-model:value="catalogForm.connector_config.default_open_conversation_id" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="mcpModalOpen"
      :title="editingMcp ? '编辑 MCP Server' : '添加 MCP Server'"
      @ok="saveMcp"
      :confirm-loading="saving"
      width="720px"
    >
      <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item v-if="!editingMcp && mcpForm.transport === 'stdio'" label="快捷预设">
          <a-select allow-clear placeholder="可选：应用常用 MCP 预设" @change="applyMcpPreset">
            <a-select-option v-for="p in mcpPresets" :key="p.key" :value="p.key">{{ p.label }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="名称" required>
          <a-input v-model:value="mcpForm.name" placeholder="唯一标识，如 github_mcp" :disabled="!!editingMcp" />
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="mcpForm.display_name" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="mcpForm.description" :rows="2" />
        </a-form-item>
        <a-form-item label="传输方式" required>
          <a-radio-group v-model:value="mcpForm.transport">
            <a-radio-button value="stdio">stdio</a-radio-button>
            <a-radio-button value="sse">SSE</a-radio-button>
            <a-radio-button value="streamable_http">Streamable HTTP</a-radio-button>
          </a-radio-group>
        </a-form-item>
        <template v-if="mcpForm.transport === 'stdio'">
          <a-form-item label="命令">
            <a-input v-model:value="mcpForm.command" placeholder="npx" />
          </a-form-item>
          <a-form-item label="参数 JSON">
            <a-textarea v-model:value="mcpForm.args_text" :rows="2" placeholder='["-y", "@modelcontextprotocol/server-fetch"]' />
          </a-form-item>
          <a-form-item label="环境变量 JSON">
            <a-textarea v-model:value="mcpForm.env_text" :rows="2" placeholder="{}" />
          </a-form-item>
        </template>
        <template v-else>
          <a-form-item :label="mcpForm.transport === 'sse' ? 'SSE URL' : 'HTTP URL'">
            <a-input v-model:value="mcpForm.url" placeholder="https://mcp.example.com/mcp" />
          </a-form-item>
          <a-form-item label="认证">
            <a-select v-model:value="mcpForm.auth_type">
              <a-select-option value="none">无</a-select-option>
              <a-select-option value="bearer">Bearer Token</a-select-option>
              <a-select-option value="oauth">OAuth 2.1</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="mcpForm.auth_type === 'bearer'" label="Bearer Token">
            <a-input-password v-model:value="mcpForm.auth_token" />
            <div class="field-hint">将写入自定义请求头 Authorization。</div>
          </a-form-item>
          <a-form-item label="请求头 JSON">
            <a-textarea v-model:value="mcpForm.headers_text" :rows="2" placeholder="{}" />
          </a-form-item>
        </template>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="editModalOpen"
      title="编辑连接器"
      @ok="submitEdit"
      :confirm-loading="saving"
      width="640px"
    >
      <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="类型">
          <a-tag>{{ catalogLabel(editForm.catalog_key) }}</a-tag>
          <span style="margin-left: 8px; color: #888">{{ editForm.name }}</span>
        </a-form-item>
        <a-form-item label="显示名称">
          <a-input v-model:value="editForm.display_name" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="editForm.description" :rows="2" />
        </a-form-item>

        <template v-if="editCatalog?.catalog_key === 'email'">
          <a-form-item label="服务商">
            <a-select v-model:value="editEmailProvider" @change="applyEditEmailPreset">
              <a-select-option v-for="(preset, key) in emailPresets" :key="key" :value="key">
                {{ preset.label }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-alert
            v-if="emailPresets[editEmailProvider]?.auth_hint"
            type="info"
            show-icon
            :message="emailPresets[editEmailProvider].auth_hint"
            style="margin-bottom: 16px"
          />
        </template>

        <a-form-item
          v-for="field in editCatalog?.required_fields || []"
          :key="field.key"
          :label="field.label"
        >
          <a-input-password
            v-if="field.type === 'password'"
            v-model:value="editForm.credentials[field.key]"
            :placeholder="'留空则不修改'"
          />
          <a-input-number
            v-else-if="field.type === 'number'"
            v-model:value="editForm.credentials[field.key]"
            style="width: 100%"
          />
          <a-switch
            v-else-if="field.type === 'boolean'"
            v-model:checked="editForm.credentials[field.key]"
          />
          <a-input v-else v-model:value="editForm.credentials[field.key]" />
        </a-form-item>

        <a-form-item v-if="editCatalog?.catalog_key === 'github'" label="只读模式">
          <a-switch v-model:checked="editForm.connector_config.readonly" />
        </a-form-item>
        <a-form-item v-if="editCatalog?.catalog_key === 'feishu_group'" label="默认群 chat_id">
          <a-input v-model:value="editForm.connector_config.default_chat_id" />
        </a-form-item>
        <a-form-item v-if="editCatalog?.catalog_key === 'dingtalk_group'" label="默认群 ID">
          <a-input v-model:value="editForm.connector_config.default_open_conversation_id" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="toolTestOpen"
      :title="`测试工具 — ${toolTestTitle}`"
      :footer="null"
      width="920px"
      destroy-on-close
      @cancel="resetToolTest"
    >
      <a-spin :spinning="toolTestLoading">
        <a-alert
          v-if="toolTestDiscoverError"
          type="error"
          show-icon
          :message="toolTestDiscoverError"
          style="margin-bottom: 12px"
        />
        <div v-else class="tool-test-layout">
          <div class="tool-test-list">
            <div class="tool-test-list-title">工具列表 ({{ toolTestTools.length }})</div>
            <div v-if="!toolTestTools.length && !toolTestLoading" class="tool-test-empty">暂无工具</div>
            <div
              v-for="tool in toolTestTools"
              :key="tool.name"
              class="tool-test-item"
              :class="{ active: selectedToolName === tool.name }"
              @click="selectTool(tool)"
            >
              <div class="tool-test-item-name">{{ tool.name }}</div>
              <div class="tool-test-item-desc">{{ tool.description || '无描述' }}</div>
            </div>
          </div>
          <div class="tool-test-panel">
            <div class="tool-test-panel-title">模型调用测试</div>
            <a-textarea
              v-model:value="toolTestInstruction"
              :rows="3"
              :disabled="!selectedToolName"
              placeholder="用自然语言描述要测试的操作，例如：搜索主题包含周报的未读邮件"
              style="margin-bottom: 8px"
            />
            <a-space wrap style="margin-bottom: 8px; width: 100%">
              <a-select
                v-model:value="toolTestProviderId"
                placeholder="供应商"
                style="width: 180px"
                show-search
                option-filter-prop="label"
                :disabled="!selectedToolName"
                @change="onToolTestProviderChange"
              >
                <a-select-option
                  v-for="p in toolTestProviders"
                  :key="p.provider_id"
                  :value="p.provider_id"
                  :label="p.display_name"
                >
                  {{ p.display_name }}
                </a-select-option>
              </a-select>
              <a-select
                v-model:value="toolTestModelServiceId"
                placeholder="模型"
                style="width: 240px"
                show-search
                option-filter-prop="label"
                :disabled="!selectedToolName || !toolTestProviderId"
              >
                <a-select-option
                  v-for="s in toolTestModelServices"
                  :key="s.model_service_id"
                  :value="s.model_service_id"
                  :label="s.display_name || s.model_name"
                >
                  {{ s.display_name || s.model_name }}
                </a-select-option>
              </a-select>
              <a-button
                type="primary"
                :loading="toolTestLlmRunning"
                :disabled="!selectedToolName || !toolTestInstruction.trim() || !toolTestModelServiceId"
                @click="runToolTestLlm"
              >
                模型调用测试
              </a-button>
            </a-space>
            <div class="tool-test-panel-title">调用参数</div>
            <pre class="tool-test-result tool-test-result-sm">{{ toolTestLlmArgs || '模型调用后在此展示生成的参数' }}</pre>
            <div class="tool-test-panel-title" style="margin-top: 8px">工具响应</div>
            <pre class="tool-test-result tool-test-result-sm">{{ toolTestLlmResult || '模型调用后在此展示工具响应' }}</pre>

            <a-divider style="margin: 12px 0" />

            <div class="tool-test-panel-title">参数 (JSON) — 手动执行</div>
            <a-textarea
              v-model:value="toolTestParams"
              :rows="6"
              :disabled="!selectedToolName"
              placeholder="选择工具后自动生成样例参数，可编辑"
              style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
            />
            <div style="margin: 12px 0">
              <a-button
                :loading="toolTestRunning"
                :disabled="!selectedToolName"
                @click="runToolTest"
              >
                执行测试
              </a-button>
            </div>
            <div class="tool-test-panel-title">手动执行响应</div>
            <pre class="tool-test-result">{{ toolTestResult || '执行后在此展示结果' }}</pre>
          </div>
        </div>
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { connectorApi, mcpServerApi, providerApi, serviceApi } from '../../api'

const route = useRoute()
const catalog = ref([])
const connectors = ref([])
const platformServers = ref([])
const loading = ref(false)
const saving = ref(false)
const actionLoading = ref(false)
const catalogModalOpen = ref(false)
const mcpModalOpen = ref(false)
const editModalOpen = ref(false)
const selectedCatalog = ref(null)
const editCatalog = ref(null)
const editingConnectorId = ref('')
const editingMcp = ref(null)
const emailProvider = ref('custom')
const editEmailProvider = ref('custom')
const emailPresets = ref({})
const oauthNotice = ref(null)

const toolTestOpen = ref(false)
const toolTestLoading = ref(false)
const toolTestRunning = ref(false)
const toolTestLlmRunning = ref(false)
const toolTestTitle = ref('')
const toolTestTarget = ref(null)
const toolTestTools = ref([])
const toolTestDiscoverError = ref('')
const selectedToolName = ref('')
const toolTestParams = ref('{}')
const toolTestResult = ref('')
const toolTestInstruction = ref('')
const toolTestProviders = ref([])
const toolTestModelServices = ref([])
const toolTestProviderId = ref('')
const toolTestModelServiceId = ref('')
const toolTestLlmArgs = ref('')
const toolTestLlmResult = ref('')
const toolTestModelsLoaded = ref(false)

const catalogForm = reactive({
  name: '',
  display_name: '',
  credentials: {},
  connector_config: { readonly: true },
})

const editForm = reactive({
  catalog_key: '',
  name: '',
  display_name: '',
  description: '',
  credentials: {},
  connector_config: {},
})

const mcpForm = reactive({
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
  { title: '名称', dataIndex: 'display_name', key: 'display_name' },
  { title: '类型', key: 'kind', width: 120 },
  { title: '传输', key: 'transport', width: 130 },
  { title: '状态', key: 'status', width: 110 },
  { title: 'OAuth', key: 'oauth_status', width: 120 },
  { title: '工具数', dataIndex: 'tool_count', key: 'tool_count', width: 80 },
  { title: '来源', dataIndex: 'source', key: 'source', ellipsis: true },
  { title: '操作', key: 'action', width: 360 },
]

const listItems = computed(() => {
  const connRows = (connectors.value || []).map((c) => ({
    ...c,
    row_id: `c:${c.connector_id}`,
    kind: 'connector',
    transport: c.transport || '',
  }))
  const mcpRows = (platformServers.value || []).map((s) => ({
    ...s,
    row_id: `m:${s.server_id}`,
    kind: 'platform_mcp',
    display_name: s.display_name || s.name,
    catalog_key: 'mcp',
    status: mapMcpStatus(s.status),
    oauth_status: oauthLabel(s),
    tool_count: s.tool_count ?? 0,
    source: s.source || [s.command, ...(s.args || [])].filter(Boolean).join(' ') || s.url || '',
  }))
  return [...connRows, ...mcpRows]
})

function catalogLabel(key) {
  const map = {
    github: 'GitHub',
    email: 'Email',
    feishu_group: '飞书群',
    dingtalk_group: '钉钉群',
    mcp: 'MCP Server',
  }
  return map[key] || '自定义'
}

function mapMcpStatus(status) {
  if (status === 'ACTIVE') return 'CONNECTED'
  if (status === 'ERROR') return 'ERROR'
  return status || 'DISCONNECTED'
}

function statusColor(status) {
  if (status === 'CONNECTED' || status === 'ACTIVE') return 'green'
  if (status === 'ERROR') return 'red'
  return 'default'
}

function transportLabel(t) {
  if (t === 'stdio') return 'stdio'
  if (t === 'sse') return 'SSE'
  if (t === 'streamable_http') return 'HTTP'
  return t || '—'
}

function isRemoteTransport(t) {
  return t === 'sse' || t === 'streamable_http'
}

function oauthLabel(record) {
  if (!isRemoteTransport(record.transport)) return 'not_required'
  if (record.auth_type === 'oauth') {
    return record.oauth_status === 'authorized' || record.status === 'ACTIVE' ? 'authorized' : 'unauthorized'
  }
  if (record.auth_type === 'bearer') return 'bearer'
  return record.oauth_status || 'none'
}

function oauthTagColor(record) {
  const v = record.oauth_status || oauthLabel(record)
  if (v === 'authorized') return 'green'
  if (v === 'unauthorized') return 'orange'
  if (v === 'bearer') return 'blue'
  return 'default'
}

async function loadCatalog() {
  const res = await connectorApi.catalog()
  catalog.value = (res.items || []).filter((x) => x.catalog_key !== 'custom')
}

async function loadAll() {
  loading.value = true
  try {
    const [connRes, mcpRes] = await Promise.all([
      connectorApi.list(),
      mcpServerApi.list(),
    ])
    connectors.value = connRes.items || []
    platformServers.value = mcpRes.items || []
  } finally {
    loading.value = false
  }
}

function resetCatalogForm(item) {
  catalogForm.name = item.catalog_key
  catalogForm.display_name = item.display_name
  catalogForm.credentials = {}
  catalogForm.connector_config = { readonly: true }
  for (const field of item.required_fields || []) {
    if (field.type === 'boolean') {
      catalogForm.credentials[field.key] = field.default !== false
    } else if (field.type === 'number') {
      catalogForm.credentials[field.key] = field.default ?? undefined
    } else {
      catalogForm.credentials[field.key] = ''
    }
  }
  if (item.catalog_key === 'email') {
    emailPresets.value = item.provider_presets || {}
    emailProvider.value = 'custom'
  }
}

function openCatalogModal(item) {
  selectedCatalog.value = item
  resetCatalogForm(item)
  catalogModalOpen.value = true
}

function applyEmailPreset(key) {
  const preset = emailPresets.value[key]
  if (!preset) return
  catalogForm.credentials.imap_host = preset.imap_host || ''
  catalogForm.credentials.imap_port = preset.imap_port
  catalogForm.credentials.imap_secure = preset.imap_secure
  catalogForm.credentials.smtp_host = preset.smtp_host || ''
  catalogForm.credentials.smtp_port = preset.smtp_port
  catalogForm.credentials.smtp_secure = preset.smtp_secure
  catalogForm.connector_config.provider_hint = key
}

function resetMcpForm() {
  Object.assign(mcpForm, {
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

function openMcpCreate() {
  editingMcp.value = null
  resetMcpForm()
  mcpModalOpen.value = true
}

function openMcpEdit(record) {
  editingMcp.value = record
  Object.assign(mcpForm, {
    name: record.name,
    display_name: record.display_name,
    description: record.description || '',
    transport: record.transport || 'stdio',
    command: record.command || '',
    args_text: JSON.stringify(record.args || [], null, 2),
    env_text: JSON.stringify(record.env || {}, null, 2),
    url: record.url || '',
    headers_text: JSON.stringify(record.headers || {}, null, 2),
    auth_type: record.auth_type || 'none',
    auth_token: '',
  })
  mcpModalOpen.value = true
}

function applyMcpPreset(key) {
  const p = mcpPresets.find((x) => x.key === key)
  if (!p) return
  mcpForm.command = p.command
  mcpForm.args_text = JSON.stringify(p.args || [], null, 2)
  if (!mcpForm.name) mcpForm.name = p.key
  if (!mcpForm.display_name) mcpForm.display_name = p.label
}

function parseMcpPayload() {
  let args = []
  let env = {}
  let headers = {}
  try { args = JSON.parse(mcpForm.args_text || '[]') } catch { args = [] }
  try { env = JSON.parse(mcpForm.env_text || '{}') } catch { env = {} }
  try { headers = JSON.parse(mcpForm.headers_text || '{}') } catch { headers = {} }
  if (mcpForm.auth_type === 'bearer' && mcpForm.auth_token) {
    headers.Authorization = `Bearer ${mcpForm.auth_token}`
  }
  return {
    name: mcpForm.name,
    display_name: mcpForm.display_name || mcpForm.name,
    description: mcpForm.description,
    transport: mcpForm.transport,
    command: mcpForm.command,
    args,
    env,
    url: mcpForm.url,
    headers,
    auth_type: mcpForm.auth_type,
  }
}

async function saveMcp() {
  if (!mcpForm.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const data = parseMcpPayload()
    if (editingMcp.value) {
      await mcpServerApi.update(editingMcp.value.server_id, data)
      message.success('MCP Server 已更新')
    } else {
      await mcpServerApi.create(data)
      message.success('MCP Server 已创建，请同步工具')
    }
    mcpModalOpen.value = false
    await loadAll()
  } catch (e) {
    message.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function discoverMcp(record) {
  actionLoading.value = true
  try {
    const res = await mcpServerApi.discover(record.server_id)
    if (res.success) message.success(`发现 ${res.total || (res.tools || []).length} 个工具`)
    else message.error(res.error || '发现失败')
  } catch (e) {
    message.error(e.message || '发现失败')
  } finally {
    actionLoading.value = false
  }
}

async function syncMcp(record) {
  actionLoading.value = true
  try {
    const res = await mcpServerApi.sync(record.server_id)
    if (res.success) {
      message.success(`同步完成：新增 ${res.created}，更新 ${res.updated}，停用 ${res.deactivated}`)
      await loadAll()
    } else {
      message.error(res.error || '同步失败')
    }
  } catch (e) {
    message.error(e.message || '同步失败')
  } finally {
    actionLoading.value = false
  }
}

async function startMcpOauth(record) {
  try {
    const frontend = `${window.location.origin}/connectors?mcp_oauth=ok&server_id=${record.server_id}`
    const res = await mcpServerApi.startOauth(record.server_id, { frontend_redirect: frontend })
    if (res.authorization_url) window.location.href = res.authorization_url
    else message.error('未返回授权地址')
  } catch (e) {
    message.error(e.message || 'OAuth 启动失败')
  }
}

async function startConnectorOauth(record) {
  try {
    const frontend = `${window.location.origin}/connectors?oauth=ok&connector_id=${record.connector_id}`
    const res = await connectorApi.startOauth(record.connector_id, { frontend_redirect: frontend })
    if (res.authorization_url) window.location.href = res.authorization_url
    else message.error('未返回授权地址')
  } catch (e) {
    message.error(e.message || 'OAuth 启动失败')
  }
}

async function removeMcp(id) {
  try {
    await mcpServerApi.delete(id)
    message.success('已删除')
    await loadAll()
  } catch (e) {
    message.error(e.message || '删除失败')
  }
}

function openEditModal(record) {
  editingConnectorId.value = record.connector_id
  editForm.catalog_key = record.catalog_key || 'custom'
  editForm.name = record.name || ''
  editForm.display_name = record.display_name || ''
  editForm.description = record.description || ''
  editForm.credentials = { ...(record.editable_credentials || {}) }
  editForm.connector_config = { ...(record.connector_config || {}) }
  editCatalog.value = catalog.value.find((c) => c.catalog_key === record.catalog_key) || null
  if (record.catalog_key === 'email') {
    emailPresets.value = editCatalog.value?.provider_presets || {}
    editEmailProvider.value = record.connector_config?.provider_hint || 'custom'
  }
  for (const field of editCatalog.value?.required_fields || []) {
    if (editForm.credentials[field.key] === undefined) {
      if (field.type === 'boolean') {
        editForm.credentials[field.key] = field.default !== false
      } else if (field.type === 'number') {
        editForm.credentials[field.key] = field.default ?? undefined
      } else {
        editForm.credentials[field.key] = ''
      }
    }
  }
  editModalOpen.value = true
}

function applyEditEmailPreset(key) {
  const preset = emailPresets.value[key]
  if (!preset) return
  editForm.credentials.imap_host = preset.imap_host || ''
  editForm.credentials.imap_port = preset.imap_port
  editForm.credentials.imap_secure = preset.imap_secure
  editForm.credentials.smtp_host = preset.smtp_host || ''
  editForm.credentials.smtp_port = preset.smtp_port
  editForm.credentials.smtp_secure = preset.smtp_secure
  editForm.connector_config.provider_hint = key
}

async function submitEdit() {
  if (!editingConnectorId.value) return
  saving.value = true
  try {
    const payload = {
      display_name: editForm.display_name,
      description: editForm.description,
      connector_config: { ...editForm.connector_config },
    }
    if (editForm.catalog_key && editForm.catalog_key !== 'custom') {
      payload.credentials = { ...editForm.credentials }
    }
    await connectorApi.update(editingConnectorId.value, payload)
    message.success('连接器已更新，请重新测试并同步')
    editModalOpen.value = false
    await loadAll()
  } catch (e) {
    message.error(e.message || '更新失败')
  } finally {
    saving.value = false
  }
}

async function submitCatalog() {
  if (!catalogForm.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    await connectorApi.fromCatalog({
      catalog_key: selectedCatalog.value.catalog_key,
      name: catalogForm.name.trim(),
      display_name: catalogForm.display_name,
      credentials: { ...catalogForm.credentials },
      connector_config: { ...catalogForm.connector_config },
    })
    message.success('连接器已创建，请测试并同步工具')
    catalogModalOpen.value = false
    await loadAll()
  } catch (e) {
    message.error(e.message || '创建失败')
  } finally {
    saving.value = false
  }
}

async function ensureToolTestModels() {
  if (toolTestModelsLoaded.value) return
  try {
    const res = await providerApi.list({ page_size: 100 })
    toolTestProviders.value = res.items || []
    toolTestModelsLoaded.value = true
    if (!toolTestProviderId.value && toolTestProviders.value.length) {
      toolTestProviderId.value = toolTestProviders.value[0].provider_id
      await loadToolTestModelServices(toolTestProviderId.value)
    }
  } catch (e) {
    message.error(e.message || '加载模型供应商失败')
  }
}

async function loadToolTestModelServices(providerId) {
  if (!providerId) {
    toolTestModelServices.value = []
    toolTestModelServiceId.value = ''
    return
  }
  const res = await serviceApi.list({ provider_id: providerId, page_size: 100 })
  toolTestModelServices.value = res.items || []
  if (!toolTestModelServices.value.some((s) => s.model_service_id === toolTestModelServiceId.value)) {
    toolTestModelServiceId.value = toolTestModelServices.value[0]?.model_service_id || ''
  }
}

async function onToolTestProviderChange() {
  toolTestModelServiceId.value = ''
  await loadToolTestModelServices(toolTestProviderId.value)
}

async function openToolTest(record) {
  toolTestTarget.value = record
  toolTestTitle.value = record.display_name || record.name || ''
  toolTestOpen.value = true
  toolTestTools.value = []
  toolTestDiscoverError.value = ''
  selectedToolName.value = ''
  toolTestParams.value = '{}'
  toolTestResult.value = ''
  toolTestInstruction.value = ''
  toolTestLlmArgs.value = ''
  toolTestLlmResult.value = ''
  toolTestLoading.value = true
  ensureToolTestModels()
  try {
    let res
    if (record.kind === 'platform_mcp') {
      res = await mcpServerApi.discover(record.server_id)
    } else {
      // Prefer /test which now returns tools on success; fall back to discover
      try {
        res = await connectorApi.test(record.connector_id)
        if (res.success && Array.isArray(res.tools)) {
          // ok
        } else {
          res = await connectorApi.discover(record.connector_id)
        }
      } catch (e) {
        toolTestDiscoverError.value = e.message || '连接失败'
        return
      }
    }
    if (!res?.success) {
      toolTestDiscoverError.value = res?.error || '发现工具失败'
      return
    }
    const tools = res.tools || []
    toolTestTools.value = tools
    if (tools.length) selectTool(tools[0])
  } catch (e) {
    toolTestDiscoverError.value = e.message || '发现工具失败'
  } finally {
    toolTestLoading.value = false
  }
}

function resetToolTest() {
  toolTestTarget.value = null
  toolTestTools.value = []
  toolTestDiscoverError.value = ''
  selectedToolName.value = ''
  toolTestParams.value = '{}'
  toolTestResult.value = ''
  toolTestInstruction.value = ''
  toolTestLlmArgs.value = ''
  toolTestLlmResult.value = ''
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
    for (const [key, prop] of Object.entries(props)) {
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

function selectTool(tool) {
  selectedToolName.value = tool.name
  const sample = mockFromJsonSchema(tool.inputSchema || {})
  toolTestParams.value = JSON.stringify(sample && typeof sample === 'object' ? sample : {}, null, 2)
  toolTestResult.value = ''
  toolTestLlmArgs.value = ''
  toolTestLlmResult.value = ''
}

async function runToolTest() {
  const target = toolTestTarget.value
  if (!target || !selectedToolName.value) return
  let args = {}
  try {
    args = JSON.parse(toolTestParams.value || '{}')
  } catch {
    message.error('参数 JSON 格式错误')
    return
  }
  toolTestRunning.value = true
  toolTestResult.value = ''
  try {
    const payload = { tool_name: selectedToolName.value, arguments: args }
    const res = target.kind === 'platform_mcp'
      ? await mcpServerApi.testTool(target.server_id, payload)
      : await connectorApi.testTool(target.connector_id, payload)
    toolTestResult.value = JSON.stringify(res, null, 2)
  } catch (e) {
    toolTestResult.value = JSON.stringify({ success: false, error: e.message || '调用失败' }, null, 2)
  } finally {
    toolTestRunning.value = false
  }
}

async function runToolTestLlm() {
  const target = toolTestTarget.value
  if (!target || !selectedToolName.value) return
  if (!toolTestInstruction.value.trim()) {
    message.warning('请输入测试指令')
    return
  }
  if (!toolTestModelServiceId.value) {
    message.warning('请选择模型')
    return
  }
  const tool = toolTestTools.value.find((t) => t.name === selectedToolName.value)
  toolTestLlmRunning.value = true
  toolTestLlmArgs.value = ''
  toolTestLlmResult.value = ''
  try {
    const payload = {
      tool_name: selectedToolName.value,
      instruction: toolTestInstruction.value.trim(),
      model_service_id: toolTestModelServiceId.value,
      input_schema: tool?.inputSchema || {},
    }
    const res = target.kind === 'platform_mcp'
      ? await mcpServerApi.testToolLlm(target.server_id, payload)
      : await connectorApi.testToolLlm(target.connector_id, payload)
    toolTestLlmArgs.value = JSON.stringify(res.arguments ?? null, null, 2)
    toolTestLlmResult.value = JSON.stringify(
      res.tool_result != null
        ? res.tool_result
        : { success: res.success, error: res.error, llm_message: res.llm_message },
      null,
      2,
    )
    if (res.arguments && typeof res.arguments === 'object') {
      toolTestParams.value = JSON.stringify(res.arguments, null, 2)
    }
    if (!res.success && res.error) {
      // keep result in panel; soft notice
      message.warning(res.error)
    }
  } catch (e) {
    toolTestLlmResult.value = JSON.stringify({ success: false, error: e.message || '调用失败' }, null, 2)
  } finally {
    toolTestLlmRunning.value = false
  }
}

async function syncConn(record) {
  actionLoading.value = true
  try {
    await connectorApi.sync(record.connector_id)
    message.success('同步成功')
    await loadAll()
  } catch (e) {
    message.error(e.message || '同步失败')
  } finally {
    actionLoading.value = false
  }
}

async function disconnectConn(record) {
  try {
    await connectorApi.disconnect(record.connector_id)
    message.success('已断开')
    await loadAll()
  } catch (e) {
    message.error(e.message || '操作失败')
  }
}

async function removeConn(id) {
  try {
    await connectorApi.delete(id)
    message.success('已删除')
    await loadAll()
  } catch (e) {
    message.error(e.message || '删除失败')
  }
}

onMounted(async () => {
  await loadCatalog()
  await loadAll()
  if (route.query.oauth === 'ok') {
    oauthNotice.value = { type: 'success', message: 'OAuth 授权完成，请同步工具' }
  }
  if (route.query.mcp_oauth === 'ok') {
    oauthNotice.value = { type: 'success', message: 'MCP OAuth 授权成功，可以同步工具了' }
  } else if (route.query.mcp_oauth === 'error') {
    oauthNotice.value = { type: 'error', message: route.query.message || 'MCP OAuth 授权失败' }
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.catalog-card {
  min-height: 120px;
  cursor: pointer;
}
.catalog-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.catalog-desc {
  color: #666;
  font-size: 13px;
  min-height: 40px;
}
.disabled {
  pointer-events: none;
  opacity: 0.5;
}
.field-hint {
  font-size: 11px;
  color: #9e9590;
  margin-top: 4px;
  line-height: 1.5;
}
.tool-test-layout {
  display: flex;
  gap: 16px;
  min-height: 520px;
  max-height: 70vh;
}
.tool-test-list {
  width: 280px;
  flex-shrink: 0;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: auto;
  max-height: 70vh;
}
.tool-test-list-title,
.tool-test-panel-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #333;
}
.tool-test-list-title {
  padding: 10px 12px 6px;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 1;
}
.tool-test-item {
  padding: 10px 12px;
  cursor: pointer;
  border-top: 1px solid #f5f5f5;
}
.tool-test-item:hover {
  background: #fafafa;
}
.tool-test-item.active {
  background: #eef5ff;
}
.tool-test-item-name {
  font-weight: 500;
  font-size: 13px;
  word-break: break-all;
}
.tool-test-item-desc {
  margin-top: 4px;
  font-size: 12px;
  color: #888;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tool-test-empty {
  padding: 24px 12px;
  color: #999;
  text-align: center;
}
.tool-test-panel {
  flex: 1;
  min-width: 0;
  overflow: auto;
  max-height: 70vh;
}
.tool-test-result {
  margin: 0;
  padding: 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 8px;
  min-height: 140px;
  max-height: 220px;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.tool-test-result-sm {
  min-height: 72px;
  max-height: 160px;
}
</style>

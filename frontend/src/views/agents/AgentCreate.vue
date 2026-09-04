<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑 Agent' : '创建 Agent' }}</h2>
    </div>
    <a-card style="max-width: 900px">
      <a-form :model="form" :label-col="{ span: 4 }" :wrapper-col="{ span: 18 }" @finish="onSubmit">
        <a-divider>Agent 类型</a-divider>

        <a-form-item label="Agent 类型" name="agent_type">
          <a-radio-group v-model:value="form.agent_type">
            <a-radio value="SINGLE">单体 Agent</a-radio>
            <a-radio value="COMPOSITE">多 Agent 编排</a-radio>
            <a-radio value="WORKFLOW">工作流型</a-radio>
          </a-radio-group>
          <span class="form-hint" v-if="form.agent_type === 'COMPOSITE'">
            创建后需在编排配置页面添加子 Agent 和 Coordinator 配置
          </span>
          <span class="form-hint" v-if="form.agent_type === 'WORKFLOW'">
            创建后需在工作流画布页面配置节点与连线
          </span>
        </a-form-item>
        <a-form-item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <a-input v-model:value="form.name" placeholder="Agent 名称" />
        </a-form-item>
        <a-form-item label="描述" name="description">
          <a-textarea v-model:value="form.description" placeholder="Agent 描述" :rows="2" />
        </a-form-item>
        <a-form-item label="供应商" :rules="[{ required: true, message: '请选择供应商' }]">
          <a-select v-model:value="selectedProviderId" placeholder="选择供应商" show-search option-filter-prop="label" @change="onProviderChange">
            <a-select-option v-for="p in providers" :key="p.provider_id" :value="p.provider_id" :label="p.display_name">
              {{ p.display_name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模型服务" name="model_service_id" :rules="[{ required: true, message: '请选择模型服务' }]">
          <a-select
            v-model:value="form.model_service_id"
            placeholder="选择模型服务"
            show-search
            option-filter-prop="label"
            :disabled="!selectedProviderId"
          >
            <a-select-option v-for="s in filteredServices" :key="s.model_service_id" :value="s.model_service_id" :label="s.display_name">
              {{ s.display_name }} ({{ s.model_name }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="System Prompt" name="system_prompt">
          <a-textarea v-model:value="form.system_prompt" placeholder="System Prompt" :rows="6" />
        </a-form-item>
        <a-form-item label="部门" name="dept_id">
          <a-input v-model:value="form.dept_id" placeholder="部门 ID" />
        </a-form-item>
        <a-form-item label="自主级别" name="autonomy_level">
          <a-select v-model:value="form.autonomy_level">
            <a-select-option value="L1">L1 - 需审批</a-select-option>
            <a-select-option value="L2">L2 - 半自主</a-select-option>
            <a-select-option value="L3">L3 - 全自主</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="并发上限" name="max_concurrent_sessions">
          <a-input-number v-model:value="form.max_concurrent_sessions" :min="1" :max="100" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Token 预算" name="token_budget">
          <a-input-number v-model:value="form.token_budget" :min="1000" :step="1000" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Skill 包" name="skill_pack_ids">
          <a-select v-model:value="form.skill_pack_ids" mode="multiple" placeholder="选择 Skill 包">
            <a-select-option v-for="s in skills" :key="s.skill_pack_id" :value="s.skill_pack_id">
              {{ s.name }} ({{ s.scope }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="知识库" name="knowledge_base_ids">
          <a-select v-model:value="form.knowledge_base_ids" mode="multiple" placeholder="选择知识库">
            <a-select-option v-for="k in knowledgeBases" :key="k.kb_id" :value="k.kb_id">
              {{ k.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="工具" name="tool_ids">
          <a-select v-model:value="form.tool_ids" mode="multiple" placeholder="选择工具" @change="onToolSelectionChange">
            <a-select-opt-group v-for="group in groupedTools" :key="group.label" :label="group.label">
              <a-select-option v-for="t in group.items" :key="t.tool_id" :value="t.tool_id">
                {{ t.display_name || t.name }} ({{ t.tool_type }})
              </a-select-option>
            </a-select-opt-group>
          </a-select>
        </a-form-item>

        <a-form-item v-if="form.tool_ids && form.tool_ids.length > 0" label="需人工审批的工具" name="tool_approvals">
          <a-table
            :dataSource="selectedToolBindings"
            :columns="toolApprovalColumns"
            rowKey="tool_id"
            size="small"
            :pagination="false"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'require_approval'">
                <a-switch v-model:checked="record.require_approval" />
              </template>
            </template>
          </a-table>
          <span class="form-hint">勾选后，该工具调用前会触发 HITL 审批（SGL-CFG-06）</span>
        </a-form-item>

        <a-form-item label="连接器" name="connector_catalog_keys">
          <a-select
            v-model:value="selectedCatalogKeys"
            mode="multiple"
            placeholder="选择连接器或 MCP Server"
            style="width: 100%"
            option-label-prop="label"
            @change="onConnectorSelectionChange"
          >
            <a-select-option
              v-for="c in connectorOptions"
              :key="c.binding_key"
              :value="c.binding_key"
              :label="c.display_name"
            >
              <a-space>
                <a-tag :color="c.kind === 'platform_mcp' ? 'purple' : 'blue'" style="margin-right: 0">
                  {{ c.kind === 'platform_mcp' ? 'MCP Server' : (c.catalog_label || c.catalog_key) }}
                </a-tag>
                <span>{{ c.display_name }}</span>
              </a-space>
            </a-select-option>
          </a-select>
          <span class="form-hint">
            列表与「连接器」页一致。目录类按类型启用（当前用户已连接实例 ∩ Agent 配置）；平台 MCP Server 对所有用户直接可用。
          </span>
        </a-form-item>

        <a-form-item
          v-if="selectedCatalogKeys.length > 0"
          label="连接器工具策略"
          name="connector_tool_policies"
        >
          <div v-for="key in selectedCatalogKeys" :key="key" class="connector-policy-block">
            <div class="connector-policy-title">
              {{ optionLabel(key) }}
            </div>
            <a-table
              :dataSource="connectorToolRows(key)"
              :columns="connectorToolColumns"
              rowKey="mcp_tool_name"
              size="small"
              :pagination="false"
              style="margin-bottom: 12px"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'enabled'">
                  <a-switch v-model:checked="record.enabled" />
                </template>
                <template v-else-if="column.key === 'require_approval'">
                  <a-switch v-model:checked="record.require_approval" :disabled="!record.enabled" />
                </template>
              </template>
            </a-table>
          </div>
          <span class="form-hint">可为每个 MCP 工具设置启用与人工审批；留空策略表示全部启用且不审批</span>
        </a-form-item>

        <a-form-item label="工具加载策略">
          <a-space direction="vertical" style="width: 100%;">
            <a-switch
              v-model:checked="toolLoadingEnabled"
              checked-children="延迟加载"
              un-checked-children="系统默认"
            />
            <a-radio-group v-if="toolLoadingEnabled" v-model:value="toolLoadingMode">
              <a-radio-button value="deferred">Deferred（按需搜索激活）</a-radio-button>
              <a-radio-button value="eager">Eager（全量注入）</a-radio-button>
            </a-radio-group>
            <span class="form-hint">
              需在系统配置中启用 Tool Search。deferred 模式下平台内置工具始终可用；
              绑定的用户/MCP 工具需经 <code>tool_search</code> 搜索激活后进入 LLM context（可配置额外常驻）。
            </span>
          </a-space>
        </a-form-item>

        <a-form-item label="标签" name="tags">
          <a-select v-model:value="form.tags" mode="tags" placeholder="输入标签" />
        </a-form-item>

        <a-divider v-if="form.agent_type === 'SINGLE'">ReAct 循环参数</a-divider>

        <template v-if="form.agent_type === 'SINGLE'">
        <a-form-item label="最大迭代次数" name="max_iterations">
          <a-input-number v-model:value="form.max_iterations" :min="1" :max="50" style="width: 100%" />
          <span class="form-hint">ReAct 循环最大迭代次数，默认 10</span>
        </a-form-item>
        <a-form-item label="单步超时(秒)" name="step_timeout_seconds">
          <a-input-number v-model:value="form.step_timeout_seconds" :min="5" :max="600" style="width: 100%" />
          <span class="form-hint">单个工具调用的超时时间，默认 60 秒</span>
        </a-form-item>
        <a-form-item label="整体超时(秒)" name="timeout_seconds">
          <a-input-number v-model:value="form.timeout_seconds" :min="10" :max="600" style="width: 100%" />
          <span class="form-hint">单次对话整体超时，默认 180 秒；带 Skill/Web 搜索建议 ≥180</span>
        </a-form-item>
        <a-form-item label="工具重试次数" name="tool_retry_count">
          <a-input-number v-model:value="form.tool_retry_count" :min="0" :max="10" style="width: 100%" />
          <span class="form-hint">工具调用失败时的重试次数，默认 2</span>
        </a-form-item>
        <a-form-item label="重试退避策略" name="tool_retry_backoff">
          <a-select v-model:value="form.tool_retry_backoff">
            <a-select-option value="fixed">固定间隔</a-select-option>
            <a-select-option value="exponential">指数退避</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="防死循环" name="allow_repeat_tool_calls">
          <a-switch v-model:checked="form.allow_repeat_tool_calls" />
          <span class="form-hint">开启后检测连续相同工具调用并自动中断</span>
        </a-form-item>
        <a-form-item label="死循环阈值" name="max_repeat_threshold" v-if="form.allow_repeat_tool_calls">
          <a-input-number v-model:value="form.max_repeat_threshold" :min="2" :max="10" style="width: 100%" />
          <span class="form-hint">连续 N 次相同调用触发中断，默认 3</span>
        </a-form-item>
        <a-form-item label="单次Token上限" name="single_call_token_limit">
          <a-input-number v-model:value="form.single_call_token_limit" :min="1024" :step="1024" style="width: 100%" />
          <span class="form-hint">单次 LLM 调用的 Token 上限，默认 8192</span>
        </a-form-item>
        </template>

        <a-form-item :wrapper-col="{ offset: 4, span: 18 }">
          <a-space>
            <a-button type="primary" html-type="submit" :loading="submitting">{{ isEdit ? '保存' : '创建' }}</a-button>
            <a-button @click="$router.back()">取消</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-card>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { agentApi, providerApi, serviceApi, skillApi, knowledgeApi, toolApi, connectorApi, mcpServerApi } from '../../api'
import { message } from 'ant-design-vue'

const router = useRouter()
const route = useRoute()
const submitting = ref(false)
const providers = ref([])
const services = ref([])
const skills = ref([])
const knowledgeBases = ref([])
const toolList = ref([])
const connectorCatalog = ref([])
const connectorOptions = ref([])
const selectedCatalogKeys = ref([])
const connectorPolicies = reactive({})
const selectedProviderId = ref('')
const toolLoadingEnabled = ref(false)
const toolLoadingMode = ref('deferred')

const connectorToolColumns = [
  { title: '工具', dataIndex: 'mcp_tool_name', key: 'mcp_tool_name', ellipsis: true },
  { title: '说明', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '启用', dataIndex: 'enabled', key: 'enabled', width: 80 },
  { title: '需审批', dataIndex: 'require_approval', key: 'require_approval', width: 90 },
]

const CATALOG_LABELS = {
  github: 'GitHub',
  email: 'Email',
  feishu_group: '飞书群',
  dingtalk_group: '钉钉群',
}

function isPlatformMcpKey(key) {
  return String(key || '').startsWith('mcp:')
}

function platformServerId(key) {
  return String(key || '').slice(4)
}

function optionLabel(key) {
  const item = connectorOptions.value.find((c) => c.binding_key === key)
  return item?.display_name || key
}

function catalogLabel(key) {
  if (isPlatformMcpKey(key)) return optionLabel(key)
  const item = connectorCatalog.value.find((c) => c.catalog_key === key)
  return item?.display_name || CATALOG_LABELS[key] || key
}

function defaultToolsForKey(key) {
  if (isPlatformMcpKey(key)) {
    const item = connectorOptions.value.find((c) => c.binding_key === key)
    return item?.default_tools || []
  }
  const tmpl = connectorCatalog.value.find((c) => c.catalog_key === key)
  return tmpl?.default_tools || []
}

async function loadPlatformMcpTools(serverId) {
  try {
    const res = await toolApi.list({ mcp_server_id: serverId, page_size: 100, status: 'ACTIVE' })
    return (res.items || []).map((t) => ({
      name: (t.config && t.config.mcp_tool_name) || t.display_name || t.name,
      description: t.description || '',
    }))
  } catch {
    return []
  }
}

async function buildConnectorOptions(connectors, servers) {
  const options = []
  const seenCatalog = new Set()
  for (const c of connectors || []) {
    if (!c.catalog_key || c.catalog_key === 'custom') continue
    // One selectable entry per catalog type (same runtime semantics as before).
    if (seenCatalog.has(c.catalog_key)) continue
    seenCatalog.add(c.catalog_key)
    const tmpl = connectorCatalog.value.find((x) => x.catalog_key === c.catalog_key)
    options.push({
      binding_key: c.catalog_key,
      kind: 'connector',
      catalog_key: c.catalog_key,
      catalog_label: CATALOG_LABELS[c.catalog_key] || c.catalog_key,
      display_name: tmpl?.display_name || c.display_name || c.catalog_key,
      default_tools: tmpl?.default_tools || [],
    })
  }
  for (const s of servers || []) {
    const bindingKey = `mcp:${s.server_id}`
    const tools = await loadPlatformMcpTools(s.server_id)
    options.push({
      binding_key: bindingKey,
      kind: 'platform_mcp',
      catalog_key: bindingKey,
      mcp_server_id: s.server_id,
      catalog_label: 'MCP Server',
      display_name: s.display_name || s.name,
      default_tools: tools,
    })
  }
  return options
}

function ensureConnectorPolicy(key) {
  if (!connectorPolicies[key]) {
    const defaults = defaultToolsForKey(key)
    connectorPolicies[key] = defaults.map((t) => ({
      mcp_tool_name: t.name,
      description: t.description || '',
      enabled: true,
      require_approval: false,
    }))
  }
  return connectorPolicies[key]
}

function connectorToolRows(key) {
  return ensureConnectorPolicy(key)
}

async function onConnectorSelectionChange(keys) {
  const next = keys || []
  selectedCatalogKeys.value = next
  for (const key of next) {
    if (isPlatformMcpKey(key)) {
      const opt = connectorOptions.value.find((c) => c.binding_key === key)
      if (opt && (!opt.default_tools || !opt.default_tools.length)) {
        opt.default_tools = await loadPlatformMcpTools(platformServerId(key))
      }
    }
    ensureConnectorPolicy(key)
  }
  for (const key of Object.keys(connectorPolicies)) {
    if (!next.includes(key)) {
      delete connectorPolicies[key]
    }
  }
}

function buildConnectorBindingsPayload() {
  return (selectedCatalogKeys.value || []).map((key) => ({
    catalog_key: key,
    tools: (connectorPolicies[key] || []).map((t) => ({
      mcp_tool_name: t.mcp_tool_name,
      enabled: !!t.enabled,
      require_approval: !!t.require_approval,
    })),
  }))
}

function loadConnectorBindingsFromAgent(bindings) {
  selectedCatalogKeys.value = []
  Object.keys(connectorPolicies).forEach((k) => delete connectorPolicies[k])
  for (const b of bindings || []) {
    const key = b.catalog_key
    if (!key || key === 'custom') continue
    // Keep orphan catalog/MCP bindings selectable even if not in current options.
    if (!connectorOptions.value.find((c) => c.binding_key === key)) {
      connectorOptions.value.push({
        binding_key: key,
        kind: isPlatformMcpKey(key) ? 'platform_mcp' : 'connector',
        catalog_key: key,
        catalog_label: isPlatformMcpKey(key) ? 'MCP Server' : (CATALOG_LABELS[key] || key),
        display_name: b.display_name || catalogLabel(key),
        default_tools: [],
      })
    }
    selectedCatalogKeys.value.push(key)
    const defaults = defaultToolsForKey(key)
    const byName = new Map((b.tools || []).map((t) => [t.mcp_tool_name, t]))
    const names = new Set([
      ...defaults.map((t) => t.name),
      ...[...byName.keys()],
    ])
    connectorPolicies[key] = [...names].sort().map((name) => {
      const def = defaults.find((t) => t.name === name)
      const saved = byName.get(name)
      return {
        mcp_tool_name: name,
        description: def?.description || '',
        enabled: saved ? saved.enabled !== false : true,
        require_approval: !!(saved && saved.require_approval),
      }
    })
  }
}

const groupedTools = computed(() => {
  return [{ label: '全部工具', items: toolList.value }]
})
const filteredServices = computed(() => {
  if (!selectedProviderId.value) return []
  return services.value.filter((s) => s.provider_id === selectedProviderId.value)
})

const isEdit = computed(() => !!route.params.id)
const agentId = computed(() => route.params.id)

const form = reactive({
  name: '',
  description: '',
  model_service_id: '',
  system_prompt: '',
  dept_id: '',
  autonomy_level: 'L2',
  max_concurrent_sessions: 5,
  token_budget: 8000,
  skill_pack_ids: [],
  knowledge_base_ids: [],
  tool_ids: [],
  tags: [],
  tool_permissions: {},
  max_iterations: 10,
  step_timeout_seconds: 60,
  timeout_seconds: 180,
  tool_retry_count: 2,
  tool_retry_backoff: 'fixed',
  allow_repeat_tool_calls: true,
  max_repeat_threshold: 3,
  single_call_token_limit: 8192,
  agent_type: 'SINGLE',
  composition_config: {},
})

// SGL-CFG-06: 每个选中工具的 HITL 审批配置
const selectedToolBindings = ref([])
const toolApprovalColumns = [
  { title: '工具 ID', dataIndex: 'tool_id', key: 'tool_id', ellipsis: true },
  { title: '工具名', dataIndex: 'tool_name', key: 'tool_name', ellipsis: true },
  { title: '需审批', dataIndex: 'require_approval', key: 'require_approval', width: 100 },
]

function syncToolBindingsFromForm() {
  const ids = form.tool_ids || []
  // 保留已勾选状态，新增的默认 false，移除的删除
  const existing = new Map(selectedToolBindings.value.map(b => [b.tool_id, b]))
  selectedToolBindings.value = ids.map(tid => {
    const t = toolList.value.find(x => x.tool_id === tid)
    return {
      tool_id: tid,
      tool_name: t ? (t.display_name || t.name) : tid,
      require_approval: existing.get(tid)?.require_approval || false,
    }
  })
}

function onToolSelectionChange() {
  syncToolBindingsFromForm()
}

async function loadModelServices(providerId) {
  if (!providerId) {
    services.value = []
    return
  }
  const res = await serviceApi.list({ provider_id: providerId, page_size: 100 })
  services.value = res.items || []
}

async function onProviderChange() {
  form.model_service_id = ''
  await loadModelServices(selectedProviderId.value)
}

function ensureCurrentModelService(agent) {
  if (!agent?.model_service_id) return false
  const exists = services.value.some((s) => s.model_service_id === agent.model_service_id)
  if (!exists) {
    services.value.unshift({
      model_service_id: agent.model_service_id,
      display_name: agent.model_name || agent.model_service_id,
      model_name: agent.model_name || '',
      provider_id: selectedProviderId.value || agent.provider_id || '',
    })
  }
  return exists
}

onMounted(async () => {
  try {
    const [pv, sk, kb, tl, cat, connRes, mcpRes] = await Promise.all([
      providerApi.list({ page_size: 100 }),
      skillApi.list({ page_size: 100 }),
      knowledgeApi.list({ page_size: 100 }),
      toolApi.list({ page_size: 100 }),
      connectorApi.catalog(),
      connectorApi.list(),
      mcpServerApi.list(),
    ])
    providers.value = pv.items || []
    skills.value = sk.items
    knowledgeBases.value = kb.items
    toolList.value = tl.items
    connectorCatalog.value = (cat.items || []).filter((c) => c.catalog_key !== 'custom')
    connectorOptions.value = await buildConnectorOptions(connRes.items, mcpRes.items)

    if (isEdit.value) {
      const agent = await agentApi.get(agentId.value)
      selectedProviderId.value = agent.provider_id || ''
      await loadModelServices(selectedProviderId.value)
      ensureCurrentModelService(agent)
      Object.assign(form, {
        name: agent.name,
        description: agent.description,
        model_service_id: agent.model_service_id,
        system_prompt: agent.system_prompt,
        dept_id: agent.dept_id,
        autonomy_level: agent.autonomy_level,
        max_concurrent_sessions: agent.max_concurrent_sessions,
        token_budget: agent.token_budget,
        skill_pack_ids: agent.skill_pack_ids || [],
        knowledge_base_ids: agent.knowledge_base_ids || [],
        tool_ids: agent.tool_ids || [],
        tags: agent.tags || [],
        tool_permissions: agent.tool_permissions || {},
        max_iterations: agent.max_iterations || 10,
        step_timeout_seconds: agent.step_timeout_seconds || 60,
        timeout_seconds: agent.timeout_seconds || 180,
        tool_retry_count: agent.tool_retry_count ?? 2,
        tool_retry_backoff: agent.tool_retry_backoff || 'fixed',
        allow_repeat_tool_calls: agent.allow_repeat_tool_calls ?? true,
        max_repeat_threshold: agent.max_repeat_threshold || 3,
        single_call_token_limit: agent.single_call_token_limit || 8192,
        agent_type: agent.agent_type || 'SINGLE',
        composition_config: agent.composition_config || {},
      })
      const tlCfg = (agent.composition_config || {}).tool_loading || {}
      toolLoadingEnabled.value = tlCfg.enabled === true || tlCfg.mode === 'deferred' || tlCfg.mode === 'eager'
      toolLoadingMode.value = tlCfg.mode === 'eager' ? 'eager' : 'deferred'
      // SGL-CFG-06: 回填工具审批配置
      const bindings = agent.tool_bindings || []
      selectedToolBindings.value = (agent.tool_ids || []).map(tid => {
        const t = toolList.value.find(x => x.tool_id === tid)
        const b = bindings.find(x => x.tool_id === tid)
        return {
          tool_id: tid,
          tool_name: t ? (t.display_name || t.name) : tid,
          require_approval: !!(b && b.require_approval),
        }
      })
      loadConnectorBindingsFromAgent(agent.connector_bindings || [])
      for (const key of selectedCatalogKeys.value) {
        if (isPlatformMcpKey(key)) {
          const opt = connectorOptions.value.find((c) => c.binding_key === key)
          if (opt) {
            opt.default_tools = await loadPlatformMcpTools(platformServerId(key))
          }
          ensureConnectorPolicy(key)
        }
      }
    } else {
      services.value = []
    }
  } catch (e) {
    message.error(e.message)
  }
})

async function onSubmit() {
  submitting.value = true
  try {
    // SGL-CFG-06: 提交时合并 tool_ids + require_approval 为 tool_bindings
    const payload = { ...form }
    if (toolLoadingEnabled.value) {
      payload.composition_config = {
        ...(form.composition_config || {}),
        tool_loading: {
          enabled: true,
          mode: toolLoadingMode.value,
        },
      }
    } else if (form.composition_config?.tool_loading) {
      const next = { ...(form.composition_config || {}) }
      delete next.tool_loading
      payload.composition_config = next
    }
    if (selectedToolBindings.value.length > 0) {
      payload.tool_bindings = selectedToolBindings.value.map(b => ({
        tool_id: b.tool_id,
        require_approval: !!b.require_approval,
      }))
      delete payload.tool_ids
    }
    payload.connector_bindings = buildConnectorBindingsPayload()
    if (isEdit.value) {
      await agentApi.update(agentId.value, payload)
      message.success('Agent 更新成功')
      if (form.agent_type === 'COMPOSITE') {
        router.push(`/agents/${agentId.value}/composition`)
        return
      }
      if (form.agent_type === 'WORKFLOW') {
        router.push(`/agents/${agentId.value}/workflow`)
        return
      }
    } else {
      const res = await agentApi.create(payload)
      message.success('Agent 创建成功')
      if (form.agent_type === 'COMPOSITE' && res.agent_id) {
        router.push(`/agents/${res.agent_id}/composition`)
        return
      }
      if (form.agent_type === 'WORKFLOW' && res.agent_id) {
        router.push(`/agents/${res.agent_id}/workflow`)
        return
      }
    }
    router.push('/agents')
  } catch (e) {
    message.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.form-hint { display: block; font-size: 12px; color: #999; margin-top: 2px; }
.connector-policy-block { margin-bottom: 8px; }
.connector-policy-title { font-weight: 600; margin-bottom: 6px; color: #1a1714; }
</style>
/**
 * Map vela_* ops tools → app routes + typed cards for OpsAgentPanel.
 */

const WIDTH_KEY = 'vela_ops_panel_width'
const PAGE_SIZE = 8

export function loadPanelWidth(fallback = 420) {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY))
    if (Number.isFinite(n) && n >= 360) return n
  } catch (_) { /* ignore */ }
  return fallback
}

export function savePanelWidth(w) {
  try {
    localStorage.setItem(WIDTH_KEY, String(Math.round(w)))
  } catch (_) { /* ignore */ }
}

export function clampPanelWidth(w) {
  const max = Math.min(900, (typeof window !== 'undefined' ? window.innerWidth : 1200) - 48)
  return Math.max(360, Math.min(max, Math.round(w)))
}

export const DOMAIN_ROUTES = {
  agents: { list: '/agents', create: '/agents/create', label: '智能体', idKey: 'agent_id' },
  tools: { list: '/tools', create: '/tools', label: '工具', idKey: 'tool_id' },
  skills: { list: '/skills', create: '/skills', label: 'Skill 包', idKey: 'skill_pack_id' },
  kb: { list: '/knowledge', create: '/knowledge', label: '知识库', idKey: 'kb_id' },
  approvals: { list: '/approvals', create: '/approvals', label: '审批中心', idKey: 'approval_id' },
  models: { list: '/services', create: '/services', label: '模型服务', idKey: 'model_service_id' },
  schedules: { list: '/schedules', create: '/schedules', label: '定时任务', idKey: 'schedule_id' },
  connectors: { list: '/connectors', create: '/connectors', label: '连接器', idKey: 'connector_id' },
  sessions: { list: '/monitor', create: '/monitor', label: '监控', idKey: 'session_id' },
  memory: { list: '/memory', create: '/memory', label: '记忆管理', idKey: 'passage_id' },
}

const ACTION_TITLES = {
  list: '已列出',
  get: '已查看',
  create: '已创建',
  update: '已更新',
  delete: '已删除',
  publish: '已发布',
  deprecate: '已下线',
  republish: '已重新发布',
  approve: '已批准',
  reject: '已拒绝',
  bind: '已绑定',
  bind_tools: '已绑定工具',
  bind_skills: '已绑定 Skill',
  bind_kb: '已绑定知识库',
  test: '已测试',
  enable: '已启用',
  disable: '已停用',
  trigger: '已触发',
  sync: '已同步',
  search: '已搜索',
  catalog: '已查看目录',
  providers: '已列出供应商',
  builtin: '已列出内置工具',
  run: '已执行',
}

const LIST_ACTIONS = new Set(['list', 'providers', 'builtin', 'catalog', 'search', 'passages_list', 'scopes_list'])
const ENTITY_ACTIONS = new Set(['get', 'create', 'update', 'passages_create'])
const CHOICE_ACTIONS = new Set(['approve', 'reject'])
/** List tools that require the user to pick one row before the agent continues. */
const SELECT_ACTIONS = new Set(['scopes_list'])
const STATUS_ACTIONS = new Set([
  'delete', 'publish', 'deprecate', 'republish', 'bind', 'bind_tools', 'bind_skills',
  'bind_kb', 'test', 'enable', 'disable', 'trigger', 'sync', 'run',
])

const FIELD_LABELS = {
  name: '名称',
  display_name: '显示名',
  agent_type: '类型',
  tool_type: '类型',
  status: '状态',
  description: '描述',
  model_name: '模型',
  model_service_id: '模型服务',
  agent_id: '智能体 ID',
  tool_id: '工具 ID',
  skill_pack_id: 'Skill ID',
  kb_id: '知识库 ID',
  approval_id: '审批 ID',
  session_id: '会话 ID',
  schedule_id: '任务 ID',
  connector_id: '连接器 ID',
  category: '类别',
  tool_name: '工具名',
  cron_expression: 'Cron',
  version: '版本',
  scope: '范围',
}

/** Deep-unwrap nested JSON / {success,result} wrappers until we hit list/items or entity. */
export function tryParseJson(text) {
  if (text == null) return null
  if (typeof text === 'object') return unwrapPayload(text)
  if (typeof text !== 'string') return null
  const t = text.trim()
  if (!t) return null

  const candidates = [t]
  const start = t.indexOf('{')
  const end = t.lastIndexOf('}')
  if (start >= 0 && end > start) candidates.push(t.slice(start, end + 1))
  const aStart = t.indexOf('[')
  const aEnd = t.lastIndexOf(']')
  if (aStart >= 0 && aEnd > aStart) candidates.push(t.slice(aStart, aEnd + 1))

  for (const c of candidates) {
    try {
      let obj = JSON.parse(c)
      if (typeof obj === 'string') {
        try { obj = JSON.parse(obj) } catch (_) { /* keep */ }
      }
      const unwrapped = unwrapPayload(obj)
      if (unwrapped) return unwrapped
    } catch (_) { /* next */ }
  }
  return null
}

function unwrapPayload(obj, depth = 0) {
  if (!obj || typeof obj !== 'object' || depth > 6) return obj && typeof obj === 'object' ? obj : null
  if (Array.isArray(obj)) return { items: obj, total: obj.length }
  if (Array.isArray(obj.items)) return obj
  if (obj.result != null) {
    let inner = obj.result
    if (typeof inner === 'string') {
      const parsed = tryParseJson(inner)
      if (parsed) return unwrapPayload(parsed, depth + 1)
      try {
        inner = JSON.parse(inner)
      } catch (_) {
        return obj
      }
    }
    if (inner && typeof inner === 'object') {
      return unwrapPayload(inner, depth + 1)
    }
  }
  return obj
}

function parseToolName(toolName) {
  const name = String(toolName || '').trim()
  if (!name.startsWith('vela_')) return null
  if (name === 'vela_run') return { domain: null, action: 'run', raw: name }
  const rest = name.slice('vela_'.length)
  const parts = rest.split('_')
  const domain = parts[0]
  const action = parts.slice(1).join('_') || 'list'
  return { domain, action, raw: name }
}

function domainFromSubcommand(subcommand) {
  const first = String(subcommand || '').trim().split(/\s+/)[0]
  if (DOMAIN_ROUTES[first]) return first
  return null
}

export function buildItemPath(domain, item) {
  if (!item || typeof item !== 'object') return DOMAIN_ROUTES[domain]?.list || null
  const meta = DOMAIN_ROUTES[domain]
  if (!meta) return null
  const id = item[meta.idKey]
  if (!id) return meta.list
  if (domain === 'agents') return `/agents/${id}`
  if (domain === 'kb') return `/knowledge/${id}`
  if (domain === 'schedules') return `/schedules/${id}`
  if (domain === 'approvals') return `/approvals`
  if (domain === 'tools') return `/tools`
  if (domain === 'skills') return `/skills`
  if (domain === 'models') return `/services`
  if (domain === 'connectors') return `/connectors`
  if (domain === 'sessions') return `/monitor`
  if (domain === 'memory') {
    const aid = item.agent_id
    return aid ? `/memory?agent_id=${encodeURIComponent(aid)}&tab=passages` : `${meta.list}?tab=passages`
  }
  return meta.list
}

function buildPath(domain, payload) {
  const meta = DOMAIN_ROUTES[domain]
  if (!meta) return null
  if (payload && !Array.isArray(payload.items) && payload[meta.idKey]) {
    return buildItemPath(domain, payload)
  }
  return meta.list
}

function hasEntityId(domain, payload) {
  const idKey = DOMAIN_ROUTES[domain]?.idKey
  return !!(idKey && payload && typeof payload === 'object' && !Array.isArray(payload.items) && payload[idKey])
}

/**
 * Best app path after a successful ops action.
 * list/search → domain list; entity with id → detail (or list); else list.
 */
export function resolveNavigatePath(action) {
  if (!action?.domain || !DOMAIN_ROUTES[action.domain]) return null
  const domain = action.domain
  const meta = DOMAIN_ROUTES[domain]
  const payload = action.payload
  // Selection / empty list cards must not auto-jump away from the chat wait state
  if (action.type === 'choice_select' || action.awaitingSelection) return null
  if (domain === 'memory') {
    const aid = payload?.agent_id || payload?.result?.agent_id
      || (Array.isArray(payload?.items) && payload.items[0]?.agent_id)
    // Only navigate after a real write (create) or when a concrete agent scope is known
    if (action.action === 'passages_create' || action.action === 'create') {
      return aid ? `/memory?agent_id=${encodeURIComponent(aid)}&tab=passages` : null
    }
    if (action.action === 'passages_list' && aid) {
      return `/memory?agent_id=${encodeURIComponent(aid)}&tab=passages`
    }
    return null
  }
  if (action.type === 'data_list' || LIST_ACTIONS.has(action.action) || action.hasItems) {
    return meta.list
  }
  if (action.type === 'action_prompt' && action.promptPath) {
    return action.promptPath
  }
  if (hasEntityId(domain, payload)) {
    return buildItemPath(domain, payload)
  }
  if (action.path) return action.path
  return meta.list
}

function summarizePayload(domain, action, payload) {
  if (!payload || typeof payload !== 'object') return ''
  if (Array.isArray(payload.items)) {
    const n = payload.total != null ? payload.total : payload.items.length
    return `共 ${n} 条`
  }
  if (Array.isArray(payload)) return `共 ${payload.length} 条`
  const idKeys = [
    'agent_id', 'tool_id', 'skill_pack_id', 'kb_id', 'approval_id',
    'session_id', 'schedule_id', 'connector_id', 'model_service_id',
  ]
  for (const k of idKeys) {
    if (payload[k]) {
      const name = payload.name || payload.display_name || ''
      return name ? `${name} · ${String(payload[k]).slice(0, 8)}…` : `${k}=${String(payload[k]).slice(0, 12)}`
    }
  }
  if (payload.message) return String(payload.message).slice(0, 80)
  if (payload.ok) return '操作成功'
  return ''
}

function titleFor(domain, action) {
  const label = DOMAIN_ROUTES[domain]?.label || domain || '操作'
  const verb = ACTION_TITLES[action] || '已完成'
  return `${verb}${label}`
}

function itemDedupKey(domain, item) {
  const idKey = DOMAIN_ROUTES[domain]?.idKey
  if (idKey && item?.[idKey]) return String(item[idKey])
  return JSON.stringify(item?.name || item)
}

function mergeListPayloads(domain, payloads) {
  const byId = new Map()
  let total = 0
  for (const p of payloads) {
    if (!p) continue
    const items = Array.isArray(p.items) ? p.items : (Array.isArray(p) ? p : [])
    if (typeof p.total === 'number') total = Math.max(total, p.total)
    for (const it of items) {
      const key = itemDedupKey(domain, it)
      byId.set(key, it)
    }
  }
  const items = [...byId.values()]
  return {
    items,
    total: Math.max(total, items.length),
    page: 1,
    page_size: items.length,
  }
}

function isListLikeAction(action, payload) {
  if (LIST_ACTIONS.has(action)) return true
  if (payload && Array.isArray(payload.items)) return true
  return false
}

function isSelectableList(domain, action) {
  if (SELECT_ACTIONS.has(action)) return true
  // Agents list is often used to pick which agent to operate on (e.g. memory write)
  if (domain === 'agents' && (action === 'list' || action === 'search')) return true
  return false
}

function inferCardType(domain, action, payload) {
  const hasItems = !!(payload && Array.isArray(payload.items) && payload.items.length)
  if (isSelectableList(domain, action) && hasItems) return 'choice_select'
  if (hasItems || LIST_ACTIONS.has(action)) return 'data_list'
  if (CHOICE_ACTIONS.has(action)) return 'choice_confirm'
  if (ENTITY_ACTIONS.has(action) && hasEntityId(domain, payload)) return 'entity_display'
  if (ENTITY_ACTIONS.has(action) && !hasEntityId(domain, payload) && !hasItems) {
    // create/update without entity body → guide user to app form
    if (action === 'create') return 'action_prompt'
    return 'status_result'
  }
  if (STATUS_ACTIONS.has(action)) return 'status_result'
  if (hasEntityId(domain, payload)) return 'entity_display'
  return 'status_result'
}

/** Drop blank / useless rows so cards never show empty memory/content lines. */
export function filterEmptyItems(domain, action, items) {
  if (!Array.isArray(items)) return { items: [], dropped: 0 }
  const out = []
  let dropped = 0
  for (const it of items) {
    if (!it || typeof it !== 'object') {
      dropped += 1
      continue
    }
    const looksLikePassage = !!(it.passage_id || ((it.content != null || it.text != null) && !it.mapping_id && !it.name))
    if (domain === 'memory' && (action === 'passages_list' || looksLikePassage)) {
      const text = String(it.content || it.text || '').trim()
      if (!text) {
        dropped += 1
        continue
      }
    }
    const idKey = DOMAIN_ROUTES[domain]?.idKey
    const hasId = !!(idKey && it[idKey]) || !!(it.agent_id || it.mapping_id || it.passage_id)
    const hasLabel = !!(it.name || it.display_name || it.content || it.text || it.username || it.tool_name)
    if (!hasId && !hasLabel) {
      dropped += 1
      continue
    }
    out.push(it)
  }
  return { items: out, dropped }
}

function buildActionPrompt(domain, action) {
  const meta = DOMAIN_ROUTES[domain]
  if (!meta) return null
  const label = meta.label
  if (action === 'create') {
    return {
      promptPath: meta.create || meta.list,
      promptTitle: `去创建${label}`,
      promptHint: `可在「${label}」页面完成完整表单录入与发布。`,
      primaryLabel: `打开${label}创建`,
      secondaryPath: meta.list,
      secondaryLabel: `查看${label}列表`,
    }
  }
  return {
    promptPath: meta.list,
    promptTitle: `打开${label}`,
    promptHint: `前往应用中查看或继续操作${label}。`,
    primaryLabel: `打开${label}`,
    secondaryPath: null,
    secondaryLabel: null,
  }
}

function enrichCard(base) {
  const rawItems = Array.isArray(base.payload?.items)
    ? base.payload.items
    : (Array.isArray(base.items) ? base.items : [])
  const filtered = filterEmptyItems(base.domain, base.action, rawItems)
  const payload = base.payload && typeof base.payload === 'object'
    ? {
        ...base.payload,
        items: filtered.items,
        total: filtered.items.length
          ? (typeof base.payload.total === 'number'
            ? Math.max(0, base.payload.total - filtered.dropped)
            : filtered.items.length)
          : 0,
      }
    : base.payload
  // Failed ops always render as status_result (never fake success list/entity cards)
  const type = base.ok === false
    ? 'status_result'
    : inferCardType(base.domain, base.action, payload)
  const awaitingSelection = type === 'choice_select'
  const card = {
    ...base,
    payload,
    type,
    awaitingSelection,
    path: resolveNavigatePath({ ...base, payload, type, awaitingSelection }) || base.path,
    pageSize: PAGE_SIZE,
    _emptyDropped: filtered.dropped,
  }
  if (type === 'data_list' || type === 'choice_select') {
    card.items = filtered.items
    card.total = payload?.total ?? filtered.items.length
    card.hasItems = filtered.items.length > 0
    if (type === 'choice_select') {
      card.title = base.domain === 'memory'
        ? '请选择记忆作用域（智能体）'
        : `请选择${DOMAIN_ROUTES[base.domain]?.label || '一项'}`
      card.summary = filtered.items.length
        ? `共 ${card.total} 项，点击「选择」后继续`
        : '无可选项'
      card.selectHint = '选择后将自动发送确认消息，助手会继续执行。'
    }
  } else if (type === 'entity_display') {
    card.entity = payload
    card.fields = entityFieldsForDomain(base.domain, payload)
    card.hasItems = false
  } else if (type === 'action_prompt') {
    Object.assign(card, buildActionPrompt(base.domain, base.action) || {})
    card.hasItems = false
  } else if (type === 'choice_confirm') {
    card.choices = [
      { key: 'approve', label: '批准', tone: 'primary' },
      { key: 'reject', label: '拒绝', tone: 'danger' },
    ]
    card.choiceDone = base.action === 'approve' || base.action === 'reject'
    card.choiceResult = base.action === 'approve' ? 'approved' : (base.action === 'reject' ? 'rejected' : null)
    card.hasItems = false
  } else {
    card.hasItems = false
    if (base.ok === false) {
      card.title = card.title || `${DOMAIN_ROUTES[base.domain]?.label || '操作'}失败`
    }
  }
  // Drop empty list cards entirely (e.g. all blank passages)
  if ((type === 'data_list' || type === 'choice_select') && !card.hasItems && filtered.dropped > 0) {
    return null
  }
  return card
}

/**
 * Prefer field list for entity display cards.
 */
export function entityFieldsForDomain(domain, entity) {
  if (!entity || typeof entity !== 'object') return []
  const preferByDomain = {
    agents: ['name', 'agent_type', 'status', 'description', 'model_name', 'agent_id'],
    tools: ['name', 'display_name', 'tool_type', 'status', 'description', 'tool_id'],
    skills: ['name', 'version', 'scope', 'status', 'description', 'skill_pack_id'],
    kb: ['name', 'status', 'description', 'scope', 'kb_id'],
    schedules: ['name', 'status', 'cron_expression', 'description', 'schedule_id', 'agent_id'],
    approvals: ['tool_name', 'category', 'status', 'approval_id', 'session_id'],
    models: ['name', 'display_name', 'status', 'model_service_id'],
    connectors: ['name', 'status', 'description', 'connector_id'],
    sessions: ['session_id', 'status', 'agent_id'],
  }
  const keys = preferByDomain[domain] || [
    'name', 'display_name', 'status', 'description',
  ]
  const out = []
  for (const k of keys) {
    if (entity[k] == null || entity[k] === '' || typeof entity[k] === 'object') continue
    out.push({
      key: k,
      label: FIELD_LABELS[k] || k,
      value: String(entity[k]),
    })
  }
  return out
}

export function fieldLabel(key) {
  return FIELD_LABELS[key] || key
}

/**
 * Extract ops actions from an execution_story object (merged/deduped, typed cards).
 */
export function extractOpsActions(story) {
  if (!story || !Array.isArray(story.phases)) return []
  const raw = []
  for (const phase of story.phases) {
    for (const step of phase.steps || []) {
      if (step.kind !== 'tool' && step.kind !== 'code') continue
      const toolName = step.tool_name || ''
      if (!String(toolName).startsWith('vela_')) continue
      const stepOk = step.status !== 'fail' && step.status !== 'error'

      const parsed = parseToolName(toolName)
      if (!parsed) continue

      const detailRaw = step.detail || ''
      const payload = tryParseJson(detailRaw)
      // CLI wrappers embed business success in JSON even when the Python call "succeeded"
      const businessOk = !(
        payload
        && typeof payload === 'object'
        && (payload.success === false
          || payload.error
          || payload.exit_code > 0
          || (payload.result && payload.result.error === true))
      )
      const ok = stepOk && businessOk

      let domain = parsed.domain
      let action = parsed.action

      if (parsed.raw === 'vela_run') {
        const cmd = (payload && payload.command) || step.detail || ''
        const m = String(cmd).match(/vela_cli[^\s]*\s+--json\s+(\w+)/)
          || String(cmd).match(/\b(agents|tools|skills|kb|approvals|sessions|models|schedules|connectors|memory)\b/)
        domain = domainFromSubcommand(m?.[1]) || domain
        action = action || 'run'
      }

      if (!domain || !DOMAIN_ROUTES[domain]) continue

      const failSummary = !ok ? failSummaryFromPayload(payload) : ''

      raw.push({
        toolName,
        domain,
        action,
        path: buildPath(domain, payload),
        title: ok ? titleFor(domain, action) : `${DOMAIN_ROUTES[domain].label}失败`,
        summary: ok
          ? (summarizePayload(domain, action, payload) || (DOMAIN_ROUTES[domain].label + '已更新'))
          : failSummary,
        pageLabel: DOMAIN_ROUTES[domain].label,
        ok,
        payload: payload || null,
        hasItems: !!(payload && Array.isArray(payload.items) && payload.items.length),
      })
    }
  }

  return preferSelectionCards(mergeOpsActions(raw).map(enrichCard).filter(Boolean))
}

function failSummaryFromPayload(payload) {
  if (!payload || typeof payload !== 'object') return '操作失败'
  const candidates = [
    payload?.error?.detail,
    typeof payload.error === 'string' ? payload.error : null,
    payload?.result?.body?.detail,
    payload?.body?.detail,
    typeof payload.message === 'string' ? payload.message : null,
  ]
  for (const c of candidates) {
    if (c && typeof c === 'string' && c.trim()) return c.trim().slice(0, 100)
  }
  return '操作失败'
}

/** Prefer one agent picker; drop redundant scopes picker when agents list exists. */
function preferSelectionCards(cards) {
  if (!cards?.length) return cards
  const hasAgentSelect = cards.some((c) => c.type === 'choice_select' && c.domain === 'agents')
  if (!hasAgentSelect) return cards
  return cards.filter((c) => !(c.type === 'choice_select' && c.domain === 'memory' && c.action === 'scopes_list'))
}

function mergeOpsActions(raw) {
  if (!raw.length) return []
  const listBuckets = new Map()
  const others = new Map()

  for (const a of raw) {
    if (a.ok && isListLikeAction(a.action, a.payload) && a.domain) {
      // Keep scopes / passages / generic lists separate — different schemas
      const kind = a.action === 'scopes_list'
        ? 'scopes'
        : (a.action === 'passages_list' ? 'passages' : 'list')
      const key = `${a.domain}:${kind}`
      if (!listBuckets.has(key)) listBuckets.set(key, [])
      listBuckets.get(key).push(a)
    } else {
      // Dedupe status/entity by domain; prefer dedicated tools over vela_run
      const family = (a.action === 'run' || a.action === 'passages_create' || a.action === 'create')
        ? 'write'
        : a.action
      const key = `${a.ok === false ? 'fail' : 'ok'}:${a.domain}:${family}`
      const prev = others.get(key)
      if (!prev) {
        others.set(key, a)
      } else if (prev.toolName === 'vela_run' && a.toolName !== 'vela_run') {
        others.set(key, a)
      } else if (a.toolName === 'vela_run' && prev.toolName !== 'vela_run') {
        // keep dedicated tool
      } else {
        others.set(key, a)
      }
    }
  }

  const out = []
  for (const [, group] of listBuckets) {
    const domain = group[0].domain
    const payloads = group.map((g) => g.payload).filter(Boolean)
    const merged = payloads.length ? mergeListPayloads(domain, payloads) : { items: [], total: 0 }
    const last = group[group.length - 1]
    const preservedAction = ['scopes_list', 'passages_list', 'search'].includes(last.action)
      ? last.action
      : 'list'
    const summary = merged.items.length
      ? `共 ${merged.total != null ? merged.total : merged.items.length} 条`
      : last.summary
    out.push({
      ...last,
      action: preservedAction,
      toolName: last.toolName,
      title: titleFor(domain, preservedAction === 'scopes_list' ? 'list' : preservedAction),
      summary,
      path: DOMAIN_ROUTES[domain].list,
      pageLabel: DOMAIN_ROUTES[domain].label,
      payload: merged,
      items: merged.items,
      total: merged.total,
      hasItems: merged.items.length > 0,
      pageSize: PAGE_SIZE,
    })
  }
  for (const a of others.values()) {
    out.push({
      ...a,
      items: a.payload?.items || null,
      total: a.payload?.total,
      pageSize: PAGE_SIZE,
    })
  }
  return out
}

export function pickNavigateAction(actions) {
  if (!actions?.length) return null
  // Prefer concrete writes / entity results over list/selection cards
  for (let i = actions.length - 1; i >= 0; i -= 1) {
    const a = actions[i]
    if (a.ok === false) continue
    if (a.awaitingSelection || a.type === 'choice_select') continue
    if (a.type === 'data_list' && a.domain === 'memory') continue
    return a
  }
  return null
}

/** Build the user chat line after picking a row from a choice_select card. */
export function buildSelectionUserMessage(card, item) {
  if (!card || !item) return ''
  const domain = card.domain
  if (domain === 'agents' || domain === 'memory') {
    const name = item.name || item.username || item.display_name || ''
    const id = item.agent_id || item[DOMAIN_ROUTES[domain]?.idKey] || ''
    if (!id && !name) return ''
    const label = name ? `「${name}」` : ''
    return `我选择智能体${label}${id ? `（agent_id=${id}）` : ''}，请继续执行刚才的操作。`
  }
  const idKey = DOMAIN_ROUTES[domain]?.idKey
  const id = idKey ? item[idKey] : ''
  const name = item.name || item.display_name || rowPrimaryLabel(item)
  return `我选择「${name}」${id ? `（${idKey}=${id}）` : ''}，请继续执行刚才的操作。`
}

export function storyHasVisibleSteps(story) {
  if (!story?.phases?.length) return false
  return story.phases.some((p) => (p.steps && p.steps.length) || (p.status && p.status !== 'skipped'))
}

/** Column defs for list cards by domain */
export function listColumnsForDomain(domain, action = '', items = []) {
  if (domain === 'agents') {
    return [
      { key: 'name', title: '名称' },
      { key: 'agent_type', title: '类型' },
      { key: 'description', title: '描述' },
      { key: 'status', title: '状态' },
    ]
  }
  if (domain === 'memory') {
    const sample = Array.isArray(items) && items[0] ? items[0] : null
    const isScope = action === 'scopes_list' || !!(sample && sample.mapping_id) || !!(sample && sample.agent_id && !sample.passage_id && sample.content == null && sample.text == null)
    if (isScope) {
      return [
        { key: 'agent_id', title: '智能体 ID' },
        { key: 'username', title: '用户' },
        { key: 'user_id', title: '用户 ID' },
        { key: 'mapping_id', title: '映射' },
      ]
    }
    return [
      { key: 'content', title: '内容' },
      { key: 'tags', title: '标签' },
      { key: 'created_at', title: '时间' },
      { key: 'passage_id', title: 'ID' },
    ]
  }
  if (domain === 'tools') {
    return [
      { key: 'name', title: '名称' },
      { key: 'tool_type', title: '类型' },
      { key: 'display_name', title: '显示名' },
      { key: 'status', title: '状态' },
    ]
  }
  if (domain === 'approvals') {
    return [
      { key: 'tool_name', title: '工具' },
      { key: 'category', title: '类别' },
      { key: 'status', title: '状态' },
      { key: 'session_id', title: '会话' },
    ]
  }
  return [
    { key: 'name', title: '名称' },
    { key: 'display_name', title: '显示名' },
    { key: 'status', title: '状态' },
    { key: 'description', title: '描述' },
  ]
}

export function rowPrimaryLabel(item) {
  return item?.name || item?.display_name || item?.tool_name || item?.title
    || (item?.content && String(item.content).slice(0, 40))
    || item?.username || item?.agent_id || '—'
}

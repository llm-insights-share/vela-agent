/**
 * Build / normalize execution_story for AgentChat.
 * Prefer backend structured story; fall back to synthesizing from thinking steps / turns / audit trail.
 */

const PHASE_META = [
  { id: 'understand', title: '理解任务', kinds: ['rewrite', 'intent', 'skill'] },
  { id: 'gather', title: '收集信息', kinds: ['memory', 'knowledge'] },
  { id: 'act', title: '执行操作', kinds: ['phase', 'thought', 'tool', 'code_exec', 'action', 'info', 'dispatch'] },
  { id: 'verify', title: '核对结果', kinds: ['check', 'hitl'] },
  { id: 'deliver', title: '生成答复', kinds: [] },
]

const COORD_PHASE_TITLES = {
  understand: '调度与理解',
  act: '角色执行',
  verify: '核对与审批',
  deliver: '汇总交付',
}

function emptyPhases(titles = null) {
  return PHASE_META.map((p) => ({
    id: p.id,
    title: (titles && titles[p.id]) || p.title,
    status: 'pending',
    summary: '',
    steps: [],
  }))
}

function mapLegacyTypeToKind(step) {
  if (step.type === 'rewrite') return 'intent'
  if (step.type === 'code_exec') return 'code'
  if (step.type === 'phase' || step.type === 'action' || step.type === 'info') return 'thought'
  return step.type || 'thought'
}

function phaseForLegacyStep(step) {
  const kind = mapLegacyTypeToKind(step)
  if (kind === 'intent' || kind === 'skill' || step.type === 'rewrite') return 'understand'
  if (kind === 'memory' || kind === 'knowledge') return 'gather'
  if (kind === 'check' || kind === 'hitl' || /质检|校验|审批/.test(step.text || '')) return 'verify'
  if (step.type === 'error') return 'act'
  return 'act'
}

function visibleStory(phases, { status = 'done', metrics = null, summary = '' } = {}) {
  const visible = phases.filter((p) => p.steps.length)
  const autoSummary = summary || visible.map((p) => p.summary || p.title).slice(0, 4).join(' → ')
  return {
    version: 1,
    status,
    summary: autoSummary,
    phases: visible,
    metrics: metrics || {},
  }
}

export function synthesizeStoryFromSteps(steps, { status = 'done', metrics = null, summary = '' } = {}) {
  if (!steps?.length) return null
  const phases = emptyPhases()
  const byId = Object.fromEntries(phases.map((p) => [p.id, p]))

  for (const step of steps) {
    const phaseId = phaseForLegacyStep(step)
    const phase = byId[phaseId]
    const kind = mapLegacyTypeToKind(step)
    phase.steps.push({
      id: `legacy_${phase.steps.length}_${phaseId}`,
      kind,
      title: step.toolName
        ? `调用 ${step.toolName}`
        : (step.text || '').slice(0, 80) || '步骤',
      detail: step.text || '',
      tool_name: step.toolName || null,
      status: step.type === 'error' ? 'fail' : 'ok',
      evidence: step.searchCard
        ? { type: 'search', preview: step.text }
        : null,
    })
    phase.status = step.type === 'error' ? 'error' : 'done'
    if (!phase.summary) phase.summary = phase.steps[phase.steps.length - 1].title
  }

  if (status === 'done' && byId.deliver.steps.length === 0 && steps.length) {
    byId.deliver.steps.push({
      id: 'legacy_deliver',
      kind: 'thought',
      title: '已生成正式答复',
      detail: '',
      status: 'ok',
    })
    byId.deliver.status = 'done'
    byId.deliver.summary = '已生成正式答复'
  }

  return visibleStory(phases, { status, metrics, summary })
}

export function synthesizeStoryFromTurns(turns, { status = 'done', metrics = null, summary = '' } = {}) {
  if (!turns?.length) return null
  const phases = emptyPhases()
  const byId = Object.fromEntries(phases.map((p) => [p.id, p]))
  const act = byId.act
  act.status = status === 'running' ? 'active' : 'done'

  for (const turn of turns) {
    const seq = turn.seq || 0
    const toolCalls = turn.response?.tool_calls || []
    const toolResults = turn.tool_results || []
    const headline = turn.thinking
      ? String(turn.thinking).slice(0, 80)
      : (turn.response?.content || '').slice(0, 80) || `第 ${seq || '?'} 轮`
    act.steps.push({
      id: `turn_${turn.turn_id || seq}`,
      kind: toolCalls.length || toolResults.length ? 'tool' : 'thought',
      title: headline || `第 ${seq} 轮`,
      detail: [
        turn.thinking ? `思考: ${String(turn.thinking)}` : '',
        toolCalls.length ? `工具调用: ${toolCalls.map((t) => t.name).join(', ')}` : '',
        turn.response?.raw_error ? `错误: ${turn.response.raw_error}` : '',
        !toolCalls.length && turn.response?.content ? String(turn.response.content) : '',
      ].filter(Boolean).join('\n\n'),
      tool_name: toolCalls[0]?.name || null,
      status: turn.response?.raw_error ? 'fail' : 'ok',
      duration_ms: turn.duration_ms,
    })
    for (const tr of toolResults) {
      act.steps.push({
        id: `turn_${turn.turn_id || seq}_tool_${tr.name}`,
        kind: tr.code_exec ? 'code' : 'tool',
        title: tr.ok === false ? `${tr.name} 失败` : `调用 ${tr.name}`,
        detail: tr.content_preview || tr.content || '',
        tool_name: tr.name,
        status: tr.ok === false ? 'fail' : 'ok',
      })
    }
  }
  if (!act.summary) act.summary = `${turns.length} 轮推理`

  if (status === 'done') {
    byId.deliver.steps.push({
      id: 'turns_deliver',
      kind: 'thought',
      title: '已生成正式答复',
      status: 'ok',
    })
    byId.deliver.status = 'done'
    byId.deliver.summary = '已生成正式答复'
  }

  const m = { ...(metrics || {}) }
  m.iterations = m.iterations || turns.length
  return visibleStory(phases, { status, metrics: m, summary })
}

export function synthesizeCoordinatorStory(auditTrail, thinkingLog, {
  status = 'done',
  metrics = null,
  summary = '',
  userMessage = '',
} = {}) {
  const trail = auditTrail || []
  const logLines = Array.isArray(thinkingLog)
    ? thinkingLog
    : String(thinkingLog || '').split('\n').map((l) => l.trim()).filter(Boolean)

  if (!trail.length && !logLines.some((l) => l.includes('[Coordinator]'))) {
    return null
  }

  const phases = emptyPhases(COORD_PHASE_TITLES)
  const byId = Object.fromEntries(phases.map((p) => [p.id, p]))

  const intentText = userMessage
    || (logLines.find((l) => l.includes('开始处理用户任务:')) || '').split(':').slice(1).join(':').trim()
  byId.understand.steps.push({
    id: 'coord_intent',
    kind: 'intent',
    title: '多 Agent 协作任务',
    detail: intentText || '已启动协调',
    status: 'ok',
  })
  byId.understand.status = 'done'
  byId.understand.summary = intentText ? intentText.slice(0, 80) : '已启动协调'

  if (trail.length) {
    byId.act.status = status === 'running' ? 'active' : 'done'
    trail.forEach((entry, i) => {
      const role = entry.role_name || entry.receiver_name || entry.receiver || '子 Agent'
      const roleLabel = (typeof role === 'string' && role.length > 36 && role.includes('-'))
        ? `${role.slice(0, 8)}…`
        : String(role)
      const rnd = entry.round
      const ok = entry.success !== false
      byId.act.steps.push({
        id: `coord_${i}`,
        kind: 'dispatch',
        title: rnd ? `第 ${rnd} 轮 · ${roleLabel}` : roleLabel,
        detail: [
          entry.task ? `任务: ${entry.task}` : '',
          entry.duration_ms != null ? `耗时 ${entry.duration_ms}ms` : '',
          entry.tokens ? `Token ${entry.tokens}` : '',
          entry.result_preview || entry.error || '',
        ].filter(Boolean).join('\n'),
        tool_name: roleLabel,
        role_name: roleLabel,
        round: rnd,
        status: ok ? 'ok' : 'fail',
        duration_ms: entry.duration_ms,
      })
    })
    byId.act.summary = `已调度 ${trail.length} 次子 Agent 调用`
  } else {
    logLines.filter((l) => l.startsWith('[Coordinator]')).forEach((line, i) => {
      byId.act.steps.push({
        id: `coord_log_${i}`,
        kind: 'thought',
        title: line.slice(0, 80),
        detail: line,
        status: 'ok',
      })
    })
    if (byId.act.steps.length) {
      byId.act.status = 'done'
      byId.act.summary = '协调过程'
    }
  }

  const hitl = status === 'hitl_wait' || logLines.some((l) => /HITL|交付前|等待人工审批/.test(l))
  if (hitl) {
    byId.verify.steps.push({
      id: 'coord_hitl',
      kind: 'hitl',
      title: '交付物等待审批',
      detail: '多 Agent 汇总结果待人工确认后交付',
      tool_name: '__delivery__',
      status: 'pending',
    })
    byId.verify.status = 'hitl'
    byId.verify.summary = '待交付审批'
  } else if (status === 'done' || byId.act.steps.length) {
    byId.deliver.steps.push({
      id: 'coord_deliver',
      kind: 'thought',
      title: '已汇总多 Agent 结果',
      status: 'ok',
    })
    byId.deliver.status = 'done'
    byId.deliver.summary = '已汇总交付'
  }

  const m = { ...(metrics || {}) }
  if (trail.length) {
    m.tool_calls = m.tool_calls || trail.length
    m.elapsed_ms = m.elapsed_ms || trail.reduce((s, e) => s + (e.duration_ms || 0), 0)
  }
  const finalStatus = hitl ? 'hitl_wait' : status
  const finalSummary = summary
    || (hitl ? '已完成协作 · 待交付审批' : undefined)
  return visibleStory(phases, { status: finalStatus, metrics: m, summary: finalSummary })
}

export function mergeWorkflowTraceIntoStory(story, trace) {
  if (!trace?.length) return story
  const base = story
    ? {
        version: story.version || 1,
        status: story.status || 'done',
        summary: story.summary || '',
        phases: (story.phases || []).map((p) => ({
          ...p,
          steps: [...(p.steps || [])],
        })),
        metrics: { ...(story.metrics || {}) },
      }
    : visibleStory(emptyPhases(), { status: 'done' })

  let act = base.phases.find((p) => p.id === 'act')
  if (!act) {
    act = {
      id: 'act',
      title: '执行操作',
      status: 'done',
      summary: '',
      steps: [],
    }
    base.phases.push(act)
  }
  const existing = new Set(act.steps.map((s) => s.id))
  trace.forEach((step, i) => {
    const id = `wf_${step.node_id || i}`
    if (existing.has(id)) return
    const st = step.status
    const isHitl = st === 'hitl_wait'
    const phase = isHitl
      ? (base.phases.find((p) => p.id === 'verify') || act)
      : act
    if (isHitl && phase.id === 'verify') {
      phase.status = 'hitl'
    }
    phase.steps.push({
      id,
      kind: isHitl ? 'hitl' : 'tool',
      title: step.label || step.node_id || `节点 ${i + 1}`,
      detail: `${step.node_type || 'node'}${step.duration_ms ? ` · ${step.duration_ms}ms` : ''}`,
      tool_name: step.node_type || null,
      status: st === 'success' ? 'ok' : (isHitl ? 'pending' : 'fail'),
      duration_ms: step.duration_ms,
    })
  })
  if (!act.summary) act.summary = `工作流 ${trace.length} 步`
  if (!base.summary) {
    base.summary = `工作流执行轨迹 ${trace.length} 步`
  }
  return base
}

export function normalizeExecutionStory(raw) {
  if (!raw || typeof raw !== 'object') return null
  if (!Array.isArray(raw.phases)) return null
  return {
    version: raw.version || 1,
    status: raw.status || 'done',
    summary: raw.summary || '',
    phases: raw.phases,
    metrics: raw.metrics || {},
  }
}

/** Compact one-line process summary for collapsed headers / live bubble */
export function processSummaryLine({ story, turns, steps, runMetrics } = {}) {
  const parts = []
  if (story?.summary) parts.push(story.summary)
  const m = { ...(runMetrics || {}), ...(story?.metrics || {}) }
  const meta = []
  if (turns?.length) meta.push(`${turns.length} 轮`)
  else if (m.iterations) meta.push(`${m.iterations} 轮`)
  if (m.tool_calls || m.web_search_calls || m.tool_search_calls) {
    const tools = (m.tool_calls || 0) + (m.web_search_calls || 0) + (m.tool_search_calls || 0)
    if (tools) meta.push(`${tools} 次工具`)
  } else if (steps?.length) {
    const toolCount = steps.filter((s) => s.type === 'tool' || s.type === 'code_exec').length
    if (toolCount) meta.push(`${toolCount} 次工具`)
  }
  if (m.elapsed_ms) meta.push(`${Math.round(m.elapsed_ms / 1000)}s`)
  if (m.forced_synthesis) meta.push('强制合成')
  if (meta.length) parts.push(meta.join(' · '))
  return parts.filter(Boolean).join(' · ') || ''
}

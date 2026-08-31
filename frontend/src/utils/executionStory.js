/**
 * Build / normalize execution_story for AgentChat.
 * Prefer backend structured story; fall back to synthesizing from thinking steps.
 */

const PHASE_META = [
  { id: 'understand', title: '理解任务', kinds: ['rewrite', 'intent', 'skill'] },
  { id: 'gather', title: '收集信息', kinds: ['memory', 'knowledge'] },
  { id: 'act', title: '执行操作', kinds: ['phase', 'thought', 'tool', 'code_exec', 'action', 'info'] },
  { id: 'verify', title: '核对结果', kinds: ['check', 'hitl'] },
  { id: 'deliver', title: '生成答复', kinds: [] },
]

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

export function synthesizeStoryFromSteps(steps, { status = 'done', metrics = null, summary = '' } = {}) {
  if (!steps?.length) return null
  const phases = PHASE_META.map((p) => ({
    id: p.id,
    title: p.title,
    status: 'pending',
    summary: '',
    steps: [],
  }))
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

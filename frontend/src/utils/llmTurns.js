/**
 * Normalize / synthesize LLM turn cards for AgentChat process panel.
 */

export function normalizeLlmTurns(raw) {
  if (!Array.isArray(raw) || !raw.length) return null
  return raw.map((t, i) => ({
    turn_id: t.turn_id || t.call_id || `turn_${i}`,
    seq: t.seq ?? i + 1,
    source: t.source || 'react',
    model_name: t.model_name || '',
    duration_ms: t.duration_ms || 0,
    created_at: t.created_at,
    input: t.input || { messages: [], summary: '', has_system: false, tools_count: 0 },
    thinking: t.thinking || null,
    response: t.response || { content: null, tool_calls: null, raw_error: null },
    tool_results: (t.tool_results || []).map((r) => ({
      ...r,
      code_exec: r.code_exec || null,
      tool_search: r.tool_search || null,
    })),
  }))
}

export function isCodeToolName(name) {
  return name === 'execute_code' || name === 'install_packages'
}

/** Attach structured code executions to turn tool_results (fallback for legacy messages). */
export function enrichTurnsWithCodeExecutions(turns, codeExecutions) {
  if (!Array.isArray(turns) || !turns.length) return turns
  const pool = Array.isArray(codeExecutions) ? [...codeExecutions] : []
  return turns.map((turn) => {
    const toolResults = (turn.tool_results || []).map((r) => {
      if (r.code_exec || !isCodeToolName(r.name) || !pool.length) return r
      return { ...r, code_exec: pool.shift() }
    })
    return { ...turn, tool_results: toolResults }
  })
}

/** Build rough turns from llm_calls records (session-level history fallback). */
export function turnsFromLlmCalls(llmCalls) {
  if (!Array.isArray(llmCalls) || !llmCalls.length) return null
  const sorted = [...llmCalls].sort((a, b) => (a.seq || 0) - (b.seq || 0))
  let prevCount = 0
  const turns = sorted.map((rec, i) => {
    const messages = rec.input?.messages || []
    const delta = prevCount > 0
      ? messages.slice(prevCount)
      : messages.filter((m) => m.role !== 'system').slice(-2)
    prevCount = messages.length
    const previews = delta.map((m) => ({
      role: m.role,
      content: typeof m.content === 'string' ? m.content.slice(0, 800) : '',
      tool_call_id: m.tool_call_id,
      tool_calls: (m.tool_calls || []).map((tc) => ({
        id: tc.id,
        name: tc.function?.name || tc.name,
        arguments: String(tc.function?.arguments || '').slice(0, 600),
      })),
    }))
    const out = rec.output || {}
    const toolCalls = (out.tool_calls || []).map((tc) => ({
      id: tc.id,
      name: tc.function?.name || tc.name,
      arguments: String(tc.function?.arguments || '').slice(0, 600),
    }))
    return {
      turn_id: rec.call_id || `call_${i}`,
      seq: rec.seq ?? i + 1,
      source: rec.source || 'react',
      model_name: rec.model_name || '',
      duration_ms: rec.duration_ms || 0,
      created_at: rec.created_at,
      input: {
        messages: previews,
        has_system: messages.some((m) => m.role === 'system'),
        tools_count: rec.input?.tools?.length || 0,
        summary: previews.map((p) => p.role).join(', ') || '模型输入',
      },
      thinking: out.reasoning_content || null,
      response: {
        content: out.content ?? null,
        tool_calls: toolCalls.length ? toolCalls : null,
        raw_error: out.raw_error || null,
      },
      tool_results: [],
    }
  })
  return turns
}

/** Very rough fallback from legacy thinking steps. */
export function turnsFromThinkingSteps(steps) {
  if (!Array.isArray(steps) || !steps.length) return null
  const turns = []
  let current = null
  const push = () => { if (current) turns.push(current) }

  for (const step of steps) {
    if (step.type === 'phase' || step.type === 'thought' || step.type === 'action') {
      if (current && (current.response.content || current.response.tool_calls?.length)) {
        push()
        current = null
      }
      if (!current) {
        current = {
          turn_id: `legacy_${turns.length}`,
          seq: turns.length + 1,
          source: 'react',
          input: { messages: [], summary: step.text?.slice(0, 80) || '推理', has_system: false, tools_count: 0 },
          thinking: null,
          response: { content: null, tool_calls: null },
          tool_results: [],
        }
      }
      if (step.type === 'thought') {
        current.thinking = (current.thinking ? `${current.thinking}\n` : '') + (step.text || '')
      } else {
        current.response.content = (current.response.content ? `${current.response.content}\n` : '') + (step.text || '')
      }
    } else if (step.type === 'tool' || step.type === 'code_exec') {
      if (!current) {
        current = {
          turn_id: `legacy_${turns.length}`,
          seq: turns.length + 1,
          source: 'react',
          input: { messages: [], summary: '工具调用', has_system: false, tools_count: 0 },
          thinking: null,
          response: { content: null, tool_calls: [] },
          tool_results: [],
        }
      }
      if (!current.response.tool_calls) current.response.tool_calls = []
      current.response.tool_calls.push({
        id: `legacy_tc_${current.response.tool_calls.length}`,
        name: step.toolName || 'tool',
        arguments: '',
      })
      current.tool_results.push({
        tool_call_id: null,
        name: step.toolName || 'tool',
        content_preview: (step.text || '').slice(0, 800),
        ok: true,
      })
    }
  }
  push()
  return turns.length ? turns : null
}

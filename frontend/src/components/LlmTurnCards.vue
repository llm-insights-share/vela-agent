<template>
  <div v-if="displayTurns && displayTurns.length" class="llm-turns">
    <div class="llm-turns-header" @click="expanded = !expanded">
      <CaretRightOutlined v-if="!expanded" style="font-size: 10px;" />
      <CaretDownOutlined v-else style="font-size: 10px;" />
      <span class="llm-turns-title">思考与执行过程</span>
      <span class="llm-turns-summary">{{ headerSummary }}</span>
    </div>

    <div v-if="expanded" class="llm-turns-body">
      <div
        v-for="(turn, idx) in displayTurns"
        :key="turn.turn_id || turn.seq || idx"
        class="llm-turn-card"
      >
        <div class="llm-turn-card-head" @click="toggleTurn(idx)">
          <span class="llm-turn-seq">第 {{ turn.seq || idx + 1 }} 轮</span>
          <a-tag size="small" color="blue">{{ sourceLabel(turn.source) }}</a-tag>
          <span class="llm-turn-head-summary">{{ turnHeadline(turn) }}</span>
          <span v-if="turn.duration_ms" class="llm-turn-meta">{{ turn.duration_ms }}ms</span>
          <CaretDownOutlined v-if="isTurnOpen(idx)" style="font-size: 10px; margin-left: auto;" />
          <CaretRightOutlined v-else style="font-size: 10px; margin-left: auto;" />
        </div>

        <div v-if="isTurnOpen(idx)" class="llm-turn-card-body">
          <!-- 输入 -->
          <div class="llm-section">
            <div class="llm-section-head" @click.stop="toggleSection(idx, 'input')">
              <span class="llm-section-label">输入</span>
              <span class="llm-section-preview">{{ turn.input?.summary || '—' }}</span>
            </div>
            <div v-if="isSectionOpen(idx, 'input')" class="llm-section-body">
              <div v-if="turn.input?.has_system" class="llm-msg-row muted">系统提示已注入</div>
              <div
                v-for="(m, mi) in (turn.input?.messages || [])"
                :key="mi"
                class="llm-msg-row"
              >
                <a-tag size="small">{{ m.role }}</a-tag>
                <pre class="llm-pre">{{ messagePreview(m) }}</pre>
              </div>
              <div v-if="turn.input?.tools_count" class="llm-msg-row muted">
                可用工具 {{ turn.input.tools_count }} 个
                <template v-if="turn.input?.loaded_tool_names?.length">
                  · 已激活 {{ turn.input.loaded_tool_names.join(', ') }}
                </template>
              </div>
            </div>
          </div>

          <!-- 思考 -->
          <div v-if="turn.thinking" class="llm-section">
            <div class="llm-section-head" @click.stop="toggleSection(idx, 'thinking')">
              <span class="llm-section-label">思考过程</span>
              <span class="llm-section-preview">{{ shortPreview(turn.thinking) }}</span>
            </div>
            <div v-if="isSectionOpen(idx, 'thinking')" class="llm-section-body">
              <pre class="llm-pre">{{ turn.thinking }}</pre>
            </div>
          </div>

          <!-- 响应 -->
          <div class="llm-section">
            <div class="llm-section-head" @click.stop="toggleSection(idx, 'response')">
              <span class="llm-section-label">响应结果</span>
              <span class="llm-section-preview">{{ responsePreview(turn) }}</span>
            </div>
            <div v-if="isSectionOpen(idx, 'response')" class="llm-section-body">
              <a-alert
                v-if="turn.response?.raw_error"
                type="error"
                show-icon
                :message="turn.response.raw_error"
                style="margin-bottom: 8px;"
              />
              <pre v-if="turn.response?.content" class="llm-pre">{{ turn.response.content }}</pre>
              <div v-if="turn.response?.tool_calls?.length" class="llm-tool-calls">
                <div
                  v-for="(tc, ti) in turn.response.tool_calls"
                  :key="tc.id || ti"
                  class="llm-tool-call"
                >
                  <a-tag color="geekblue" size="small">{{ tc.name }}</a-tag>
                  <pre class="llm-pre compact">{{ tc.arguments }}</pre>
                </div>
              </div>
              <div v-if="!turn.response?.content && !turn.response?.tool_calls?.length && !turn.response?.raw_error" class="muted">
                （无文本响应）
              </div>
            </div>
          </div>

          <!-- 工具执行结果 -->
          <div v-if="turn.tool_results?.length" class="llm-section">
            <div class="llm-section-head" @click.stop="toggleSection(idx, 'tools')">
              <span class="llm-section-label">工具执行</span>
              <span class="llm-section-preview">
                {{ turn.tool_results.map(r => r.name).join(', ') }}
              </span>
            </div>
            <div v-if="isSectionOpen(idx, 'tools')" class="llm-section-body">
              <div
                v-for="(r, ri) in turn.tool_results"
                :key="r.tool_call_id || ri"
                class="llm-tool-result"
              >
                <CodeExecutionCard
                  v-if="r.code_exec"
                  :exec="r.code_exec"
                  :default-expanded="ri === turn.tool_results.length - 1"
                />
                <div v-else-if="r.tool_search" class="llm-tool-search-card">
                  <a-tag color="purple" size="small">tool_search</a-tag>
                  <div v-if="r.tool_search.matches?.length" class="llm-tool-search-row">
                    <span class="muted">命中：</span>
                    <a-tag v-for="n in r.tool_search.matches" :key="n" size="small">{{ n }}</a-tag>
                  </div>
                  <div v-if="r.tool_search.activated?.length" class="llm-tool-search-row">
                    <span class="muted">已激活：</span>
                    <a-tag v-for="n in r.tool_search.activated" :key="`a-${n}`" color="green" size="small">{{ n }}</a-tag>
                  </div>
                  <pre v-if="r.content_preview" class="llm-pre compact">{{ r.content_preview }}</pre>
                </div>
                <template v-else>
                  <a-tag :color="r.ok ? 'green' : 'red'" size="small">{{ r.name }}</a-tag>
                  <pre class="llm-pre compact">{{ r.content_preview }}</pre>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { CaretDownOutlined, CaretRightOutlined } from '@ant-design/icons-vue'
import CodeExecutionCard from './CodeExecutionCard.vue'
import { enrichTurnsWithCodeExecutions } from '../utils/llmTurns'

const props = defineProps({
  turns: { type: Array, default: () => [] },
  codeExecutions: { type: Array, default: () => [] },
  defaultExpanded: { type: Boolean, default: false },
})

const expanded = ref(!!props.defaultExpanded)
const openTurns = reactive({})
const openSections = reactive({})

const displayTurns = computed(() => (
  enrichTurnsWithCodeExecutions(props.turns || [], props.codeExecutions || [])
))

watch(
  () => props.defaultExpanded,
  (v) => { if (v) expanded.value = true },
)

watch(
  () => (displayTurns.value || []).length,
  (n, prev) => {
    if (n > (prev || 0) && props.defaultExpanded) {
      expanded.value = true
      openTurns[n - 1] = true
      openSections[`${n - 1}:response`] = true
      if (displayTurns.value[n - 1]?.thinking) openSections[`${n - 1}:thinking`] = true
    }
  },
)

const headerSummary = computed(() => {
  const turns = displayTurns.value || []
  if (!turns.length) return ''
  let toolCount = 0
  for (const t of turns) {
    toolCount += (t.tool_results || []).length || (t.response?.tool_calls || []).length
  }
  const parts = [`${turns.length} 轮交互`]
  if (toolCount) parts.push(`${toolCount} 次工具`)
  return parts.join(' · ')
})

function sourceLabel(source) {
  return ({
    react: 'ReAct',
    plan: 'Plan',
    direct: 'Direct',
    tool_assess: '质检',
    query_rewrite: '改写',
    coordinator: '协调',
    workflow: '工作流',
  })[source] || source || 'LLM'
}

function isTurnOpen(idx) {
  return openTurns[idx] !== false
}

function toggleTurn(idx) {
  openTurns[idx] = !isTurnOpen(idx)
}

function isSectionOpen(turnIdx, section) {
  const key = `${turnIdx}:${section}`
  return openSections[key] === true
}

function toggleSection(turnIdx, section) {
  const key = `${turnIdx}:${section}`
  openSections[key] = !isSectionOpen(turnIdx, section)
}

function shortPreview(text, max = 80) {
  if (!text) return '—'
  const s = String(text).trim()
  return s.length <= max ? s : `${s.slice(0, max)}…`
}

function messagePreview(m) {
  if (m.content) return m.content
  if (m.tool_calls?.length) {
    return m.tool_calls.map((tc) => `${tc.name}(${tc.arguments || ''})`).join('\n')
  }
  return '—'
}

function responsePreview(turn) {
  if (turn.response?.raw_error) return turn.response.raw_error.slice(0, 80)
  if (turn.response?.tool_calls?.length) {
    return turn.response.tool_calls.map((tc) => tc.name).join(', ')
  }
  return shortPreview(turn.response?.content || '')
}

function turnHeadline(turn) {
  if (turn.response?.tool_calls?.length) {
    return `调用 ${turn.response.tool_calls.map((tc) => tc.name).join(', ')}`
  }
  if (turn.response?.content) return shortPreview(turn.response.content, 60)
  if (turn.thinking) return shortPreview(turn.thinking, 60)
  return turn.input?.summary || 'LLM 交互'
}
</script>

<style scoped>
.llm-turns {
  margin: 8px 0 12px;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fafafa;
  overflow: hidden;
}
.llm-turns-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
}
.llm-turns-header:hover { background: #f0f0f0; }
.llm-turns-title { font-weight: 500; }
.llm-turns-summary { margin-left: 8px; color: #999; font-size: 12px; }
.llm-turns-body { padding: 0 12px 12px; }
.llm-turn-card {
  border: 1px solid #eee;
  border-radius: 8px;
  background: #fff;
  margin-top: 8px;
  overflow: hidden;
}
.llm-turn-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  background: #fcfcfc;
}
.llm-turn-card-head:hover { background: #f5f5f5; }
.llm-turn-seq { font-weight: 600; color: #333; }
.llm-turn-head-summary { color: #666; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.llm-turn-meta { color: #999; font-size: 11px; }
.llm-turn-card-body { padding: 8px 10px 10px; }
.llm-section { margin-top: 8px; border-top: 1px dashed #f0f0f0; padding-top: 8px; }
.llm-section:first-child { border-top: none; padding-top: 0; margin-top: 0; }
.llm-section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  cursor: pointer;
  font-size: 12px;
}
.llm-section-label { font-weight: 600; color: #555; min-width: 64px; }
.llm-section-preview { color: #999; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.llm-section-body { margin-top: 6px; }
.llm-msg-row { margin-bottom: 6px; }
.llm-pre {
  margin: 4px 0 0;
  padding: 8px 10px;
  background: #f7f7f7;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}
.llm-pre.compact { max-height: 160px; }
.llm-tool-calls, .llm-tool-result { margin-top: 6px; }
.llm-tool-call { margin-bottom: 8px; }
.llm-tool-search-card { margin-top: 4px; }
.llm-tool-search-row { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.muted { color: #999; font-size: 12px; }
</style>

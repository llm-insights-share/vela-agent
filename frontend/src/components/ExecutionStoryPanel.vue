<template>
  <div v-if="visible" class="exec-story">
    <div class="exec-story-header" @click="expanded = !expanded">
      <CaretRightOutlined v-if="!expanded" style="font-size: 10px;" />
      <CaretDownOutlined v-else style="font-size: 10px;" />
      <span class="exec-story-title">思考与执行过程</span>
      <a-tag v-if="statusTag" :color="statusTag.color" size="small">{{ statusTag.label }}</a-tag>
      <span class="exec-story-summary">{{ headerSummary }}</span>
    </div>

    <div v-if="expanded" class="exec-story-body">
      <div v-if="liveThinking" class="exec-live-thinking">
        <div class="exec-live-thinking-label">实时思考</div>
        <pre class="exec-live-thinking-text">{{ liveThinking }}</pre>
      </div>

      <div
        v-for="phase in visiblePhases"
        :key="phase.id"
        :class="['exec-phase', `exec-phase-${phase.status}`]"
      >
        <div class="exec-phase-head" @click="togglePhase(phase.id)">
          <span class="exec-phase-marker">{{ phaseMarker(phase) }}</span>
          <span class="exec-phase-title">{{ phase.title }}</span>
          <span v-if="phase.summary" class="exec-phase-summary">{{ phase.summary }}</span>
          <a-tag :color="phaseStatusColor(phase.status)" size="small">{{ phaseStatusLabel(phase.status) }}</a-tag>
        </div>
        <div v-if="isPhaseOpen(phase)" class="exec-phase-steps">
          <div
            v-for="step in phase.steps || []"
            :key="step.id"
            :class="['exec-step', `exec-step-${step.kind}`]"
          >
            <div class="exec-step-head">
              <a-tag :color="stepKindColor(step.kind)" size="small">{{ stepKindLabel(step) }}</a-tag>
              <a-tag v-if="step.role_name" color="purple" size="small">{{ step.role_name }}</a-tag>
              <a-tag v-if="step.round" color="default" size="small">第 {{ step.round }} 轮</a-tag>
              <span class="exec-step-title">{{ step.title }}</span>
              <span v-if="step.duration_ms" class="exec-step-duration">{{ step.duration_ms }}ms</span>
              <a-button
                v-if="step.detail && step.detail.length > 80"
                type="link"
                size="small"
                class="exec-step-toggle"
                @click.stop="toggleStep(step.id)"
              >{{ openSteps.has(step.id) ? '收起' : '详情' }}</a-button>
            </div>
            <div
              v-if="step.detail && (openSteps.has(step.id) || step.detail.length <= 80)"
              class="exec-step-detail"
            >{{ step.detail }}</div>
            <div
              v-else-if="step.detail && !openSteps.has(step.id)"
              class="exec-step-detail muted"
            >{{ step.detail.slice(0, 80) }}…</div>
            <div v-if="step.evidence?.type === 'search' && step.evidence.preview" class="exec-step-evidence">
              <pre class="exec-step-detail">{{ step.evidence.preview.slice(0, 600) }}</pre>
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

const props = defineProps({
  story: { type: Object, default: null },
  /** When running/hitl, expand by default so user sees live progress */
  defaultExpanded: { type: Boolean, default: false },
  extraSummary: { type: String, default: '' },
  /** Streaming thinking text for the current LLM turn */
  liveThinking: { type: String, default: '' },
})

const emit = defineEmits(['expand-change'])

const expanded = ref(!!props.defaultExpanded)
const openPhases = reactive(new Set())
const openSteps = reactive(new Set())

watch(
  () => props.story?.status,
  (status) => {
    if (props.defaultExpanded && (status === 'running' || status === 'hitl_wait')) {
      expanded.value = true
    }
  },
)

watch(
  () => props.defaultExpanded,
  (v) => {
    expanded.value = !!v
  },
)

watch(
  () => props.liveThinking,
  (v) => {
    if (v) expanded.value = true
  },
)

watch(expanded, (v) => emit('expand-change', v))

const visible = computed(() => {
  if (props.liveThinking) return true
  return !!(props.story && visiblePhases.value.length)
})

const visiblePhases = computed(() => {
  const phases = props.story?.phases || []
  return phases.filter((p) => p.status !== 'skipped' || (p.steps && p.steps.length))
})

const statusTag = computed(() => {
  const s = props.story?.status
  if (s === 'running') return { label: '进行中', color: 'processing' }
  if (s === 'hitl_wait') return { label: '待审批', color: 'orange' }
  if (s === 'error') return { label: '异常', color: 'red' }
  if (s === 'aborted') return { label: '已中止', color: 'default' }
  if (s === 'done') return { label: '完成', color: 'green' }
  if (props.liveThinking) return { label: '进行中', color: 'processing' }
  return null
})

const headerSummary = computed(() => {
  const story = props.story
  if (!story) {
    if (props.liveThinking) return props.extraSummary || '模型思考中…'
    return props.extraSummary || ''
  }
  const parts = []
  if (story.summary) parts.push(story.summary)
  const m = story.metrics || {}
  const meta = []
  if (m.tool_calls) meta.push(`${m.tool_calls} 次工具`)
  if (m.elapsed_ms) meta.push(`${Math.round(m.elapsed_ms / 1000)}s`)
  if (meta.length) parts.push(meta.join(' · '))
  if (props.extraSummary) parts.push(props.extraSummary)
  if (props.liveThinking && !parts.length) parts.push('模型思考中…')
  return parts.join(' · ')
})

function phaseMarker(phase) {
  if (phase.status === 'done') return '✓'
  if (phase.status === 'active' || phase.status === 'hitl') return '●'
  if (phase.status === 'error') return '!'
  return '○'
}

function phaseStatusColor(status) {
  return ({
    done: 'green',
    active: 'blue',
    hitl: 'orange',
    error: 'red',
    pending: 'default',
    skipped: 'default',
  })[status] || 'default'
}

function phaseStatusLabel(status) {
  return ({
    done: '完成',
    active: '进行中',
    hitl: '等待',
    error: '失败',
    pending: '待开始',
    skipped: '跳过',
  })[status] || status
}

function stepKindColor(kind) {
  return ({
    intent: 'cyan',
    memory: 'purple',
    knowledge: 'purple',
    skill: 'orange',
    thought: 'default',
    tool: 'geekblue',
    code: 'purple',
    ui_skill: 'blue',
    hitl: 'orange',
    check: 'green',
    error: 'red',
    dispatch: 'purple',
  })[kind] || 'default'
}

function stepKindLabel(step) {
  if (step.kind === 'dispatch') return '调度'
  if (step.kind === 'tool' || step.kind === 'code' || step.kind === 'ui_skill') {
    return step.tool_name || step.kind
  }
  return ({
    intent: '理解',
    memory: '记忆',
    knowledge: '知识',
    skill: 'Skill',
    thought: '思考',
    hitl: '审批',
    check: '校验',
    error: '异常',
  })[step.kind] || '步骤'
}

function isPhaseOpen(phase) {
  if (openPhases.has(phase.id)) return true
  if (openPhases.has(`closed:${phase.id}`)) return false
  return phase.status === 'active' || phase.status === 'error' || phase.status === 'hitl'
}

function togglePhase(id) {
  if (openPhases.has(id)) {
    openPhases.delete(id)
    openPhases.add(`closed:${id}`)
  } else if (openPhases.has(`closed:${id}`)) {
    openPhases.delete(`closed:${id}`)
    openPhases.add(id)
  } else {
    openPhases.add(`closed:${id}`)
  }
}

function toggleStep(id) {
  if (openSteps.has(id)) openSteps.delete(id)
  else openSteps.add(id)
}
</script>

<style scoped>
.exec-story {
  margin-bottom: 10px;
  border: 1px solid #eef0f3;
  border-radius: 8px;
  background: #fafbfc;
  overflow: hidden;
}
.exec-story-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  color: #555;
  user-select: none;
}
.exec-story-header:hover {
  background: #f3f5f7;
}
.exec-story-title {
  font-weight: 500;
  color: #333;
}
.exec-story-summary {
  margin-left: 4px;
  color: #888;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.exec-story-body {
  padding: 4px 12px 12px;
  max-height: 420px;
  overflow-y: auto;
  border-top: 1px solid #eef0f3;
}
.exec-live-thinking {
  margin: 8px 0 12px;
  padding: 8px 10px;
  background: #fff;
  border: 1px dashed #e0dcd4;
  border-radius: 6px;
}
.exec-live-thinking-label {
  font-size: 11px;
  color: #9e9590;
  margin-bottom: 4px;
  font-weight: 500;
}
.exec-live-thinking-text {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #5c5650;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  max-height: 220px;
  overflow-y: auto;
}
.exec-phase {
  margin-top: 8px;
}
.exec-phase-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
}
.exec-phase-marker {
  width: 16px;
  text-align: center;
  color: #1677ff;
  font-weight: 600;
}
.exec-phase-error .exec-phase-marker { color: #cf1322; }
.exec-phase-done .exec-phase-marker { color: #389e0d; }
.exec-phase-hitl .exec-phase-marker { color: #d46b08; }
.exec-phase-title {
  font-weight: 500;
  color: #222;
}
.exec-phase-summary {
  flex: 1;
  color: #888;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.exec-phase-steps {
  margin: 6px 0 0 24px;
  padding-left: 10px;
  border-left: 2px solid #e6e8eb;
}
.exec-step {
  margin-bottom: 8px;
}
.exec-step-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.exec-step-title {
  color: #444;
}
.exec-step-duration {
  margin-left: auto;
  color: #999;
  font-size: 11px;
}
.exec-step-toggle {
  padding: 0;
  height: auto;
}
.exec-step-detail {
  margin: 4px 0 0;
  padding: 6px 8px;
  background: #fff;
  border-radius: 4px;
  font-size: 12px;
  color: #555;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.exec-step-detail.muted {
  color: #999;
}
</style>

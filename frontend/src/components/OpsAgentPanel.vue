<template>
  <div
    v-if="modelValue"
    class="ops-panel"
    role="dialog"
    aria-label="应用操作助手"
    :style="{ width: panelWidth + 'px' }"
  >
    <div
      class="ops-resize-handle"
      title="拖动调整宽度"
      @mousedown.prevent="onResizeStart"
    />

    <div class="ops-panel-header">
      <div class="ops-panel-title-wrap">
        <ThunderboltOutlined class="ops-panel-title-icon" />
        <div>
          <div class="ops-panel-title">应用操作助手</div>
          <div class="ops-panel-sub">{{ agent?.name || 'vela-ops-assistant' }}</div>
        </div>
      </div>
      <div class="ops-panel-actions">
        <a-tooltip title="新对话">
          <a-button
            type="text"
            size="small"
            :disabled="sending || isRunning"
            @click="onNewChat"
          >
            <PlusOutlined />
          </a-button>
        </a-tooltip>
        <a-tooltip title="会话历史">
          <a-button
            type="text"
            size="small"
            :class="{ 'ops-action-active': panelView === 'history' }"
            @click="toggleHistory"
          >
            <HistoryOutlined />
          </a-button>
        </a-tooltip>
        <a-button type="text" size="small" @click="close">
          <CloseOutlined />
        </a-button>
      </div>
    </div>

    <div v-if="loadError" class="ops-panel-error">
      {{ loadError }}
    </div>

    <div v-else-if="panelView === 'history'" class="ops-panel-body ops-history-body">
      <div class="ops-history-header">
        <span class="ops-history-title">会话历史</span>
        <a-button type="text" size="small" :loading="loadingSessions" @click="fetchSessions">
          <ReloadOutlined />
        </a-button>
      </div>
      <div v-if="loadingSessions && !sessions.length" class="ops-panel-empty">
        <a-spin size="small" />
      </div>
      <div v-else-if="!sessions.length" class="ops-panel-empty">暂无会话</div>
      <div v-else class="ops-session-list">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['ops-session-item', { active: s.session_id === sessionId }]"
          @click="openSession(s)"
        >
          <div class="ops-session-item-top">
            <span class="ops-session-item-title" :title="s.title || '新对话'">{{ s.title || '新对话' }}</span>
            <a-tag :color="sessionStatusColor(s.status)" size="small">
              <LoadingOutlined v-if="s.status === 'RUNNING'" style="margin-right: 2px;" />
              {{ sessionStatusLabel(s.status) }}
            </a-tag>
          </div>
          <div class="ops-session-item-meta">
            <span>{{ (s.messages || []).length }} 条消息</span>
            <span>{{ formatSessionTime(s.updated_at || s.created_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="ops-panel-body" ref="msgContainer">
      <div v-if="!messages.length && !sending" class="ops-panel-empty">
        可以问我：列出智能体、创建工具、查看待审批工单…
      </div>
      <div
        v-for="(msg, i) in messages"
        :key="msg.sourceIndex != null ? `src-${msg.sourceIndex}` : `i-${i}`"
        :class="['ops-msg', msg.role === 'user' ? 'ops-msg-user' : 'ops-msg-assistant']"
      >
        <div class="ops-msg-role">{{ msg.role === 'user' ? '你' : (agent?.name || '助手') }}</div>

        <ExecutionStoryPanel
          v-if="msg.role === 'assistant' && (msg._executionStory || (isLiveAssistant(msg, i) && liveThinkingText))"
          :story="msg._executionStory || livePlaceholderStory"
          :default-expanded="shouldExpandStory(msg, i)"
          :force-expanded="shouldForceExpandStory(msg, i)"
          :live-thinking="isLiveAssistant(msg, i) ? liveThinkingText : ''"
          @expand-change="(v) => onStoryExpandChange(msg, i, v)"
        />

        <OpsResultCard
          v-for="(card, ci) in (msg._opsCards || [])"
          :key="`card-${msg.sourceIndex || i}-${ci}`"
          :card="card"
          @open="openCardPage"
          @choice="(payload) => onCardChoice(payload)"
          @select="(payload) => onCardSelect(payload)"
        />

        <div
          v-if="msg.role === 'assistant' && msg.pendingApprovalId && !msg.approvalStatus"
          class="ops-hitl"
        >
          <div class="ops-hitl-title">待审批：{{ msg.pendingToolName || '工具调用' }}</div>
          <div v-if="msg.content" class="ops-msg-bubble ops-md" v-html="renderMarkdown(msg.content)"></div>
          <div class="ops-hitl-btns">
            <a-button type="primary" size="small" :loading="msg.approving" @click="approveHitl(msg)">批准</a-button>
            <a-button danger size="small" :loading="msg.rejecting" @click="rejectHitl(msg)">拒绝</a-button>
          </div>
        </div>

        <div
          v-else-if="msg.content && !shouldHideMarkdown(msg)"
          :class="['ops-msg-bubble', msg.role === 'assistant' ? 'ops-md' : '']"
          v-html="msg.role === 'assistant' ? renderMarkdown(msg.content) : escapeHtml(msg.content)"
        ></div>
        <div
          v-else-if="msg.role === 'assistant' && msg.content && shouldHideMarkdown(msg) && assistantFollowupNote(msg)"
          class="ops-msg-bubble ops-md ops-short-note"
        >{{ assistantFollowupNote(msg) }}</div>

        <div v-if="msg.approvalStatus === 'approved'" class="ops-hitl-result">已批准</div>
        <div v-if="msg.approvalStatus === 'rejected'" class="ops-hitl-result">已拒绝</div>
      </div>

      <div v-if="showTypingHint" class="ops-typing">
        <LoadingOutlined /> 思考中…
      </div>
    </div>

    <div v-if="panelView === 'chat' && !loadError" class="ops-panel-input">
      <a-textarea
        v-model:value="inputText"
        :auto-size="{ minRows: 2, maxRows: 5 }"
        placeholder="输入指令，例如：列出所有工具"
        :disabled="!agent || !!loadError"
        @pressEnter="onEnter"
      />
      <a-button
        type="primary"
        class="ops-send"
        :loading="sending"
        :disabled="!inputText.trim() || !agent || isRunning"
        @click="sendMessage"
      >
        发送
      </a-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { ThunderboltOutlined, CloseOutlined, LoadingOutlined, PlusOutlined, HistoryOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { marked } from 'marked'
import { agentApi, sessionApi, hitlApi } from '../api'
import { useAuthStore } from '../stores/auth'
import ExecutionStoryPanel from './ExecutionStoryPanel.vue'
import OpsResultCard from './OpsResultCard.vue'
import { normalizeExecutionStory } from '../utils/executionStory'
import { formatRelativeTime } from '../utils/datetime'
import {
  loadPanelWidth,
  savePanelWidth,
  clampPanelWidth,
  extractOpsActions,
  pickNavigateAction,
  resolveNavigatePath,
  storyHasVisibleSteps,
  buildSelectionUserMessage,
} from '../utils/opsNavigation'

marked.setOptions({ gfm: true, breaks: true })
import {
  watchBackgroundSession,
  setActiveViewing,
} from '../composables/useBackgroundSessions'

const OPS_AGENT_NAME = 'vela-ops-assistant'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

function close() {
  emit('update:modelValue', false)
}

const router = useRouter()
const auth = useAuthStore()
const agent = ref(null)
const loadError = ref('')
const sessionId = ref(null)
const messages = ref([])
const inputText = ref('')
const sending = ref(false)
const currentSessionStatus = ref('ACTIVE')
const liveThinkingText = ref('')
const liveThinkingTurn = ref(null)
const msgContainer = ref(null)
const panelWidth = ref(clampPanelWidth(loadPanelWidth(420)))
const lastNavigatedKey = ref('')
const storyExpandPrefs = ref({})
const storyKeepUntil = ref(0)
const storyKeepTick = ref(0)
const panelView = ref('chat')
const sessions = ref([])
const loadingSessions = ref(false)

const STORY_KEEP_MS = 8000

let sessionEventsController = null
let pollTimer = null
let storyKeepTimer = null
let resizing = false
let resizeStartX = 0
let resizeStartW = 0

const isRunning = computed(() => currentSessionStatus.value === 'RUNNING')

const livePlaceholderStory = computed(() => ({
  status: 'running',
  phases: [],
  summary: '执行中',
}))

const showTypingHint = computed(() => {
  void storyKeepTick.value
  if (!(sending.value || isRunning.value)) return false
  const last = messages.value[messages.value.length - 1]
  if (last?.role === 'assistant') {
    if (liveThinkingText.value) return false
    if (storyHasVisibleSteps(last._executionStory)) return false
  }
  return true
})

watch(
  () => props.modelValue,
  async (v) => {
    if (v) {
      await ensureAgent()
      if (sessionId.value) setActiveViewing(sessionId.value, agent.value?.agent_id)
    } else {
      setActiveViewing(null, null)
    }
  },
)

onUnmounted(() => {
  stopSessionEvents()
  stopPoll()
  clearStoryKeepTimer()
  stopResizeListeners()
  setActiveViewing(null, null)
})

function onResizeStart(e) {
  resizing = true
  resizeStartX = e.clientX
  resizeStartW = panelWidth.value
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
}

function onResizeMove(e) {
  if (!resizing) return
  // Handle is on the left edge; drag left → wider
  const delta = resizeStartX - e.clientX
  panelWidth.value = clampPanelWidth(resizeStartW + delta)
}

function onResizeEnd() {
  if (!resizing) return
  resizing = false
  document.body.style.userSelect = ''
  stopResizeListeners()
  savePanelWidth(panelWidth.value)
}

function stopResizeListeners() {
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br/>')
}

function renderMarkdown(text) {
  if (!text) return ''
  return marked.parse(text)
}

function isLiveAssistant(msg, i) {
  return msg.role === 'assistant' && i === messages.value.length - 1 && (sending.value || isRunning.value)
}

function storyKey(msg, i) {
  if (msg?.sourceIndex != null) return `src-${msg.sourceIndex}`
  if (i === messages.value.length - 1 && (sending.value || isRunning.value)) return 'pending'
  return `i-${i}`
}

function clearStoryKeepTimer() {
  if (storyKeepTimer) {
    clearTimeout(storyKeepTimer)
    storyKeepTimer = null
  }
}

function armStoryKeep() {
  storyKeepUntil.value = Date.now() + STORY_KEEP_MS
  storyKeepTick.value += 1
  clearStoryKeepTimer()
  storyKeepTimer = setTimeout(() => {
    storyKeepTick.value += 1
    storyKeepTimer = null
  }, STORY_KEEP_MS + 50)
}

function clearStoryKeep() {
  storyKeepUntil.value = 0
  clearStoryKeepTimer()
  storyKeepTick.value += 1
}

function shouldExpandStory(msg, i) {
  void storyKeepTick.value
  const key = storyKey(msg, i)
  if (shouldForceExpandStory(msg, i)) return true
  if (Object.prototype.hasOwnProperty.call(storyExpandPrefs.value, key)) {
    return !!storyExpandPrefs.value[key]
  }
  // Keep open through post-run cooldown
  const isLast = i === messages.value.length - 1
  if (isLast && Date.now() < storyKeepUntil.value) return true
  return false
}

function shouldForceExpandStory(msg, i) {
  void storyKeepTick.value
  const isLast = i === messages.value.length - 1
  if (!isLast) return false
  return !!(sending.value || isRunning.value || liveThinkingText.value)
}

function onStoryExpandChange(msg, i, expanded) {
  const key = storyKey(msg, i)
  storyExpandPrefs.value = { ...storyExpandPrefs.value, [key]: !!expanded }
}

function shouldHideMarkdown(msg) {
  return (msg._opsCards || []).length > 0
}

function assistantFollowupNote(msg) {
  const cards = msg._opsCards || []
  if (cards.some((c) => c.type === 'choice_select' || c.awaitingSelection)) {
    return '请在上方卡片中选择一项；确认后将自动发送，助手会继续执行。'
  }
  const text = String(msg.content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\|.+\|$/gm, ' ')
    .replace(/\|[^\n]+\|/g, ' ')
    .replace(/[#*`|>_\-\[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  if (!text) return ''
  const first = text.split(/[。.!？?\n]/)[0] || text
  return first.length > 100 ? `${first.slice(0, 100)}…` : first
}

function openCardPage(card) {
  const path = card?.promptPath || card?.path
  if (path) {
    try {
      if (router.currentRoute.value.path !== path) {
        router.push(path)
      }
    } catch (_) { /* ignore */ }
  }
}

function onCardChoice({ key, card }) {
  const label = card?.pageLabel || '该项'
  const text = key === 'approve'
    ? `请批准刚才的${label}操作`
    : `请拒绝刚才的${label}操作`
  inputText.value = text
  if (!sending.value && !isRunning.value) {
    nextTick(() => sendMessage())
  }
}

function onCardSelect({ item, card }) {
  const text = buildSelectionUserMessage(card, item)
  if (!text) return
  inputText.value = text
  if (!sending.value && !isRunning.value) {
    nextTick(() => sendMessage())
  }
}

function applyOpsSideEffects(msgs, { navigate } = { navigate: false }) {
  let lastActions = []
  for (const msg of msgs) {
    if (msg.role !== 'assistant' || !msg._executionStory) continue
    if (msg.pendingApprovalId && !msg.approvalStatus) continue
    let actions = extractOpsActions(msg._executionStory)
    // If awaiting agent/scope selection, suppress passages dump in the same turn
    const awaiting = actions.some((a) => a.type === 'choice_select' || a.awaitingSelection)
    if (awaiting) {
      actions = actions.filter((a) => !(a.domain === 'memory' && a.action === 'passages_list'))
    }
    msg._opsCards = actions
    if (actions.length) lastActions = actions
  }
  if (navigate && lastActions.length) {
    const action = pickNavigateAction(lastActions)
    const path = resolveNavigatePath(action)
    if (path) {
      const key = `${sessionId.value}:${action.toolName}:${path}`
      if (key !== lastNavigatedKey.value) {
        lastNavigatedKey.value = key
        try {
          if (router.currentRoute.value.path !== path) {
            router.push(path)
          }
        } catch (_) { /* ignore */ }
      }
    }
  }
}

async function ensureAgent() {
  if (agent.value?.agent_id) return
  loadError.value = ''
  try {
    const res = await agentApi.list({ name: OPS_AGENT_NAME, page: 1, page_size: 20, status: 'PUBLISHED' })
    const items = res.items || res || []
    const found = (Array.isArray(items) ? items : []).find((a) => a.name === OPS_AGENT_NAME)
    if (!found) {
      loadError.value = '未找到已发布的 vela-ops-assistant。请先运行：python -m scripts.seed_demo'
      return
    }
    agent.value = found
  } catch (e) {
    loadError.value = e.message || '加载应用操作智能体失败'
  }
}

async function ensureSession() {
  if (sessionId.value) return sessionId.value
  const session = await sessionApi.create({
    agent_id: agent.value.agent_id,
    caller_type: 'web_playground',
    caller_id: auth.user?.user_id || '',
  })
  sessionId.value = session.session_id
  currentSessionStatus.value = session.status || 'ACTIVE'
  setActiveViewing(sessionId.value, agent.value.agent_id)
  return sessionId.value
}

function newChat() {
  stopSessionEvents()
  stopPoll()
  clearStoryKeep()
  sessionId.value = null
  messages.value = []
  currentSessionStatus.value = 'ACTIVE'
  liveThinkingText.value = ''
  sending.value = false
  lastNavigatedKey.value = ''
  storyExpandPrefs.value = {}
}

function onNewChat() {
  newChat()
  panelView.value = 'chat'
}

async function toggleHistory() {
  if (panelView.value === 'history') {
    panelView.value = 'chat'
    return
  }
  await ensureAgent()
  if (loadError.value) return
  panelView.value = 'history'
  await fetchSessions()
}

async function fetchSessions() {
  if (!agent.value?.agent_id) return
  loadingSessions.value = true
  try {
    const res = await sessionApi.list({ agent_id: agent.value.agent_id, page_size: 50 })
    sessions.value = (res.items || []).filter(
      (s) => (s.messages || []).length > 0 || s.status === 'RUNNING' || s.status === 'HITL_WAIT',
    )
  } catch (e) {
    message.error(e.message || '加载会话列表失败')
  } finally {
    loadingSessions.value = false
  }
}

async function openSession(s) {
  if (!s?.session_id) return
  stopSessionEvents()
  stopPoll()
  clearStoryKeep()
  liveThinkingText.value = ''
  sending.value = false
  lastNavigatedKey.value = ''
  storyExpandPrefs.value = {}
  sessionId.value = s.session_id
  setActiveViewing(sessionId.value, agent.value?.agent_id)
  panelView.value = 'chat'
  await refreshCurrentSession({ navigate: false })
  if (['RUNNING', 'HITL_WAIT'].includes(currentSessionStatus.value)) {
    startSessionEvents(sessionId.value)
    startPollIfNeeded()
  }
  scrollToBottom()
}

function sessionStatusLabel(status) {
  const map = {
    ACTIVE: '活跃',
    RUNNING: '运行中',
    HITL_WAIT: '待审批',
    ERROR: '错误',
    CLOSED: '已关闭',
    IDLE: '空闲',
  }
  return map[status] || status
}

function sessionStatusColor(status) {
  const map = {
    ACTIVE: 'green',
    RUNNING: 'orange',
    HITL_WAIT: 'gold',
    ERROR: 'red',
  }
  return map[status] || 'default'
}

function formatSessionTime(t) {
  return formatRelativeTime(t, '')
}

function onEnter(e) {
  if (e.shiftKey) return
  e.preventDefault()
  sendMessage()
}

function scrollToBottom() {
  nextTick(() => {
    const el = msgContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function stopSessionEvents() {
  try {
    sessionEventsController?.abort?.()
  } catch (_) { /* ignore */ }
  sessionEventsController = null
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function startSessionEvents(sid) {
  stopSessionEvents()
  sessionEventsController = sessionApi.events(sid, {
    onEvent: (evt) => handleSessionEvent(evt),
    onError: () => {
      startPollIfNeeded()
    },
  })
}

function startPollIfNeeded() {
  if (pollTimer) return
  if (!['RUNNING', 'HITL_WAIT'].includes(currentSessionStatus.value)) return
  pollTimer = setInterval(() => refreshCurrentSession({ navigate: false }), 2500)
}

function handleSessionEvent(evt) {
  if (!evt || typeof evt !== 'object') return
  const type = evt.type
  if (type === 'thinking_delta') {
    const turn = evt.turn
    if (turn != null && liveThinkingTurn.value != null && turn !== liveThinkingTurn.value) {
      liveThinkingText.value = ''
    }
    if (turn != null) liveThinkingTurn.value = turn
    if (evt.text) {
      liveThinkingText.value = (liveThinkingText.value || '') + evt.text
      scrollToBottom()
    }
    return
  }
  if (type === 'story_patch' && evt.story) {
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant') {
      last._executionStory = evt.story
      // Keep expand prefs under pending → will remap after refresh via forceExpand
      storyKeepTick.value += 1
    }
    return
  }
  if (type === 'hitl' || (type === 'status' && evt.status === 'HITL_WAIT')) {
    currentSessionStatus.value = 'HITL_WAIT'
    liveThinkingText.value = ''
    sending.value = false
    stopSessionEvents()
    refreshCurrentSession({ navigate: false })
    startPollIfNeeded()
    return
  }
  if (type === 'done' || type === 'error' || (type === 'status' && ['ACTIVE', 'ERROR', 'CLOSED'].includes(evt.status))) {
    currentSessionStatus.value = evt.status === 'ERROR' ? 'ERROR' : (evt.status === 'CLOSED' ? 'CLOSED' : 'ACTIVE')
    liveThinkingText.value = ''
    sending.value = false
    stopSessionEvents()
    stopPoll()
    if (evt.status !== 'ERROR') armStoryKeep()
    else clearStoryKeep()
    refreshCurrentSession({ navigate: evt.status !== 'ERROR' })
  }
}

function normalizeMessage(msg) {
  const pendingApprovalId = msg.pendingApprovalId || msg.pending_approval_id || null
  const approvalStatus = msg.approvalStatus
    || (msg.meta && msg.meta.approved === true && 'approved')
    || (msg.meta && msg.meta.approved === false && 'rejected')
    || null
  let executionStory = normalizeExecutionStory(msg.executionStory || msg.execution_story)
  const hideProcess = (approvalStatus === 'approved' || approvalStatus === 'rejected')
    && !(msg.pendingDelivery || msg.pending_delivery)
  return {
    ...msg,
    pendingApprovalId,
    approvalStatus,
    pendingToolName: msg.pendingToolName || msg.pending_tool_name || '',
    _executionStory: hideProcess ? null : executionStory,
    _opsCards: [],
  }
}

async function refreshCurrentSession({ navigate = false } = {}) {
  if (!sessionId.value) return
  try {
    const s = await sessionApi.get(sessionId.value)
    const prev = currentSessionStatus.value
    currentSessionStatus.value = s.status || currentSessionStatus.value
    const raw = s.messages || []
    const normalized = raw
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m, idx) => normalizeMessage({ ...m, sourceIndex: idx }))
    const becameIdle = ['RUNNING', 'HITL_WAIT'].includes(prev)
      && currentSessionStatus.value === 'ACTIVE'
    if (becameIdle) armStoryKeep()
    const shouldNav = navigate || becameIdle
    const prevPendingPref = storyExpandPrefs.value.pending
    applyOpsSideEffects(normalized, { navigate: shouldNav })
    messages.value = normalized
    if (prevPendingPref != null && normalized.length) {
      const last = normalized[normalized.length - 1]
      if (last?.role === 'assistant' && last.sourceIndex != null) {
        const k = `src-${last.sourceIndex}`
        if (!(k in storyExpandPrefs.value)) {
          storyExpandPrefs.value = { ...storyExpandPrefs.value, [k]: prevPendingPref }
        }
      }
    }
    scrollToBottom()
    if (['RUNNING', 'HITL_WAIT'].includes(currentSessionStatus.value)) {
      startPollIfNeeded()
    } else {
      stopPoll()
      sending.value = false
    }
  } catch (e) {
    /* ignore transient */
  }
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value || isRunning.value || !agent.value) return
  inputText.value = ''
  clearStoryKeep()
  messages.value.push({ role: 'user', content: text })
  messages.value.push({
    role: 'assistant',
    content: '',
    _executionStory: livePlaceholderStory.value,
    _opsCards: [],
  })
  sending.value = true
  liveThinkingText.value = ''
  scrollToBottom()
  try {
    await ensureSession()
    await sessionApi.chatAsync(sessionId.value, {
      message: text,
      execution_mode: 'react',
      timeout_seconds: 300,
    })
    currentSessionStatus.value = 'RUNNING'
    watchBackgroundSession(sessionId.value, agent.value.agent_id, agent.value.name)
    startSessionEvents(sessionId.value)
    startPollIfNeeded()
  } catch (e) {
    sending.value = false
    message.error(e.message || '发送失败')
    messages.value.pop()
  }
}

async function approveHitl(msg) {
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: auth.user?.username || 'current_user',
      comment: '',
    })
    msg.approvalStatus = 'approved'
    message.success(res.message || '已批准')
    if (res?.session_status === 'RUNNING') {
      currentSessionStatus.value = 'RUNNING'
      startSessionEvents(sessionId.value)
      startPollIfNeeded()
    }
    await refreshCurrentSession({ navigate: true })
  } catch (e) {
    message.error('批准失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function rejectHitl(msg) {
  msg.rejecting = true
  try {
    await hitlApi.reject(sessionId.value, msg.pendingApprovalId, {
      approved: false,
      reviewer: auth.user?.username || 'current_user',
      comment: '',
    })
    msg.approvalStatus = 'rejected'
    message.success('已拒绝')
    await refreshCurrentSession({ navigate: false })
  } catch (e) {
    message.error('拒绝失败: ' + e.message)
  } finally {
    msg.rejecting = false
  }
}
</script>

<style scoped>
.ops-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  height: 640px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 48px);
  z-index: 920;
  background: #faf8f4;
  border: 1px solid #ddd8ce;
  border-radius: 12px;
  box-shadow: 0 16px 48px rgba(26, 23, 20, 0.28);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.ops-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 2;
}
.ops-resize-handle:hover,
.ops-resize-handle:active {
  background: rgba(194, 65, 12, 0.25);
}
.ops-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  background: #fff;
  border-bottom: 1px solid #e8e4dc;
}
.ops-panel-title-wrap {
  display: flex;
  gap: 10px;
  align-items: center;
}
.ops-panel-title-icon {
  color: #c2410c;
  font-size: 18px;
}
.ops-panel-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 15px;
  font-weight: 600;
  color: #1a1714;
  line-height: 1.2;
}
.ops-panel-sub {
  font-size: 11px;
  color: #9e9590;
  font-family: 'JetBrains Mono', monospace;
}
.ops-panel-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.ops-action-active {
  color: #c2410c !important;
}
.ops-history-body {
  gap: 8px;
}
.ops-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.ops-history-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
}
.ops-session-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ops-session-item {
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e8e4dc;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.ops-session-item:hover {
  border-color: #f0d9b5;
  background: #fffaf5;
}
.ops-session-item.active {
  border-color: #c2410c;
  background: #fff7ed;
}
.ops-session-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ops-session-item-title {
  font-size: 13px;
  font-weight: 500;
  color: #1a1714;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.ops-session-item-meta {
  margin-top: 4px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: #9e9590;
}
.ops-panel-error {
  padding: 16px;
  color: #b5341c;
  font-size: 13px;
}
.ops-panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ops-panel-empty {
  color: #9e9590;
  font-size: 13px;
  text-align: center;
  margin-top: 40px;
  padding: 0 20px;
}
.ops-msg-role {
  font-size: 11px;
  color: #9e9590;
  margin-bottom: 4px;
}
.ops-msg-user {
  align-self: flex-end;
  max-width: 92%;
}
.ops-msg-assistant {
  align-self: stretch;
  max-width: 100%;
}
.ops-msg-bubble {
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
.ops-msg-user .ops-msg-bubble {
  background: #1a1714;
  color: #fff;
}
.ops-msg-assistant .ops-msg-bubble {
  background: #f3f0e8;
  color: #1a1714;
}
.ops-md :deep(h1),
.ops-md :deep(h2),
.ops-md :deep(h3),
.ops-md :deep(h4) {
  margin: 0.55em 0 0.35em;
  font-family: 'Noto Serif SC', serif;
  font-weight: 600;
  color: #1a1714;
  line-height: 1.3;
}
.ops-md :deep(h1) { font-size: 1.15em; }
.ops-md :deep(h2) { font-size: 1.08em; }
.ops-md :deep(h3),
.ops-md :deep(h4) { font-size: 1em; }
.ops-md :deep(p) {
  margin: 0 0 0.55em;
}
.ops-md :deep(p:last-child) {
  margin-bottom: 0;
}
.ops-md :deep(ul),
.ops-md :deep(ol) {
  margin: 0.35em 0 0.55em;
  padding-left: 1.35em;
}
.ops-md :deep(li) {
  margin: 0.15em 0;
}
.ops-md :deep(blockquote) {
  margin: 0.4em 0;
  padding: 4px 10px;
  border-left: 3px solid #c2410c;
  background: rgba(194, 65, 12, 0.06);
  color: #5c5650;
}
.ops-md :deep(code) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9em;
  background: rgba(26, 23, 20, 0.06);
  padding: 1px 5px;
  border-radius: 4px;
}
.ops-md :deep(pre) {
  background: #2a2622;
  color: #f3f0e8;
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12px;
  margin: 0.45em 0;
}
.ops-md :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
}
.ops-md :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 0.5em 0;
  display: block;
  overflow-x: auto;
}
.ops-md :deep(th),
.ops-md :deep(td) {
  border: 1px solid #ddd8ce;
  padding: 5px 8px;
  text-align: left;
}
.ops-md :deep(th) {
  background: #f3f0e8;
  font-weight: 600;
}
.ops-md :deep(a) {
  color: #c2410c;
}
.ops-md :deep(hr) {
  border: none;
  border-top: 1px solid #e8e4dc;
  margin: 0.75em 0;
}
.ops-hitl {
  background: #fff7ed;
  border: 1px solid #f0d9b5;
  border-radius: 10px;
  padding: 10px;
}
.ops-hitl-title {
  font-size: 12px;
  font-weight: 600;
  color: #9a3412;
  margin-bottom: 8px;
}
.ops-hitl-btns {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.ops-hitl-result {
  font-size: 12px;
  color: #5c5650;
  margin-top: 4px;
}
.ops-typing {
  font-size: 12px;
  color: #9e9590;
}
.ops-short-note {
  font-size: 12px;
  color: #5c5650;
  padding: 6px 10px;
  background: transparent !important;
  border: none;
}
.ops-panel-input {
  border-top: 1px solid #e8e4dc;
  background: #fff;
  padding: 10px 12px;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.ops-send {
  background: #c2410c;
  border-color: #c2410c;
}
</style>

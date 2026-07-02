<template>
  <div style="height: calc(100vh - 140px); display: flex; gap: 0">
    <div class="session-sidebar">
      <div class="session-sidebar-header">
        <span class="session-sidebar-title">会话历史</span>
        <a-button size="small" type="primary" @click="createNewSession" :loading="creatingSession">
          <PlusOutlined />
        </a-button>
      </div>
      <div class="session-list" v-if="sessions.length > 0">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-item', { active: s.session_id === sessionId }]"
          @click="switchSession(s)"
        >
          <div class="session-item-top">
            <span class="session-item-id">{{ s.session_id?.substring(0, 8) }}...</span>
            <a-tag :color="s.status === 'ACTIVE' ? 'green' : 'default'" size="small">
              {{ s.status === 'ACTIVE' ? '活跃' : s.status }}
            </a-tag>
          </div>
          <div class="session-item-meta">
            <span class="session-item-msg-count">{{ (s.messages || []).length }} 条消息</span>
            <span class="session-item-time">{{ formatTime(s.created_at) }}</span>
          </div>
        </div>
      </div>
      <div class="session-list-empty" v-else-if="!loadingSessions">
        <span style="color: #9e9590; font-size: 12px;">暂无会话</span>
      </div>
      <div class="session-list-empty" v-else>
        <a-spin size="small" />
      </div>
    </div>

    <div style="flex: 1; display: flex; flex-direction: column; min-width: 0;">
      <div class="chat-header">
        <a-button type="text" @click="$router.back()">
          <ArrowLeftOutlined /> 返回
        </a-button>
        <span class="chat-title">{{ agent.name }} - 对话测试</span>
        <a-tag color="green">会话: {{ sessionId?.substring(0, 8) }}...</a-tag>
        <a-select
          v-model:value="executionMode"
          size="small"
          style="width: 160px; margin-left: auto;"
          :options="executionModeOptions"
        />
      </div>

    <div class="chat-messages" ref="msgContainer">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        :class="['chat-msg', msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-assistant']"
      >
        <div class="chat-msg-role">
          <template v-if="msg.role === 'user'">你</template>
          <template v-else>
            {{ agent.name }}
            <a-tag v-if="msg.activeSkill" color="orange" style="margin-left: 6px; font-size: 10px;">
              {{ msg.activeSkill }}
            </a-tag>
            <a-tag v-if="msg.executionMode && msg.executionMode !== 'direct'" color="blue" style="margin-left: 4px; font-size: 10px;">
              {{ executionModeOptions.find(o => o.value === msg.executionMode)?.label || msg.executionMode }}
            </a-tag>
          </template>
        </div>

        <div v-if="msg.thinking" class="chat-thinking">
          <div class="chat-thinking-header" @click="msg.thinkingExpanded = !msg.thinkingExpanded">
            <CaretRightOutlined v-if="!msg.thinkingExpanded" style="font-size: 10px;" />
            <CaretDownOutlined v-else style="font-size: 10px;" />
            <span style="margin-left: 4px;">思考与执行过程</span>
          </div>
          <div v-if="msg.thinkingExpanded" class="chat-thinking-body">
            {{ msg.thinking }}
          </div>
        </div>

        <div class="chat-msg-content" v-if="msg.content" v-html="renderMarkdown(msg.content)"></div>
        <div v-if="msg.files && msg.files.length > 0" class="chat-files">
          <div class="chat-files-title">生成的文件：</div>
          <div
            v-for="f in msg.files"
            :key="f.url"
            class="chat-file-item"
          >
            <a :href="f.url" :download="f.name" class="chat-file-link">
              <DownloadOutlined />
              <span class="chat-file-name">{{ f.name }}</span>
              <span class="chat-file-size">({{ f.size_display }})</span>
            </a>
          </div>
        </div>
      </div>

      <div v-if="sending" class="chat-msg chat-msg-assistant">
        <div class="chat-msg-role">
          {{ agent.name }}
          <a-tag v-if="activeSkill" color="orange" style="margin-left: 6px; font-size: 10px;">
            {{ activeSkill }}
          </a-tag>
        </div>
        <div class="chat-thinking sending">
          <div class="chat-thinking-header" @click="thinkingExpanded = !thinkingExpanded">
            <CaretRightOutlined v-if="!thinkingExpanded" style="font-size: 10px;" />
            <CaretDownOutlined v-else style="font-size: 10px;" />
            <span style="margin-left: 4px;">分析规划中...</span>
            <a-spin size="small" style="margin-left: 8px;" />
          </div>
          <div v-if="thinkingExpanded" class="chat-thinking-body">
            <div class="thinking-steps">
              <div class="thinking-step">
                <span class="step-dot active"></span>
                执行模式: {{ executionModeOptions.find(o => o.value === executionMode)?.label || executionMode }}
              </div>
              <div class="thinking-step">
                <span class="step-dot active"></span>
                正在分析请求...
              </div>
              <div class="thinking-step" v-if="activeSkill">
                <span class="step-dot active"></span>
                使用 Skill: {{ activeSkill }}
              </div>
              <div class="thinking-step">
                <span class="step-dot active"></span>
                等待模型响应...
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input-area">
      <div class="skill-bar" v-if="activeSkill">
        <a-tag color="orange" closable @close="clearSkill">
          <ThunderboltOutlined /> {{ activeSkill }}
        </a-tag>
      </div>
      <div class="chat-input-row">
        <div class="chat-input-wrapper" ref="inputWrapper">
          <a-textarea
            ref="inputRef"
            v-model:value="inputText"
            placeholder="输入消息... 输入 / 选择 Skill"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            @pressEnter="onEnter"
            @input="onInput"
            :disabled="sending"
          />
          <a-button
            type="primary"
            :loading="sending"
            :disabled="!inputText.trim()"
            @click="sendMessage"
            class="send-btn"
          >
            <SendOutlined />
          </a-button>
        </div>
        <div class="chat-timeout-setting">
          <a-checkbox v-model:checked="skipHistory" :disabled="sending" style="white-space: nowrap; font-size: 12px;">
            不引用历史
          </a-checkbox>
          <span class="timeout-label">超时</span>
          <a-input-number
            v-model:value="timeoutSeconds"
            :min="10"
            :max="600"
            :step="5"
            size="small"
            style="width: 80px"
          />
          <span class="timeout-unit">秒</span>
        </div>
      </div>

      <div class="skill-popover" v-if="showSkillMenu && filteredSkills.length > 0" ref="skillMenuRef">
        <div
          v-for="skill in filteredSkills"
          :key="skill.skill_pack_id"
          class="skill-item"
          :class="{ active: skillMenuIndex === filteredSkills.indexOf(skill) }"
          @click="selectSkill(skill)"
          @mouseenter="skillMenuIndex = filteredSkills.indexOf(skill)"
        >
          <div class="skill-item-name">
            <ThunderboltOutlined style="color: #c2410c; margin-right: 6px;" />
            {{ skill.name }}
          </div>
          <div class="skill-item-desc">{{ skill.description || skill.version }}</div>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeftOutlined, CaretRightOutlined, CaretDownOutlined,
  ThunderboltOutlined, SendOutlined, PlusOutlined, DownloadOutlined,
} from '@ant-design/icons-vue'
import { agentApi, sessionApi } from '../../api'
import { message } from 'ant-design-vue'
import { marked } from 'marked'

marked.setOptions({
  breaks: true,
  gfm: true,
})

const route = useRoute()
const agentId = route.params.id
const agent = reactive({})
const sessionId = ref('')
const messages = ref([])
const inputText = ref('')
const sending = ref(false)
const thinkingExpanded = ref(false)
const msgContainer = ref(null)
const inputRef = ref(null)
const inputWrapper = ref(null)
const skillMenuRef = ref(null)

const skills = ref([])
const activeSkill = ref(null)
const activeSkillId = ref(null)
const showSkillMenu = ref(false)
const skillMenuIndex = ref(0)
const slashQuery = ref('')
const timeoutSeconds = ref(120)
const executionMode = ref('auto')
const skipHistory = ref(false)
const creatingSession = ref(false)
const sessions = ref([])
const loadingSessions = ref(false)
const executionModeOptions = [
  { label: '自动选择模式', value: 'auto' },
  { label: 'ReAct 模式', value: 'react' },
  { label: 'Plan & Execute', value: 'plan_and_execute' },
  { label: '直接对话', value: 'direct' },
]

const filteredSkills = computed(() => {
  if (!slashQuery.value) return skills.value
  const q = slashQuery.value.toLowerCase()
  return skills.value.filter(s =>
    s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
  )
})

onMounted(async () => {
  try {
    const a = await agentApi.get(agentId)
    Object.assign(agent, a)

    skills.value = await agentApi.getSkills(agentId)

    const session = await sessionApi.create({
      agent_id: agentId,
      caller_type: 'web_playground',
      caller_id: 'anonymous',
    })
    sessionId.value = session.session_id

    await fetchSessions()
  } catch (e) {
    message.error(e.message)
  }
})

async function fetchSessions() {
  loadingSessions.value = true
  try {
    const res = await sessionApi.list({ agent_id: agentId, page_size: 50 })
    sessions.value = (res.items || []).filter(s => (s.messages || []).length > 0)
  } catch (e) {
    console.error('获取会话列表失败:', e)
  } finally {
    loadingSessions.value = false
  }
}

async function switchSession(s) {
  if (s.session_id === sessionId.value) return
  sessionId.value = s.session_id
  messages.value = (s.messages || []).map(msg => ({
    ...msg,
    thinkingExpanded: false,
  }))
  activeSkill.value = null
  activeSkillId.value = null
  skipHistory.value = false
  await nextTick()
  scrollToBottom()
}

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

async function createNewSession() {
  try {
    creatingSession.value = true
    const session = await sessionApi.create({
      agent_id: agentId,
      caller_type: 'web_playground',
      caller_id: 'anonymous',
    })
    sessionId.value = session.session_id
    messages.value = []
    activeSkill.value = null
    activeSkillId.value = null
    skipHistory.value = false
    await fetchSessions()
    message.success('新会话已创建')
  } catch (e) {
    message.error(e.message)
  } finally {
    creatingSession.value = false
  }
}

function onInput(e) {
  const val = e.target?.value || inputText.value
  const cursorPos = e.target?.selectionStart || 0

  const beforeCursor = val.substring(0, cursorPos)
  const slashMatch = beforeCursor.match(/\/(\S*)$/)

  if (slashMatch) {
    slashQuery.value = slashMatch[1]
    showSkillMenu.value = true
    skillMenuIndex.value = 0
  } else {
    showSkillMenu.value = false
    slashQuery.value = ''
  }
}

function onEnter(e) {
  if (showSkillMenu.value) {
    e.preventDefault()
    if (filteredSkills.value.length > 0) {
      selectSkill(filteredSkills.value[skillMenuIndex.value])
    }
    return
  }
  if (!e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function selectSkill(skill) {
  const val = inputText.value
  const cursorPos = inputRef.value?.$el?.querySelector('textarea')?.selectionStart || val.length
  const beforeCursor = val.substring(0, cursorPos)
  const afterCursor = val.substring(cursorPos)

  const slashIdx = beforeCursor.lastIndexOf('/')
  const newBefore = beforeCursor.substring(0, slashIdx)
  inputText.value = newBefore + afterCursor

  activeSkill.value = skill.name
  activeSkillId.value = skill.skill_pack_id
  showSkillMenu.value = false
  slashQuery.value = ''

  nextTick(() => {
    inputRef.value?.focus()
  })
}

function clearSkill() {
  activeSkill.value = null
  activeSkillId.value = null
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  inputText.value = ''
  showSkillMenu.value = false
  messages.value.push({ role: 'user', content: text })
  sending.value = true
  thinkingExpanded.value = false

  await nextTick()
  scrollToBottom()

  try {
    const payload = { message: text, timeout_seconds: timeoutSeconds.value, execution_mode: executionMode.value, skip_history: skipHistory.value }
    if (activeSkillId.value) {
      payload.skill_pack_id = activeSkillId.value
    }

    const res = await sessionApi.chat(sessionId.value, payload)

    const assistantMsg = {
      role: 'assistant',
      content: res.content,
      thinking: res.thinking || '',
      thinkingExpanded: false,
      activeSkill: res.active_skill || activeSkill.value,
      executionMode: res.execution_mode || executionMode.value,
      files: res.files || [],
    }

    if (res.thinking) {
      assistantMsg.thinkingExpanded = true
    }

    messages.value.push(assistantMsg)
    scrollToBottom()
  } catch (e) {
    message.error(e.message)
  } finally {
    sending.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

function renderMarkdown(text) {
  if (!text) return ''
  return marked.parse(text)
}
</script>

<style scoped>
.session-sidebar {
  width: 220px;
  min-width: 220px;
  background: #faf8f5;
  border-right: 1px solid #ddd8ce;
  display: flex;
  flex-direction: column;
  border-radius: 8px 0 0 0;
  overflow: hidden;
}
.session-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid #ddd8ce;
  background: #fff;
}
.session-sidebar-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.session-list-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.session-item:hover {
  background: #f0ede6;
}
.session-item.active {
  background: #e8e4dc;
}
.session-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.session-item-id {
  font-size: 12px;
  font-family: monospace;
  color: #5c5650;
  font-weight: 500;
}
.session-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.session-item-msg-count {
  font-size: 11px;
  color: #9e9590;
}
.session-item-time {
  font-size: 11px;
  color: #b5afa8;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ddd8ce;
  border-radius: 8px 8px 0 0;
}
.chat-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 16px;
  font-weight: 600;
  color: #1a1714;
  flex: 1;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fff;
  border-left: 1px solid #ddd8ce;
  border-right: 1px solid #ddd8ce;
}
.chat-msg {
  margin-bottom: 16px;
  max-width: 80%;
}
.chat-msg-user {
  margin-left: auto;
}
.chat-msg-role {
  font-size: 11px;
  color: #9e9590;
  margin-bottom: 4px;
}
.chat-msg-user .chat-msg-role {
  text-align: right;
}
.chat-msg-content {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.chat-msg-assistant .chat-msg-content {
  background: #f3f0e8;
  color: #1a1714;
}
.chat-msg-user .chat-msg-content {
  background: #1a1714;
  color: #fff;
}
.chat-msg-content :deep(p) {
  margin: 0 0 8px 0;
}
.chat-msg-content :deep(p:last-child) {
  margin-bottom: 0;
}
.chat-msg-content :deep(a) {
  color: #1a6fb5;
  text-decoration: underline;
}
.chat-msg-content :deep(a:hover) {
  color: #0d4f85;
}
.chat-msg-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
}
.chat-msg-content :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.chat-msg-content :deep(pre code) {
  background: none;
  padding: 0;
}
.chat-msg-content :deep(ul), .chat-msg-content :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}
.chat-msg-content :deep(li) {
  margin-bottom: 4px;
}
.chat-msg-content :deep(h1), .chat-msg-content :deep(h2),
.chat-msg-content :deep(h3), .chat-msg-content :deep(h4) {
  margin: 12px 0 6px 0;
  font-weight: 600;
}
.chat-msg-content :deep(h1) { font-size: 18px; }
.chat-msg-content :deep(h2) { font-size: 16px; }
.chat-msg-content :deep(h3) { font-size: 14px; }
.chat-msg-content :deep(h4) { font-size: 13px; }
.chat-msg-content :deep(hr) {
  border: none;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
  margin: 12px 0;
}
.chat-msg-content :deep(blockquote) {
  border-left: 3px solid rgba(0, 0, 0, 0.15);
  padding-left: 10px;
  margin: 8px 0;
  color: rgba(0, 0, 0, 0.6);
}
.chat-msg-content :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}
.chat-msg-content :deep(th), .chat-msg-content :deep(td) {
  border: 1px solid rgba(0, 0, 0, 0.1);
  padding: 6px 10px;
  text-align: left;
}
.chat-msg-content :deep(th) {
  background: rgba(0, 0, 0, 0.04);
  font-weight: 600;
}

.chat-files {
  margin-top: 10px;
  padding: 10px 14px;
  background: #f8f6f2;
  border: 1px solid #e8e4dc;
  border-radius: 8px;
}
.chat-files-title {
  font-size: 12px;
  color: #6b6560;
  margin-bottom: 6px;
  font-weight: 500;
}
.chat-file-item {
  margin-bottom: 4px;
}
.chat-file-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #2563eb;
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
}
.chat-file-link:hover {
  background: #e8e4dc;
  color: #1d4ed8;
}
.chat-file-name {
  font-weight: 500;
}
.chat-file-size {
  font-size: 11px;
  color: #9e9590;
}

.chat-thinking {
  margin-bottom: 8px;
}
.chat-thinking-header {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #9e9590;
  cursor: pointer;
  padding: 4px 0;
  user-select: none;
}
.chat-thinking-header:hover {
  color: #1a1714;
}
.chat-thinking-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: #faf8f5;
  border: 1px solid #e8e4dc;
  border-radius: 6px;
  font-size: 12px;
  color: #5c5650;
  white-space: pre-wrap;
  max-height: 240px;
  overflow-y: auto;
  line-height: 1.6;
}
.chat-thinking.sending .chat-thinking-body {
  background: #fef9f0;
  border-color: #f5e6cc;
}

.thinking-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.thinking-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #5c5650;
}
.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d9d0c5;
  flex-shrink: 0;
}
.step-dot.active {
  background: #c2410c;
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.chat-input-area {
  position: relative;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #ddd8ce;
  border-top: none;
  border-radius: 0 0 8px 8px;
}
.skill-bar {
  margin-bottom: 8px;
}
.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex: 1;
}
.chat-input-wrapper :deep(.ant-input) {
  flex: 1;
}
.send-btn {
  flex-shrink: 0;
}
.chat-input-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.chat-timeout-setting {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding-bottom: 4px;
}
.timeout-label {
  font-size: 12px;
  color: #9e9590;
  white-space: nowrap;
}
.timeout-unit {
  font-size: 12px;
  color: #9e9590;
}

.skill-popover {
  position: absolute;
  bottom: 100%;
  left: 16px;
  right: 16px;
  margin-bottom: 4px;
  background: #fff;
  border: 1px solid #e8e4dc;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
}
.skill-item {
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f3f0e8;
}
.skill-item:last-child {
  border-bottom: none;
}
.skill-item.active {
  background: #fef9f0;
}
.skill-item:hover {
  background: #fef9f0;
}
.skill-item-name {
  font-size: 13px;
  font-weight: 500;
  color: #1a1714;
}
.skill-item-desc {
  font-size: 11px;
  color: #9e9590;
  margin-top: 2px;
  margin-left: 22px;
}
</style>
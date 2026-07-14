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
            <a-tag :color="sessionStatusColor(s.status)" size="small">
              <LoadingOutlined v-if="s.status === 'RUNNING'" style="margin-right: 4px;" />
              {{ sessionStatusLabel(s.status) }}
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
        <a-tag v-if="isRunning" color="orange">
          <LoadingOutlined style="margin-right: 4px;" />运行中
        </a-tag>
        <a-tag v-else-if="isHitlWait" color="gold">待审批</a-tag>
        <a-select
          v-if="agent.agent_type === 'SINGLE'"
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
          <a-alert
            v-if="msg.filesTruncated || hasTruncatedFiles(msg.files)"
            type="warning"
            show-icon
            style="margin-bottom: 8px;"
          >
            <template #message>文件可能不完整</template>
            <template #description>
              模型输出在生成文件时被截断，当前文件内容可能缺失尾部。请尝试简化请求、增加超时时间，或让 Agent 继续补全。
            </template>
          </a-alert>
          <div class="chat-files-title">生成的文件：</div>
          <div
            v-for="f in msg.files"
            :key="f.url"
            class="chat-file-item"
          >
            <span class="chat-file-link" @click="previewFile(f)">
              <FileOutlined />
              <span class="chat-file-name">{{ f.name }}</span>
              <span class="chat-file-size">({{ f.size_display }})</span>
              <a-tag v-if="f.truncated" color="warning" class="chat-file-truncated-tag">可能不完整</a-tag>
            </span>
          </div>
        </div>

        <div v-if="msg.executionTrace && msg.executionTrace.length" class="chat-trace">
          <div class="chat-thinking-header" @click="msg.traceExpanded = !msg.traceExpanded">
            <CaretRightOutlined v-if="!msg.traceExpanded" style="font-size: 10px;" />
            <CaretDownOutlined v-else style="font-size: 10px;" />
            <span style="margin-left: 4px;">工作流执行轨迹 ({{ msg.executionTrace.length }} 步)</span>
          </div>
          <div v-if="msg.traceExpanded" class="chat-trace-body">
            <div v-for="(step, si) in msg.executionTrace" :key="si" class="trace-step">
              <a-tag :color="step.status === 'success' ? 'green' : step.status === 'hitl_wait' ? 'orange' : 'red'" size="small">
                {{ step.node_type }}
              </a-tag>
              <span class="trace-label">{{ step.label || step.node_id }}</span>
              <span class="trace-duration" v-if="step.duration_ms">{{ step.duration_ms }}ms</span>
            </div>
          </div>
        </div>

        <div v-if="msg.pendingApprovalId && !msg.approvalStatus" class="chat-hitl-actions">
          <a-alert
            :message="msg.pendingOtp || msg.previewPayload?.flow_kind === 'otp_wait'
              ? (msg.previewPayload?.prompt || '请输入短信验证码')
              : msg.pendingWorkflow ? '工作流 HITL 等待审批'
              : msg.pendingDelivery ? '多 Agent 交付物等待审批'
              : `工具 [${msg.pendingToolName}] 等待审批`"
            type="warning"
            show-icon
            style="margin-bottom: 8px;"
          />
          <div v-if="msg.previewPayload && (msg.previewPayload.som_image_b64 || msg.previewPayload.screenshot_b64)" class="hitl-som-preview">
            <div class="hitl-preview-meta">
              <a-tag v-if="msg.previewPayload.risk_tier" color="orange">{{ msg.previewPayload.risk_tier }}</a-tag>
              <span v-if="msg.previewPayload.action">动作: {{ msg.previewPayload.action }}</span>
              <span v-if="msg.previewPayload.target_label">目标: {{ msg.previewPayload.target_label }}</span>
            </div>
            <img
              :src="'data:image/png;base64,' + (msg.previewPayload.som_image_b64 || msg.previewPayload.screenshot_b64)"
              alt="SoM 预览"
              class="hitl-som-image"
            />
          </div>
          <div v-if="msg.pendingOtp || msg.previewPayload?.flow_kind === 'otp_wait'" class="hitl-otp-form">
            <a-input
              v-model:value="msg.otpCode"
              placeholder="请输入验证码"
              maxlength="12"
              style="width: 200px;"
              @pressEnter="submitOtpHitl(msg)"
            />
            <a-button type="primary" size="small" :loading="msg.approving" @click="submitOtpHitl(msg)">
              提交验证码
            </a-button>
            <a-button size="small" :loading="msg.approving" @click="rejectHitl(msg)">
              取消
            </a-button>
          </div>
          <a-space v-else>
            <a-button type="primary" size="small" :loading="msg.approving" @click="approveHitl(msg)">
              批准
            </a-button>
            <a-button danger size="small" :loading="msg.approving" @click="rejectHitl(msg)">
              拒绝
            </a-button>
          </a-space>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && msg.pendingWorkflow && msg.approvalFinalResult" class="chat-hitl-result">
          <a-alert message="工作流审批已通过 - 执行结果" type="success" show-icon style="margin-bottom: 8px;" />
          <div class="chat-msg-content" v-html="renderMarkdown(msg.approvalFinalResult)"></div>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && msg.pendingDelivery && msg.approvalFinalResult" class="chat-hitl-result">
          <a-alert message="审批已通过 - 交付物" type="success" show-icon style="margin-bottom: 8px;" />
          <div class="chat-msg-content" v-html="renderMarkdown(msg.approvalFinalResult)"></div>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && !msg.pendingDelivery && !msg.pendingWorkflow" class="chat-hitl-result">
          <a-alert message="工具审批已通过，结果已注入对话上下文。请发送消息继续。" type="success" show-icon />
        </div>

        <div v-if="msg.approvalStatus === 'rejected'" class="chat-hitl-result">
          <a-alert :message="msg.pendingWorkflow ? '工作流审批已拒绝' : msg.pendingDelivery ? '交付物审批已拒绝' : '工具审批已拒绝，已通知 Agent。'" type="error" show-icon />
        </div>
      </div>

      <div v-if="isSending" class="chat-msg chat-msg-assistant">
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
            :disabled="isSending"
          />
          <a-button
            v-if="canAbort"
            type="primary"
            danger
            :loading="aborting"
            :disabled="aborting"
            @click="abortCurrentSession"
            class="send-btn"
          >
            <StopOutlined v-if="!aborting" />
          </a-button>
          <a-button
            v-else
            type="primary"
            :loading="isSending"
            :disabled="!inputText.trim() || isSending"
            @click="sendMessage"
            class="send-btn"
          >
            <SendOutlined />
          </a-button>
        </div>
        <div class="chat-timeout-setting">
          <a-checkbox v-model:checked="skipHistory" :disabled="isSending" style="white-space: nowrap; font-size: 12px;">
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

    <!-- 文件预览弹窗 -->
    <Teleport to="body">
      <div class="preview-overlay" v-if="previewVisible" @mousedown.self="closePreview">
        <div
          class="preview-modal"
          :style="{ width: previewWidth + 'px', height: previewHeight + 'px' }"
        >
          <div class="preview-header">
            <span class="preview-title">
              <FileOutlined style="margin-right: 6px;" />{{ previewFileName }}
              <a-tag v-if="previewFileTruncated" color="warning" style="margin-left: 8px; font-size: 11px;">可能不完整</a-tag>
            </span>
            <div class="preview-actions">
              <a-button size="small" type="text" :href="previewFileUrl" :download="previewFileName">
                <DownloadOutlined /> 下载
              </a-button>
              <a-button size="small" type="text" @click="closePreview">
                <CloseOutlined />
              </a-button>
            </div>
          </div>
          <div class="preview-body" ref="previewBodyRef">
            <a-alert
              v-if="previewFileTruncated"
              type="warning"
              show-icon
              message="此文件可能因模型输出截断而不完整"
              description="预览内容可能缺少尾部，建议重新生成或请求 Agent 补全文件。"
              style="margin: 12px 12px 0;"
            />
            <!-- HTML 预览 -->
            <iframe
              v-if="previewType === 'html'"
              :srcdoc="previewContent"
              class="preview-iframe"
              sandbox="allow-scripts allow-same-origin"
            />
            <!-- Markdown 预览 -->
            <div
              v-else-if="previewType === 'markdown'"
              class="preview-markdown"
              v-html="renderMarkdown(previewContent)"
            />
            <!-- 图片预览 -->
            <img
              v-else-if="previewType === 'image'"
              :src="previewFileUrl"
              class="preview-image"
              :alt="previewFileName"
            />
            <!-- CSV 表格预览 -->
            <div v-else-if="previewType === 'csv'" class="preview-csv">
              <table class="csv-table" v-if="csvData.length > 0">
                <thead>
                  <tr>
                    <th v-for="(h, hi) in csvData[0]" :key="hi">{{ h }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in csvData.slice(1)" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- 文本/JSON/XML 预览 -->
            <pre v-else-if="previewType === 'text'" class="preview-text">{{ previewContent }}</pre>
            <!-- PDF 预览 -->
            <iframe
              v-else-if="previewType === 'pdf'"
              :src="previewFileUrl"
              class="preview-iframe"
            />
            <!-- Office 文件：提示下载 -->
            <div v-else-if="previewType === 'office'" class="preview-office">
              <FileOutlined style="font-size: 48px; color: #9e9590;" />
              <p style="margin-top: 16px; color: #5c5650;">此文件类型不支持在线预览</p>
              <a-button type="primary" :href="previewFileUrl" :download="previewFileName" style="margin-top: 12px;">
                <DownloadOutlined /> 下载文件
              </a-button>
            </div>
            <!-- 加载中 -->
            <div v-else-if="previewLoading" class="preview-loading">
              <a-spin size="large" />
              <p style="margin-top: 12px; color: #9e9590;">加载中...</p>
            </div>
          </div>
          <!-- 右下角拖拽调整大小 -->
          <div class="preview-resize-handle" @mousedown="startResize"></div>
        </div>
      </div>
    </Teleport>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeftOutlined, CaretRightOutlined, CaretDownOutlined,
  ThunderboltOutlined, SendOutlined, PlusOutlined, DownloadOutlined,
  FileOutlined, CloseOutlined, LoadingOutlined, StopOutlined,
} from '@ant-design/icons-vue'
import { agentApi, sessionApi, hitlApi, skillApi } from '../../api'
import { message } from 'ant-design-vue'
import { marked } from 'marked'
import {
  watchBackgroundSession,
  setActiveViewing,
  unwatchBackgroundSession,
} from '../../composables/useBackgroundSessions'

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
const currentSessionStatus = ref('ACTIVE')
const aborting = ref(false)
let sessionPollTimer = null

const isRunning = computed(() => currentSessionStatus.value === 'RUNNING')
const isHitlWait = computed(() => currentSessionStatus.value === 'HITL_WAIT')
const canAbort = computed(() => isRunning.value || isHitlWait.value)
const isSending = computed(() => sending.value || isRunning.value)

async function abortCurrentSession() {
  if (!sessionId.value || !canAbort.value || aborting.value) return
  aborting.value = true
  try {
    const res = await sessionApi.abort(sessionId.value)
    message.success(res.message || '已请求中止')
    if (res.status) {
      currentSessionStatus.value = res.status
    }
    startSessionPollIfNeeded()
    await fetchSessions()
    const s = await sessionApi.get(sessionId.value)
    currentSessionStatus.value = s.status
    if (s.messages) {
      messages.value = mapSessionMessages(s.messages)
    }
  } catch (e) {
    message.error(e.message || '中止失败')
  } finally {
    aborting.value = false
  }
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

function mapSessionMessages(msgs) {
  return (msgs || []).map(msg => ({
    ...msg,
    thinking: msg.thinking || '',
    thinkingExpanded: !!msg.thinking,
    traceExpanded: true,
    executionTrace: msg.executionTrace || msg.execution_trace || [],
    executionMode: msg.executionMode || msg.execution_mode || '',
    activeSkill: msg.activeSkill || msg.active_skill || null,
    files: msg.files || [],
    filesTruncated: msg.filesTruncated || msg.files_truncated || false,
    pendingApprovalId: msg.pendingApprovalId || msg.pending_approval_id || null,
    pendingDelivery: msg.pendingDelivery || msg.pending_delivery || false,
    pendingWorkflow: msg.pendingWorkflow || msg.pending_workflow || false,
    pendingToolName: msg.pendingToolName || msg.pending_tool_name || '',
    previewPayload: msg.previewPayload || msg.preview_payload || null,
    pendingOtp: msg.pendingOtp || msg.pending_otp
      || (msg.previewPayload || msg.preview_payload || {})?.flow_kind === 'otp_wait',
    otpCode: msg.otpCode || '',
    approvalStatus: msg.approvalStatus || null,
    approvalFinalResult: msg.approvalFinalResult || '',
  }))
}

async function loadSessionById(id) {
  const s = await sessionApi.get(id)
  currentSessionStatus.value = s.status
  messages.value = mapSessionMessages(s.messages)
  await nextTick()
  scrollToBottom()
}

async function refreshCurrentSession() {
  if (!sessionId.value) return
  try {
    const s = await sessionApi.get(sessionId.value)
    const prevStatus = currentSessionStatus.value
    currentSessionStatus.value = s.status
    messages.value = mapSessionMessages(s.messages)

    const idx = sessions.value.findIndex(x => x.session_id === s.session_id)
    if (idx >= 0) {
      sessions.value[idx] = s
    } else if ((s.messages || []).length > 0 || s.status === 'RUNNING') {
      sessions.value.unshift(s)
    }

    if (prevStatus === 'RUNNING' && s.status !== 'RUNNING') {
      unwatchBackgroundSession(sessionId.value)
      await fetchSessions()
      stopSessionPoll()
    }
    await nextTick()
    scrollToBottom()
  } catch (e) {
    console.error('刷新会话失败:', e)
  }
}

function startSessionPollIfNeeded() {
  stopSessionPoll()
  if (currentSessionStatus.value === 'RUNNING') {
    sessionPollTimer = setInterval(refreshCurrentSession, 2500)
  }
}

function stopSessionPoll() {
  if (sessionPollTimer) {
    clearInterval(sessionPollTimer)
    sessionPollTimer = null
  }
}
const executionModeOptions = [
  { label: '自动选择模式', value: 'auto' },
  { label: 'ReAct 模式', value: 'react' },
  { label: 'Plan & Execute', value: 'plan_and_execute' },
  { label: '直接对话', value: 'direct' },
]

// 文件预览相关状态
const previewVisible = ref(false)
const previewFileName = ref('')
const previewFileUrl = ref('')
const previewFileTruncated = ref(false)
const previewType = ref('')
const previewContent = ref('')
const previewLoading = ref(false)
const csvData = ref([])
const previewWidth = ref(900)
const previewHeight = ref(600)
const previewBodyRef = ref(null)
let isResizing = false
let resizeStartX = 0
let resizeStartY = 0
let resizeStartW = 0
let resizeStartH = 0

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

    skills.value = (await skillApi.list({ page_size: 100 })).items || []

    const querySessionId = route.query.session_id
    if (querySessionId) {
      sessionId.value = querySessionId
      await loadSessionById(querySessionId)
    } else {
      const session = await sessionApi.create({
        agent_id: agentId,
        caller_type: 'web_playground',
        caller_id: 'anonymous',
      })
      sessionId.value = session.session_id
      currentSessionStatus.value = session.status || 'ACTIVE'
    }

    setActiveViewing(sessionId.value, agentId)
    await fetchSessions()
    startSessionPollIfNeeded()
  } catch (e) {
    message.error(e.message)
  }
})

async function fetchSessions() {
  loadingSessions.value = true
  try {
    const res = await sessionApi.list({ agent_id: agentId, page_size: 50 })
    sessions.value = (res.items || []).filter(
      s => (s.messages || []).length > 0 || s.status === 'RUNNING'
    )
  } catch (e) {
    console.error('获取会话列表失败:', e)
  } finally {
    loadingSessions.value = false
  }
}

async function switchSession(s) {
  if (s.session_id === sessionId.value) return
  sessionId.value = s.session_id
  setActiveViewing(sessionId.value, agentId)
  activeSkill.value = null
  activeSkillId.value = null
  skipHistory.value = false
  try {
    await loadSessionById(s.session_id)
    startSessionPollIfNeeded()
  } catch (e) {
    message.error(e.message)
  }
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
    currentSessionStatus.value = session.status || 'ACTIVE'
    setActiveViewing(sessionId.value, agentId)
    stopSessionPoll()
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
    if (canAbort.value) return
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

// ---- 文件预览 ----

const TEXT_EXTENSIONS = new Set(['.txt', '.json', '.xml', '.drawio', '.dio', '.py', '.js', '.ts', '.css', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.sh', '.bat', '.log', '.env'])
const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'])
const OFFICE_EXTENSIONS = new Set(['.docx', '.xlsx', '.pptx', '.doc', '.xls', '.ppt'])

function getPreviewType(filename) {
  const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase()
  if (ext === '.html' || ext === '.htm') return 'html'
  if (ext === '.md' || ext === '.markdown') return 'markdown'
  if (ext === '.csv') return 'csv'
  if (ext === '.pdf') return 'pdf'
  if (IMAGE_EXTENSIONS.has(ext)) return 'image'
  if (OFFICE_EXTENSIONS.has(ext)) return 'office'
  if (TEXT_EXTENSIONS.has(ext)) return 'text'
  return 'text'
}

function hasTruncatedFiles(files) {
  return Array.isArray(files) && files.some(f => f.truncated)
}

async function previewFile(file) {
  previewVisible.value = true
  previewFileName.value = file.name
  previewFileUrl.value = file.url
  previewFileTruncated.value = !!file.truncated
  previewContent.value = ''
  previewLoading.value = true
  csvData.value = []

  const type = getPreviewType(file.name)
  previewType.value = type

  if (type === 'text' || type === 'markdown' || type === 'html' || type === 'csv' || type === 'json') {
    try {
      const resp = await fetch(file.url)
      if (!resp.ok) throw new Error('加载失败')
      const text = await resp.text()
      previewContent.value = text

      if (type === 'csv') {
        parseCsv(text)
      }
    } catch (e) {
      previewContent.value = '加载文件内容失败: ' + e.message
    }
  }

  previewLoading.value = false
}

function parseCsv(text) {
  const lines = text.trim().split('\n')
  const result = []
  for (const line of lines) {
    const cols = []
    let current = ''
    let inQuotes = false
    for (const ch of line) {
      if (ch === '"') {
        inQuotes = !inQuotes
      } else if (ch === ',' && !inQuotes) {
        cols.push(current.trim())
        current = ''
      } else {
        current += ch
      }
    }
    cols.push(current.trim())
    result.push(cols)
  }
  csvData.value = result
}

function closePreview() {
  previewVisible.value = false
  previewFileName.value = ''
  previewFileUrl.value = ''
  previewFileTruncated.value = false
  previewType.value = ''
  previewContent.value = ''
  csvData.value = []
}

function startResize(e) {
  if (!e.target.classList.contains('preview-resize-handle')) return
  isResizing = true
  resizeStartX = e.clientX
  resizeStartY = e.clientY
  resizeStartW = previewWidth.value
  resizeStartH = previewHeight.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', onResizeEnd)
  e.preventDefault()
}

function onResize(e) {
  if (!isResizing) return
  const dx = e.clientX - resizeStartX
  const dy = e.clientY - resizeStartY
  previewWidth.value = Math.max(400, resizeStartW + dx)
  previewHeight.value = Math.max(300, resizeStartH + dy)
}

function onResizeEnd() {
  isResizing = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', onResizeEnd)
}

onUnmounted(() => {
  stopSessionPoll()
  setActiveViewing(null, null)
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', onResizeEnd)
})

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isSending.value) return

  const skillPackId = activeSkillId.value
  const skillName = activeSkill.value

  inputText.value = ''
  showSkillMenu.value = false
  activeSkill.value = null
  activeSkillId.value = null
  messages.value.push({ role: 'user', content: text })
  sending.value = true
  thinkingExpanded.value = false

  await nextTick()
  scrollToBottom()

  try {
    const payload = { message: text, timeout_seconds: timeoutSeconds.value, execution_mode: executionMode.value, skip_history: skipHistory.value }
    if (skillPackId) {
      payload.skill_pack_id = skillPackId
    }

    await sessionApi.chatAsync(sessionId.value, payload)
    currentSessionStatus.value = 'RUNNING'
    watchBackgroundSession(sessionId.value, agentId, agent.name)
    startSessionPollIfNeeded()
    await fetchSessions()
  } catch (e) {
    message.error(e.message)
  } finally {
    sending.value = false
  }
}

async function submitOtpHitl(msg) {
  const code = (msg.otpCode || '').trim()
  if (!code) {
    message.warning('请输入验证码')
    return
  }
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: 'current_user',
      comment: '',
      otp_code: code,
    })
    msg.approvalStatus = 'approved'
    message.success(res.message || '验证码已提交')
  } catch (e) {
    message.error('提交失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function approveHitl(msg) {
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: 'current_user',
      comment: '',
    })
    msg.approvalStatus = 'approved'
    if (res.kind === 'delivery') {
      msg.approvalFinalResult = res.final_result || ''
    } else if (res.kind === 'workflow') {
      msg.approvalFinalResult = res.final_result || ''
      if (res.execution_trace?.length) {
        msg.executionTrace = res.execution_trace
      }
      if (res.pending_approval_id) {
        msg.pendingApprovalId = res.pending_approval_id
        msg.approvalStatus = null
        msg.pendingWorkflow = true
        msg.content = res.final_result || msg.content
      }
    }
    message.success(res.message || '已批准')
  } catch (e) {
    message.error('审批失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function rejectHitl(msg) {
  msg.approving = true
  try {
    const res = await hitlApi.reject(sessionId.value, msg.pendingApprovalId, {
      approved: false,
      reviewer: 'current_user',
      comment: '用户拒绝',
    })
    msg.approvalStatus = 'rejected'
    message.success(res.message || '已拒绝')
  } catch (e) {
    message.error('审批失败: ' + e.message)
  } finally {
    msg.approving = false
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
.chat-hitl-actions {
  margin-top: 8px;
}
.hitl-som-preview {
  margin-bottom: 10px;
  border: 1px solid #ffd591;
  border-radius: 8px;
  padding: 8px;
  background: #fffbe6;
}
.hitl-preview-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  color: #595959;
}
.hitl-som-image {
  max-width: 100%;
  border-radius: 6px;
  border: 1px solid #f0f0f0;
}
.hitl-otp-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.chat-hitl-result {
  margin-top: 10px;
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
  cursor: pointer;
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
.chat-file-truncated-tag {
  margin-left: 6px;
  font-size: 10px;
  line-height: 18px;
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

.chat-trace {
  margin: 6px 0;
  font-size: 12px;
}
.chat-trace-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: #f0f5ff;
  border: 1px solid #adc6ff;
  border-radius: 6px;
}
.trace-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid #e8e4dc;
}
.trace-step:last-child { border-bottom: none; }
.trace-label { flex: 1; color: #333; }
.trace-duration { color: #999; font-size: 11px; }

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

/* ---- 文件预览弹窗 ---- */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.preview-modal {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  min-width: 400px;
  min-height: 300px;
}
.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #e8e4dc;
  background: #faf8f5;
  flex-shrink: 0;
}
.preview-title {
  font-size: 13px;
  font-weight: 500;
  color: #1a1714;
  display: flex;
  align-items: center;
}
.preview-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.preview-body {
  flex: 1;
  overflow: auto;
  padding: 0;
}
.preview-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
.preview-markdown {
  padding: 20px 24px;
  font-size: 13px;
  line-height: 1.7;
  color: #1a1714;
}
.preview-markdown :deep(p) {
  margin: 0 0 10px 0;
}
.preview-markdown :deep(h1) { font-size: 20px; margin: 16px 0 8px; }
.preview-markdown :deep(h2) { font-size: 17px; margin: 14px 0 6px; }
.preview-markdown :deep(h3) { font-size: 15px; margin: 12px 0 6px; }
.preview-markdown :deep(code) {
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.preview-markdown :deep(pre) {
  background: rgba(0, 0, 0, 0.05);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.preview-markdown :deep(pre code) {
  background: none;
  padding: 0;
}
.preview-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.preview-text {
  padding: 16px 20px;
  margin: 0;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1a1714;
  background: #faf8f5;
  min-height: 100%;
}
.preview-csv {
  padding: 0;
  overflow: auto;
}
.csv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.csv-table th,
.csv-table td {
  border: 1px solid #e8e4dc;
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap;
}
.csv-table th {
  background: #f5f2ed;
  font-weight: 600;
  color: #1a1714;
  position: sticky;
  top: 0;
  z-index: 1;
}
.csv-table tr:hover td {
  background: #fef9f0;
}
.preview-office {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
}
.preview-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
}
.preview-resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 20px;
  height: 20px;
  cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 50%, #d9d0c5 50%);
  border-radius: 0 0 12px 0;
}
.preview-resize-handle:hover {
  background: linear-gradient(135deg, transparent 50%, #b5afa8 50%);
}
</style>
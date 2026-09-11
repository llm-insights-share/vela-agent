<template>
  <div class="approval-center">
    <div class="page-header">
      <h2 class="page-title">审批中心</h2>
      <a-space>
        <a-select v-model:value="statusFilter" style="width: 120px" @change="onFilterChange">
          <a-select-option value="PENDING">待审批</a-select-option>
          <a-select-option value="APPROVED">已审批</a-select-option>
          <a-select-option value="REJECTED">已拒绝</a-select-option>
          <a-select-option value="ALL">全部</a-select-option>
        </a-select>
        <a-select v-model:value="categoryFilter" style="width: 140px" @change="onFilterChange">
          <a-select-option value="all">全部类型</a-select-option>
          <a-select-option value="hitl">通用 HITL</a-select-option>
          <a-select-option value="screenpilot">驭屏</a-select-option>
          <a-select-option value="delivery">多 Agent 交付</a-select-option>
          <a-select-option value="workflow">工作流</a-select-option>
          <a-select-option value="tool">工具审批</a-select-option>
        </a-select>
        <a-select
          v-if="categoryFilter === 'screenpilot'"
          v-model:value="tierFilter"
          style="width: 100px"
          allow-clear
          placeholder="风险"
          @change="onFilterChange"
        >
          <a-select-option value="T3">T3</a-select-option>
          <a-select-option value="T2">T2</a-select-option>
          <a-select-option value="T1">T1</a-select-option>
        </a-select>
        <a-button @click="loadList">刷新</a-button>
      </a-space>
    </div>

    <a-card>
      <a-table
        :columns="columns"
        :data-source="items"
        :loading="loading"
        row-key="approval_id"
        size="middle"
        :pagination="pagination"
        @change="onTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'category'">
            <a-tag :color="categoryColor(record.category)">{{ categoryLabel(record.category) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'risk_tier'">
            <a-tag v-if="record.risk_tier" :color="record.risk_tier === 'T3' ? 'red' : 'orange'">
              {{ record.risk_tier }}
            </a-tag>
            <span v-else>—</span>
          </template>
          <template v-else-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'created_at'">
            {{ formatDateTime(record.created_at) }}
          </template>
          <template v-else-if="column.key === 'summary'">
            <span class="summary-cell" :title="record.summary">{{ record.summary || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a @click="openDetail(record)">详情</a>
              <template v-if="record.status === 'PENDING'">
                <a @click="quickApprove(record)">通过</a>
                <a style="color: #b5341c" @click="openReject(record)">拒绝</a>
              </template>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-drawer
      v-model:open="drawerOpen"
      title="审批详情"
      width="640"
      destroy-on-close
    >
      <template v-if="selected">
        <a-descriptions :column="1" size="small" bordered>
          <a-descriptions-item label="类型">
            <a-tag :color="categoryColor(selected.category)">{{ categoryLabel(selected.category) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusColor(selected.status)">{{ statusLabel(selected.status) }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="Agent">{{ selected.agent_name || selected.agent_id }}</a-descriptions-item>
          <a-descriptions-item label="会话">
            {{ selected.session_title || selected.session_id }}
            <a
              v-if="selected.agent_id && selected.session_id"
              style="margin-left: 8px"
              @click="goSession"
            >打开会话</a>
          </a-descriptions-item>
          <a-descriptions-item label="工具/事项">{{ selected.tool_name }}</a-descriptions-item>
          <a-descriptions-item v-if="selected.risk_tier" label="风险等级">
            <a-tag :color="selected.risk_tier === 'T3' ? 'red' : 'orange'">{{ selected.risk_tier }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item v-if="selected.action" label="动作">{{ selected.action }}</a-descriptions-item>
          <a-descriptions-item v-if="selected.target_label" label="目标">{{ selected.target_label }}</a-descriptions-item>
          <a-descriptions-item v-if="selected.url" label="URL">{{ selected.url }}</a-descriptions-item>
          <a-descriptions-item label="创建时间">{{ formatDateTime(selected.created_at) }}</a-descriptions-item>
        </a-descriptions>

        <div v-if="previewImage" class="som-preview">
          <img :src="previewImage" alt="预览" />
        </div>

        <a-alert
          v-if="isSkillParamsApproval(selected)"
          type="info"
          show-icon
          style="margin-top: 16px"
          message="技能缺参请在 Agent 会话中填写"
          description="此类工单应在对话页补全参数并继续，不在审批中心批准。可拒绝本单后回到会话处理。"
        />

        <div v-if="deliveryPreview" class="delivery-preview">
          <div class="delivery-preview-title">交付内容预览</div>
          <pre>{{ deliveryPreview }}</pre>
        </div>

        <div v-else-if="toolArgsPreview && selected.category !== 'screenpilot'" class="delivery-preview">
          <div class="delivery-preview-title">参数</div>
          <pre>{{ toolArgsPreview }}</pre>
        </div>

        <template v-if="selected.status === 'PENDING'">
          <a-divider />
          <a-form layout="vertical">
            <a-form-item
              v-if="isOtpApproval(selected)"
              label="验证码"
              required
            >
              <a-input v-model:value="otpCode" placeholder="请输入短信/邮箱验证码" allow-clear />
            </a-form-item>
            <a-space>
              <a-button
                type="primary"
                :loading="acting"
                :disabled="isSkillParamsApproval(selected)"
                @click="doApprove"
              >通过</a-button>
              <a-button danger :loading="acting" @click="openReject(selected)">拒绝</a-button>
            </a-space>
          </a-form>
        </template>
        <template v-else>
          <a-divider />
          <p>审批人：{{ selected.reviewer || '—' }}</p>
          <p>备注：{{ selected.review_comment || '—' }}</p>
          <p>审批时间：{{ formatDateTime(selected.reviewed_at) || '—' }}</p>
        </template>
      </template>
    </a-drawer>

    <a-modal
      v-model:open="rejectOpen"
      title="拒绝审批"
      ok-text="确认拒绝"
      ok-type="danger"
      :confirm-loading="acting"
      destroy-on-close
      @ok="doReject"
    >
      <a-form layout="vertical">
        <a-form-item label="拒绝理由" required>
          <a-textarea
            v-model:value="rejectReason"
            :rows="4"
            placeholder="请填写拒绝理由"
            :maxlength="2048"
            show-count
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { hitlApi, screenpilotApi } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { formatDateTime } from '../../utils/datetime'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const acting = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const statusFilter = ref('PENDING')
const categoryFilter = ref('all')
const tierFilter = ref(undefined)

const drawerOpen = ref(false)
const selected = ref(null)
const otpCode = ref('')

const rejectOpen = ref(false)
const rejectTarget = ref(null)
const rejectReason = ref('')

const columns = [
  { title: '类型', key: 'category', width: 110 },
  { title: 'Agent', dataIndex: 'agent_name', key: 'agent_name', width: 140, ellipsis: true },
  { title: '会话', dataIndex: 'session_title', key: 'session_title', width: 140, ellipsis: true },
  { title: '事项摘要', key: 'summary', ellipsis: true },
  { title: '风险', key: 'risk_tier', width: 70 },
  { title: '状态', key: 'status', width: 90 },
  { title: '创建时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'action', width: 160 },
]

const pagination = computed(() => ({
  current: page.value,
  pageSize: pageSize.value,
  total: total.value,
  showSizeChanger: true,
  showTotal: (t) => `共 ${t} 条`,
}))

const previewImage = computed(() => {
  const p = selected.value?.preview_payload
  if (!p) return ''
  const b64 = p.som_image_b64 || p.screenshot_b64
  return b64 ? `data:image/png;base64,${b64}` : ''
})

const deliveryPreview = computed(() => {
  if (!selected.value || selected.value.category !== 'delivery') return ''
  const fr = selected.value.tool_args?.final_result || ''
  return String(fr).slice(0, 4000)
})

const toolArgsPreview = computed(() => {
  const args = selected.value?.tool_args
  if (!args || !Object.keys(args).length) return ''
  try {
    return JSON.stringify(args, null, 2).slice(0, 4000)
  } catch {
    return String(args)
  }
})

function categoryLabel(c) {
  return {
    screenpilot: '驭屏',
    delivery: '交付',
    workflow: '工作流',
    tool: '工具',
  }[c] || c
}

function categoryColor(c) {
  return {
    screenpilot: 'purple',
    delivery: 'blue',
    workflow: 'cyan',
    tool: 'default',
  }[c] || 'default'
}

function statusLabel(s) {
  return { PENDING: '待审批', APPROVED: '已审批', REJECTED: '已拒绝' }[s] || s
}

function statusColor(s) {
  return { PENDING: 'gold', APPROVED: 'green', REJECTED: 'red' }[s] || 'default'
}

function isOtpApproval(record) {
  if (!record || record.category !== 'screenpilot') return false
  return (
    record.tool_name === 'cu_login_otp' ||
    record.flow_kind === 'otp_wait' ||
    record.preview_payload?.flow_kind === 'otp_wait'
  )
}

function isSkillParamsApproval(record) {
  if (!record || record.category !== 'screenpilot') return false
  return (
    record.tool_name === 'cu_skill_params' ||
    record.flow_kind === 'skill_params' ||
    record.preview_payload?.flow_kind === 'skill_params'
  )
}

function reviewerName() {
  return auth.user?.display_name || auth.user?.username || 'current_user'
}

async function loadList() {
  loading.value = true
  try {
    const params = {
      status: statusFilter.value,
      category: categoryFilter.value,
      page: page.value,
      page_size: pageSize.value,
    }
    if (categoryFilter.value === 'screenpilot' && tierFilter.value) {
      params.risk_tier = tierFilter.value
    }
    const res = await hitlApi.list(params)
    items.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  if (categoryFilter.value !== 'screenpilot') {
    tierFilter.value = undefined
  }
  loadList()
}

function onTableChange(pag) {
  page.value = pag.current
  pageSize.value = pag.pageSize
  loadList()
}

async function openDetail(record) {
  try {
    selected.value = await hitlApi.get(record.approval_id)
    otpCode.value = ''
    drawerOpen.value = true
  } catch (e) {
    message.error(e.message || '加载详情失败')
  }
}

function goSession() {
  if (!selected.value?.agent_id || !selected.value?.session_id) return
  router.push(`/agents/${selected.value.agent_id}/chat?session_id=${selected.value.session_id}`)
}

async function quickApprove(record) {
  selected.value = record
  await doApprove()
}

async function doApprove() {
  const rec = selected.value
  if (!rec) return
  if (isSkillParamsApproval(rec)) {
    message.warning('技能缺参请在 Agent 会话页填写，勿在此批准')
    return
  }
  if (isOtpApproval(rec) && !otpCode.value.trim()) {
    message.warning('请输入验证码后再批准')
    drawerOpen.value = true
    return
  }
  acting.value = true
  try {
    if (rec.category === 'screenpilot') {
      await screenpilotApi.approveApproval(rec.approval_id, {
        reviewer: reviewerName(),
        comment: '',
        otp_code: otpCode.value.trim() || undefined,
      })
    } else {
      await hitlApi.approve(rec.session_id, rec.approval_id, {
        approved: true,
        reviewer: reviewerName(),
        comment: '',
      })
    }
    message.success(isOtpApproval(rec) ? '验证码已提交' : '已批准')
    drawerOpen.value = false
    await loadList()
  } catch (e) {
    message.error(e.message || '批准失败')
  } finally {
    acting.value = false
  }
}

function openReject(record) {
  rejectTarget.value = record
  rejectReason.value = ''
  rejectOpen.value = true
}

async function doReject() {
  const reason = (rejectReason.value || '').trim()
  if (!reason) {
    message.warning('请填写拒绝理由')
    return Promise.reject()
  }
  const rec = rejectTarget.value
  if (!rec) return
  acting.value = true
  try {
    if (rec.category === 'screenpilot') {
      await screenpilotApi.rejectApproval(rec.approval_id, {
        reviewer: reviewerName(),
        comment: reason,
      })
    } else {
      await hitlApi.reject(rec.session_id, rec.approval_id, {
        approved: false,
        reviewer: reviewerName(),
        comment: reason,
      })
    }
    message.success('已拒绝')
    rejectOpen.value = false
    drawerOpen.value = false
    await loadList()
  } catch (e) {
    message.error(e.message || '拒绝失败')
    return Promise.reject(e)
  } finally {
    acting.value = false
  }
}

function applyRouteQuery() {
  const cat = route.query.category
  if (typeof cat === 'string' && cat) {
    categoryFilter.value = cat
  }
  const st = route.query.status
  if (typeof st === 'string' && st) {
    statusFilter.value = st
  }
}

watch(
  () => route.query,
  () => {
    applyRouteQuery()
    loadList()
  },
)

onMounted(() => {
  applyRouteQuery()
  loadList()
})
</script>

<style scoped>
.approval-center {
  padding: 0 4px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #1a1714;
}
.summary-cell {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.som-preview {
  margin-top: 16px;
  border: 1px solid #eee;
  border-radius: 8px;
  overflow: hidden;
  background: #fafafa;
}
.som-preview img {
  display: block;
  max-width: 100%;
}
.delivery-preview {
  margin-top: 16px;
}
.delivery-preview-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.delivery-preview pre {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  background: #f7f5f1;
  border-radius: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

<template>
  <div class="approval-page">
    <div class="page-header">
      <h2>驭屏审批收件箱</h2>
      <a-space>
        <a-select v-model:value="statusFilter" style="width: 120px;" @change="loadApprovals">
          <a-select-option value="PENDING">待审批</a-select-option>
          <a-select-option value="APPROVED">已通过</a-select-option>
          <a-select-option value="REJECTED">已拒绝</a-select-option>
        </a-select>
        <a-select v-model:value="tierFilter" style="width: 100px;" allowClear placeholder="风险" @change="loadApprovals">
          <a-select-option value="T3">T3</a-select-option>
          <a-select-option value="T2">T2</a-select-option>
        </a-select>
        <a-button @click="loadApprovals">刷新</a-button>
      </a-space>
    </div>

    <a-table
      :dataSource="items"
      :columns="columns"
      rowKey="approval_id"
      :loading="loading"
      size="middle"
      :customRow="customRow"
    />

    <a-drawer v-model:open="drawerOpen" title="审批详情" width="560">
      <template v-if="selected">
        <a-descriptions :column="1" size="small" bordered>
          <a-descriptions-item label="风险等级">
            <a-tag :color="selected.risk_tier === 'T3' ? 'red' : 'orange'">{{ selected.risk_tier }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="动作">{{ selected.action || selected.tool_name }}</a-descriptions-item>
          <a-descriptions-item label="目标">{{ selected.target_label || '—' }}</a-descriptions-item>
          <a-descriptions-item label="URL">{{ selected.url || '—' }}</a-descriptions-item>
          <a-descriptions-item label="会话">{{ selected.session_id }}</a-descriptions-item>
        </a-descriptions>

        <div
          v-if="previewImage"
          class="som-preview"
        >
          <img :src="previewImage" alt="SoM 预览" />
        </div>

        <template v-if="selected.status === 'PENDING'">
          <a-divider />
          <a-form layout="vertical">
            <a-form-item label="审批人">
              <a-input v-model:value="reviewer" placeholder="您的姓名" />
            </a-form-item>
            <a-form-item label="备注">
              <a-textarea v-model:value="comment" :rows="3" placeholder="审批意见（可选）" />
            </a-form-item>
            <a-space>
              <a-button type="primary" :loading="acting" @click="doApprove">批准</a-button>
              <a-button danger :loading="acting" @click="doReject">拒绝</a-button>
            </a-space>
          </a-form>
        </template>
        <template v-else>
          <a-divider />
          <p>审批人：{{ selected.reviewer || '—' }}</p>
          <p>备注：{{ selected.review_comment || '—' }}</p>
        </template>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const loading = ref(false)
const acting = ref(false)
const items = ref([])
const statusFilter = ref('PENDING')
const tierFilter = ref(undefined)
const drawerOpen = ref(false)
const selected = ref(null)
const reviewer = ref('')
const comment = ref('')

const columns = [
  { title: '风险', dataIndex: 'risk_tier', key: 'risk_tier', width: 70 },
  { title: '动作', dataIndex: 'action', key: 'action', width: 90 },
  { title: '目标', dataIndex: 'target_label', key: 'target_label', ellipsis: true },
  { title: '工具', dataIndex: 'tool_name', key: 'tool_name', width: 120 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
]

const previewImage = computed(() => {
  const p = selected.value?.preview_payload
  if (!p) return ''
  const b64 = p.som_image_b64 || p.screenshot_b64
  return b64 ? `data:image/png;base64,${b64}` : ''
})

function customRow(record) {
  return {
    onClick: () => openDetail(record),
    style: { cursor: 'pointer' },
  }
}

async function loadApprovals() {
  loading.value = true
  try {
    const params = { status: statusFilter.value, limit: 50 }
    if (tierFilter.value) params.risk_tier = tierFilter.value
    items.value = await screenpilotApi.listApprovals(params)
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openDetail(record) {
  selected.value = record
  reviewer.value = ''
  comment.value = ''
  drawerOpen.value = true
}

async function doApprove() {
  if (!selected.value) return
  acting.value = true
  try {
    await screenpilotApi.approveApproval(selected.value.approval_id, {
      reviewer: reviewer.value,
      comment: comment.value,
    })
    message.success('已批准')
    drawerOpen.value = false
    await loadApprovals()
  } catch (e) {
    message.error(e.message)
  } finally {
    acting.value = false
  }
}

async function doReject() {
  if (!selected.value) return
  acting.value = true
  try {
    await screenpilotApi.rejectApproval(selected.value.approval_id, {
      reviewer: reviewer.value,
      comment: comment.value,
    })
    message.success('已拒绝')
    drawerOpen.value = false
    await loadApprovals()
  } catch (e) {
    message.error(e.message)
  } finally {
    acting.value = false
  }
}

onMounted(loadApprovals)
</script>

<style scoped>
.approval-page { padding: 0 4px; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; }
.som-preview {
  margin-top: 16px;
  border: 1px solid #eee;
  border-radius: 6px;
  overflow: hidden;
}
.som-preview img {
  width: 100%;
  display: block;
}
</style>

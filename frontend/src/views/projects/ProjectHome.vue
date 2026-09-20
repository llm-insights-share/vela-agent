<template>
  <div class="project-home">
    <div class="page-header">
      <div class="header-left">
        <a-button type="text" @click="$router.push('/projects')">
          <ArrowLeftOutlined />
        </a-button>
        <div>
          <h2 class="page-title">
            {{ project.name || '项目' }}
            <a-tag v-if="project.status === 'ARCHIVED'" color="default">已归档</a-tag>
          </h2>
          <div class="subtitle">{{ project.description || '暂无描述' }}</div>
        </div>
      </div>
      <a-space>
        <a-button @click="toggleStar">
          <StarFilled v-if="project.starred" style="color:#faad14" />
          <StarOutlined v-else />
          {{ project.starred ? '已收藏' : '收藏' }}
        </a-button>
        <a-button type="primary" :disabled="project.status === 'ARCHIVED'" @click="openNewChat">
          <PlusOutlined /> 新对话
        </a-button>
        <a-dropdown v-if="canEdit">
          <a-button>
            更多 <DownOutlined />
          </a-button>
          <template #overlay>
            <a-menu @click="onMoreMenu">
              <a-menu-item key="archive" v-if="isOwner && project.status !== 'ARCHIVED'">归档</a-menu-item>
              <a-menu-item key="unarchive" v-if="isOwner && project.status === 'ARCHIVED'">取消归档</a-menu-item>
              <a-menu-item key="delete" danger v-if="isOwner">删除项目</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
      </a-space>
    </div>

    <a-row :gutter="16">
      <a-col :xs="24" :lg="14">
        <a-card title="会话" style="margin-bottom: 16px">
          <a-spin :spinning="loadingSessions">
            <div v-if="sessions.length" class="session-list">
              <div
                v-for="s in sessions"
                :key="s.session_id"
                class="session-row"
                @click="openSession(s)"
              >
                <div class="session-title">{{ s.title || '新对话' }}</div>
                <div class="session-meta">
                  <a-tag size="small">{{ s.agent_name || s.agent_id?.slice(0, 8) }}</a-tag>
                  <span>{{ s.caller_display_name || '' }}</span>
                  <span>{{ formatTime(s.last_active_at || s.created_at) }}</span>
                  <a-tag v-if="s.can_write === false" color="default">只读</a-tag>
                </div>
              </div>
            </div>
            <a-empty v-else description="还没有会话，点击「新对话」开始" />
          </a-spin>
        </a-card>
      </a-col>

      <a-col :xs="24" :lg="10">
        <a-card title="项目指令" style="margin-bottom: 16px">
          <a-textarea
            v-model:value="instructionsDraft"
            :rows="6"
            :disabled="!canEdit || project.status === 'ARCHIVED'"
            placeholder="例如：你是产品经理助手，用简洁中文回复，输出需带依据…"
          />
          <div style="margin-top: 8px; text-align: right" v-if="canEdit">
            <a-button
              type="primary"
              size="small"
              :loading="savingInstructions"
              :disabled="project.status === 'ARCHIVED'"
              @click="saveInstructions"
            >
              保存指令
            </a-button>
          </div>
        </a-card>

        <a-card title="项目知识">
          <template #extra>
            <a-upload
              v-if="canEdit && project.status !== 'ARCHIVED'"
              :show-upload-list="false"
              :before-upload="beforeUpload"
              :custom-request="doUpload"
            >
              <a-button size="small" :loading="uploading">
                <UploadOutlined /> 上传
              </a-button>
            </a-upload>
          </template>
          <a-spin :spinning="loadingFiles">
            <div v-if="files.length" class="file-list">
              <div v-for="f in files" :key="f.doc_id" class="file-row">
                <FileOutlined />
                <span class="file-name">{{ f.filename }}</span>
                <span class="file-meta">{{ f.chunk_count || 0 }} 块</span>
                <a-popconfirm
                  v-if="canEdit"
                  title="删除该文件？"
                  @confirm="removeFile(f.doc_id)"
                >
                  <a style="color:#b5341c">删除</a>
                </a-popconfirm>
              </div>
            </div>
            <a-empty v-else description="上传文档供项目内所有会话引用" />
          </a-spin>
        </a-card>

        <a-card title="成员" style="margin-top: 16px">
          <template #extra>
            <a-button v-if="canEdit" size="small" @click="inviteOpen = true">邀请</a-button>
          </template>
          <div v-for="m in members" :key="m.user_id" class="member-row">
            <div>
              <strong>{{ m.display_name || m.username }}</strong>
              <span class="muted"> @{{ m.username }}</span>
            </div>
            <a-space>
              <a-tag>{{ roleLabel(m.role) }}</a-tag>
              <a-popconfirm
                v-if="canEdit && m.role !== 'owner'"
                title="移除该成员？"
                @confirm="removeMember(m.user_id)"
              >
                <a style="color:#b5341c">移除</a>
              </a-popconfirm>
            </a-space>
          </div>
        </a-card>
      </a-col>
    </a-row>

    <a-modal
      v-model:open="agentPickOpen"
      title="选择智能体开始对话"
      @ok="confirmNewChat"
      :confirm-loading="startingChat"
    >
      <a-select
        v-model:value="pickedAgentId"
        style="width: 100%"
        placeholder="选择 Agent"
        show-search
        :options="agentOptions"
        :filter-option="filterAgent"
      />
    </a-modal>

    <a-modal
      v-model:open="inviteOpen"
      title="邀请成员"
      @ok="inviteMember"
      :confirm-loading="inviting"
    >
      <a-form layout="vertical">
        <a-form-item label="用户名">
          <a-auto-complete
            v-model:value="inviteUsername"
            :options="userSuggestions"
            placeholder="输入用户名搜索"
            @search="searchUsers"
          />
        </a-form-item>
        <a-form-item label="角色">
          <a-select v-model:value="inviteRole" :options="roleOptions" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  PlusOutlined,
  StarOutlined,
  StarFilled,
  DownOutlined,
  UploadOutlined,
  FileOutlined,
} from '@ant-design/icons-vue'
import { projectApi, agentApi, userApi } from '../../api'
import { formatRelativeTime } from '../../utils/datetime'

const route = useRoute()
const router = useRouter()
const projectId = route.params.id

const project = ref({})
const sessions = ref([])
const files = ref([])
const members = ref([])
const instructionsDraft = ref('')
const loadingSessions = ref(false)
const loadingFiles = ref(false)
const savingInstructions = ref(false)
const uploading = ref(false)
const agentPickOpen = ref(false)
const pickedAgentId = ref(undefined)
const agentOptions = ref([])
const startingChat = ref(false)
const inviteOpen = ref(false)
const inviteUsername = ref('')
const inviteRole = ref('viewer')
const inviting = ref(false)
const userSuggestions = ref([])

const roleOptions = [
  { value: 'viewer', label: '可查看' },
  { value: 'editor', label: '可编辑' },
  { value: 'owner', label: '所有者' },
]

const canEdit = computed(() => ['owner', 'editor'].includes(project.value.my_role))
const isOwner = computed(() => project.value.my_role === 'owner')

function roleLabel(role) {
  return { owner: '所有者', editor: '可编辑', viewer: '可查看' }[role] || role
}

function formatTime(t) {
  return formatRelativeTime(t, '')
}

async function loadProject() {
  project.value = await projectApi.get(projectId)
  instructionsDraft.value = project.value.instructions || ''
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const res = await projectApi.listSessions(projectId, { page_size: 50 })
    sessions.value = (res.items || []).filter(
      (s) => (s.messages || []).length > 0 || s.status === 'RUNNING' || !s.messages
    )
  } finally {
    loadingSessions.value = false
  }
}

async function loadFiles() {
  loadingFiles.value = true
  try {
    const res = await projectApi.listFiles(projectId)
    files.value = res.files || []
  } finally {
    loadingFiles.value = false
  }
}

async function loadMembers() {
  members.value = await projectApi.listMembers(projectId)
}

async function toggleStar() {
  try {
    if (project.value.starred) {
      await projectApi.unstar(projectId)
      project.value.starred = false
    } else {
      await projectApi.star(projectId)
      project.value.starred = true
    }
  } catch (e) {
    message.error(e.message)
  }
}

async function saveInstructions() {
  savingInstructions.value = true
  try {
    project.value = await projectApi.update(projectId, {
      instructions: instructionsDraft.value,
    })
    message.success('指令已保存')
  } catch (e) {
    message.error(e.message)
  } finally {
    savingInstructions.value = false
  }
}

function beforeUpload(file) {
  return true
}

async function doUpload({ file, onSuccess, onError }) {
  uploading.value = true
  try {
    await projectApi.uploadFile(projectId, file, file.name)
    message.success(`已上传 ${file.name}`)
    await loadFiles()
    onSuccess?.()
  } catch (e) {
    message.error(e.message)
    onError?.(e)
  } finally {
    uploading.value = false
  }
}

async function removeFile(docId) {
  try {
    await projectApi.deleteFile(projectId, docId)
    message.success('已删除')
    await loadFiles()
  } catch (e) {
    message.error(e.message)
  }
}

async function openNewChat() {
  try {
    const res = await agentApi.list({ page_size: 100 })
    const items = (res.items || []).filter((a) => a.status !== 'DELETED')
    agentOptions.value = items.map((a) => ({
      value: a.agent_id,
      label: a.name,
    }))
    pickedAgentId.value =
      project.value.last_agent_id ||
      (agentOptions.value[0] && agentOptions.value[0].value) ||
      undefined
    agentPickOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

function filterAgent(input, option) {
  return (option.label || '').toLowerCase().includes((input || '').toLowerCase())
}

async function confirmNewChat() {
  if (!pickedAgentId.value) {
    message.warning('请选择智能体')
    return
  }
  startingChat.value = true
  try {
    await projectApi.update(projectId, { last_agent_id: pickedAgentId.value })
    agentPickOpen.value = false
    router.push({
      path: `/projects/${projectId}/chat`,
      query: { agent_id: pickedAgentId.value },
    })
  } catch (e) {
    message.error(e.message)
  } finally {
    startingChat.value = false
  }
}

function openSession(s) {
  router.push({
    path: `/projects/${projectId}/chat`,
    query: {
      agent_id: s.agent_id,
      session_id: s.session_id,
    },
  })
}

async function onMoreMenu({ key }) {
  if (key === 'archive') {
    try {
      project.value = await projectApi.update(projectId, { status: 'ARCHIVED' })
      message.success('已归档')
    } catch (e) {
      message.error(e.message)
    }
  } else if (key === 'unarchive') {
    try {
      project.value = await projectApi.update(projectId, { status: 'ACTIVE' })
      message.success('已恢复')
    } catch (e) {
      message.error(e.message)
    }
  } else if (key === 'delete') {
    Modal.confirm({
      title: '删除项目？',
      content: '会话记录会保留但脱离本项目；项目知识将归档。',
      okType: 'danger',
      onOk: async () => {
        await projectApi.remove(projectId)
        message.success('已删除')
        router.push('/projects')
      },
    })
  }
}

async function searchUsers(q) {
  if (!q || q.length < 1) {
    userSuggestions.value = []
    return
  }
  try {
    const hits = await userApi.search(q)
    userSuggestions.value = (hits || []).map((u) => ({
      value: u.username,
      label: `${u.display_name || u.username} (@${u.username})`,
    }))
  } catch (_) {
    userSuggestions.value = []
  }
}

async function inviteMember() {
  if (!inviteUsername.value.trim()) {
    message.warning('请输入用户名')
    return
  }
  inviting.value = true
  try {
    await projectApi.addMember(projectId, {
      username: inviteUsername.value.trim(),
      role: inviteRole.value,
    })
    message.success('已添加成员')
    inviteOpen.value = false
    inviteUsername.value = ''
    await loadMembers()
  } catch (e) {
    message.error(e.message)
  } finally {
    inviting.value = false
  }
}

async function removeMember(userId) {
  try {
    await projectApi.removeMember(projectId, userId)
    message.success('已移除')
    await loadMembers()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  try {
    await loadProject()
    await Promise.all([loadSessions(), loadFiles(), loadMembers()])
  } catch (e) {
    message.error(e.message)
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  gap: 12px;
}
.header-left {
  display: flex;
  gap: 4px;
  align-items: flex-start;
}
.page-title {
  margin: 0;
  font-size: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.subtitle {
  color: #8c8580;
  font-size: 13px;
  margin-top: 4px;
}
.session-row,
.file-row,
.member-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f0ebe6;
  gap: 8px;
}
.session-row {
  cursor: pointer;
  flex-direction: column;
  align-items: flex-start;
}
.session-row:hover {
  background: #faf8f6;
}
.session-title {
  font-weight: 500;
}
.session-meta {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: #8c8580;
  align-items: center;
  flex-wrap: wrap;
}
.file-name {
  flex: 1;
  margin-left: 6px;
}
.file-meta {
  color: #8c8580;
  font-size: 12px;
  margin-right: 8px;
}
.muted {
  color: #8c8580;
  font-size: 12px;
}
</style>

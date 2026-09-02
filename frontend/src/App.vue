<template>
  <router-view v-if="isAuthPage" />
  <a-layout v-else style="min-height: 100vh">
    <a-layout-sider v-model:collapsed="collapsed" collapsible theme="dark" width="220">
      <div class="logo">
        <div class="logo-dot"></div>
        <span v-if="!collapsed" class="logo-text">Vela · 织帆</span>
      </div>
      <a-menu
        v-model:selectedKeys="selectedKeys"
        theme="dark"
        mode="inline"
        @click="onMenuClick"
      >
        <a-menu-item key="/">
          <DashboardOutlined />
          <span>仪表盘</span>
        </a-menu-item>
        <a-sub-menu key="agents">
          <template #icon><RobotOutlined /></template>
          <template #title>Agent 管理</template>
          <a-menu-item key="/agents">Agent 列表</a-menu-item>
          <a-menu-item key="/agents/create">创建 Agent</a-menu-item>
          <a-menu-item key="/schedules">定时任务</a-menu-item>
          <a-menu-item key="/monitor">监控</a-menu-item>
          <a-menu-item key="/eval">评测</a-menu-item>
        </a-sub-menu>
        <a-sub-menu key="models">
          <template #icon><ApiOutlined /></template>
          <template #title>模型服务</template>
          <a-menu-item key="/providers">供应商管理</a-menu-item>
          <a-menu-item key="/services">模型服务</a-menu-item>
        </a-sub-menu>
        <a-menu-item key="/skills">
          <ThunderboltOutlined />
          <span>Skill 包</span>
        </a-menu-item>
        <a-menu-item key="/knowledge">
          <BookOutlined />
          <span>知识库</span>
        </a-menu-item>
        <a-menu-item key="/memory">
          <BulbOutlined />
          <span>记忆管理</span>
        </a-menu-item>
        <a-menu-item key="/data-access">
          <DatabaseOutlined />
          <span>数据访问</span>
        </a-menu-item>
        <a-menu-item key="/tools">
          <ToolOutlined />
          <span>工具</span>
        </a-menu-item>
        <a-menu-item key="/connectors">
          <ApiOutlined />
          <span>连接器</span>
        </a-menu-item>
        <a-sub-menu key="screenpilot">
          <template #icon><DesktopOutlined /></template>
          <template #title>驭屏系统</template>
          <a-menu-item key="/screenpilot/systems">驭屏系统管理</a-menu-item>
          <a-menu-item key="/screenpilot/skills">UI 技能库</a-menu-item>
          <a-menu-item key="/screenpilot/approvals">驭屏审批收件箱</a-menu-item>
        </a-sub-menu>
        <a-menu-item v-if="auth.isAdmin" key="/users">
          <TeamOutlined />
          <span>用户管理</span>
        </a-menu-item>
        <a-menu-item key="/settings">
          <SettingOutlined />
          <span>系统配置</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout>
      <a-layout-header class="header">
        <span class="header-title">Agent Playground</span>
        <div class="header-user">
          <a-popover
            v-model:open="inboxOpen"
            trigger="click"
            placement="bottomRight"
            overlay-class-name="inbox-popover"
          >
            <template #content>
              <div class="inbox-panel">
                <div class="inbox-panel-title">站内消息</div>
                <a-spin :spinning="inboxLoading">
                  <div v-if="!inboxItems.length" class="inbox-empty">暂无消息</div>
                  <div
                    v-for="msg in inboxItems"
                    :key="msg.message_id"
                    class="inbox-item"
                    :class="{ unread: !msg.is_read }"
                    @click="onInboxItemClick(msg)"
                  >
                    <div class="inbox-item-title">{{ msg.title }}</div>
                    <div class="inbox-item-body">{{ msg.body }}</div>
                    <div class="inbox-item-time">{{ formatDateTimeShort(msg.created_at) }}</div>
                  </div>
                </a-spin>
              </div>
            </template>
            <a-badge :count="inboxUnread" :overflow-count="99" color="#b5341c">
              <BellOutlined class="inbox-bell" />
            </a-badge>
          </a-popover>
          <a-dropdown>
            <a class="user-trigger" @click.prevent>
              <a-avatar :size="28" :src="auth.user?.avatar_url || undefined">
                <template #icon><UserOutlined /></template>
              </a-avatar>
              <span class="user-name">{{ auth.user?.display_name || auth.user?.username || '' }}</span>
            </a>
            <template #overlay>
              <a-menu @click="onUserMenuClick">
                <a-menu-item key="settings">用户设置</a-menu-item>
                <a-menu-item key="logout">退出登录</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup>
import { ref, watch, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  DashboardOutlined,
  RobotOutlined,
  ApiOutlined,
  ThunderboltOutlined,
  BookOutlined,
  DatabaseOutlined,
  ToolOutlined,
  SettingOutlined,
  BulbOutlined,
  DesktopOutlined,
  TeamOutlined,
  UserOutlined,
  BellOutlined,
} from '@ant-design/icons-vue'
import {
  startBackgroundSessionWatcher,
  stopBackgroundSessionWatcher,
} from './composables/useBackgroundSessions'
import { useAuthStore } from './stores/auth'
import { inboxApi } from './api'
import { formatDateTimeShort } from './utils/datetime'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const collapsed = ref(false)
const selectedKeys = ref(['/'])
const inboxUnread = ref(0)
const inboxItems = ref([])
const inboxOpen = ref(false)
const inboxLoading = ref(false)
let inboxTimer = null

const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')

async function fetchInboxUnread() {
  try {
    const res = await inboxApi.unreadCount()
    inboxUnread.value = res.unread_count || 0
  } catch (e) {
    console.error('[inbox] unread-count failed:', e)
  }
}

async function fetchInboxList() {
  inboxLoading.value = true
  try {
    const res = await inboxApi.list({ limit: 20 })
    inboxItems.value = res.items || []
  } catch (e) {
    console.error('[inbox] list failed:', e)
  } finally {
    inboxLoading.value = false
  }
}

function startInboxWatcher() {
  if (inboxTimer) return
  fetchInboxUnread()
  inboxTimer = setInterval(fetchInboxUnread, 8000)
}

function stopInboxWatcher() {
  if (inboxTimer) {
    clearInterval(inboxTimer)
    inboxTimer = null
  }
}

async function onInboxItemClick(msg) {
  try {
    if (!msg.is_read) {
      await inboxApi.markRead(msg.message_id)
      msg.is_read = true
      inboxUnread.value = Math.max(0, inboxUnread.value - 1)
    }
    inboxOpen.value = false
    if (msg.link_path) {
      router.push(msg.link_path)
    }
  } catch (e) {
    console.error('[inbox] mark-read failed:', e)
  }
}

onMounted(() => {
  if (!isAuthPage.value) {
    startBackgroundSessionWatcher()
    startInboxWatcher()
  }
})

onUnmounted(() => {
  stopBackgroundSessionWatcher()
  stopInboxWatcher()
})

watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/eval')) {
      selectedKeys.value = ['/eval']
    } else if (path.startsWith('/monitor')) {
      selectedKeys.value = ['/monitor']
    } else {
      selectedKeys.value = [path]
    }
    if (path === '/login' || path === '/register') {
      stopBackgroundSessionWatcher()
      stopInboxWatcher()
    } else {
      startBackgroundSessionWatcher()
      startInboxWatcher()
    }
  },
  { immediate: true }
)

watch(inboxOpen, (open) => {
  if (open) {
    fetchInboxList()
  }
})

function onMenuClick({ key }) {
  router.push(key)
}

function onUserMenuClick({ key }) {
  if (key === 'settings') {
    router.push('/me/settings')
  } else if (key === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.logo-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #c2410c;
  flex-shrink: 0;
}
.logo-text {
  font-family: 'Noto Serif SC', serif;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
}
.header {
  background: #3a342e;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.header-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em;
}
.header-user {
  display: flex;
  align-items: center;
  gap: 16px;
}
.inbox-bell {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.85);
  cursor: pointer;
  padding: 4px;
}
.inbox-panel {
  width: 320px;
  max-height: 420px;
  overflow-y: auto;
}
.inbox-panel-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
  margin-bottom: 8px;
}
.inbox-empty {
  color: #8a8178;
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.inbox-item {
  padding: 8px 4px;
  border-radius: 6px;
  cursor: pointer;
}
.inbox-item:hover {
  background: #f3f0e8;
}
.inbox-item.unread .inbox-item-title {
  font-weight: 700;
}
.inbox-item-title {
  font-size: 13px;
  color: #1a1714;
}
.inbox-item-body {
  font-size: 12px;
  color: #5c564e;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inbox-item-time {
  font-size: 11px;
  color: #8a8178;
  margin-top: 2px;
}
.user-trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: rgba(255, 255, 255, 0.85);
}
.user-name {
  font-size: 13px;
}
.content {
  padding: 24px;
  background: #faf8f4;
  min-height: calc(100vh - 64px);
}
</style>

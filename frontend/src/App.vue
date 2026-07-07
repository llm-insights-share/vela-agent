<template>
  <a-layout style="min-height: 100vh">
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
        <a-menu-item key="/settings">
          <SettingOutlined />
          <span>系统配置</span>
        </a-menu-item>
        <a-menu-item key="/data-access">
          <DatabaseOutlined />
          <span>数据访问</span>
        </a-menu-item>
        <a-menu-item key="/tools">
          <ToolOutlined />
          <span>工具</span>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>
    <a-layout>
      <a-layout-header class="header">
        <span class="header-title">Agent Playground</span>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup>
import { ref, watch } from 'vue'
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
} from '@ant-design/icons-vue'

const router = useRouter()
const route = useRoute()
const collapsed = ref(false)
const selectedKeys = ref(['/'])

watch(
  () => route.path,
  (path) => {
    selectedKeys.value = [path]
  },
  { immediate: true }
)

function onMenuClick({ key }) {
  router.push(key)
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
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.header-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em;
}
.content {
  padding: 24px;
  background: #faf8f4;
  min-height: calc(100vh - 64px);
}
</style>
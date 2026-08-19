import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/auth/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/auth/Register.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/agents',
    name: 'AgentList',
    component: () => import('../views/agents/AgentList.vue'),
  },
  {
    path: '/agents/create',
    name: 'AgentCreate',
    component: () => import('../views/agents/AgentCreate.vue'),
  },
  {
    path: '/agents/:id',
    name: 'AgentDetail',
    component: () => import('../views/agents/AgentDetail.vue'),
  },
  {
    path: '/agents/:id/edit',
    name: 'AgentEdit',
    component: () => import('../views/agents/AgentCreate.vue'),
  },
  {
    path: '/agents/:id/chat',
    name: 'AgentChat',
    component: () => import('../views/agents/AgentChat.vue'),
  },
  {
    path: '/agents/:agent_id/composition',
    name: 'AgentComposition',
    component: () => import('../views/agents/AgentComposition.vue'),
  },
  {
    path: '/agents/:agent_id/workflow',
    name: 'AgentWorkflow',
    component: () => import('../views/agents/AgentWorkflow.vue'),
  },
  {
    path: '/schedules',
    name: 'ScheduleList',
    component: () => import('../views/schedules/ScheduleList.vue'),
  },
  {
    path: '/schedules/:id',
    name: 'ScheduleDetail',
    component: () => import('../views/schedules/ScheduleDetail.vue'),
  },
  {
    path: '/providers',
    name: 'ProviderList',
    component: () => import('../views/services/ProviderList.vue'),
  },
  {
    path: '/services',
    name: 'ServiceList',
    component: () => import('../views/services/ServiceList.vue'),
  },
  {
    path: '/skills',
    name: 'SkillList',
    component: () => import('../views/skills/SkillList.vue'),
  },
  {
    path: '/knowledge',
    name: 'KnowledgeList',
    component: () => import('../views/knowledge/KnowledgeList.vue'),
  },
  {
    path: '/knowledge/:id',
    name: 'KnowledgeDetail',
    component: () => import('../views/knowledge/KnowledgeDetail.vue'),
  },
  {
    path: '/memory',
    name: 'MemoryManage',
    component: () => import('../views/memory/MemoryManage.vue'),
  },
  {
    path: '/tools',
    name: 'ToolList',
    component: () => import('../views/tools/ToolList.vue'),
  },
  {
    path: '/screenpilot/systems',
    name: 'ScreenPilotSystems',
    component: () => import('../views/screenpilot/SystemList.vue'),
  },
  {
    path: '/screenpilot/skills',
    name: 'ScreenPilotSkills',
    component: () => import('../views/screenpilot/SkillList.vue'),
  },
  {
    path: '/screenpilot/shop',
    redirect: '/screenpilot/skills',
  },
  {
    path: '/screenpilot/approvals',
    name: 'ScreenPilotApprovals',
    component: () => import('../views/screenpilot/ApprovalInbox.vue'),
  },
  {
    path: '/data-access',
    name: 'DataAccessConfig',
    component: () => import('../views/dataquery/DataAccessConfig.vue'),
  },
  {
    path: '/data-access/monitor',
    name: 'DataQueryMonitor',
    component: () => import('../views/dataquery/DataQueryMonitor.vue'),
  },
  {
    path: '/settings',
    name: 'SystemConfig',
    component: () => import('../views/settings/SystemConfig.vue'),
  },
  {
    path: '/users',
    name: 'UserList',
    component: () => import('../views/users/UserList.vue'),
    meta: { requiresAdmin: true },
  },
  {
    path: '/me/settings',
    name: 'UserSettings',
    component: () => import('../views/settings/UserSettings.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const token = getToken()
  if (to.meta.public) {
    if (token && (to.path === '/login' || to.path === '/register')) {
      return '/'
    }
    return true
  }
  if (!token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  const auth = useAuthStore()
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.logout()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) {
    return '/'
  }
  return true
})

export default router

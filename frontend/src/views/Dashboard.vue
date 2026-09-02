<template>
  <div>
    <h2 class="page-title">仪表盘</h2>
    <a-row :gutter="16" style="margin-bottom: 24px">
      <a-col :span="6">
        <a-card>
          <a-statistic title="Agent 总数" :value="stats.agents" prefix="🤖" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="已发布" :value="stats.published" prefix="✅" :value-style="{ color: '#1a5c32' }" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="Run 成功率(7d)" :value="Math.round((stats.runSuccessRate || 0) * 100)" suffix="%" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="Token(7d)" :value="stats.runTokens" />
        </a-card>
      </a-col>
    </a-row>
    <a-row :gutter="16" style="margin-bottom: 24px">
      <a-col :span="6">
        <a-card>
          <a-statistic title="模型供应商" :value="stats.providers" prefix="🔌" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="知识库" :value="stats.knowledgeBases" prefix="📚" />
        </a-card>
      </a-col>
    </a-row>
    <a-card title="快速入口">
      <a-space>
        <a-button type="primary" @click="$router.push('/agents/create')">创建 Agent</a-button>
        <a-button @click="$router.push('/monitor')">监控</a-button>
        <a-button @click="$router.push('/eval')">评测</a-button>
        <a-button @click="$router.push('/providers')">管理供应商</a-button>
        <a-button @click="$router.push('/knowledge')">管理知识库</a-button>
        <a-button @click="$router.push('/skills')">管理 Skill 包</a-button>
      </a-space>
    </a-card>
  </div>
</template>

<script setup>
import { reactive, onMounted } from 'vue'
import { agentApi, providerApi, knowledgeApi, monitorApi } from '../api'

const stats = reactive({
  agents: 0,
  published: 0,
  providers: 0,
  knowledgeBases: 0,
  runSuccessRate: 0,
  runTokens: 0,
})

onMounted(async () => {
  try {
    const [agents, providers, kbs, mon] = await Promise.all([
      agentApi.list({ page_size: 1 }),
      providerApi.list({ page_size: 1 }),
      knowledgeApi.list({ page_size: 1 }),
      monitorApi.summary({ days: 7 }).catch(() => ({})),
    ])
    stats.agents = agents.total
    stats.providers = providers.total
    stats.knowledgeBases = kbs.total
    stats.runSuccessRate = mon.success_rate || 0
    stats.runTokens = mon.total_tokens || 0
    const published = await agentApi.list({ status: 'PUBLISHED', page_size: 1 })
    stats.published = published.total
  } catch (e) {
    console.error(e)
  }
})
</script>

<style scoped>
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin-bottom: 24px;
}
</style>
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">数据查询监控</h2>
      <a-space>
        <a-select v-model:value="currentAgentId" style="width: 280px" placeholder="选择 DataQueryAgent" @change="refreshAll">
          <a-select-option v-for="a in agents" :key="a.dq_agent_id" :value="a.dq_agent_id">
            {{ a.name }}
          </a-select-option>
        </a-select>
        <a-button @click="refreshAll">刷新</a-button>
      </a-space>
    </div>

    <a-row :gutter="12" style="margin-bottom:12px">
      <a-col :span="6"><a-statistic title="总查询量(最近统计日)" :value="latestStat.total_queries || 0" /></a-col>
      <a-col :span="6"><a-statistic title="成功查询" :value="latestStat.success_queries || 0" /></a-col>
      <a-col :span="6"><a-statistic title="失败查询" :value="latestStat.failed_queries || 0" /></a-col>
      <a-col :span="6"><a-statistic title="平均耗时(ms)" :value="Math.round(latestStat.avg_duration_ms || 0)" /></a-col>
    </a-row>

    <a-row :gutter="12">
      <a-col :span="12">
        <a-card title="质量统计趋势">
          <a-table :data-source="qualityStats" rowKey="id" size="small" :pagination="{ pageSize: 10 }">
            <a-table-column title="日期" dataIndex="stat_date" />
            <a-table-column title="总数" dataIndex="total_queries" />
            <a-table-column title="成功率">
              <template #default="{ record }">
                {{ record.total_queries ? `${Math.round((record.success_queries / record.total_queries) * 100)}%` : '-' }}
              </template>
            </a-table-column>
            <a-table-column title="平均耗时(ms)" dataIndex="avg_duration_ms" />
          </a-table>
        </a-card>
      </a-col>
      <a-col :span="12">
        <a-card title="失败日志 Top">
          <a-table :data-source="failedLogs" rowKey="log_id" size="small" :pagination="{ pageSize: 10 }">
            <a-table-column title="时间" dataIndex="created_at" />
            <a-table-column title="问题" dataIndex="question" ellipsis />
            <a-table-column title="状态" dataIndex="execution_status" />
          </a-table>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { dataQueryApi } from '../../api'

const agents = ref([])
const currentAgentId = ref('')
const qualityStats = ref([])
const queryLogs = ref([])

const latestStat = computed(() => (qualityStats.value && qualityStats.value.length ? qualityStats.value[0] : {}))
const failedLogs = computed(() => (queryLogs.value || []).filter(x => x.execution_status !== 'SUCCESS'))

async function loadAgents() {
  const res = await dataQueryApi.listAgents({ page_size: 100 })
  agents.value = res.items || []
  if (!currentAgentId.value && agents.value.length) currentAgentId.value = agents.value[0].dq_agent_id
}

async function refreshAll() {
  if (!currentAgentId.value) return
  const [s, l] = await Promise.all([
    dataQueryApi.listQualityStats(currentAgentId.value, { page_size: 100 }),
    dataQueryApi.listLogs(currentAgentId.value, { page_size: 100 }),
  ])
  qualityStats.value = s.items || []
  queryLogs.value = l.items || []
}

onMounted(async () => {
  try {
    await loadAgents()
    await refreshAll()
  } catch (e) {
    message.error(e.message)
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin: 0;
}
</style>

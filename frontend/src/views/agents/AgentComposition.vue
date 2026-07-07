<template>
  <div class="composition-page">
    <div class="page-header">
      <h2 class="page-title">多 Agent 编排配置</h2>
      <a-button @click="goBack">返回</a-button>
    </div>

    <a-spin :spinning="loading">
      <!-- Coordinator 配置 -->
      <a-card title="Coordinator 配置" style="margin-bottom: 16px">
        <a-form layout="vertical">
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="任务分发策略">
                <a-select v-model:value="coordinatorConfig.dispatch_strategy">
                  <a-select-option value="llm">LLM 自主判断分派</a-select-option>
                  <a-select-option value="rule">规则匹配分派（关键词）</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="最大分派轮次">
                <a-input-number v-model:value="coordinatorConfig.max_dispatch_rounds" :min="1" :max="20" style="width: 100%" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="结果整合方式">
                <a-select v-model:value="coordinatorConfig.result_integration">
                  <a-select-option value="coordinator">Coordinator 二次汇总</a-select-option>
                  <a-select-option value="concat">直接拼接子 Agent 输出</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
          </a-row>

          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="Coordinator 专用模型">
                <a-select v-model:value="coordinatorConfig.coordinator_model_service_id" placeholder="默认使用父 Agent 模型" allowClear>
                  <a-select-option v-for="s in modelServices" :key="s.model_service_id" :value="s.model_service_id">
                    {{ s.model_name }}（{{ s.provider_code }}）
                  </a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="Token 预算上限">
                <a-input-number v-model:value="coordinatorConfig.total_token_budget" :min="10000" :step="10000" style="width: 100%" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="最大 A2A 调用次数">
                <a-input-number v-model:value="coordinatorConfig.max_a2a_calls" :min="1" :max="100" style="width: 100%" />
              </a-form-item>
            </a-col>
          </a-row>

          <a-form-item>
            <a-checkbox v-model:checked="coordinatorConfig.hitl_before_delivery">
              交付前强制人工审批（HITL Gate）
            </a-checkbox>
          </a-form-item>

          <a-button type="primary" @click="saveCoordinatorConfig">保存 Coordinator 配置</a-button>
        </a-form>
      </a-card>

      <!-- 子 Agent 列表 -->
      <a-card title="子 Agent 管理" style="margin-bottom: 16px">
        <a-table :dataSource="subAgents" :columns="subAgentColumns" rowKey="composition_id" :pagination="false">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="record.child_agent_status === 'PUBLISHED' ? 'green' : 'red'">
                {{ record.child_agent_status }}
              </a-tag>
            </template>
            <template v-if="column.key === 'keywords'">
              <a-tag v-for="kw in record.task_keywords" :key="kw" color="blue">{{ kw }}</a-tag>
            </template>
            <template v-if="column.key === 'action'">
              <a-popconfirm title="确定移除该子 Agent？" @confirm="removeSubAgent(record.child_agent_id)">
                <a-button danger size="small">移除</a-button>
              </a-popconfirm>
            </template>
          </template>
        </a-table>

        <a-divider />

        <h3>添加子 Agent</h3>
        <a-form layout="inline" :model="newSubAgent">
          <a-form-item label="选择 Agent">
            <a-select v-model:value="newSubAgent.child_agent_id" style="width: 300px" placeholder="选择已发布的单体 Agent">
              <a-select-option
                v-for="c in candidates.filter(c => !c.already_added)"
                :key="c.agent_id"
                :value="c.agent_id"
              >
                {{ c.name }} - {{ c.description }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="角色名称">
            <a-input v-model:value="newSubAgent.role_name" placeholder="如：资料收集 Agent" style="width: 200px" />
          </a-form-item>
          <a-form-item label="职责描述">
            <a-input v-model:value="newSubAgent.role_description" placeholder="该子 Agent 的职责" style="width: 300px" />
          </a-form-item>
          <a-form-item label="关键词">
            <a-select v-model:value="newSubAgent.task_keywords" mode="tags" style="width: 200px" placeholder="规则匹配关键词" />
          </a-form-item>
          <a-form-item>
            <a-button type="primary" @click="addSubAgent" :disabled="!newSubAgent.child_agent_id || !newSubAgent.role_name">
              添加
            </a-button>
          </a-form-item>
        </a-form>
      </a-card>
    </a-spin>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { compositionApi, agentApi, serviceApi } from '../../api'

const route = useRoute()
const router = useRouter()
const agentId = route.params.agent_id

const loading = ref(false)
const subAgents = ref([])
const candidates = ref([])
const modelServices = ref([])

const coordinatorConfig = reactive({
  dispatch_strategy: 'llm',
  max_dispatch_rounds: 5,
  result_integration: 'coordinator',
  coordinator_model_service_id: null,
  hitl_before_delivery: true,
  total_token_budget: 500000,
  max_a2a_calls: 20,
})

const newSubAgent = reactive({
  child_agent_id: null,
  role_name: '',
  role_description: '',
  task_keywords: [],
})

const subAgentColumns = [
  { title: '角色名称', dataIndex: 'role_name', key: 'role_name' },
  { title: 'Agent 名称', dataIndex: 'child_agent_name', key: 'child_agent_name' },
  { title: '状态', key: 'status' },
  { title: '职责描述', dataIndex: 'role_description', key: 'role_description', ellipsis: true },
  { title: '关键词', key: 'keywords' },
  { title: '操作', key: 'action', width: 100 },
]

const goBack = () => router.push('/agents')

const loadComposition = async () => {
  loading.value = true
  try {
    const res = await compositionApi.get(agentId)
    subAgents.value = res.sub_agents || []
    if (res.coordinator_config) {
      Object.assign(coordinatorConfig, res.coordinator_config)
    }
  } catch (e) {
    message.error('加载编排配置失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

const loadCandidates = async () => {
  try {
    const res = await compositionApi.listCandidates(agentId)
    candidates.value = res.candidates || []
  } catch (e) {
    // 非阻塞
  }
}

const loadModelServices = async () => {
  try {
    const res = await serviceApi.list()
    modelServices.value = res.items || []
  } catch (e) {
    // 非阻塞
  }
}

const addSubAgent = async () => {
  try {
    await compositionApi.addSubAgent(agentId, { ...newSubAgent })
    message.success('子 Agent 添加成功')
    newSubAgent.child_agent_id = null
    newSubAgent.role_name = ''
    newSubAgent.role_description = ''
    newSubAgent.task_keywords = []
    await loadComposition()
    await loadCandidates()
  } catch (e) {
    message.error('添加失败: ' + e.message)
  }
}

const removeSubAgent = async (childId) => {
  try {
    await compositionApi.removeSubAgent(agentId, childId)
    message.success('子 Agent 已移除')
    await loadComposition()
    await loadCandidates()
  } catch (e) {
    message.error('移除失败: ' + e.message)
  }
}

const saveCoordinatorConfig = async () => {
  try {
    await compositionApi.updateCoordinator(agentId, { ...coordinatorConfig })
    message.success('Coordinator 配置已保存')
  } catch (e) {
    message.error('保存失败: ' + e.message)
  }
}

onMounted(() => {
  loadComposition()
  loadCandidates()
  loadModelServices()
})
</script>

<style scoped>
.composition-page { max-width: 1200px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>

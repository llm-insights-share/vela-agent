<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ agent.name || 'Agent 详情' }}</h2>
      <a-space>
        <a-button v-if="agent.status !== 'PUBLISHED'" @click="$router.push(`/agents/${agent.agent_id}/edit`)">编辑</a-button>
        <a-button v-if="agent.status === 'DRAFT'" type="primary" @click="handlePublish">发布</a-button>
        <a-button v-if="agent.status === 'PUBLISHED'" @click="handleDeprecate">下架</a-button>
        <a-button v-if="agent.status === 'DEPRECATED'" type="primary" @click="handleRepublish">重新上架</a-button>
        <a-button @click="handleValidate">校验</a-button>
        <a-button @click="$router.push(`/agents/${agent.agent_id}/chat`)" v-if="agent.status === 'PUBLISHED'">对话测试</a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <a-row :gutter="16">
        <a-col :span="12">
          <a-card title="基本信息" style="margin-bottom: 16px">
            <a-descriptions :column="1" size="small">
              <a-descriptions-item label="ID">{{ agent.agent_id }}</a-descriptions-item>
              <a-descriptions-item label="名称">{{ agent.name }}</a-descriptions-item>
              <a-descriptions-item label="描述">{{ agent.description }}</a-descriptions-item>
              <a-descriptions-item label="状态">
                <a-tag :color="statusColor(agent.status)">{{ statusLabel(agent.status) }}</a-tag>
              </a-descriptions-item>
              <a-descriptions-item label="版本">{{ agent.current_version }}</a-descriptions-item>
              <a-descriptions-item label="自主级别">{{ agent.autonomy_level }}</a-descriptions-item>
              <a-descriptions-item label="部门">{{ agent.dept_id }}</a-descriptions-item>
              <a-descriptions-item label="并发上限">{{ agent.max_concurrent_sessions }}</a-descriptions-item>
              <a-descriptions-item label="Token 预算">{{ agent.token_budget }}</a-descriptions-item>
              <a-descriptions-item label="模型">{{ agent.model_name }}</a-descriptions-item>
            </a-descriptions>
          </a-card>
        </a-col>
        <a-col :span="12">
          <a-card title="System Prompt" style="margin-bottom: 16px">
            <pre class="prompt-pre">{{ agent.system_prompt || '(空)' }}</pre>
          </a-card>
          <a-card title="技能与知识库" style="margin-bottom: 16px">
            <a-descriptions :column="1" size="small">
              <a-descriptions-item label="Skill 包">
                <a-tag v-for="(name, i) in (agent.skill_pack_names || [])" :key="(agent.skill_pack_ids || [])[i] || i" color="blue">{{ name }}</a-tag>
                <span v-if="!agent.skill_pack_names?.length" style="color: #9e9590">无</span>
              </a-descriptions-item>
              <a-descriptions-item label="知识库">
                <a-tag v-for="(name, i) in (agent.knowledge_base_names || [])" :key="(agent.knowledge_base_ids || [])[i] || i" color="green">{{ name }}</a-tag>
                <span v-if="!agent.knowledge_base_names?.length" style="color: #9e9590">无</span>
              </a-descriptions-item>
              <a-descriptions-item label="工具">
                <a-tag v-for="(name, i) in (agent.tool_names || [])" :key="(agent.tool_ids || [])[i] || i" color="orange">{{ name }}</a-tag>
                <span v-if="!agent.tool_names?.length" style="color: #9e9590">无</span>
              </a-descriptions-item>
            </a-descriptions>
          </a-card>
          <a-card title="标签" style="margin-bottom: 16px">
            <a-tag v-for="t in agent.tags || []" :key="t">{{ t }}</a-tag>
            <span v-if="!agent.tags?.length" style="color: #9e9590">无</span>
          </a-card>
        </a-col>
      </a-row>

      <a-card title="版本历史" style="margin-top: 16px">
        <a-table :columns="versionColumns" :data-source="versions" row-key="version_id" :pagination="false" size="small">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag :color="record.status === 'PUBLISHED' ? 'green' : 'default'">{{ record.status }}</a-tag>
            </template>
            <template v-if="column.key === 'action'">
              <a-button v-if="record.status === 'PUBLISHED' && record.version_id !== agent.current_version_id" size="small" @click="handleRollback(record.version_id)">回滚到此版本</a-button>
            </template>
          </template>
        </a-table>
      </a-card>
    </a-spin>

    <a-modal v-model:open="validateOpen" title="校验结果" :footer="null">
      <div v-if="validateResult">
        <a-alert v-if="validateResult.passed" type="success" message="校验通过" style="margin-bottom: 12px" />
        <a-alert v-else type="error" message="校验未通过" style="margin-bottom: 12px" />
        <div v-if="validateResult.errors?.length">
          <h4>错误：</h4>
          <ul>
            <li v-for="e in validateResult.errors" :key="e.field" style="color: #b5341c">{{ e.field }}: {{ e.message }}</li>
          </ul>
        </div>
        <div v-if="validateResult.warnings?.length">
          <h4>警告：</h4>
          <ul>
            <li v-for="w in validateResult.warnings" :key="w.field" style="color: #8a5e00">{{ w.field }}: {{ w.message }}</li>
          </ul>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { agentApi } from '../../api'
import { message } from 'ant-design-vue'

const route = useRoute()
const agentId = route.params.id
const loading = ref(false)
const agent = reactive({})
const versions = ref([])
const validateOpen = ref(false)
const validateResult = ref(null)

const versionColumns = [
  { title: '版本号', dataIndex: 'version' },
  { title: '变更类型', dataIndex: 'change_type', width: 100 },
  { title: '变更说明', dataIndex: 'change_summary' },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 120 },
]

function statusColor(s) {
  const m = { DRAFT: 'default', PUBLISHED: 'green', DEPRECATED: 'orange', DELETED: 'red' }
  return m[s] || 'default'
}
function statusLabel(s) {
  const m = { DRAFT: '草稿', PUBLISHED: '已发布', DEPRECATED: '已下架', DELETED: '已删除' }
  return m[s] || s
}

async function fetchAgent() {
  loading.value = true
  try {
    const [a, v] = await Promise.all([
      agentApi.get(agentId),
      agentApi.versions(agentId),
    ])
    Object.assign(agent, a)
    versions.value = v
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function handleValidate() {
  try {
    validateResult.value = await agentApi.validate(agentId)
    validateOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

async function handlePublish() {
  try {
    await agentApi.publish(agentId, {})
    message.success('发布成功')
    fetchAgent()
  } catch (e) {
    message.error(e.message)
  }
}

async function handleDeprecate() {
  try {
    await agentApi.deprecate(agentId)
    message.success('已下架')
    fetchAgent()
  } catch (e) {
    message.error(e.message)
  }
}

async function handleRepublish() {
  try {
    await agentApi.republish(agentId)
    message.success('已重新上架')
    fetchAgent()
  } catch (e) {
    message.error(e.message)
  }
}

async function handleRollback(versionId) {
  try {
    await agentApi.rollback(agentId, versionId)
    message.success('回滚成功')
    fetchAgent()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(fetchAgent)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.prompt-pre { white-space: pre-wrap; font-size: 12px; color: #3a342e; background: #f3f0e8; padding: 12px; border-radius: 6px; max-height: 200px; overflow-y: auto; }
</style>
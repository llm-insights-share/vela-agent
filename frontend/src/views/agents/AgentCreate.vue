<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ isEdit ? '编辑 Agent' : '创建 Agent' }}</h2>
    </div>
    <a-card style="max-width: 900px">
      <a-form :model="form" :label-col="{ span: 4 }" :wrapper-col="{ span: 18 }" @finish="onSubmit">
        <a-form-item label="名称" name="name" :rules="[{ required: true, message: '请输入名称' }]">
          <a-input v-model:value="form.name" placeholder="Agent 名称" />
        </a-form-item>
        <a-form-item label="描述" name="description">
          <a-textarea v-model:value="form.description" placeholder="Agent 描述" :rows="2" />
        </a-form-item>
        <a-form-item label="模型服务" name="model_service_id" :rules="[{ required: true, message: '请选择模型服务' }]">
          <a-select v-model:value="form.model_service_id" placeholder="选择模型服务" show-search option-filter-prop="label">
            <a-select-option v-for="s in services" :key="s.model_service_id" :value="s.model_service_id" :label="s.display_name">
              {{ s.display_name }} ({{ s.model_name }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="System Prompt" name="system_prompt">
          <a-textarea v-model:value="form.system_prompt" placeholder="System Prompt" :rows="6" />
        </a-form-item>
        <a-form-item label="部门" name="dept_id">
          <a-input v-model:value="form.dept_id" placeholder="部门 ID" />
        </a-form-item>
        <a-form-item label="自主级别" name="autonomy_level">
          <a-select v-model:value="form.autonomy_level">
            <a-select-option value="L1">L1 - 需审批</a-select-option>
            <a-select-option value="L2">L2 - 半自主</a-select-option>
            <a-select-option value="L3">L3 - 全自主</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="并发上限" name="max_concurrent_sessions">
          <a-input-number v-model:value="form.max_concurrent_sessions" :min="1" :max="100" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Token 预算" name="token_budget">
          <a-input-number v-model:value="form.token_budget" :min="1000" :step="1000" style="width: 100%" />
        </a-form-item>
        <a-form-item label="Skill 包" name="skill_pack_ids">
          <a-select v-model:value="form.skill_pack_ids" mode="multiple" placeholder="选择 Skill 包">
            <a-select-option v-for="s in skills" :key="s.skill_pack_id" :value="s.skill_pack_id">
              {{ s.name }} ({{ s.scope }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="知识库" name="knowledge_base_ids">
          <a-select v-model:value="form.knowledge_base_ids" mode="multiple" placeholder="选择知识库">
            <a-select-option v-for="k in knowledgeBases" :key="k.kb_id" :value="k.kb_id">
              {{ k.name }}
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="工具" name="tool_ids">
          <a-select v-model:value="form.tool_ids" mode="multiple" placeholder="选择工具">
            <a-select-option v-for="t in toolList" :key="t.tool_id" :value="t.tool_id">
              {{ t.display_name || t.name }} ({{ t.tool_type }})
            </a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="标签" name="tags">
          <a-select v-model:value="form.tags" mode="tags" placeholder="输入标签" />
        </a-form-item>
        <a-form-item :wrapper-col="{ offset: 4, span: 18 }">
          <a-space>
            <a-button type="primary" html-type="submit" :loading="submitting">{{ isEdit ? '保存' : '创建' }}</a-button>
            <a-button @click="$router.back()">取消</a-button>
          </a-space>
        </a-form-item>
      </a-form>
    </a-card>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { agentApi, serviceApi, skillApi, knowledgeApi, toolApi } from '../../api'
import { message } from 'ant-design-vue'

const router = useRouter()
const route = useRoute()
const submitting = ref(false)
const services = ref([])
const skills = ref([])
const knowledgeBases = ref([])
const toolList = ref([])

const isEdit = computed(() => !!route.params.id)
const agentId = computed(() => route.params.id)

const form = reactive({
  name: '',
  description: '',
  model_service_id: '',
  system_prompt: '',
  dept_id: '',
  autonomy_level: 'L2',
  max_concurrent_sessions: 5,
  token_budget: 8000,
  skill_pack_ids: [],
  knowledge_base_ids: [],
  tool_ids: [],
  tags: [],
  tool_permissions: {},
})

onMounted(async () => {
  try {
    const [svc, sk, kb, tl] = await Promise.all([
      serviceApi.list({ page_size: 100 }),
      skillApi.list({ page_size: 100 }),
      knowledgeApi.list({ page_size: 100 }),
      toolApi.list({ page_size: 100 }),
    ])
    services.value = svc.items
    skills.value = sk.items
    knowledgeBases.value = kb.items
    toolList.value = tl.items

    if (isEdit.value) {
      const agent = await agentApi.get(agentId.value)
      Object.assign(form, {
        name: agent.name,
        description: agent.description,
        model_service_id: agent.model_service_id,
        system_prompt: agent.system_prompt,
        dept_id: agent.dept_id,
        autonomy_level: agent.autonomy_level,
        max_concurrent_sessions: agent.max_concurrent_sessions,
        token_budget: agent.token_budget,
        skill_pack_ids: agent.skill_pack_ids || [],
        knowledge_base_ids: agent.knowledge_base_ids || [],
        tool_ids: agent.tool_ids || [],
        tags: agent.tags || [],
        tool_permissions: agent.tool_permissions || {},
      })
    }
  } catch (e) {
    message.error(e.message)
  }
})

async function onSubmit() {
  submitting.value = true
  try {
    if (isEdit.value) {
      await agentApi.update(agentId.value, form)
      message.success('Agent 更新成功')
    } else {
      await agentApi.create(form)
      message.success('Agent 创建成功')
    }
    router.push('/agents')
  } catch (e) {
    message.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.page-header { margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">知识库</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 创建知识库
      </a-button>
    </div>
    <a-card>
      <a-table :columns="columns" :data-source="knowledgeBases" :loading="loading" row-key="kb_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'default'">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'scope'">
            <a-tag :color="record.scope === 'GLOBAL' ? 'blue' : 'orange'">{{ record.scope }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="$router.push(`/knowledge/${record.kb_id}`)">详情</a>
              <a @click="openEdit(record)">编辑</a>
              <a-popconfirm title="确认归档?" @confirm="handleDelete(record.kb_id)">
                <a style="color: #b5341c">归档</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑知识库' : '创建知识库'" @ok="handleSave" :confirm-loading="saving">
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 17 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="知识库名称" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="2" />
        </a-form-item>
        <a-form-item label="类型">
          <a-select v-model:value="form.kb_type">
            <a-select-option value="FAISS">FAISS 本地向量库</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="范围">
          <a-select v-model:value="form.scope">
            <a-select-option value="GLOBAL">全局</a-select-option>
            <a-select-option value="DEPT">部门</a-select-option>
            <a-select-option value="PRIVATE">私有</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="上下文感知">
          <a-select v-model:value="form.contextual_mode">
            <a-select-option value="inherit">跟随全局</a-select-option>
            <a-select-option value="enabled">启用</a-select-option>
            <a-select-option value="disabled">禁用</a-select-option>
          </a-select>
          <div class="field-hint">入库时为分块生成 LLM 上下文前缀，提升检索召回</div>
        </a-form-item>
        <a-form-item label="文档标签">
          <div class="tag-presets">
            <a-button
              v-for="preset in tagPresets"
              :key="preset.name"
              size="small"
              @click="addPresetTag(preset)"
            >
              + {{ preset.name }}
            </a-button>
          </div>
          <div v-for="(tag, idx) in form.tag_defs" :key="idx" class="tag-def-row">
            <a-input
              v-model:value="tag.name"
              placeholder="标签名称"
              style="flex: 1"
              @change="onTagNameChange(tag)"
            />
            <a-select v-model:value="tag.type" style="width: 96px">
              <a-select-option value="text">文本</a-select-option>
              <a-select-option value="date">日期</a-select-option>
            </a-select>
            <a-input v-model:value="tag.hint" placeholder="抽取提示（可选）" style="flex: 1" />
            <a-button type="text" danger @click="form.tag_defs.splice(idx, 1)">删除</a-button>
          </div>
          <a-button type="dashed" block @click="addTagDef">添加标签</a-button>
          <div class="field-hint">导入时自动抽取，检索时可按标签筛选。名称在知识库内需唯一。</div>
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { knowledgeApi } from '../../api'
import { message } from 'ant-design-vue'

const loading = ref(false)
const knowledgeBases = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)

const columns = [
  { title: '名称', dataIndex: 'name' },
  { title: '描述', dataIndex: 'description', ellipsis: true },
  { title: '类型', dataIndex: 'kb_type' },
  { title: '范围', key: 'scope', width: 100 },
  { title: '文档数', dataIndex: 'doc_count', width: 80 },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 200 },
]

const form = reactive({
  name: '',
  description: '',
  kb_type: 'FAISS',
  scope: 'GLOBAL',
  contextual_mode: 'inherit',
  tag_defs: [],
})

const tagPresets = [
  { name: '作者', type: 'text' },
  { name: '创建时间', type: 'date' },
  { name: '失效时间', type: 'date' },
  { name: '发布部门', type: 'text' },
]

function inferTagType(name) {
  return /时间|日期|日/.test(name || '') ? 'date' : 'text'
}

function emptyTagDef() {
  return { name: '', type: 'text', hint: '' }
}

function cloneTagDefs(defs) {
  return (defs || []).map((d) => ({
    name: d.name || '',
    type: d.type === 'date' ? 'date' : inferTagType(d.name),
    hint: d.hint || '',
  }))
}

function addTagDef() {
  form.tag_defs.push(emptyTagDef())
}

function addPresetTag(preset) {
  if (form.tag_defs.some((t) => t.name === preset.name)) return
  form.tag_defs.push({ name: preset.name, type: preset.type, hint: '' })
}

function onTagNameChange(tag) {
  if (inferTagType(tag.name) === 'date') tag.type = 'date'
}

function contextualModeToApi(mode) {
  if (mode === 'enabled') return true
  if (mode === 'disabled') return false
  return null
}

function contextualModeFromApi(value) {
  if (value === true) return 'enabled'
  if (value === false) return 'disabled'
  return 'inherit'
}

function buildPayload() {
  return {
    name: form.name,
    description: form.description,
    kb_type: form.kb_type,
    scope: form.scope,
    contextual_retrieval_enabled: contextualModeToApi(form.contextual_mode),
    tag_defs: form.tag_defs
      .filter((t) => (t.name || '').trim())
      .map((t) => ({
        name: t.name.trim(),
        type: t.type === 'date' ? 'date' : inferTagType(t.name),
        hint: (t.hint || '').trim(),
      })),
  }
}

async function fetchKnowledgeBases() {
  loading.value = true
  try {
    const res = await knowledgeApi.list({ page_size: 100 })
    knowledgeBases.value = res.items
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    name: '',
    description: '',
    kb_type: 'FAISS',
    scope: 'GLOBAL',
    contextual_mode: 'inherit',
    tag_defs: [],
  })
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  Object.assign(form, {
    name: record.name,
    description: record.description,
    kb_type: record.kb_type,
    scope: record.scope,
    contextual_mode: contextualModeFromApi(record.contextual_retrieval_enabled),
    tag_defs: cloneTagDefs(record.tag_defs),
  })
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    const payload = buildPayload()
    if (editing.value) {
      await knowledgeApi.update(editing.value.kb_id, payload)
      message.success('更新成功')
    } else {
      await knowledgeApi.create(payload)
      message.success('创建成功')
    }
    modalOpen.value = false
    fetchKnowledgeBases()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  try {
    await knowledgeApi.delete(id)
    message.success('已归档')
    fetchKnowledgeBases()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(fetchKnowledgeBases)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.field-hint { font-size: 11px; color: #9e9590; margin-top: 4px; line-height: 1.5; }
.tag-presets { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tag-def-row { display: flex; gap: 8px; margin-bottom: 8px; align-items: center; }
</style>
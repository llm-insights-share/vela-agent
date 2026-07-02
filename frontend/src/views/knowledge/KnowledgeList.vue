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
})

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
  Object.assign(form, { name: '', description: '', kb_type: 'FAISS', scope: 'GLOBAL' })
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  Object.assign(form, {
    name: record.name,
    description: record.description,
    kb_type: record.kb_type,
    scope: record.scope,
  })
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      await knowledgeApi.update(editing.value.kb_id, { ...form })
      message.success('更新成功')
    } else {
      await knowledgeApi.create({ ...form })
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
</style>
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">Skill 包</h2>
      <a-space>
        <a-button @click="openImport">
          <ImportOutlined /> 导入 Skill 包
        </a-button>
        <a-button type="primary" @click="openCreate">
          <PlusOutlined /> 创建 Skill 包
        </a-button>
      </a-space>
    </div>
    <a-card>
      <a-table :columns="columns" :data-source="skills" :loading="loading" row-key="skill_pack_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'default'">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'scope'">
            <a-tag :color="record.scope === 'GLOBAL' ? 'blue' : 'orange'">{{ record.scope }}</a-tag>
          </template>
          <template v-if="column.key === 'tools'">
            {{ (record.tools || []).length }} 个工具
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openEdit(record)">编辑</a>
              <a-popconfirm title="确认归档?" @confirm="handleDelete(record.skill_pack_id)">
                <a style="color: #b5341c">归档</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑 Skill 包' : '创建 Skill 包'" @ok="handleSave" :confirm-loading="saving" width="700px">
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 17 }">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="Skill 包名称" />
        </a-form-item>
        <a-form-item label="版本" required>
          <a-input v-model:value="form.version" placeholder="1.0.0" />
        </a-form-item>
        <a-form-item label="范围" required>
          <a-select v-model:value="form.scope">
            <a-select-option value="GLOBAL">全局</a-select-option>
            <a-select-option value="DEPT">部门</a-select-option>
            <a-select-option value="PRIVATE">私有</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="2" />
        </a-form-item>
        <a-form-item label="工具定义">
          <a-textarea v-model:value="toolsText" :rows="8" placeholder='JSON 数组，每个工具包含 name, description, parameters 等字段' />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="importOpen" title="导入 Skill 包" @ok="handleImport" :confirm-loading="importing" width="500px">
      <a-upload-dragger
        :before-upload="beforeUpload"
        :file-list="importFileList"
        :max-count="1"
        accept=".zip"
        @remove="importFileList = []"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined style="font-size: 48px; color: #c2410c" />
        </p>
        <p class="ant-upload-text">点击或拖拽 Skill 压缩包到此区域</p>
        <p class="ant-upload-hint">
          支持 .zip 格式，需包含 skill.yaml 或 skill.json 清单文件
        </p>
      </a-upload-dragger>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined, ImportOutlined, InboxOutlined } from '@ant-design/icons-vue'
import { skillApi } from '../../api'
import { message } from 'ant-design-vue'

const loading = ref(false)
const skills = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const toolsText = ref('[]')

const importOpen = ref(false)
const importFileList = ref([])
const importing = ref(false)
let importFile = null

const columns = [
  { title: '名称', dataIndex: 'name' },
  { title: '版本', dataIndex: 'version' },
  { title: '范围', key: 'scope', width: 100 },
  { title: '工具数', key: 'tools', width: 80 },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 150 },
]

const form = reactive({
  name: '',
  version: '1.0.0',
  scope: 'GLOBAL',
  description: '',
  tools: [],
})

async function fetchSkills() {
  loading.value = true
  try {
    const res = await skillApi.list({ page_size: 100 })
    skills.value = res.items
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', version: '1.0.0', scope: 'GLOBAL', description: '', tools: [] })
  toolsText.value = '[]'
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  Object.assign(form, {
    name: record.name,
    version: record.version,
    scope: record.scope,
    description: record.description,
    tools: record.tools,
  })
  toolsText.value = JSON.stringify(record.tools || [], null, 2)
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    let tools = []
    try {
      tools = JSON.parse(toolsText.value)
    } catch {
      message.error('工具定义 JSON 格式错误')
      saving.value = false
      return
    }
    const data = { ...form, tools }
    if (editing.value) {
      await skillApi.update(editing.value.skill_pack_id, data)
      message.success('更新成功')
    } else {
      await skillApi.create(data)
      message.success('创建成功')
    }
    modalOpen.value = false
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  try {
    await skillApi.delete(id)
    message.success('已归档')
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  }
}

function openImport() {
  importFileList.value = []
  importFile = null
  importOpen.value = true
}

function beforeUpload(file) {
  const isZip = file.type === 'application/zip' || file.name.toLowerCase().endsWith('.zip')
  if (!isZip) {
    message.error('仅支持 .zip 格式文件')
    return false
  }
  importFile = file
  importFileList.value = [file]
  return false
}

async function handleImport() {
  if (!importFile) {
    message.warning('请先选择文件')
    return
  }
  importing.value = true
  try {
    await skillApi.import(importFile)
    message.success('Skill 包导入成功')
    importOpen.value = false
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    importing.value = false
  }
}

onMounted(fetchSkills)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>
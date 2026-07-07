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

    <a-modal v-model:open="importOpen" title="导入 Skill 包" :footer="null" width="500px">
      <div
        class="drop-zone"
        :class="{ 'drop-zone-active': dragOver }"
        @dragenter.prevent="onDragEnter"
        @dragover.prevent="onDragOver"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
        @click="triggerFileInput"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined style="font-size: 48px; color: #c2410c" />
        </p>
        <p class="ant-upload-text">点击或拖拽 Skill 目录 / .zip 文件到此区域</p>
        <p class="ant-upload-hint">
          支持拖拽整个 Skill 目录，或 .zip 压缩包，需包含 SKILL.md、skill.yaml 或 skill.json 清单文件
        </p>
        <input
          ref="fileInputRef"
          type="file"
          accept=".zip"
          style="display: none"
          @change="onFileSelected"
        />
      </div>
      <div v-if="selectedName" class="drop-selected">
        <a-tag color="blue">{{ selectedName }}</a-tag>
        <span v-if="selectedFileCount" style="color: #888; font-size: 12px">{{ selectedFileCount }} 个文件</span>
      </div>
      <div v-if="importing" style="margin-top: 12px; text-align: center">
        <a-spin /> 正在打包导入...
      </div>
      <div v-if="!importing && selectedName" style="margin-top: 16px; text-align: right">
        <a-button @click="resetImport" style="margin-right: 8px">取消</a-button>
        <a-button type="primary" :loading="importing" @click="handleImport">导入</a-button>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined, ImportOutlined, InboxOutlined } from '@ant-design/icons-vue'
import { skillApi } from '../../api'
import { message } from 'ant-design-vue'
import JSZip from 'jszip'

const loading = ref(false)
const skills = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)
const toolsText = ref('[]')

const importOpen = ref(false)
const importing = ref(false)
const dragOver = ref(false)
const selectedName = ref('')
const selectedFileCount = ref(0)
const fileInputRef = ref(null)
let importBlob = null
let importFileName = ''

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
  importBlob = null
  importFileName = ''
  selectedName.value = ''
  selectedFileCount.value = 0
  dragOver.value = false
  importOpen.value = true
}

function resetImport() {
  importBlob = null
  importFileName = ''
  selectedName.value = ''
  selectedFileCount.value = 0
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function onFileSelected(e) {
  const file = e.target.files[0]
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    message.error('仅支持 .zip 格式文件')
    return
  }
  importBlob = file
  importFileName = file.name
  selectedName.value = file.name
  selectedFileCount.value = 0
  e.target.value = ''
}

function onDragEnter() {
  dragOver.value = true
}

function onDragOver() {
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

async function onDrop(e) {
  dragOver.value = false
  const items = e.dataTransfer.items
  if (!items || items.length === 0) return

  const firstItem = items[0]
  // 检查是否是目录拖拽
  const entry = firstItem.webkitGetAsEntry?.()
  if (entry && entry.isDirectory) {
    await handleDirectoryDrop(entry)
    return
  }

  // 检查是否是文件拖拽
  const file = firstItem.getAsFile?.()
  if (file) {
    handleFileDrop(file)
    return
  }
}

function handleFileDrop(file) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    message.error('仅支持 .zip 格式文件')
    return
  }
  importBlob = file
  importFileName = file.name
  selectedName.value = file.name
  selectedFileCount.value = 0
}

async function handleDirectoryDrop(dirEntry) {
  const files = []
  await readDirectoryEntries(dirEntry, '', files)

  if (files.length === 0) {
    message.error('目录为空')
    return
  }

  const dirName = dirEntry.name || 'skill'
  selectedName.value = dirName
  selectedFileCount.value = files.length

  const zip = new JSZip()
  for (const { path, blob } of files) {
    zip.file(dirName + '/' + path, blob)
  }
  importBlob = await zip.generateAsync({ type: 'blob' })
  importFileName = dirName + '.zip'
}

async function readDirectoryEntries(dirEntry, basePath, results) {
  const reader = dirEntry.createReader()
  const entries = await readAllEntries(reader)
  for (const entry of entries) {
    const fullPath = basePath ? basePath + '/' + entry.name : entry.name
    if (entry.isFile) {
      const file = await entryToFile(entry)
      results.push({ path: fullPath, blob: file })
    } else if (entry.isDirectory) {
      // 跳过隐藏目录
      if (entry.name.startsWith('.')) continue
      await readDirectoryEntries(entry, fullPath, results)
    }
  }
}

function readAllEntries(reader) {
  return new Promise((resolve, reject) => {
    const allEntries = []
    function readBatch() {
      reader.readEntries((entries) => {
        if (entries.length === 0) {
          resolve(allEntries)
        } else {
          allEntries.push(...entries)
          readBatch()
        }
      }, reject)
    }
    readBatch()
  })
}

function entryToFile(entry) {
  return new Promise((resolve, reject) => {
    entry.file(resolve, reject)
  })
}

async function handleImport() {
  if (!importBlob) {
    message.warning('请先选择文件或拖拽目录')
    return
  }
  importing.value = true
  try {
    const file = new File([importBlob], importFileName, { type: 'application/zip' })
    await skillApi.import(file)
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

.drop-zone {
  border: 2px dashed #d9d9d9;
  border-radius: 8px;
  padding: 32px 16px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.3s, background 0.3s;
}
.drop-zone:hover {
  border-color: #c2410c;
  background: #fff7ed;
}
.drop-zone-active {
  border-color: #c2410c;
  background: #fff7ed;
}
.drop-selected {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
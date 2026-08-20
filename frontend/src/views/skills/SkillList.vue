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
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'default'">
              {{ statusLabel(record.status) }}
            </a-tag>
          </template>
          <template v-if="column.key === 'scope'">
            <a-tag :color="record.scope === 'GLOBAL' ? 'blue' : 'orange'">{{ scopeLabel(record.scope) }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openDetail(record)">详情</a>
              <a-popconfirm
                v-if="record.status === 'ACTIVE'"
                title="确认下架该 Skill 包？"
                @confirm="handleUnpublish(record.skill_pack_id)"
              >
                <a style="color: #b5341c">下架</a>
              </a-popconfirm>
              <a-popconfirm
                v-else
                title="确认上架该 Skill 包？"
                @confirm="handlePublish(record.skill_pack_id)"
              >
                <a>上架</a>
              </a-popconfirm>
              <a-popconfirm
                title="确认删除该 Skill 包？删除后不可恢复。"
                ok-text="删除"
                cancel-text="取消"
                @confirm="handleRemove(record.skill_pack_id)"
              >
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="modalOpen"
      title="创建 Skill 包"
      @ok="handleSave"
      :confirm-loading="saving"
      width="700px"
    >
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

    <a-modal
      v-model:open="detailOpen"
      title="Skill 包详情"
      width="920px"
      destroy-on-close
      @cancel="resetManifestEditor"
    >
      <div v-if="detailLoading" class="detail-loading">
        <a-spin tip="加载中..." />
      </div>
      <template v-else-if="detail">
        <a-descriptions :column="1" bordered size="small" class="detail-desc">
          <a-descriptions-item label="名称">{{ detail.name }}</a-descriptions-item>
          <a-descriptions-item label="版本">{{ detail.version }}</a-descriptions-item>
          <a-descriptions-item label="范围">{{ scopeLabel(detail.scope) }}</a-descriptions-item>
          <a-descriptions-item label="描述">{{ detail.description || '（无）' }}</a-descriptions-item>
        </a-descriptions>

        <a-collapse v-model:activeKey="manifestPanelKeys" class="manifest-collapse">
          <a-collapse-panel key="manifest" header="Manifest 配置">
            <div class="manifest-summary">{{ manifestSummaryText }}</div>
            <p class="manifest-hint">重新导入 zip 会覆盖数据库中的 manifest；此处编辑仅更新 DB，不回写包内 SKILL.md。</p>
            <a-form :label-col="{ span: 6 }" :wrapper-col="{ span: 17 }" class="manifest-form">
              <a-form-item label="触发词">
                <a-select
                  v-model:value="manifestForm.trigger_keywords"
                  mode="tags"
                  placeholder="输入后回车添加，如：开盘走势"
                  style="width: 100%"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
              <a-form-item label="搜索上限">
                <a-input-number
                  v-model:value="manifestForm.tool_budget.max_web_search"
                  :min="1"
                  :max="50"
                  style="width: 100%"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
              <a-form-item label="每轮 Tavily 上限">
                <a-input-number
                  v-model:value="manifestForm.tool_budget.max_tavily_per_iter"
                  :min="1"
                  :max="10"
                  style="width: 100%"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
              <a-form-item label="工具轮次上限">
                <a-input-number
                  v-model:value="manifestForm.tool_budget.max_tool_rounds"
                  :min="1"
                  :max="20"
                  style="width: 100%"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
              <a-form-item label="最小超时(秒)">
                <a-input-number
                  v-model:value="manifestForm.tool_budget.min_timeout_seconds"
                  :min="10"
                  :max="600"
                  style="width: 100%"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
              <a-form-item label="执行提示">
                <a-textarea
                  v-model:value="manifestForm.execution_hints"
                  :rows="4"
                  placeholder="注入给模型的 Skill 执行效率提示"
                  @change="syncManifestJsonFromForm"
                />
              </a-form-item>
            </a-form>
            <a-collapse v-model:activeKey="manifestJsonKeys" ghost @change="onManifestJsonPanelChange">
              <a-collapse-panel key="json" header="高级 JSON">
                <a-textarea
                  v-model:value="manifestJsonText"
                  :rows="12"
                  class="manifest-json-editor"
                  spellcheck="false"
                  @blur="applyManifestJsonToForm"
                />
              </a-collapse-panel>
            </a-collapse>
          </a-collapse-panel>
        </a-collapse>

        <div class="detail-section">
          <div class="section-label">引用 Skill</div>
          <div class="section-value">{{ referencedSkillsText(detail) }}</div>
        </div>

        <div class="detail-section">
          <div class="section-label">资产内容</div>
          <div v-if="isSingleFilePack(detail)" class="asset-single">
            <div class="preview-markdown" v-html="singleFileHtml"></div>
          </div>
          <div v-else class="asset-multi">
            <div class="asset-tree">
              <a-tree
                v-if="fileTree.length"
                :tree-data="fileTree"
                :selected-keys="selectedFileKeys"
                default-expand-all
                @select="onFileSelect"
              />
            </div>
            <div class="asset-preview">
              <table v-if="selectedFileMeta.length" class="meta-table">
                <tbody>
                  <tr v-for="row in selectedFileMeta" :key="row.key">
                    <td class="meta-key">{{ row.key }}</td>
                    <td>{{ row.value }}</td>
                  </tr>
                </tbody>
              </table>
              <div class="preview-markdown" v-html="selectedFileHtml"></div>
            </div>
          </div>
        </div>
      </template>
      <template #footer>
        <a-button @click="detailOpen = false">关闭</a-button>
        <a-button
          type="primary"
          :loading="manifestSaving"
          :disabled="!manifestDirty"
          @click="saveManifest"
        >
          保存 Manifest
        </a-button>
      </template>
    </a-modal>

    <a-modal v-model:open="importOpen" title="导入 Skill 包" :footer="null" width="520px">
      <div
        class="drop-zone"
        :class="{ 'drop-zone-active': dragOver }"
        @dragenter.prevent="onDragEnter"
        @dragover.prevent="onDragOver"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined style="font-size: 48px; color: #c2410c" />
        </p>
        <p class="ant-upload-text">拖拽 Skill 目录或 .zip 文件到此区域</p>
        <p class="ant-upload-hint">
          需包含 SKILL.md、skill.yaml 或 skill.json 清单文件
        </p>
        <a-space style="margin-top: 16px">
          <a-button @click="triggerZipInput">选择 .zip 文件</a-button>
          <a-button @click="triggerDirInput">选择文件夹</a-button>
        </a-space>
        <input
          ref="fileInputRef"
          type="file"
          accept=".zip"
          style="display: none"
          @change="onZipSelected"
        />
        <input
          ref="dirInputRef"
          type="file"
          webkitdirectory
          directory
          multiple
          style="display: none"
          @change="onDirectorySelected"
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
import { ref, reactive, computed, onMounted } from 'vue'
import { PlusOutlined, ImportOutlined, InboxOutlined } from '@ant-design/icons-vue'
import { skillApi } from '../../api'
import { message } from 'ant-design-vue'
import { marked } from 'marked'
import JSZip from 'jszip'

const loading = ref(false)
const skills = ref([])
const modalOpen = ref(false)
const saving = ref(false)
const toolsText = ref('[]')

const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const manifestSaving = ref(false)
const manifestPanelKeys = ref(['manifest'])
const manifestJsonKeys = ref([])
const manifestJsonText = ref('{}')
const savedManifestSnapshot = ref('{}')
const manifestForm = reactive({
  trigger_keywords: [],
  tool_budget: {
    max_web_search: 5,
    max_tavily_per_iter: 2,
    max_tool_rounds: 3,
    min_timeout_seconds: 180,
  },
  execution_hints: '',
})
let manifestExtraFields = {}
const selectedFileKeys = ref([])
const selectedFileContent = ref('')

const DEFAULT_TOOL_BUDGET = {
  max_web_search: 5,
  max_tavily_per_iter: 2,
  max_tool_rounds: 3,
  min_timeout_seconds: 180,
}

const manifestDirty = computed(() => {
  try {
    return JSON.stringify(getManifestForSave()) !== savedManifestSnapshot.value
  } catch {
    return true
  }
})

const manifestSummaryText = computed(() => {
  const kw = manifestForm.trigger_keywords?.length || 0
  const maxSearch = manifestForm.tool_budget?.max_web_search ?? DEFAULT_TOOL_BUDGET.max_web_search
  const minTimeout = manifestForm.tool_budget?.min_timeout_seconds ?? DEFAULT_TOOL_BUDGET.min_timeout_seconds
  return `触发词 ${kw} 个 · 搜索上限 ${maxSearch} · 最小超时 ${minTimeout}s`
})

function manifestFromDetail(record) {
  const m = record?.manifest || {}
  manifestExtraFields = { ...m }
  delete manifestExtraFields.trigger_keywords
  delete manifestExtraFields.tool_budget
  delete manifestExtraFields.execution_hints
  const tb = { ...DEFAULT_TOOL_BUDGET, ...(m.tool_budget || {}) }
  return {
    trigger_keywords: Array.isArray(m.trigger_keywords) ? [...m.trigger_keywords] : [],
    tool_budget: { ...tb },
    execution_hints: m.execution_hints || '',
  }
}

function formToManifestObject() {
  return {
    ...manifestExtraFields,
    trigger_keywords: manifestForm.trigger_keywords || [],
    tool_budget: { ...manifestForm.tool_budget },
    execution_hints: manifestForm.execution_hints || '',
  }
}

function validateManifestJson(text) {
  try {
    const parsed = JSON.parse(text || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'manifest 必须是 JSON 对象' }
    }
    return { ok: true, value: parsed }
  } catch (e) {
    return { ok: false, error: e.message || 'JSON 格式错误' }
  }
}

function applyManifestToForm(manifestObj) {
  const m = manifestObj || {}
  manifestExtraFields = { ...m }
  delete manifestExtraFields.trigger_keywords
  delete manifestExtraFields.tool_budget
  delete manifestExtraFields.execution_hints
  manifestForm.trigger_keywords = Array.isArray(m.trigger_keywords) ? [...m.trigger_keywords] : []
  manifestForm.tool_budget = { ...DEFAULT_TOOL_BUDGET, ...(m.tool_budget || {}) }
  manifestForm.execution_hints = m.execution_hints || ''
}

function syncManifestJsonFromForm() {
  manifestJsonText.value = JSON.stringify(formToManifestObject(), null, 2)
}

function applyManifestJsonToForm() {
  const result = validateManifestJson(manifestJsonText.value)
  if (!result.ok) return
  applyManifestToForm(result.value)
}

function onManifestJsonPanelChange(keys) {
  if (keys.includes('json')) {
    syncManifestJsonFromForm()
  }
}

function getManifestForSave() {
  if (manifestJsonKeys.value.includes('json')) {
    const result = validateManifestJson(manifestJsonText.value)
    if (!result.ok) {
      throw new Error(result.error)
    }
    return result.value
  }
  return formToManifestObject()
}

function loadManifestEditor(record) {
  const form = manifestFromDetail(record)
  manifestForm.trigger_keywords = form.trigger_keywords
  manifestForm.tool_budget = { ...form.tool_budget }
  manifestForm.execution_hints = form.execution_hints
  manifestJsonText.value = JSON.stringify(formToManifestObject(), null, 2)
  savedManifestSnapshot.value = manifestJsonText.value
  manifestJsonKeys.value = []
}

function resetManifestEditor() {
  manifestJsonKeys.value = []
  manifestPanelKeys.value = ['manifest']
}

async function saveManifest() {
  if (!detail.value?.skill_pack_id) return
  let payload
  try {
    payload = getManifestForSave()
  } catch (e) {
    message.error(e.message || 'Manifest JSON 格式错误')
    return
  }
  manifestSaving.value = true
  try {
    const updated = await skillApi.update(detail.value.skill_pack_id, { manifest: payload })
    detail.value = updated
    loadManifestEditor(updated)
    message.success('Manifest 已保存')
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    manifestSaving.value = false
  }
}

const importOpen = ref(false)
const importing = ref(false)
const dragOver = ref(false)
const selectedName = ref('')
const selectedFileCount = ref(0)
const fileInputRef = ref(null)
const dirInputRef = ref(null)
let importBlob = null
let importFileName = ''

const columns = [
  { title: '名称', dataIndex: 'name' },
  { title: '版本', dataIndex: 'version' },
  { title: '范围', key: 'scope', width: 100 },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 220 },
]

const form = reactive({
  name: '',
  version: '1.0.0',
  scope: 'GLOBAL',
  description: '',
  tools: [],
})

const fileTree = computed(() => {
  const files = detail.value?.package_files?.files || []
  return buildFileTree(files)
})

const singleFileHtml = computed(() => {
  if (!detail.value) return ''
  const content = getSingleFileContent(detail.value)
  return renderMarkdown(content)
})

const selectedFileHtml = computed(() => {
  const { body } = parseSkillMd(selectedFileContent.value)
  const text = body || selectedFileContent.value
  if (isMarkdownFile(selectedFileKeys.value[0])) {
    return renderMarkdown(text)
  }
  return `<pre class="preview-text">${escapeHtml(text)}</pre>`
})

const selectedFileMeta = computed(() => {
  const path = selectedFileKeys.value[0]
  if (!path || !isSkillMdPath(path)) return []
  const { frontmatter } = parseSkillMd(selectedFileContent.value)
  const rows = []
  const name = frontmatter.name || detail.value?.manifest?.name
  const desc = frontmatter.description || detail.value?.manifest?.description
  if (name) rows.push({ key: 'name', value: name })
  if (desc) rows.push({ key: 'description', value: desc })
  return rows
})

function statusLabel(status) {
  if (status === 'ACTIVE') return '已上架'
  if (status === 'ARCHIVED') return '已下架'
  return status
}

function scopeLabel(scope) {
  const map = { GLOBAL: '全局', DEPT: '部门', PRIVATE: '私有', platform: '平台' }
  return map[scope] || scope
}

function referencedSkillsText(record) {
  const refs = record?.manifest?.references || record?.manifest?.skills
  if (!refs || (Array.isArray(refs) && refs.length === 0)) return '无'
  if (Array.isArray(refs)) return refs.map(r => (typeof r === 'string' ? r : r.name || r)).join('、')
  return String(refs)
}

function isSingleFilePack(record) {
  const files = record?.package_files?.files || []
  if (files.length === 0) return true
  if (files.length === 1) return true
  const skillMdPath = record.package_files?.skill_md_path
  const others = files.filter(f => f.path !== skillMdPath)
  return others.length === 0
}

function getSingleFileContent(record) {
  const pf = record.package_files
  if (pf?.skill_md_path) {
    const file = (pf.files || []).find(f => f.path === pf.skill_md_path)
    if (file) return parseSkillMd(file.content).body
  }
  if (pf?.files?.length === 1) {
    return parseSkillMd(pf.files[0].content).body
  }
  return record.skill_content || ''
}

function buildFileTree(files) {
  const root = []
  for (const f of files) {
    const parts = f.path.split('/')
    let current = root
    let pathSoFar = ''
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      pathSoFar = pathSoFar ? `${pathSoFar}/${part}` : part
      const isLeaf = i === parts.length - 1
      if (isLeaf) {
        current.push({ title: part, key: f.path, isLeaf: true })
      } else {
        let node = current.find(n => n.key === pathSoFar && n.children)
        if (!node) {
          node = { title: part, key: pathSoFar, children: [] }
          current.push(node)
        }
        current = node.children
      }
    }
  }
  return root
}

function parseSkillMd(raw) {
  raw = (raw || '').trim()
  const frontmatter = {}
  let body = raw
  if (raw.startsWith('---')) {
    const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/)
    if (match) {
      body = match[2].trim()
      for (const line of match[1].split('\n')) {
        const m = line.match(/^([\w-]+):\s*(.+)$/)
        if (m) frontmatter[m[1]] = m[2].replace(/^["']|["']$/g, '').trim()
      }
    }
  }
  return { frontmatter, body }
}

function isSkillMdPath(path) {
  return path && path.split('/').pop().toLowerCase() === 'skill.md'
}

function isMarkdownFile(path) {
  if (!path) return false
  const bn = path.split('/').pop().toLowerCase()
  return bn.endsWith('.md') || bn.endsWith('.markdown')
}

function renderMarkdown(text) {
  if (!text) return '<p class="muted">（无内容）</p>'
  return marked.parse(text)
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function selectDefaultFile(record) {
  const files = record?.package_files?.files || []
  const defaultPath = record?.package_files?.skill_md_path
    || files.find(f => isMarkdownFile(f.path))?.path
    || files[0]?.path
  if (defaultPath) {
    selectedFileKeys.value = [defaultPath]
    const file = files.find(f => f.path === defaultPath)
    selectedFileContent.value = file?.content || ''
  } else {
    selectedFileKeys.value = []
    selectedFileContent.value = ''
  }
}

function onFileSelect(keys) {
  if (!keys.length) return
  selectedFileKeys.value = keys
  const path = keys[0]
  const file = (detail.value?.package_files?.files || []).find(f => f.path === path)
  selectedFileContent.value = file?.content || ''
}

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
  Object.assign(form, { name: '', version: '1.0.0', scope: 'GLOBAL', description: '', tools: [] })
  toolsText.value = '[]'
  modalOpen.value = true
}

async function openDetail(record) {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await skillApi.get(record.skill_pack_id)
    loadManifestEditor(detail.value)
    selectDefaultFile(detail.value)
  } catch (e) {
    message.error(e.message)
    detailOpen.value = false
  } finally {
    detailLoading.value = false
  }
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
    await skillApi.create({ ...form, tools })
    message.success('创建成功')
    modalOpen.value = false
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleUnpublish(id) {
  try {
    await skillApi.unpublish(id)
    message.success('已下架')
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  }
}

async function handlePublish(id) {
  try {
    await skillApi.publish(id)
    message.success('已上架')
    fetchSkills()
  } catch (e) {
    message.error(e.message)
  }
}

async function handleRemove(id) {
  try {
    await skillApi.delete(id)
    message.success('已删除')
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

function triggerZipInput() {
  fileInputRef.value?.click()
}

function triggerDirInput() {
  dirInputRef.value?.click()
}

function onZipSelected(e) {
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

async function onDirectorySelected(e) {
  const fileList = e.target.files
  if (!fileList || fileList.length === 0) return

  const files = Array.from(fileList).filter(f => {
    const parts = (f.webkitRelativePath || f.name).split('/')
    return !parts.some(p => p.startsWith('.'))
  })

  if (files.length === 0) {
    message.error('目录为空')
    e.target.value = ''
    return
  }

  const firstPath = files[0].webkitRelativePath || files[0].name
  const dirName = firstPath.includes('/') ? firstPath.split('/')[0] : 'skill'
  selectedName.value = dirName
  selectedFileCount.value = files.length

  const zip = new JSZip()
  for (const file of files) {
    const relPath = file.webkitRelativePath || file.name
    zip.file(relPath, file)
  }
  importBlob = await zip.generateAsync({ type: 'blob' })
  importFileName = dirName + '.zip'
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
  const entry = firstItem.webkitGetAsEntry?.()
  if (entry && entry.isDirectory) {
    await handleDirectoryDrop(entry)
    return
  }

  const file = firstItem.getAsFile?.()
  if (file) {
    handleFileDrop(file)
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

.detail-loading { text-align: center; padding: 48px; }
.detail-desc { margin-bottom: 20px; }
.manifest-collapse { margin-bottom: 20px; }
.manifest-summary { color: #666; font-size: 13px; margin-bottom: 8px; }
.manifest-hint { color: #999; font-size: 12px; margin-bottom: 12px; }
.manifest-form { margin-top: 8px; }
.manifest-json-editor { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; }
.detail-section { margin-top: 16px; }
.section-label { font-weight: 600; color: #1a1714; margin-bottom: 8px; }
.section-value { color: #444; }

.asset-single {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 16px;
  background: #fafafa;
  max-height: 480px;
  overflow-y: auto;
}

.asset-multi {
  display: flex;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  min-height: 360px;
  max-height: 480px;
  overflow: hidden;
}

.asset-tree {
  width: 220px;
  border-right: 1px solid #f0f0f0;
  padding: 12px;
  overflow-y: auto;
  background: #fafafa;
  flex-shrink: 0;
}

.asset-preview {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}

.meta-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 16px;
  font-size: 13px;
}
.meta-table td {
  border: 1px solid #f0f0f0;
  padding: 8px 12px;
}
.meta-key {
  width: 120px;
  background: #fafafa;
  color: #666;
  font-weight: 500;
}

.preview-markdown :deep(p) { margin: 0 0 8px; }
.preview-markdown :deep(h1) { font-size: 20px; margin: 16px 0 8px; }
.preview-markdown :deep(h2) { font-size: 17px; margin: 14px 0 6px; }
.preview-markdown :deep(h3) { font-size: 15px; margin: 12px 0 6px; }
.preview-markdown :deep(ul), .preview-markdown :deep(ol) { padding-left: 20px; margin: 0 0 8px; }
.preview-markdown :deep(code) {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
}
.preview-markdown :deep(pre) {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.preview-markdown :deep(.muted) { color: #999; }

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

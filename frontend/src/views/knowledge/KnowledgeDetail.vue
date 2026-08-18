<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ kb.name || '知识库详情' }}</h2>
      <a-space>
        <a-tag color="blue">{{ contextualStatusLabel }}</a-tag>
        <a-button :loading="reindexing" @click="reindexContextual">重建上下文索引</a-button>
        <a-button @click="$router.back()">
          <ArrowLeftOutlined /> 返回
        </a-button>
      </a-space>
    </div>

    <a-card :title="`知识库内容 (${files.length} 个文件)`" style="margin-bottom: 16px">
      <a-table
        :columns="fileColumns"
        :data-source="files"
        :loading="filesLoading"
        row-key="doc_id"
        :pagination="false"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'filename'">
            <FileOutlined style="margin-right: 6px; color: #c2410c" />
            {{ record.filename }}
            <div v-if="fileTagEntries(record).length" class="file-tags">
              <a-tag
                v-for="item in fileTagEntries(record)"
                :key="item.name"
                :color="item.expired ? 'red' : 'default'"
              >
                {{ item.name }} {{ item.value }}
                <span v-if="item.expired"> 已失效</span>
              </a-tag>
            </div>
          </template>
          <template v-if="column.key === 'file_type'">
            <a-tag v-if="record.file_type" color="orange">{{ record.file_type }}</a-tag>
            <a-tag v-else color="default">文本</a-tag>
          </template>
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'INACTIVE' ? 'default' : 'green'">
              {{ record.status === 'INACTIVE' ? '已下架' : '已上架' }}
            </a-tag>
          </template>
          <template v-if="column.key === 'chunk_count'">
            <a v-if="record.chunk_count > 0" @click="openChunks(record)">{{ record.chunk_count }}</a>
            <span v-else>-</span>
          </template>
          <template v-if="column.key === 'total_chars'">
            {{ record.total_chars > 1000 ? (record.total_chars / 1000).toFixed(1) + 'K' : record.total_chars }}
          </template>
          <template v-if="column.key === 'preview'">
            <span class="file-preview">{{ record.preview }}</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openDetail(record)">详情</a>
              <a v-if="hasTagDefs" @click="openEditTags(record)">编辑标签</a>
              <a v-if="record.status !== 'INACTIVE'" @click="setStatus(record, 'INACTIVE')">下架</a>
              <a v-else @click="setStatus(record, 'ACTIVE')">上架</a>
              <a-popconfirm title="确认从知识库删除该文档？" @confirm="removeFile(record)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
      <a-empty v-if="!filesLoading && files.length === 0" description="暂无文件，请上传或粘贴文档" />
    </a-card>

    <a-card title="知识库检索" style="margin-bottom: 16px">
      <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 12px">
        <span style="color: #666; white-space: nowrap">检索模式</span>
        <a-radio-group v-model:value="searchMode" size="small" button-style="solid">
          <a-radio-button value="hybrid">混合</a-radio-button>
          <a-radio-button value="vector">向量</a-radio-button>
          <a-radio-button value="bm25">关键词</a-radio-button>
        </a-radio-group>
      </div>
      <a-input-search
        v-model:value="searchQuery"
        placeholder="输入搜索内容..."
        enter-button="搜索"
        @search="searchKnowledge"
        :loading="searching"
      />
      <div v-if="hasTagDefs" class="tag-filter-panel">
        <div class="tag-filter-title">标签条件（可清空，空则不限制）</div>
        <div v-for="item in tagFilterForm" :key="item.name" class="tag-filter-row">
          <span class="tag-filter-name">{{ item.name }}</span>
          <a-select v-if="item.type === 'date'" v-model:value="item.op" style="width: 88px" size="small">
            <a-select-option value="eq">等于</a-select-option>
            <a-select-option value="gte">≥</a-select-option>
            <a-select-option value="lte">≤</a-select-option>
            <a-select-option value="gt">&gt;</a-select-option>
            <a-select-option value="lt">&lt;</a-select-option>
          </a-select>
          <a-select v-else v-model:value="item.op" style="width: 88px" size="small">
            <a-select-option value="eq">等于</a-select-option>
            <a-select-option value="contains">包含</a-select-option>
          </a-select>
          <a-date-picker
            v-if="item.type === 'date'"
            v-model:value="item.value"
            value-format="YYYY/MM/DD"
            style="flex: 1"
            size="small"
            allow-clear
          />
          <a-input v-else v-model:value="item.value" allow-clear size="small" style="flex: 1" placeholder="不填则不限制" />
        </div>
      </div>
      <div v-if="searchResults.length > 0" style="margin-top: 16px">
        <div class="search-time">查询耗时: {{ searchTime }}ms</div>
        <div v-if="appliedFilters.length" class="applied-filters">
          已按标签筛选：
          <a-tag v-for="(f, i) in appliedFilters" :key="i">{{ f.name }} {{ opLabel(f.op) }} {{ f.value }}</a-tag>
        </div>
        <div v-for="(r, i) in searchResults" :key="i" class="search-result">
          <div class="search-score">
            {{ formatScore(r, i) }}
            <span v-if="r.sources?.length" class="search-sources">
              · {{ formatSources(r.sources) }}
            </span>
          </div>
          <div class="search-content">{{ r.content }}</div>
          <div v-if="resultTagEntries(r).length" class="file-tags">
            <a-tag v-for="item in resultTagEntries(r)" :key="item.name" :color="item.expired ? 'red' : 'orange'">
              {{ item.name }} {{ item.value }}
              <span v-if="item.expired"> 已失效</span>
            </a-tag>
          </div>
          <div v-if="r.metadata?.contextual_prefix" class="search-prefix">
            上下文前缀: {{ r.metadata.contextual_prefix }}
          </div>
        </div>
      </div>
      <div v-else-if="searchQuery && !searching" style="margin-top: 16px; color: #9e9590">
        暂无搜索结果
      </div>
    </a-card>

    <a-card title="导入内容" style="margin-bottom: 16px">
      <a-radio-group v-model:value="importMode" style="margin-bottom: 16px">
        <a-radio-button value="file">导入文件</a-radio-button>
        <a-radio-button value="text">输入文本</a-radio-button>
      </a-radio-group>

      <div v-if="importMode === 'file'">
        <a-upload-dragger
          :multiple="true"
          :before-upload="beforeUpload"
          :show-upload-list="false"
          :disabled="uploading"
          accept=".pdf,.docx,.doc,.txt,.md,.markdown,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.gif"
        >
          <p class="upload-icon">
            <InboxOutlined style="font-size: 40px; color: #c2410c" />
          </p>
          <p class="upload-text">点击或拖拽文件到此处上传</p>
          <p class="upload-hint">支持 PDF、DOCX、XLSX、TXT、Markdown、图片格式</p>
        </a-upload-dragger>
        <div v-if="uploading" style="margin-top: 12px; text-align: center">
          <a-spin />
          <span style="margin-left: 8px; color: #c2410c">{{ uploadingHint }}</span>
        </div>
        <div v-if="uploadResult" style="margin-top: 12px">
          <a-alert :message="uploadResult" type="success" show-icon />
        </div>
      </div>

      <div v-else>
        <a-textarea
          v-model:value="docForm.content"
          :rows="10"
          placeholder="粘贴或输入文档内容，自动按段落切片..."
        />
        <div style="margin-top: 12px; text-align: right">
          <a-button type="primary" @click="addDocument" :loading="addingDoc">添加文本</a-button>
        </div>
      </div>
    </a-card>

    <a-modal
      v-model:open="previewOpen"
      :title="previewTitle"
      width="860px"
      :footer="null"
      destroy-on-close
      @cancel="closePreview"
    >
      <div v-if="previewLoading" style="text-align: center; padding: 48px">
        <a-spin tip="加载中..." />
      </div>
      <template v-else>
        <iframe
          v-if="previewKind === 'pdf'"
          :src="previewUrl"
          class="preview-frame"
        />
        <img
          v-else-if="previewKind === 'image'"
          :src="previewUrl"
          class="preview-image"
          alt="preview"
        />
        <div
          v-else-if="previewKind === 'markdown'"
          class="preview-markdown"
          v-html="previewHtml"
        />
        <pre v-else class="preview-text">{{ previewText }}</pre>
      </template>
    </a-modal>

    <a-modal
      v-model:open="chunksOpen"
      :title="chunksTitle"
      width="920px"
      :footer="null"
      destroy-on-close
    >
      <a-table
        :columns="chunkColumns"
        :data-source="chunksList"
        :loading="chunksLoading"
        row-key="chunk_id"
        size="small"
        :pagination="chunksList.length > 10 ? { pageSize: 10 } : false"
      >
        <template #expandedRowRender="{ record }">
          <div class="chunk-expand">
            <div class="chunk-expand-label">上下文前缀</div>
            <div class="search-prefix">{{ record.contextual_prefix || '未生成' }}</div>
            <div class="chunk-expand-label" style="margin-top: 12px">原文内容</div>
            <pre class="chunk-full-content">{{ record.content }}</pre>
          </div>
        </template>
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'chunk_id'">
            <span class="chunk-id">{{ record.chunk_id }}</span>
          </template>
          <template v-if="column.key === 'contextualized'">
            <a-tag v-if="record.contextualized" color="green">已上下文化</a-tag>
            <a-tag v-else color="default">无</a-tag>
          </template>
          <template v-if="column.key === 'content'">
            <span class="chunk-preview">{{ record.content }}</span>
          </template>
        </template>
      </a-table>
    </a-modal>

    <a-modal
      v-model:open="importTagOpen"
      :title="`确认文档标签 · ${importPreview.filename || ''}`"
      :confirm-loading="importConfirming"
      ok-text="确认入库"
      cancel-text="取消"
      @ok="confirmImportTags"
      @cancel="cancelImportTags"
    >
      <p class="field-hint">未能自动识别的字段可跳过，不强制填写。</p>
      <a-form layout="vertical">
        <a-form-item v-for="item in importTagForm" :key="item.name" :label="item.name">
          <a-date-picker
            v-if="item.type === 'date'"
            v-model:value="item.value"
            value-format="YYYY/MM/DD"
            style="width: 100%"
            allow-clear
          />
          <a-input v-else v-model:value="item.value" allow-clear :placeholder="item.hint || '可选'" />
          <div v-if="item.source === 'empty'" class="tag-empty-hint">未能自动识别，请填写</div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="editTagsOpen"
      title="编辑文档标签"
      :confirm-loading="editTagsSaving"
      @ok="saveEditTags"
    >
      <a-form layout="vertical">
        <a-form-item v-for="item in editTagForm" :key="item.name" :label="item.name">
          <a-date-picker
            v-if="item.type === 'date'"
            v-model:value="item.value"
            value-format="YYYY/MM/DD"
            style="width: 100%"
            allow-clear
          />
          <a-input v-else v-model:value="item.value" allow-clear />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeftOutlined, InboxOutlined, FileOutlined } from '@ant-design/icons-vue'
import { knowledgeApi, configApi } from '../../api'
import { message } from 'ant-design-vue'
import { marked } from 'marked'

const route = useRoute()
const kbId = route.params.id
const kb = reactive({})
const docForm = reactive({ content: '', metadata: {} })
const addingDoc = ref(false)
const uploading = ref(false)
const uploadResult = ref('')
const importMode = ref('file')
const searchQuery = ref('')
const searchMode = ref('hybrid')
const searching = ref(false)
const searchResults = ref([])
const searchTime = ref(0)
const files = ref([])
const filesLoading = ref(false)
const globalContextualEnabled = ref(false)
const reindexing = ref(false)
const hasTagDefs = computed(() => Array.isArray(kb.tag_defs) && kb.tag_defs.length > 0)
const uploadingHint = computed(() => (
  hasTagDefs.value ? '正在解析并抽取标签...' : '正在解析并生成上下文索引...'
))
const tagFilterForm = ref([])
const appliedFilters = ref([])
let lastSuggestedQuery = ''
const uploadQueue = []
let queueRunning = false
const importTagOpen = ref(false)
const importConfirming = ref(false)
const importPreview = reactive({ preview_id: '', filename: '' })
const importTagForm = ref([])
let importWaiter = null
const editTagsOpen = ref(false)
const editTagsSaving = ref(false)
const editTagForm = ref([])
const editTagDocId = ref('')

const contextualStatusLabel = computed(() => {
  if (kb.contextual_retrieval_enabled === true) return '上下文感知: 已启用'
  if (kb.contextual_retrieval_enabled === false) return '上下文感知: 已关闭'
  return globalContextualEnabled.value ? '上下文感知: 跟随全局(开)' : '上下文感知: 跟随全局(关)'
})

const previewOpen = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const previewKind = ref('text')
const previewUrl = ref('')
const previewText = ref('')
const previewHtml = ref('')
let previewObjectUrl = ''

const chunksOpen = ref(false)
const chunksLoading = ref(false)
const chunksDoc = reactive({ doc_id: '', filename: '' })
const chunksList = ref([])
const chunksTitle = computed(() => {
  const name = chunksDoc.filename || '文档'
  return `${name} · 共 ${chunksList.value.length} 个分块`
})

const fileColumns = [
  { title: '文件名', key: 'filename', ellipsis: true },
  { title: '类型', key: 'file_type', width: 80 },
  { title: '状态', key: 'status', width: 90 },
  { title: '分块数', key: 'chunk_count', width: 80 },
  { title: '总字符', key: 'total_chars', width: 80 },
  { title: '内容预览', key: 'preview', ellipsis: true },
  { title: '操作', key: 'action', width: 240 },
]

const chunkColumns = [
  { title: '序号', dataIndex: 'index', width: 60 },
  { title: '分块 ID', key: 'chunk_id', width: 120 },
  { title: '字符数', dataIndex: 'char_count', width: 80 },
  { title: '上下文', key: 'contextualized', width: 110 },
  { title: '内容', key: 'content', ellipsis: true },
]

onMounted(async () => {
  try {
    const [res, cfg] = await Promise.all([
      knowledgeApi.get(kbId),
      configApi.getContextualRetrieval().catch(() => ({ enabled: false })),
    ])
    Object.assign(kb, res)
    globalContextualEnabled.value = !!cfg.enabled
    tagFilterForm.value = emptyFilterRows()
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  }
})

onUnmounted(() => {
  revokePreviewUrl()
})

function revokePreviewUrl() {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = ''
  }
  previewUrl.value = ''
}

async function fetchFiles() {
  filesLoading.value = true
  try {
    const res = await knowledgeApi.listFiles(kbId)
    files.value = res.files
  } catch (e) {
    message.error(e.message)
  } finally {
    filesLoading.value = false
  }
}

async function beforeUpload(file) {
  uploadQueue.push(file)
  if (queueRunning) return false
  queueRunning = true
  uploading.value = true
  uploadResult.value = ''
  try {
    while (uploadQueue.length) {
      await processOneFile(uploadQueue.shift())
    }
    const kbres = await knowledgeApi.get(kbId)
    Object.assign(kb, kbres)
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  } finally {
    uploading.value = false
    queueRunning = false
  }
  return false
}

function todayStr() {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}/${m}/${day}`
}

function parseDateValue(value) {
  const match = String(value || '').match(/(20\d{2})[./\-年](\d{1,2})[./\-月]?(\d{1,2})/)
  if (!match) return ''
  return `${match[1]}/${String(match[2]).padStart(2, '0')}/${String(match[3]).padStart(2, '0')}`
}

function isExpireTagName(name) {
  return /失效|过期|废止/.test(name || '')
}

function isExpiredValue(value) {
  const parsed = parseDateValue(value)
  return !!parsed && parsed < todayStr()
}

function fileTagEntries(record) {
  const tags = record.tags || {}
  return Object.entries(tags)
    .filter(([, v]) => v)
    .map(([name, value]) => ({
      name,
      value,
      expired: isExpireTagName(name) && isExpiredValue(value),
    }))
}

function resultTagEntries(r) {
  return fileTagEntries({ tags: r.tags || r.metadata?.tags || {} })
}

function opLabel(op) {
  return { eq: '=', contains: '包含', gte: '≥', lte: '≤', gt: '>', lt: '<' }[op] || op
}

function emptyFilterRows() {
  return (kb.tag_defs || []).map((d) => ({
    name: d.name,
    type: d.type === 'date' ? 'date' : 'text',
    op: 'eq',
    value: '',
  }))
}

function applySuggestedFilters(filters) {
  const byName = Object.fromEntries((filters || []).map((f) => [f.name, f]))
  tagFilterForm.value = (kb.tag_defs || []).map((d) => {
    const suggested = byName[d.name]
    return {
      name: d.name,
      type: d.type === 'date' ? 'date' : 'text',
      op: suggested?.op || 'eq',
      value: suggested?.value || '',
    }
  })
}

function currentTagFilters() {
  return tagFilterForm.value
    .filter((item) => String(item.value || '').trim())
    .map((item) => ({
      name: item.name,
      op: item.op || 'eq',
      value: String(item.value).trim(),
    }))
}

function tagsFromForm(rows) {
  const out = {}
  for (const item of rows || []) {
    const value = String(item.value || '').trim()
    if (value) out[item.name] = value
  }
  return out
}

function fillImportTagForm(extracted) {
  const byName = Object.fromEntries((extracted || []).map((t) => [t.name, t]))
  importTagForm.value = (kb.tag_defs || []).map((d) => {
    const found = byName[d.name] || {}
    return {
      name: d.name,
      type: d.type === 'date' ? 'date' : 'text',
      hint: d.hint || '',
      value: found.value || '',
      source: found.source || (found.value ? 'heuristic' : 'empty'),
    }
  })
}

function waitImportDecision() {
  return new Promise((resolve) => {
    importWaiter = resolve
  })
}

async function processOneFile(file) {
  if (!hasTagDefs.value) {
    const formData = new FormData()
    formData.append('file', file, file.name)
    const res = await knowledgeApi.uploadFile(kbId, formData)
    uploadResult.value = res.message
    return
  }
  const formData = new FormData()
  formData.append('file', file, file.name)
  const preview = await knowledgeApi.previewImport(kbId, formData)
  importPreview.preview_id = preview.preview_id
  importPreview.filename = preview.filename
  fillImportTagForm(preview.tags)
  importTagOpen.value = true
  const decision = await waitImportDecision()
  if (!decision?.ok) {
    await knowledgeApi.cancelImport(kbId, preview.preview_id).catch(() => {})
  }
}

async function confirmImportTags() {
  if (!importPreview.preview_id) {
    importTagOpen.value = false
    return
  }
  importConfirming.value = true
  try {
    const res = await knowledgeApi.confirmImport(kbId, {
      preview_id: importPreview.preview_id,
      tags: tagsFromForm(importTagForm.value),
    })
    uploadResult.value = res.message
    importTagOpen.value = false
    const waiter = importWaiter
    importWaiter = null
    waiter && waiter({ ok: true })
  } catch (e) {
    message.error(e.message)
  } finally {
    importConfirming.value = false
  }
}

function cancelImportTags() {
  const waiter = importWaiter
  importWaiter = null
  waiter && waiter({ ok: false })
}

async function addDocument() {
  if (!docForm.content.trim()) {
    message.warning('请输入文档内容')
    return
  }
  addingDoc.value = true
  try {
    if (!hasTagDefs.value) {
      const res = await knowledgeApi.addDocuments(kbId, {
        content: docForm.content,
        metadata: docForm.metadata,
      })
      message.success(`添加成功，共 ${res.chunk_count} 个分块`)
    } else {
      const preview = await knowledgeApi.previewImportText(kbId, {
        content: docForm.content,
        filename: '粘贴文本.txt',
      })
      importPreview.preview_id = preview.preview_id
      importPreview.filename = preview.filename
      fillImportTagForm(preview.tags)
      importTagOpen.value = true
      const decision = await waitImportDecision()
      if (!decision?.ok) {
        await knowledgeApi.cancelImport(kbId, preview.preview_id).catch(() => {})
        return
      }
      message.success(uploadResult.value || '添加成功')
    }
    docForm.content = ''
    const kbres = await knowledgeApi.get(kbId)
    Object.assign(kb, kbres)
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  } finally {
    addingDoc.value = false
  }
}

async function searchKnowledge() {
  if (!searchQuery.value.trim()) return
  searching.value = true
  try {
    if (hasTagDefs.value && searchQuery.value !== lastSuggestedQuery) {
      const sug = await knowledgeApi.suggestSearchFilters(kbId, { query: searchQuery.value })
      applySuggestedFilters(sug.filters || [])
      lastSuggestedQuery = searchQuery.value
    }
    const res = await knowledgeApi.search(kbId, {
      query: searchQuery.value,
      top_k: 5,
      mode: searchMode.value,
      tag_filters: currentTagFilters(),
    })
    searchResults.value = res.results
    searchTime.value = res.query_time_ms
    appliedFilters.value = res.applied_filters || []
  } catch (e) {
    message.error(e.message)
  } finally {
    searching.value = false
  }
}

function openEditTags(record) {
  editTagDocId.value = record.doc_id
  const tags = record.tags || {}
  editTagForm.value = (kb.tag_defs || []).map((d) => ({
    name: d.name,
    type: d.type === 'date' ? 'date' : 'text',
    value: tags[d.name] || '',
  }))
  editTagsOpen.value = true
}

async function saveEditTags() {
  editTagsSaving.value = true
  try {
    await knowledgeApi.updateFileTags(kbId, editTagDocId.value, {
      tags: tagsFromForm(editTagForm.value),
    })
    message.success('已更新文档标签')
    editTagsOpen.value = false
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  } finally {
    editTagsSaving.value = false
  }
}

async function openChunks(record) {
  chunksOpen.value = true
  chunksLoading.value = true
  chunksList.value = []
  chunksDoc.doc_id = record.doc_id
  chunksDoc.filename = record.filename || '文档'
  try {
    const res = await knowledgeApi.listFileChunks(kbId, record.doc_id)
    chunksDoc.filename = res.filename || chunksDoc.filename
    chunksList.value = res.chunks || []
  } catch (e) {
    message.error(e.message)
    chunksOpen.value = false
  } finally {
    chunksLoading.value = false
  }
}

async function reindexContextual() {
  reindexing.value = true
  try {
    const res = await knowledgeApi.reindexContextual(kbId)
    message.success(
      `${res.message || '重建完成'} · ${res.processed_chunks || 0} 块，`
      + `已上下文化 ${res.contextualized_count || 0} 块`
    )
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  } finally {
    reindexing.value = false
  }
}

function formatSources(sources) {
  const map = { vector: '向量', bm25: '关键词' }
  return (sources || []).map((s) => map[s] || s).join('+')
}

function formatScore(r, index) {
  if (searchMode.value === 'hybrid') {
    const rrf = Number(r.score || 0).toFixed(4)
    return `排名 #${index + 1} · RRF ${rrf}`
  }
  return `相似度: ${(Number(r.score || 0) * 100).toFixed(1)}%`
}

async function setStatus(record, status) {
  try {
    await knowledgeApi.updateFileStatus(kbId, record.doc_id, { status })
    message.success(status === 'ACTIVE' ? '已上架' : '已下架')
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  }
}

async function removeFile(record) {
  try {
    await knowledgeApi.deleteFile(kbId, record.doc_id)
    message.success('文档已删除')
    const kbres = await knowledgeApi.get(kbId)
    Object.assign(kb, kbres)
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  }
}

function normalizeType(fileType) {
  return String(fileType || '').replace(/^\./, '').toLowerCase()
}

function closePreview() {
  previewOpen.value = false
  revokePreviewUrl()
  previewText.value = ''
  previewHtml.value = ''
}

async function openDetail(record) {
  previewOpen.value = true
  previewLoading.value = true
  previewTitle.value = record.filename || '文档详情'
  revokePreviewUrl()
  previewText.value = ''
  previewHtml.value = ''

  const ft = normalizeType(record.file_type)
  const isImage = ['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ft)
  const isPdf = ft === 'pdf'
  const preferText = ['docx', 'doc', 'xlsx', 'xls', 'txt', 'md', 'markdown', ''].includes(ft) || record.source === 'paste'

  try {
    if (isPdf || isImage) {
      const blob = await knowledgeApi.getFileContent(kbId, record.doc_id)
      if (blob.type && blob.type.includes('application/json')) {
        const json = JSON.parse(await blob.text())
        previewKind.value = 'text'
        previewText.value = json.content || ''
      } else {
        previewObjectUrl = URL.createObjectURL(blob)
        previewUrl.value = previewObjectUrl
        previewKind.value = isPdf ? 'pdf' : 'image'
      }
    } else {
      const blob = await knowledgeApi.getFileContent(kbId, record.doc_id, preferText ? { as_text: true } : undefined)
      if (blob.type && blob.type.includes('application/json')) {
        const json = JSON.parse(await blob.text())
        const content = json.content || ''
        if (['md', 'markdown'].includes(normalizeType(json.file_type) || ft)) {
          previewKind.value = 'markdown'
          previewHtml.value = marked.parse(content)
        } else {
          previewKind.value = 'text'
          previewText.value = content
        }
      } else {
        const text = await blob.text()
        if (['md', 'markdown'].includes(ft)) {
          previewKind.value = 'markdown'
          previewHtml.value = marked.parse(text)
        } else {
          previewKind.value = 'text'
          previewText.value = text
        }
      }
    }
  } catch (e) {
    message.error(e.message || '预览失败')
    previewOpen.value = false
  } finally {
    previewLoading.value = false
  }
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.upload-icon { margin-bottom: 8px; }
.upload-text { font-size: 14px; color: #1a1714; }
.upload-hint { font-size: 12px; color: #9e9590; }
.search-time { font-size: 12px; color: #9e9590; margin-bottom: 12px; }
.search-result { padding: 12px; margin-bottom: 8px; background: #f3f0e8; border-radius: 6px; }
.search-score { font-size: 11px; color: #c2410c; margin-bottom: 4px; font-family: 'JetBrains Mono', monospace; }
.search-sources { color: #9e9590; font-weight: normal; }
.search-content { font-size: 13px; color: #3a342e; line-height: 1.6; white-space: pre-wrap; }
.search-prefix { font-size: 12px; color: #9e9590; margin-top: 6px; line-height: 1.5; }
.file-preview { font-size: 12px; color: #9e9590; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.chunk-id { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: #5c5650; }
.chunk-preview {
  font-size: 12px;
  color: #3a342e;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
}
.chunk-expand { padding: 4px 8px 12px; }
.chunk-expand-label { font-size: 12px; color: #9e9590; margin-bottom: 4px; }
.chunk-full-content {
  margin: 0;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  color: #3a342e;
  line-height: 1.6;
  background: #f3f0e8;
  padding: 12px;
  border-radius: 6px;
}
.preview-frame { width: 100%; height: 70vh; border: 1px solid #e8e2d9; border-radius: 6px; }
.preview-image { max-width: 100%; max-height: 70vh; display: block; margin: 0 auto; }
.preview-text {
  margin: 0;
  max-height: 70vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  background: #faf8f5;
  padding: 12px;
  border-radius: 6px;
}
.preview-markdown {
  max-height: 70vh;
  overflow: auto;
  line-height: 1.6;
  font-size: 14px;
}
.file-tags { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.tag-filter-panel { margin-top: 12px; padding: 12px; background: #faf8f5; border-radius: 6px; }
.tag-filter-title { font-size: 12px; color: #9e9590; margin-bottom: 8px; }
.tag-filter-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.tag-filter-name { width: 88px; color: #3a342e; flex-shrink: 0; }
.applied-filters { font-size: 12px; color: #5c5650; margin-bottom: 10px; }
.tag-empty-hint { font-size: 12px; color: #d97706; margin-top: 4px; }
.field-hint { font-size: 12px; color: #9e9590; margin-bottom: 8px; }
</style>

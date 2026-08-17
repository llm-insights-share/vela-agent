<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ kb.name || '知识库详情' }}</h2>
      <a-button @click="$router.back()">
        <ArrowLeftOutlined /> 返回
      </a-button>
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
          <template v-if="column.key === 'total_chars'">
            {{ record.total_chars > 1000 ? (record.total_chars / 1000).toFixed(1) + 'K' : record.total_chars }}
          </template>
          <template v-if="column.key === 'preview'">
            <span class="file-preview">{{ record.preview }}</span>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openDetail(record)">详情</a>
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
      <div v-if="searchResults.length > 0" style="margin-top: 16px">
        <div class="search-time">查询耗时: {{ searchTime }}ms</div>
        <div v-for="(r, i) in searchResults" :key="i" class="search-result">
          <div class="search-score">
            {{ formatScore(r, i) }}
            <span v-if="r.sources?.length" class="search-sources">
              · {{ formatSources(r.sources) }}
            </span>
          </div>
          <div class="search-content">{{ r.content }}</div>
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
          <span style="margin-left: 8px; color: #c2410c">正在解析文件...</span>
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
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeftOutlined, InboxOutlined, FileOutlined } from '@ant-design/icons-vue'
import { knowledgeApi } from '../../api'
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

const previewOpen = ref(false)
const previewLoading = ref(false)
const previewTitle = ref('')
const previewKind = ref('text')
const previewUrl = ref('')
const previewText = ref('')
const previewHtml = ref('')
let previewObjectUrl = ''

const fileColumns = [
  { title: '文件名', key: 'filename', ellipsis: true },
  { title: '类型', key: 'file_type', width: 80 },
  { title: '状态', key: 'status', width: 90 },
  { title: '分块数', dataIndex: 'chunk_count', width: 80 },
  { title: '总字符', key: 'total_chars', width: 80 },
  { title: '内容预览', key: 'preview', ellipsis: true },
  { title: '操作', key: 'action', width: 180 },
]

onMounted(async () => {
  try {
    const res = await knowledgeApi.get(kbId)
    Object.assign(kb, res)
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
  uploading.value = true
  uploadResult.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file, file.name)
    const res = await knowledgeApi.uploadFile(kbId, formData)
    uploadResult.value = res.message
    const kbres = await knowledgeApi.get(kbId)
    Object.assign(kb, kbres)
    await fetchFiles()
  } catch (e) {
    message.error(e.message)
  } finally {
    uploading.value = false
  }
  return false
}

async function addDocument() {
  if (!docForm.content.trim()) {
    message.warning('请输入文档内容')
    return
  }
  addingDoc.value = true
  try {
    const res = await knowledgeApi.addDocuments(kbId, {
      content: docForm.content,
      metadata: docForm.metadata,
    })
    message.success(`添加成功，共 ${res.chunk_count} 个分块`)
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
    const res = await knowledgeApi.search(kbId, {
      query: searchQuery.value,
      top_k: 5,
      mode: searchMode.value,
    })
    searchResults.value = res.results
    searchTime.value = res.query_time_ms
  } catch (e) {
    message.error(e.message)
  } finally {
    searching.value = false
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
.file-preview { font-size: 12px; color: #9e9590; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
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
</style>

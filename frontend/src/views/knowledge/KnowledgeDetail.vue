<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">{{ kb.name || '知识库详情' }}</h2>
      <a-button @click="$router.back()">
        <ArrowLeftOutlined /> 返回
      </a-button>
    </div>

    <a-row :gutter="16">
      <a-col :span="14">
        <a-card title="导入文件" style="margin-bottom: 16px">
          <a-upload-dragger
            :multiple="true"
            :before-upload="beforeUpload"
            :show-upload-list="false"
            :disabled="uploading"
            accept=".pdf,.docx,.doc,.txt,.md,.markdown"
          >
            <p class="upload-icon">
              <InboxOutlined style="font-size: 40px; color: #c2410c" />
            </p>
            <p class="upload-text">点击或拖拽文件到此处上传</p>
            <p class="upload-hint">支持 PDF、DOCX、TXT、Markdown 格式</p>
          </a-upload-dragger>
          <div v-if="uploading" style="margin-top: 12px; text-align: center">
            <a-spin />
            <span style="margin-left: 8px; color: #c2410c">正在解析文件...</span>
          </div>
          <div v-if="uploadResult" style="margin-top: 12px">
            <a-alert :message="uploadResult" type="success" show-icon />
          </div>
        </a-card>

        <a-card title="粘贴文本" style="margin-bottom: 16px">
          <a-textarea v-model:value="docForm.content" :rows="10" placeholder="粘贴文档内容，自动按段落切片..." />
          <div style="margin-top: 12px; text-align: right">
            <a-button type="primary" @click="addDocument" :loading="addingDoc">添加文本</a-button>
          </div>
        </a-card>

        <a-card :title="`知识库内容 (${files.length} 个文件)`" style="margin-bottom: 16px">
          <a-table
            :columns="fileColumns"
            :data-source="files"
            :loading="filesLoading"
            row-key="filename"
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
              <template v-if="column.key === 'total_chars'">
                {{ record.total_chars > 1000 ? (record.total_chars / 1000).toFixed(1) + 'K' : record.total_chars }}
              </template>
              <template v-if="column.key === 'preview'">
                <span class="file-preview">{{ record.preview }}</span>
              </template>
            </template>
          </a-table>
          <a-empty v-if="!filesLoading && files.length === 0" description="暂无文件，请上传或粘贴文档" />
        </a-card>
      </a-col>
      <a-col :span="10">
        <a-card title="知识库检索" style="margin-bottom: 16px">
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
              <div class="search-score">相似度: {{ (r.score * 100).toFixed(1) }}%</div>
              <div class="search-content">{{ r.content }}</div>
            </div>
          </div>
          <div v-else-if="searchQuery && !searching" style="margin-top: 16px; color: #9e9590">
            暂无搜索结果
          </div>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeftOutlined, InboxOutlined, FileOutlined } from '@ant-design/icons-vue'
import { knowledgeApi } from '../../api'
import { message } from 'ant-design-vue'

const route = useRoute()
const kbId = route.params.id
const kb = reactive({})
const docForm = reactive({ content: '', metadata: {} })
const addingDoc = ref(false)
const uploading = ref(false)
const uploadResult = ref('')
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref([])
const searchTime = ref(0)
const files = ref([])
const filesLoading = ref(false)

const fileColumns = [
  { title: '文件名', key: 'filename', ellipsis: true },
  { title: '类型', key: 'file_type', width: 80 },
  { title: '分块数', dataIndex: 'chunk_count', width: 80 },
  { title: '总字符', key: 'total_chars', width: 80 },
  { title: '内容预览', key: 'preview', ellipsis: true },
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
    })
    searchResults.value = res.results
    searchTime.value = res.query_time_ms
  } catch (e) {
    message.error(e.message)
  } finally {
    searching.value = false
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
.search-content { font-size: 13px; color: #3a342e; line-height: 1.6; white-space: pre-wrap; }
.file-preview { font-size: 12px; color: #9e9590; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
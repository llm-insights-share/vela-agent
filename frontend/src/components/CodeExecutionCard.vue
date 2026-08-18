<template>
  <div class="code-exec-card">
    <div class="code-exec-header" @click="expanded = !expanded">
      <CaretRightOutlined v-if="!expanded" style="font-size: 10px;" />
      <CaretDownOutlined v-else style="font-size: 10px;" />
      <CodeOutlined style="margin: 0 6px;" />
      <span class="code-exec-title">{{ exec.language || 'python' }} 代码执行</span>
      <a-tag :color="exec.success ? 'green' : 'red'" size="small">
        {{ exec.success ? '成功' : '失败' }}
      </a-tag>
      <span v-if="exec.duration_ms" class="code-exec-meta">{{ exec.duration_ms }}ms</span>
      <span v-if="exec.exit_code != null && !exec.success" class="code-exec-meta">exit {{ exec.exit_code }}</span>
    </div>

    <div v-if="expanded" class="code-exec-body">
      <div class="code-exec-section">
        <div class="code-exec-section-head">
          <span>代码</span>
          <a-space size="small">
            <a-button type="link" size="small" @click="copyCode">复制</a-button>
            <a-button type="link" size="small" @click="downloadCode">下载</a-button>
          </a-space>
        </div>
        <pre class="code-exec-code"><code v-html="highlightedCode"></code></pre>
      </div>

      <div v-if="exec.stdout" class="code-exec-section">
        <div class="code-exec-section-head"><span>stdout</span></div>
        <pre class="code-exec-output">{{ exec.stdout }}</pre>
      </div>

      <div v-if="exec.stderr" class="code-exec-section">
        <div class="code-exec-section-head"><span>stderr</span></div>
        <pre class="code-exec-output code-exec-stderr">{{ exec.stderr }}</pre>
      </div>

      <div v-if="exec.error && !exec.success" class="code-exec-section">
        <div class="code-exec-section-head"><span>错误</span></div>
        <pre class="code-exec-output code-exec-stderr">{{ exec.error }}</pre>
      </div>

      <div v-if="imageArtifacts.length" class="code-exec-section">
        <div class="code-exec-section-head"><span>产物</span></div>
        <div class="code-exec-artifacts">
          <div v-for="(art, i) in imageArtifacts" :key="i" class="code-exec-artifact">
            <img :src="art.url" :alt="art.name" class="code-exec-img" />
            <div class="code-exec-artifact-name">{{ art.name }}</div>
          </div>
          <a-tag
            v-for="(art, i) in fileArtifacts"
            :key="'f-' + i"
            color="blue"
            class="code-exec-file-chip"
          >
            <a :href="art.url" target="_blank" rel="noopener">{{ art.name }}</a>
            <span v-if="art.size_display"> ({{ art.size_display }})</span>
          </a-tag>
        </div>
      </div>
      <div v-else-if="fileArtifacts.length" class="code-exec-section">
        <div class="code-exec-section-head"><span>产物</span></div>
        <a-space wrap>
          <a-tag v-for="(art, i) in fileArtifacts" :key="i" color="blue">
            <a :href="art.url" target="_blank" rel="noopener">{{ art.name }}</a>
          </a-tag>
        </a-space>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import { CaretRightOutlined, CaretDownOutlined, CodeOutlined } from '@ant-design/icons-vue'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'

hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)

const props = defineProps({
  exec: { type: Object, required: true },
  defaultExpanded: { type: Boolean, default: false },
})

const expanded = ref(props.defaultExpanded)

const highlightedCode = computed(() => {
  const lang = props.exec.language || 'python'
  const code = props.exec.code || ''
  try {
    if (hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value
    }
  } catch (_) { /* ignore */ }
  return code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
})

const imageArtifacts = computed(() =>
  (props.exec.artifacts || []).filter(a => a.kind === 'image' && a.url)
)

const fileArtifacts = computed(() =>
  (props.exec.artifacts || []).filter(a => a.kind !== 'image' && a.url)
)

function copyCode() {
  navigator.clipboard.writeText(props.exec.code || '').then(() => {
    message.success('已复制代码')
  }).catch(() => message.error('复制失败'))
}

function downloadCode() {
  const ext = props.exec.language === 'javascript' ? '.js' : '.py'
  const blob = new Blob([props.exec.code || ''], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `code${ext}`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.code-exec-card {
  margin: 8px 0;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fafafa;
  overflow: hidden;
}
.code-exec-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
}
.code-exec-header:hover { background: #f0f0f0; }
.code-exec-title { font-weight: 500; margin-right: 8px; }
.code-exec-meta { margin-left: 8px; color: #999; font-size: 12px; }
.code-exec-body { padding: 0 12px 12px; }
.code-exec-section { margin-top: 10px; }
.code-exec-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #666;
  margin-bottom: 4px;
}
.code-exec-code {
  margin: 0;
  padding: 10px 12px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 320px;
}
.code-exec-output {
  margin: 0;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}
.code-exec-stderr { color: #cf1322; background: #fff2f0; }
.code-exec-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-start;
}
.code-exec-artifact { text-align: center; }
.code-exec-img {
  max-width: 100%;
  max-height: 280px;
  border-radius: 6px;
  border: 1px solid #eee;
}
.code-exec-artifact-name { font-size: 11px; color: #888; margin-top: 4px; }
.code-exec-file-chip { margin: 4px 0; }
</style>

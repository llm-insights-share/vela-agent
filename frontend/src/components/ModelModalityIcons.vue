<template>
  <div v-if="modalities.length" class="modality-icons">
    <a-tooltip v-for="m in modalities" :key="m.key" :title="m.label">
      <span class="modality-icon" :aria-label="m.label">
        <component :is="m.icon" />
      </span>
    </a-tooltip>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import {
  FileTextOutlined,
  PictureOutlined,
  AudioOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons-vue'

const props = defineProps({
  capabilities: {
    type: Array,
    default: () => [],
  },
  modelName: {
    type: String,
    default: '',
  },
})

const VISION_NEEDLES = [
  '-vl', '/vl', 'vl-', 'vl_', 'vision', 'gpt-4o', 'gpt-4.1',
  'qvq', '-ocr', '/ocr', 'ocr-', 'ocr_', 'omni',
]

function looksLikeVision(name) {
  const n = (name || '').toLowerCase()
  if (!n) return false
  return VISION_NEEDLES.some((needle) => n.includes(needle))
}

function looksLikeAudio(name) {
  const n = (name || '').toLowerCase()
  return !!n && (n.includes('omni') || n.includes('audio') || n.includes('whisper'))
}

const modalities = computed(() => {
  const caps = (props.capabilities || []).map((c) => String(c).toLowerCase())
  const items = []
  const hasText = !caps.length || caps.includes('text')
  if (hasText) {
    items.push({ key: 'text', label: '文本', icon: FileTextOutlined })
  }
  const hasVision =
    caps.some((c) => ['vision', 'image', 'multimodal'].includes(c)) ||
    looksLikeVision(props.modelName)
  if (hasVision) {
    items.push({ key: 'vision', label: '图像 / 视觉', icon: PictureOutlined })
  }
  if (caps.includes('audio') || looksLikeAudio(props.modelName)) {
    items.push({ key: 'audio', label: '音频', icon: AudioOutlined })
  }
  if (caps.includes('video') || (props.modelName || '').toLowerCase().includes('omni')) {
    items.push({ key: 'video', label: '视频', icon: VideoCameraOutlined })
  }
  return items
})
</script>

<style scoped>
.modality-icons {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  color: #5c564e;
  font-size: 16px;
}
.modality-icon {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
</style>

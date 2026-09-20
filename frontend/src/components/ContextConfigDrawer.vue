<template>
  <a-drawer
    :open="open"
    title="上下文配置"
    width="560"
    :destroy-on-close="false"
    @close="emit('update:open', false)"
  >
    <div class="ctx-drawer">
      <div class="ctx-meta">
        <div>Agent：{{ agentName || agentId }}</div>
        <div class="ctx-hint">日期靠后更利于 prefix / KV cache；动态块（⚡）运行时填充。</div>
      </div>

      <a-segmented
        v-model:value="localMode"
        block
        :options="modeOptions"
        class="ctx-mode"
      />

      <a-spin :spinning="loading">
        <div v-if="!loading && blocks.length === 0" class="ctx-empty">
          <a-empty description="暂无上下文块" />
        </div>

        <div v-for="group in groupedBlocks" :key="group.key" class="ctx-group">
          <div class="ctx-group-title">{{ group.title }}</div>
          <div
            v-for="(block, idx) in group.items"
            :key="block.block_key + '-' + idx"
            class="ctx-block"
          >
            <div class="ctx-block-main">
              <span class="ctx-order">{{ block.sort_order }}</span>
              <span class="ctx-title">{{ block.title || block.block_key }}</span>
              <a-tag v-if="isDynamic(block)" color="processing">动态</a-tag>
              <a-tag v-if="block.deletable" color="purple">自定义</a-tag>
              <a-switch
                size="small"
                :checked="block.enabled"
                @change="(v) => (block.enabled = v)"
              />
            </div>
            <div class="ctx-block-actions">
              <a-button type="link" size="small" @click="moveBlock(block, -1)">上移</a-button>
              <a-button type="link" size="small" @click="moveBlock(block, 1)">下移</a-button>
              <a-button type="link" size="small" @click="openEdit(block)">编辑</a-button>
              <a-button
                v-if="block.deletable"
                type="link"
                size="small"
                danger
                @click="removeBlock(block)"
              >
                删除
              </a-button>
            </div>
          </div>
        </div>
      </a-spin>

      <div class="ctx-footer">
        <a-button @click="addCustom">+ 自定义块</a-button>
        <div class="ctx-footer-right">
          <a-popconfirm
            title="将清除本模式下全部自定义与修改，恢复为系统缺省，是否继续？"
            ok-text="恢复"
            cancel-text="取消"
            @confirm="restoreDefaults"
          >
            <a-button :loading="restoring">恢复缺省配置</a-button>
          </a-popconfirm>
          <a-button type="primary" :loading="saving" @click="save">保存</a-button>
        </div>
      </div>
    </div>

    <a-modal
      v-model:open="editOpen"
      :title="editForm.deletable ? '编辑自定义块' : `编辑 · ${editForm.title || editForm.block_key}`"
      ok-text="确定"
      cancel-text="取消"
      @ok="applyEdit"
    >
      <a-form layout="vertical">
        <a-form-item label="标题">
          <a-input v-model:value="editForm.title" />
        </a-form-item>
        <a-form-item v-if="editForm.deletable" label="放置位置">
          <a-select
            v-model:value="editForm.placement"
            :options="placementOptions"
          />
        </a-form-item>
        <a-form-item :label="isDynamic(editForm) ? '包装模板（可用 {body} 等占位符）' : '内容'">
          <a-textarea v-model:value="editForm.content" :rows="10" />
        </a-form-item>
        <a-alert
          v-if="isDynamic(editForm)"
          type="info"
          show-icon
          message="动态块正文由运行时填充；此处只配置模板与启停。"
          style="margin-bottom: 8px"
        />
      </a-form>
    </a-modal>
  </a-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { agentContextApi } from '../api'

const props = defineProps({
  open: { type: Boolean, default: false },
  agentId: { type: String, default: '' },
  agentName: { type: String, default: '' },
  executionMode: { type: String, default: 'auto' },
})

const emit = defineEmits(['update:open', 'update:executionMode'])

const modeOptions = [
  { label: '自动', value: 'auto' },
  { label: 'ReAct', value: 'react' },
  { label: 'Plan', value: 'plan_and_execute' },
  { label: '直接', value: 'direct' },
]

const placementOptions = [
  { label: 'system', value: 'system' },
  { label: 'user 附注', value: 'user_suffix' },
  { label: '模式注入', value: 'mode_inject' },
]

const localMode = ref(props.executionMode || 'auto')
const blocks = ref([])
const loading = ref(false)
const saving = ref(false)
const restoring = ref(false)
const editOpen = ref(false)
const editForm = reactive({
  block_key: '',
  title: '',
  placement: 'system',
  source: 'static',
  content: '',
  deletable: false,
  enabled: true,
})
let editTarget = null

const groupedBlocks = computed(() => {
  const groups = [
    { key: 'system', title: 'system', items: [] },
    { key: 'user_suffix', title: 'user 附注', items: [] },
    { key: 'mode_inject', title: '模式注入', items: [] },
  ]
  const map = Object.fromEntries(groups.map((g) => [g.key, g]))
  for (const b of blocks.value) {
    const p = b.placement || 'system'
    ;(map[p] || map.system).items.push(b)
  }
  return groups.filter((g) => g.items.length > 0)
})

function isDynamic(block) {
  return block?.source === 'dynamic' || block?.source === 'builtin_template'
}

async function loadBlocks() {
  if (!props.agentId) return
  loading.value = true
  try {
    const res = await agentContextApi.list(props.agentId, localMode.value)
    blocks.value = (res.items || []).map((x) => ({ ...x }))
  } catch (e) {
    message.error(e?.response?.data?.detail || e.message || '加载上下文配置失败')
    blocks.value = []
  } finally {
    loading.value = false
  }
}

function onModeChange(val) {
  emit('update:executionMode', val)
  loadBlocks()
}

watch(localMode, (val, prev) => {
  if (!props.open || val === prev) return
  onModeChange(val)
})

function renumberSort() {
  blocks.value.forEach((b, i) => {
    b.sort_order = (i + 1) * 10
  })
}

function moveBlock(block, delta) {
  const idx = blocks.value.findIndex((b) => b === block)
  if (idx < 0) return
  const j = idx + delta
  if (j < 0 || j >= blocks.value.length) return
  const arr = blocks.value.slice()
  const tmp = arr[idx]
  arr[idx] = arr[j]
  arr[j] = tmp
  blocks.value = arr
  renumberSort()
}

function removeBlock(block) {
  blocks.value = blocks.value.filter((b) => b !== block)
  renumberSort()
}

function addCustom() {
  const key = `custom_${Date.now().toString(36)}`
  blocks.value.push({
    block_key: key,
    title: '自定义块',
    placement: 'system',
    source: 'static',
    content: '',
    enabled: true,
    sort_order: (blocks.value.length + 1) * 10,
    deletable: true,
  })
}

function openEdit(block) {
  editTarget = block
  Object.assign(editForm, {
    block_key: block.block_key,
    title: block.title || '',
    placement: block.placement || 'system',
    source: block.source || 'static',
    content: block.content || '',
    deletable: !!block.deletable,
    enabled: !!block.enabled,
  })
  editOpen.value = true
}

function applyEdit() {
  if (!editTarget) {
    editOpen.value = false
    return
  }
  editTarget.title = editForm.title
  editTarget.content = editForm.content
  if (editTarget.deletable) {
    editTarget.placement = editForm.placement
  }
  editOpen.value = false
  editTarget = null
}

async function save() {
  if (!props.agentId) return
  saving.value = true
  try {
    renumberSort()
    const res = await agentContextApi.replace(props.agentId, localMode.value, {
      items: blocks.value,
    })
    blocks.value = (res.items || []).map((x) => ({ ...x }))
    message.success('已保存')
  } catch (e) {
    message.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function restoreDefaults() {
  if (!props.agentId) return
  restoring.value = true
  try {
    const res = await agentContextApi.restoreDefaults(props.agentId, localMode.value)
    blocks.value = (res.items || []).map((x) => ({ ...x }))
    message.success('已恢复系统缺省配置')
  } catch (e) {
    message.error(e?.response?.data?.detail || e.message || '恢复失败')
  } finally {
    restoring.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) {
      localMode.value = props.executionMode || 'auto'
      loadBlocks()
    }
  },
)

watch(
  () => props.executionMode,
  (v) => {
    if (props.open && v && v !== localMode.value) {
      localMode.value = v
      loadBlocks()
    }
  },
)
</script>

<style scoped>
.ctx-drawer {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 100%;
}
.ctx-meta {
  font-size: 13px;
  color: #595959;
}
.ctx-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #8c8c8c;
}
.ctx-mode {
  margin-bottom: 4px;
}
.ctx-group {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.ctx-group-title {
  font-size: 12px;
  font-weight: 600;
  color: #8c8c8c;
  margin-bottom: 6px;
}
.ctx-block {
  padding: 8px 0;
  border-top: 1px solid #f5f5f5;
}
.ctx-block:first-of-type {
  border-top: none;
}
.ctx-block-main {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ctx-order {
  font-size: 11px;
  color: #bfbfbf;
  width: 28px;
}
.ctx-title {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
}
.ctx-block-actions {
  margin-top: 2px;
  padding-left: 28px;
}
.ctx-footer {
  margin-top: auto;
  padding-top: 12px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid #f0f0f0;
}
.ctx-footer-right {
  display: flex;
  gap: 8px;
}
.ctx-empty {
  padding: 24px 0;
}
</style>

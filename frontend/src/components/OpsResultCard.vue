<template>
  <div class="ops-result-card" :class="`ops-card-${cardType}`">
    <div class="ops-result-card-top">
      <div class="ops-result-card-title-wrap">
        <a-button
          v-if="cardType === 'data_list' && view === 'detail'"
          type="text"
          size="small"
          class="ops-back"
          @click="backToList"
        >
          ← 返回
        </a-button>
        <span class="ops-result-card-title">{{ headerTitle }}</span>
      </div>
      <a-tag :color="statusTagColor" size="small">{{ statusTagLabel }}</a-tag>
    </div>

    <!-- data_list -->
    <template v-if="cardType === 'data_list' || cardType === 'choice_select'">
      <div v-if="view === 'list' && card.summary" class="ops-result-card-summary">{{ card.summary }}</div>
      <div v-if="view === 'list' && card.selectHint" class="ops-select-hint">{{ card.selectHint }}</div>
      <div v-if="view === 'list' && hasItems" class="ops-list">
        <div class="ops-list-head" :style="{ gridTemplateColumns: gridTemplate }">
          <span
            v-for="col in columns"
            :key="col.key"
            class="ops-list-cell"
          >{{ col.title }}</span>
          <span v-if="cardType === 'choice_select'" class="ops-list-cell">操作</span>
        </div>
        <div
          v-for="(row, idx) in pageItems"
          :key="rowKey(row, idx)"
          class="ops-list-row"
          :style="{ gridTemplateColumns: gridTemplate }"
        >
          <span
            v-for="col in columns"
            :key="col.key"
            class="ops-list-cell"
          >
            <a
              v-if="col.key === columns[0].key && cardType === 'data_list'"
              class="ops-row-link"
              href="#"
              @click.prevent="onRowClick(row)"
            >{{ cellText(row, col.key) }}</a>
            <a-tag
              v-else-if="col.key === 'status' && row.status"
              :color="statusColor(row.status)"
              size="small"
            >{{ row.status }}</a-tag>
            <span v-else>{{ cellText(row, col.key) }}</span>
          </span>
          <span v-if="cardType === 'choice_select'" class="ops-list-cell">
            <a-button
              type="primary"
              size="small"
              :disabled="!!selectedKey"
              @click="onSelectRow(row)"
            >选择</a-button>
          </span>
        </div>
        <div v-if="totalPages > 1" class="ops-pager">
          <a-button type="text" size="small" :disabled="page <= 1" @click="page--">上一页</a-button>
          <span class="ops-pager-info">{{ page }} / {{ totalPages }}</span>
          <a-button type="text" size="small" :disabled="page >= totalPages" @click="page++">下一页</a-button>
        </div>
      </div>
      <div v-else-if="view === 'list' && !hasItems" class="ops-result-card-actions">
        <a-button
          v-if="card.path"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.path)"
        >
          查看{{ card.pageLabel || '页面' }}
        </a-button>
      </div>
      <div v-else-if="view === 'detail'" class="ops-detail">
        <a-spin :spinning="detailLoading">
          <div v-if="detailError" class="ops-detail-error">{{ detailError }}</div>
          <template v-else-if="detailFields.length">
            <div
              v-for="f in detailFields"
              :key="f.key"
              class="ops-detail-row"
            >
              <span class="ops-detail-key">{{ f.label }}</span>
              <span class="ops-detail-val">{{ f.value }}</span>
            </div>
            <a-button
              v-if="detailPath"
              type="link"
              size="small"
              class="ops-result-card-link"
              @click="openPath(detailPath)"
            >
              在页面中打开
            </a-button>
          </template>
        </a-spin>
      </div>
    </template>

    <!-- entity_display -->
    <template v-else-if="cardType === 'entity_display'">
      <div v-if="card.summary" class="ops-result-card-summary">{{ card.summary }}</div>
      <div class="ops-entity">
        <div
          v-for="f in entityFields"
          :key="f.key"
          class="ops-detail-row"
        >
          <span class="ops-detail-key">{{ f.label }}</span>
          <span class="ops-detail-val">
            <a-tag v-if="f.key === 'status'" :color="statusColor(f.value)" size="small">{{ f.value }}</a-tag>
            <template v-else>{{ f.value }}</template>
          </span>
        </div>
        <div v-if="!entityFields.length" class="ops-result-card-summary">暂无结构化字段</div>
      </div>
      <div class="ops-result-card-actions">
        <a-button
          v-if="card.path"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.path)"
        >
          在页面中打开
        </a-button>
      </div>
    </template>

    <!-- status_result -->
    <template v-else-if="cardType === 'status_result'">
      <div class="ops-status-banner" :class="card.ok === false ? 'is-fail' : 'is-ok'">
        {{ card.ok === false ? '操作未成功' : '操作已完成' }}
        <span v-if="card.summary"> · {{ card.summary }}</span>
      </div>
      <div class="ops-result-card-actions">
        <a-button
          v-if="card.path"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.path)"
        >
          前往{{ card.pageLabel || '相关页面' }}
        </a-button>
      </div>
    </template>

    <!-- choice_confirm -->
    <template v-else-if="cardType === 'choice_confirm'">
      <div v-if="card.summary" class="ops-result-card-summary">{{ card.summary }}</div>
      <div v-if="card.choiceDone || choicePicked" class="ops-choice-done">
        {{ choiceResultLabel }}
      </div>
      <div v-else class="ops-choice-btns">
        <a-button
          v-for="c in (card.choices || [])"
          :key="c.key"
          :type="c.tone === 'primary' ? 'primary' : 'default'"
          :danger="c.tone === 'danger'"
          size="small"
          @click="onChoice(c)"
        >
          {{ c.label }}
        </a-button>
        <a-button
          v-if="card.path"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.path)"
        >
          打开{{ card.pageLabel || '页面' }}
        </a-button>
      </div>
    </template>

    <!-- action_prompt -->
    <template v-else-if="cardType === 'action_prompt'">
      <div class="ops-prompt-title">{{ card.promptTitle || card.title }}</div>
      <div class="ops-prompt-hint">{{ card.promptHint || card.summary }}</div>
      <div class="ops-choice-btns">
        <a-button
          type="primary"
          size="small"
          class="ops-prompt-primary"
          @click="openPath(card.promptPath || card.path)"
        >
          {{ card.primaryLabel || '打开页面' }}
        </a-button>
        <a-button
          v-if="card.secondaryPath"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.secondaryPath)"
        >
          {{ card.secondaryLabel || '查看列表' }}
        </a-button>
      </div>
    </template>

    <!-- fallback -->
    <template v-else>
      <div v-if="card.summary" class="ops-result-card-summary">{{ card.summary }}</div>
      <div class="ops-result-card-actions">
        <a-button
          v-if="card.path"
          type="link"
          size="small"
          class="ops-result-card-link"
          @click="openPath(card.path)"
        >
          查看{{ card.pageLabel || '页面' }}
        </a-button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { agentApi, toolApi, skillApi, knowledgeApi, scheduleApi, hitlApi } from '../api'
import {
  DOMAIN_ROUTES,
  listColumnsForDomain,
  buildItemPath,
  rowPrimaryLabel,
  entityFieldsForDomain,
  fieldLabel,
} from '../utils/opsNavigation'

const props = defineProps({
  card: { type: Object, required: true },
})
const emit = defineEmits(['open', 'navigate', 'choice', 'select'])

const router = useRouter()
const view = ref('list')
const page = ref(1)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref(null)
const detailPath = ref('')
const selectedRow = ref(null)
const choicePicked = ref(null)
const selectedKey = ref('')

const cardType = computed(() => props.card.type || (props.card.hasItems ? 'data_list' : 'status_result'))
const domain = computed(() => props.card.domain || '')
const items = computed(() => {
  const raw = props.card.items || props.card.payload?.items || []
  return Array.isArray(raw) ? raw : []
})
const columns = computed(() => listColumnsForDomain(domain.value, props.card.action, items.value).slice(0, 3))
const gridTemplate = computed(() => {
  const n = columns.value.length || 3
  const selectCol = cardType.value === 'choice_select' ? ' 72px' : ''
  if (n === 2) return `1.2fr 1fr${selectCol}`
  if (n === 4) return `1.3fr 0.7fr 0.7fr 1.2fr${selectCol}`
  return `1.4fr 0.7fr 1.4fr${selectCol}`
})
const hasItems = computed(() => items.value.length > 0)
const pageSize = computed(() => props.card.pageSize || 8)
const totalPages = computed(() => Math.max(1, Math.ceil(items.value.length / pageSize.value)))
const pageItems = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return items.value.slice(start, start + pageSize.value)
})

const entityFields = computed(() => {
  if (props.card.fields?.length) return props.card.fields
  return entityFieldsForDomain(domain.value, props.card.entity || props.card.payload)
})

const detailFields = computed(() => {
  const d = detail.value
  if (!d || typeof d !== 'object') return []
  const fromHelper = entityFieldsForDomain(domain.value, d)
  if (fromHelper.length) return fromHelper
  return Object.keys(d)
    .filter((k) => d[k] != null && d[k] !== '' && typeof d[k] !== 'object')
    .slice(0, 8)
    .map((k) => ({ key: k, label: fieldLabel(k), value: String(d[k]) }))
})

const headerTitle = computed(() => {
  if (cardType.value === 'data_list' && view.value === 'detail' && selectedRow.value) {
    return rowPrimaryLabel(selectedRow.value)
  }
  const base = props.card.title || '操作结果'
  if ((cardType.value === 'data_list' || cardType.value === 'choice_select') && hasItems.value && props.card.summary) {
    return `${base} · ${props.card.summary}`
  }
  return base
})

const statusTagColor = computed(() => {
  if (props.card.ok === false) return 'red'
  if (cardType.value === 'choice_confirm' && (props.card.choiceResult === 'rejected' || choicePicked.value === 'reject')) {
    return 'red'
  }
  if (cardType.value === 'choice_select') return selectedKey.value ? 'green' : 'gold'
  if (cardType.value === 'action_prompt') return 'blue'
  return 'green'
})

const statusTagLabel = computed(() => {
  if (props.card.ok === false) return '失败'
  if (cardType.value === 'action_prompt') return '引导'
  if (cardType.value === 'choice_select') return selectedKey.value ? '已选择' : '待确认'
  if (cardType.value === 'choice_confirm') {
    if (props.card.choiceResult === 'approved' || choicePicked.value === 'approve') return '已批准'
    if (props.card.choiceResult === 'rejected' || choicePicked.value === 'reject') return '已拒绝'
    return '待确认'
  }
  return '成功'
})

const choiceResultLabel = computed(() => {
  const r = choicePicked.value || props.card.choiceResult
  if (r === 'approve' || r === 'approved') return '已选择：批准'
  if (r === 'reject' || r === 'rejected') return '已选择：拒绝'
  return '已处理'
})

watch(
  () => props.card,
  () => {
    page.value = 1
    choicePicked.value = null
    selectedKey.value = ''
    if (view.value === 'list') {
      detail.value = null
      selectedRow.value = null
    }
  },
  { deep: true },
)

function rowKey(row, idx) {
  const idKey = DOMAIN_ROUTES[domain.value]?.idKey
  return (idKey && row?.[idKey]) || row?.agent_id || row?.mapping_id || `${idx}-${rowPrimaryLabel(row)}`
}

function cellText(row, key) {
  const v = row?.[key]
  if (v == null || v === '') return '—'
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—'
  const s = String(v)
  return s.length > 48 ? `${s.slice(0, 48)}…` : s
}

function statusColor(status) {
  const s = String(status || '').toUpperCase()
  if (s === 'PUBLISHED' || s === 'ACTIVE' || s === 'APPROVED') return 'green'
  if (s === 'DEPRECATED' || s === 'PENDING') return 'gold'
  if (s === 'DELETED' || s === 'REJECTED' || s === 'ERROR') return 'red'
  return 'default'
}

function backToList() {
  view.value = 'list'
  detail.value = null
  detailError.value = ''
  selectedRow.value = null
}

async function openPath(path) {
  if (!path) return
  try {
    if (router.currentRoute.value.path !== path) {
      await router.push(path)
    }
  } catch (_) { /* ignore */ }
  emit('open', { ...props.card, path })
  emit('navigate', { path, domain: domain.value })
}

async function onRowClick(row) {
  selectedRow.value = row
  const path = buildItemPath(domain.value, row)
  detailPath.value = path
  if (path && router.currentRoute.value.path !== path) {
    try {
      await router.push(path)
      emit('navigate', { path, row, domain: domain.value })
    } catch (_) { /* ignore */ }
  }
  view.value = 'detail'
  await loadDetail(row)
}

function onChoice(c) {
  choicePicked.value = c.key
  emit('choice', { key: c.key, card: props.card })
}

function onSelectRow(row) {
  const key = rowKey(row, 0)
  selectedKey.value = key
  emit('select', { item: row, card: props.card })
}

async function loadDetail(row) {
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  const idKey = DOMAIN_ROUTES[domain.value]?.idKey
  const id = idKey ? row?.[idKey] : null
  try {
    if (domain.value === 'agents' && id) {
      detail.value = await agentApi.get(id)
    } else if (domain.value === 'tools' && id) {
      detail.value = await toolApi.get(id)
    } else if (domain.value === 'skills' && id) {
      detail.value = await skillApi.get(id)
    } else if (domain.value === 'kb' && id) {
      detail.value = await knowledgeApi.get(id)
    } else if (domain.value === 'schedules' && id) {
      detail.value = await scheduleApi.get(id)
    } else if (domain.value === 'approvals' && id) {
      detail.value = await hitlApi.get(id)
    } else {
      detail.value = { ...row }
    }
  } catch (e) {
    detailError.value = e.message || '加载详情失败'
    detail.value = { ...row }
  } finally {
    detailLoading.value = false
  }
}
</script>

<style scoped>
.ops-result-card {
  margin-top: 8px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #ddd8ce;
  border-radius: 8px;
}
.ops-card-action_prompt {
  background: linear-gradient(180deg, #fffaf5 0%, #fff 60%);
  border-color: #f0d9b5;
}
.ops-card-choice_confirm {
  background: #fff7ed;
  border-color: #f0d9b5;
}
.ops-card-choice_select {
  background: linear-gradient(180deg, #fffaf5 0%, #fff 55%);
  border-color: #f0d9b5;
}
.ops-select-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #9a3412;
  line-height: 1.4;
}
.ops-result-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ops-result-card-title-wrap {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.ops-back {
  padding: 0 4px;
  color: #c2410c;
}
.ops-result-card-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ops-result-card-summary {
  margin-top: 4px;
  font-size: 12px;
  color: #5c5650;
  line-height: 1.45;
}
.ops-result-card-actions {
  margin-top: 6px;
}
.ops-result-card-link {
  padding: 0;
  height: auto;
  color: #c2410c;
}
.ops-list {
  margin-top: 8px;
  border: 1px solid #e8e4dc;
  border-radius: 6px;
  overflow: hidden;
}
.ops-list-head,
.ops-list-row {
  display: grid;
  grid-template-columns: v-bind(gridTemplate);
  gap: 6px;
  padding: 6px 8px;
  font-size: 11px;
}
.ops-list-head {
  background: #f3f0e8;
  color: #5c5650;
  font-weight: 600;
}
.ops-list-row {
  border-top: 1px solid #eeeae2;
  color: #1a1714;
  align-items: center;
}
.ops-list-row:hover {
  background: #faf8f4;
}
.ops-list-cell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ops-row-link {
  color: #c2410c;
  text-decoration: none;
  font-weight: 500;
}
.ops-row-link:hover {
  text-decoration: underline;
}
.ops-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 4px;
  border-top: 1px solid #e8e4dc;
  background: #faf8f4;
}
.ops-pager-info {
  font-size: 11px;
  color: #9e9590;
}
.ops-detail,
.ops-entity {
  margin-top: 8px;
}
.ops-detail-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px solid #f0ebe3;
}
.ops-detail-key {
  flex: 0 0 88px;
  color: #9e9590;
}
.ops-detail-val {
  flex: 1;
  color: #1a1714;
  word-break: break-all;
}
.ops-detail-error {
  color: #b5341c;
  font-size: 12px;
}
.ops-status-banner {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.45;
}
.ops-status-banner.is-ok {
  background: #f0fdf4;
  color: #166534;
  border: 1px solid #bbf7d0;
}
.ops-status-banner.is-fail {
  background: #fef2f2;
  color: #b5341c;
  border: 1px solid #fecaca;
}
.ops-choice-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  align-items: center;
}
.ops-choice-done {
  margin-top: 8px;
  font-size: 12px;
  color: #5c5650;
}
.ops-prompt-title {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #9a3412;
}
.ops-prompt-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #5c5650;
  line-height: 1.45;
}
.ops-prompt-primary {
  background: #c2410c;
  border-color: #c2410c;
}
</style>

<template>
  <div class="skill-page">
    <div class="page-header">
      <h2>UI 技能库</h2>
      <a-space>
        <a-radio-group v-model:value="visibilityFilter" button-style="solid" size="small">
          <a-radio-button value="all">全部</a-radio-button>
          <a-radio-button value="PRIVATE">私有</a-radio-button>
          <a-radio-button value="published">已发布</a-radio-button>
        </a-radio-group>
        <a-input-search
          v-model:value="searchQuery"
          placeholder="语义搜索技能…"
          style="width: 280px;"
          @search="doSearch"
        />
        <a-button @click="loadSkills">刷新</a-button>
      </a-space>
    </div>

    <a-table
      :dataSource="displayList"
      :columns="columns"
      rowKey="skill_id"
      :loading="loading"
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'description'">
          <span class="list-desc" :title="record.description || ''">
            {{ record.description || '—' }}
          </span>
        </template>
        <template v-else-if="column.key === 'visibility'">
          <a-tag :color="visibilityTagColor(record.visibility)">
            {{ visibilityLabel(record.visibility) }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space>
            <a @click="openDetail(record.skill_id)">详情</a>
            <a @click="togglePublish(record)">
              {{ isPublished(record.visibility) ? '下架' : '发布' }}
            </a>
            <a-popconfirm
              v-if="!isPublished(record.visibility)"
              title="确认删除该技能？删除后不可恢复。"
              ok-text="删除"
              cancel-text="取消"
              @confirm="removeSkill(record)"
            >
              <a style="color: #b5341c">删除</a>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-drawer
      v-model:open="detailOpen"
      title="技能详情"
      width="640"
      destroyOnClose
      :bodyStyle="{ paddingBottom: '24px' }"
    >
      <template v-if="detail">
        <div class="detail-head">
          <div class="detail-title-row">
            <h3 class="detail-name">{{ detail.name }}</h3>
            <a-button type="link" size="small" @click="startEditMeta">编辑</a-button>
          </div>
          <a-space wrap>
            <a-tag>scope: {{ detail.scope }}</a-tag>
            <a-tag :color="visibilityTagColor(detail.visibility)">
              {{ visibilityLabel(detail.visibility) }}
            </a-tag>
          </a-space>
        </div>

        <div class="detail-section">
          <div class="section-label">技能描述</div>
          <div class="desc-full">{{ detail.description || '（无描述）' }}</div>
        </div>

        <a-modal
          v-model:open="metaEditOpen"
          title="编辑技能信息"
          ok-text="保存"
          cancel-text="取消"
          :confirmLoading="metaSaving"
          @ok="saveMeta"
        >
          <a-form layout="vertical">
            <a-form-item label="名称" required>
              <a-input v-model:value="metaForm.name" :maxlength="128" />
            </a-form-item>
            <a-form-item label="描述">
              <a-textarea
                v-model:value="metaForm.description"
                :rows="6"
                placeholder="技能用途与适用场景的完整说明"
              />
            </a-form-item>
          </a-form>
        </a-modal>

        <a-divider />
        <div class="section-label">步骤（共 {{ detail.steps?.length || 0 }}）</div>
        <div
          v-for="st in detail.steps"
          :key="st.step_id"
          class="step-card"
        >
          <div class="step-card-head">
            <a-space>
              <a-tag color="blue">#{{ st.step_order }}</a-tag>
              <code>{{ st.action }}</code>
              <span v-if="st.target_label" class="step-target">{{ st.target_label }}</span>
            </a-space>
            <a @click="startEditStep(st)">编辑</a>
          </div>
          <div v-if="st.note" class="step-note">{{ st.note }}</div>
          <div v-else class="step-note muted">暂无步骤说明，可点击编辑补充</div>
          <div v-if="st.value_template" class="step-val">
            值模板：<code>{{ st.value_template }}</code>
          </div>
        </div>

        <a-modal
          v-model:open="stepEditOpen"
          title="编辑步骤"
          ok-text="保存"
          cancel-text="取消"
          :confirmLoading="stepSaving"
          width="560"
          @ok="saveStep"
        >
          <a-form layout="vertical">
            <a-form-item label="动作" required>
              <a-select v-model:value="stepForm.action" style="width: 100%">
                <a-select-option v-for="a in ACTION_OPTIONS" :key="a" :value="a">
                  {{ a }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="目标文案">
              <a-input
                v-model:value="stepForm.target_label"
                placeholder="页面上可见的按钮/输入框标签"
              />
            </a-form-item>
            <a-form-item label="值模板">
              <a-input
                v-model:value="stepForm.value_template"
                placeholder="如 {{username}} 或固定文本"
              />
            </a-form-item>
            <a-form-item label="步骤说明">
              <a-textarea
                v-model:value="stepForm.note"
                :rows="4"
                placeholder="说明本步骤意图、前置条件或注意事项"
              />
            </a-form-item>
          </a-form>
        </a-modal>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const ACTION_OPTIONS = ['click', 'type', 'select', 'navigate', 'press', 'scroll', 'wait']

const loading = ref(false)
const skills = ref([])
const searchResults = ref(null)
const searchQuery = ref('')
const visibilityFilter = ref('all')
const detailOpen = ref(false)
const detail = ref(null)

const metaEditOpen = ref(false)
const metaSaving = ref(false)
const metaForm = ref({ name: '', description: '' })

const stepEditOpen = ref(false)
const stepSaving = ref(false)
const stepForm = ref({
  step_id: '',
  action: 'click',
  target_label: '',
  value_template: '',
  note: '',
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '步骤数', dataIndex: 'step_count', key: 'step_count', width: 80 },
  { title: 'Scope', dataIndex: 'scope', key: 'scope', width: 100 },
  { title: '状态', key: 'visibility', width: 90 },
  { title: '操作', key: 'action', width: 180 },
]

function isPublished(visibility) {
  return visibility === 'DEPARTMENT' || visibility === 'PUBLIC'
}

function visibilityLabel(visibility) {
  if (visibility === 'PUBLIC') return '已发布'
  if (visibility === 'DEPARTMENT') return '已发布'
  return '私有'
}

function visibilityTagColor(visibility) {
  return isPublished(visibility) ? 'green' : 'default'
}

function matchesFilter(record) {
  if (visibilityFilter.value === 'all') return true
  if (visibilityFilter.value === 'PRIVATE') return !isPublished(record.visibility)
  if (visibilityFilter.value === 'published') return isPublished(record.visibility)
  return true
}

const displayList = computed(() => {
  let list
  if (searchResults.value) {
    list = searchResults.value.map((r) => ({
      ...r,
      step_count: r.step_count ?? '-',
      description: r.description || '',
      _score: r.score,
    }))
  } else {
    list = skills.value
  }
  return list.filter(matchesFilter)
})

async function loadSkills() {
  loading.value = true
  searchResults.value = null
  try {
    skills.value = await screenpilotApi.listSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function doSearch() {
  if (!searchQuery.value.trim()) {
    searchResults.value = null
    return
  }
  loading.value = true
  try {
    const res = await screenpilotApi.searchSkills({ query: searchQuery.value, top_k: 10 })
    searchResults.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function openDetail(skillId) {
  try {
    detail.value = await screenpilotApi.getSkill(skillId)
    detailOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

function startEditMeta() {
  metaForm.value = {
    name: detail.value?.name || '',
    description: detail.value?.description || '',
  }
  metaEditOpen.value = true
}

async function saveMeta() {
  if (!detail.value?.skill_id) return
  if (!metaForm.value.name?.trim()) {
    message.warning('名称不能为空')
    return
  }
  metaSaving.value = true
  try {
    const updated = await screenpilotApi.updateSkill(detail.value.skill_id, {
      name: metaForm.value.name,
      description: metaForm.value.description,
    })
    detail.value = {
      ...detail.value,
      name: updated.name,
      description: updated.description,
      visibility: updated.visibility ?? detail.value.visibility,
    }
    metaEditOpen.value = false
    message.success('已保存')
    await loadSkills()
  } catch (e) {
    message.error(e.message)
  } finally {
    metaSaving.value = false
  }
}

function startEditStep(st) {
  stepForm.value = {
    step_id: st.step_id,
    action: st.action || 'click',
    target_label: st.target_label || '',
    value_template: st.value_template || '',
    note: st.note || '',
  }
  stepEditOpen.value = true
}

async function saveStep() {
  if (!detail.value?.skill_id || !stepForm.value.step_id) return
  if (!stepForm.value.action?.trim()) {
    message.warning('动作不能为空')
    return
  }
  stepSaving.value = true
  try {
    const updated = await screenpilotApi.updateSkillStep(
      detail.value.skill_id,
      stepForm.value.step_id,
      {
        action: stepForm.value.action,
        target_label: stepForm.value.target_label,
        value_template: stepForm.value.value_template,
        note: stepForm.value.note,
      },
    )
    detail.value.steps = (detail.value.steps || []).map((s) =>
      s.step_id === updated.step_id ? { ...s, ...updated } : s,
    )
    stepEditOpen.value = false
    message.success('步骤已更新')
  } catch (e) {
    message.error(e.message)
  } finally {
    stepSaving.value = false
  }
}

async function togglePublish(record) {
  try {
    if (isPublished(record.visibility)) {
      await screenpilotApi.unpublishSkill(record.skill_id)
      message.success('已下架')
    } else {
      await screenpilotApi.publishSkill(record.skill_id, { visibility: 'DEPARTMENT' })
      message.success('已发布')
    }
    await loadSkills()
    if (detail.value?.skill_id === record.skill_id) {
      detail.value = await screenpilotApi.getSkill(record.skill_id)
    }
  } catch (e) {
    message.error(e.message)
  }
}

async function removeSkill(record) {
  try {
    await screenpilotApi.deleteSkill(record.skill_id)
    message.success('已删除')
    if (detail.value?.skill_id === record.skill_id) {
      detailOpen.value = false
      detail.value = null
    }
    await loadSkills()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(loadSkills)
</script>

<style scoped>
.skill-page { padding: 0 4px; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-header h2 { margin: 0; }
.list-desc {
  display: inline-block;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}
.detail-head { margin-bottom: 16px; }
.detail-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.detail-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}
.detail-section { margin-top: 12px; }
.section-label {
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 8px;
  font-weight: 500;
}
.desc-full {
  white-space: pre-wrap;
  word-break: break-word;
  color: #262626;
  font-size: 14px;
  line-height: 1.65;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 12px 14px;
  min-height: 48px;
}
.step-card {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: #fff;
}
.step-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.step-target { color: #595959; font-size: 13px; }
.step-note {
  font-size: 13px;
  color: #262626;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
.step-note.muted { color: #bfbfbf; }
.step-val {
  margin-top: 6px;
  font-size: 12px;
  color: #8c8c8c;
}
.step-val code {
  font-size: 12px;
  background: #f5f5f5;
  padding: 1px 6px;
  border-radius: 4px;
}
</style>

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
        <a-button @click="openRunByDesc">按描述执行</a-button>
        <a-button type="primary" @click="$router.push('/screenpilot/skills/record')">录制技能</a-button>
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
            <a @click="openReplay(record)">试跑</a>
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
            <a-space>
              <a-button type="link" size="small" @click="openReplay(detail)">试跑</a-button>
              <a-button type="link" size="small" @click="startEditMeta">编辑</a-button>
            </a-space>
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

    <!-- 试跑指定技能 -->
    <a-modal
      v-model:open="replayOpen"
      title="试跑 UI 技能"
      ok-text="开始执行"
      cancel-text="取消"
      :confirmLoading="replayLoading"
      width="640"
      @ok="doReplay"
    >
      <a-form layout="vertical">
        <a-form-item label="技能">
          <a-input :value="replayForm.skill_name" disabled />
        </a-form-item>
        <a-form-item label="驭屏系统" required>
          <a-select
            v-model:value="replayForm.system_id"
            style="width: 100%"
            :options="systemOptions"
            placeholder="选择系统"
          />
        </a-form-item>
        <a-form-item
          v-for="field in replayParamFields"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <a-input
            v-model:value="replayForm.params[field.key]"
            :placeholder="field.description || field.key"
            allow-clear
          />
        </a-form-item>
      </a-form>
      <a-alert
        v-if="execHitl.pending"
        type="warning"
        show-icon
        style="margin-bottom: 12px"
        :message="`等待审批：${execHitl.approval_id}`"
      >
        <template #action>
          <a-button size="small" type="link" @click="$router.push('/screenpilot/approvals')">审批收件箱</a-button>
        </template>
      </a-alert>
      <div v-if="execResult" class="exec-result">
        <div class="section-label">执行结果</div>
        <pre>{{ formatExecResult(execResult) }}</pre>
      </div>
    </a-modal>

    <!-- 按描述执行 -->
    <a-modal
      v-model:open="runOpen"
      title="按描述执行 UI 技能"
      ok-text="执行"
      cancel-text="取消"
      :confirmLoading="runLoading"
      width="680"
      @ok="doRunByDesc"
    >
      <a-form layout="vertical">
        <a-form-item label="驭屏系统" required>
          <a-select
            v-model:value="runForm.system_id"
            style="width: 100%"
            :options="systemOptions"
            placeholder="选择系统"
          />
        </a-form-item>
        <a-form-item label="目标描述" required>
          <a-textarea
            v-model:value="runForm.goal"
            :rows="3"
            placeholder="例如：打开通讯录并搜索张三"
          />
        </a-form-item>
        <a-form-item v-if="skillCandidates.length" label="匹配到的技能（可点选后重试）">
          <a-radio-group v-model:value="runForm.skill_id" style="display: flex; flex-direction: column; gap: 6px">
            <a-radio v-for="c in skillCandidates" :key="c.skill_id" :value="c.skill_id">
              {{ c.name }}（score: {{ Number(c.score || 0).toFixed(2) }}）
            </a-radio>
          </a-radio-group>
        </a-form-item>
      </a-form>
      <a-alert
        v-if="execHitl.pending"
        type="warning"
        show-icon
        style="margin-bottom: 12px"
        :message="`等待审批：${execHitl.approval_id}`"
      >
        <template #action>
          <a-button size="small" type="link" @click="$router.push('/screenpilot/approvals')">审批收件箱</a-button>
        </template>
      </a-alert>
      <div v-if="execResult" class="exec-result">
        <div class="section-label">执行日志</div>
        <pre>{{ formatExecResult(execResult) }}</pre>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const ACTION_OPTIONS = ['click', 'type', 'select', 'navigate', 'press', 'scroll', 'wait']

const route = useRoute()
const loading = ref(false)
const skills = ref([])
const systems = ref([])
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

const replayOpen = ref(false)
const replayLoading = ref(false)
const replayForm = ref({
  skill_id: '',
  skill_name: '',
  system_id: undefined,
  params: {},
  param_schema: null,
})

const replayParamFields = computed(() => {
  const schema = replayForm.value.param_schema || {}
  const props = schema.properties || {}
  const required = new Set(schema.required || Object.keys(props))
  const skip = new Set(['password', 'username', 'otp', 'token', 'secret', 'passwd', 'user'])
  return Object.keys(props)
    .filter((k) => !skip.has(String(k).toLowerCase()))
    .map((key) => ({
      key,
      label: key,
      description: props[key]?.description || '',
      required: required.has(key),
    }))
})

const runOpen = ref(false)
const runLoading = ref(false)
const runForm = ref({
  system_id: undefined,
  goal: '',
  skill_id: undefined,
})
const skillCandidates = ref([])
const execResult = ref(null)
const execHitl = ref({ pending: false, approval_id: '' })

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '步骤数', dataIndex: 'step_count', key: 'step_count', width: 80 },
  { title: 'Scope', dataIndex: 'scope', key: 'scope', width: 100 },
  { title: '状态', key: 'visibility', width: 90 },
  { title: '操作', key: 'action', width: 220 },
]

const systemOptions = computed(() =>
  (systems.value || [])
    .filter((s) => !s.status || s.status === 'ACTIVE')
    .map((s) => ({ value: s.system_id, label: s.name })),
)

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

function formatExecResult(res) {
  try {
    return JSON.stringify(res, null, 2)
  } catch {
    return String(res)
  }
}

function applyHitl(res) {
  if (res?.hitl_pending) {
    execHitl.value = { pending: true, approval_id: res.approval_id || '' }
    message.warning(res.message || '操作需审批')
    return true
  }
  execHitl.value = { pending: false, approval_id: '' }
  return false
}

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

async function loadSystems() {
  try {
    systems.value = await screenpilotApi.listSystems()
  } catch (e) {
    // optional for list page
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

function openReplay(record) {
  execResult.value = null
  execHitl.value = { pending: false, approval_id: '' }
  const schema = record.param_schema || null
  const props = (schema && schema.properties) || {}
  const params = {}
  Object.keys(props).forEach((k) => { params[k] = '' })
  replayForm.value = {
    skill_id: record.skill_id,
    skill_name: record.name || record.skill_id,
    system_id: record.system_id || undefined,
    params,
    param_schema: schema,
  }
  replayOpen.value = true
  // Refresh schema from detail if list row is thin
  if (!schema && record.skill_id) {
    screenpilotApi.getSkill(record.skill_id).then((detail) => {
      const s = detail?.param_schema || null
      const p = (s && s.properties) || {}
      const init = {}
      Object.keys(p).forEach((k) => { init[k] = '' })
      replayForm.value.param_schema = s
      replayForm.value.params = init
    }).catch(() => {})
  }
}

async function doReplay() {
  if (!replayForm.value.skill_id || !replayForm.value.system_id) {
    message.warning('请选择驭屏系统')
    return
  }
  const missing = replayParamFields.value
    .filter((f) => f.required && !(String(replayForm.value.params?.[f.key] || '').trim()))
    .map((f) => f.key)
  if (missing.length) {
    message.warning(`请填写参数：${missing.join(', ')}`)
    return
  }
  replayLoading.value = true
  execResult.value = null
  try {
    const nav = await screenpilotApi.navigateSession({
      system_id: replayForm.value.system_id,
      auto_login: true,
    })
    if (applyHitl(nav)) {
      execResult.value = nav
      return
    }
    if (!nav.success) {
      message.error(nav.error || '打开会话失败')
      execResult.value = nav
      return
    }
    const sid = nav.screen_session_id
    const params = { ...(replayForm.value.params || {}) }
    Object.keys(params).forEach((k) => {
      if (!String(params[k] || '').trim()) delete params[k]
    })
    const res = await screenpilotApi.replaySkill({
      skill_id: replayForm.value.skill_id,
      screen_session_id: sid,
      params,
    })
    execResult.value = res
    if (applyHitl(res)) return
    if (res.needs_params && (res.missing_params || []).length) {
      const schema = res.param_schema || replayForm.value.param_schema
      replayForm.value.param_schema = schema
      const init = { ...(replayForm.value.params || {}) }
      ;(res.missing_params || []).forEach((k) => {
        if (init[k] == null) init[k] = ''
      })
      replayForm.value.params = init
      message.warning(`请补充参数：${(res.missing_params || []).join(', ')}`)
      return
    }
    if (res.success) {
      message.success(`已重放 ${res.replayed_steps || 0} 步`)
    } else {
      message.error(res.error || '试跑失败')
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    replayLoading.value = false
  }
}

function openRunByDesc() {
  execResult.value = null
  execHitl.value = { pending: false, approval_id: '' }
  skillCandidates.value = []
  runForm.value = {
    system_id: systems.value?.[0]?.system_id,
    goal: '',
    skill_id: undefined,
  }
  runOpen.value = true
}

async function doRunByDesc() {
  if (!runForm.value.system_id) {
    message.warning('请选择驭屏系统')
    return
  }
  if (!runForm.value.goal?.trim() && !runForm.value.skill_id) {
    message.warning('请填写目标描述或选择匹配技能')
    return
  }
  runLoading.value = true
  execResult.value = null
  try {
    const res = await screenpilotApi.runSkill({
      system_id: runForm.value.system_id,
      goal: runForm.value.goal || '',
      skill_id: runForm.value.skill_id || null,
      scope: 'default',
    })
    execResult.value = res
    if (res.skill_candidates?.length) {
      skillCandidates.value = res.skill_candidates
    } else if (res.plan_hints?.skill_candidates?.length) {
      skillCandidates.value = res.plan_hints.skill_candidates
    }
    if (applyHitl(res)) return
    if (res.success) {
      message.success('执行完成')
    } else if (res.needs_agent) {
      message.warning(res.message || '未匹配到合适技能，可从候选中点选后重试')
    } else {
      message.error(res.error || '执行失败')
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    runLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadSkills(), loadSystems()])
  const qid = route.query.skill_id
  if (qid) {
    await openDetail(String(qid))
  }
})
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
.exec-result {
  margin-top: 12px;
}
.exec-result pre {
  max-height: 280px;
  overflow: auto;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  margin: 0;
}
</style>

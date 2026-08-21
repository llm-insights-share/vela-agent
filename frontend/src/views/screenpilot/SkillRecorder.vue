<template>
  <div class="recorder-page">
    <div class="page-header">
      <div class="header-left">
        <a-button type="link" @click="$router.push('/screenpilot/skills')">← 返回技能库</a-button>
        <h2>录制 UI 技能</h2>
      </div>
      <a-space>
        <a-select
          v-model:value="systemId"
          placeholder="选择驭屏系统"
          style="width: 240px"
          :disabled="!!screenSessionId"
          show-search
          :filter-option="filterSystem"
          :options="systemOptions"
        />
        <a-button type="primary" :loading="starting" :disabled="!systemId || !!screenSessionId" @click="startSession">
          开始录制
        </a-button>
        <a-button :disabled="!screenSessionId" :loading="observing" @click="refreshObserve">刷新观测</a-button>
        <a-button danger :disabled="!screenSessionId" :loading="closing" @click="endSession">结束会话</a-button>
      </a-space>
    </div>

    <a-alert
      v-if="hitlPending"
      type="warning"
      show-icon
      style="margin-bottom: 12px"
      message="操作等待审批"
      :description="`审批单 ${hitlApprovalId}。请在审批收件箱处理后，再点击「刷新观测」继续录制。`"
    >
      <template #action>
        <a-button size="small" type="link" @click="$router.push('/screenpilot/approvals')">打开审批收件箱</a-button>
      </template>
    </a-alert>

    <a-alert
      v-if="observeAlert"
      :type="observeAlert.type"
      show-icon
      style="margin-bottom: 12px"
      :message="observeAlert.message"
      :description="observeAlert.description"
    >
      <template v-if="observeAlert.showSystemsLink" #action>
        <a-button size="small" type="link" @click="$router.push('/screenpilot/systems')">打开驭屏系统</a-button>
      </template>
    </a-alert>

    <a-alert
      v-if="!screenSessionId"
      type="info"
      show-icon
      message="请先选择驭屏系统并开始录制。系统将打开浏览器会话，通过 SoM 截图点击或元素列表引导逐步操作并生成技能步骤。"
      style="margin-bottom: 12px"
    />

    <div v-else class="recorder-layout">
      <!-- 主区：页面观测 -->
      <div class="panel observe-panel">
        <div class="panel-title-row">
          <div class="panel-title">页面观测</div>
          <span class="hint">点击标注框可选中目标元素</span>
        </div>
        <div class="meta-line">
          <span>会话：{{ shortId(screenSessionId) }}</span>
          <span v-if="currentUrl" class="url" :title="currentUrl">{{ currentUrl }}</span>
        </div>
        <div class="som-wrap">
          <div v-if="somImage" class="som-stage">
            <img
              ref="somImgRef"
              :src="somImageSrc"
              alt="SoM 截图"
              class="som-img"
              draggable="false"
              @load="onSomImgLoad"
              @click="onSomClick"
            />
            <div
              v-if="selectedHighlight"
              class="som-highlight"
              :style="selectedHighlight"
            />
          </div>
          <div v-else class="som-empty">暂无截图，请刷新观测</div>
        </div>
      </div>

      <!-- 右侧：元素与动作 + 轨迹 -->
      <aside class="right-rail">
        <div class="panel act-panel">
          <div class="panel-title">元素与动作</div>
          <a-input-search
            v-model:value="elementQuery"
            placeholder="搜索元素 label / role / ref"
            style="margin-bottom: 8px"
            allow-clear
          />
          <a-table
            :dataSource="filteredElements"
            :columns="elementColumns"
            rowKey="ref"
            size="small"
            :pagination="{ pageSize: 6, size: 'small' }"
            :row-class-name="(r) => (r.ref === selectedRef ? 'row-selected' : '')"
            :customRow="(record) => ({ onClick: () => selectElement(record) })"
            :scroll="{ y: 180 }"
          />
          <a-form layout="vertical" class="act-form" size="small">
            <a-form-item label="已选目标">
              <a-input :value="selectedSummary" disabled />
            </a-form-item>
            <a-row :gutter="8">
              <a-col :span="12">
                <a-form-item label="动作" required>
                  <a-select v-model:value="actForm.action" style="width: 100%">
                    <a-select-option v-for="a in ACTION_OPTIONS" :key="a" :value="a">{{ a }}</a-select-option>
                  </a-select>
                </a-form-item>
              </a-col>
              <a-col :span="12">
                <a-form-item label="值（type/select/press）">
                  <a-input v-model:value="actForm.value" placeholder="可选" />
                </a-form-item>
              </a-col>
            </a-row>
            <a-form-item label="步骤说明（可选，默认自动生成）">
              <a-input v-model:value="actForm.note" placeholder="例如：点击通讯录入口" />
            </a-form-item>
            <a-form-item v-if="showParamMark" label="标记为参数">
              <a-checkbox v-model:checked="actForm.markParam">将输入值编译为占位符</a-checkbox>
              <a-input
                v-if="actForm.markParam"
                v-model:value="actForm.paramKey"
                placeholder="参数名，如 query / dept"
                style="margin-top: 6px"
                allow-clear
              />
            </a-form-item>
            <a-button type="primary" block :loading="acting" :disabled="!canAct" @click="doAct">
              执行并录制
            </a-button>
          </a-form>
        </div>

        <div class="panel traj-panel">
          <div class="panel-title-row">
            <div class="panel-title">轨迹（{{ trajectory.length }}）</div>
            <a-space>
              <a-button size="small" :disabled="!trajectory.length" @click="clearSteps">清空</a-button>
              <a-button type="primary" size="small" :disabled="!trajectory.length" @click="openSave">完成并保存</a-button>
            </a-space>
          </div>
          <div v-if="!trajectory.length" class="traj-empty">尚无步骤。在观测图或元素列表中选择目标并执行动作。</div>
          <div v-else class="traj-list">
            <div v-for="(st, idx) in trajectory" :key="idx" class="traj-item">
              <div class="traj-head">
                <a-tag color="blue">#{{ st.step_order || idx + 1 }}</a-tag>
                <code>{{ st.action }}</code>
                <span class="traj-label">{{ st.target_label || st.target_ref || '' }}</span>
                <a-tag v-if="st.param_key" color="purple" style="margin-left: 6px">{{ '{' + '{' + st.param_key + '}' + '}' }}</a-tag>
                <a style="color: #b5341c; margin-left: auto" @click="removeStep(idx)">删除</a>
              </div>
              <a-textarea
                :value="st.note || ''"
                :rows="2"
                placeholder="步骤描述"
                @change="(e) => updateStepNote(idx, e.target.value)"
              />
            </div>
          </div>
        </div>
      </aside>
    </div>

    <a-modal
      v-model:open="saveOpen"
      title="保存为 UI 技能"
      ok-text="编译并保存"
      cancel-text="取消"
      :confirmLoading="saving"
      @ok="saveSkill"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="saveForm.name" :maxlength="128" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="saveForm.description" :rows="4" placeholder="技能用途与适用场景" />
        </a-form-item>
        <a-form-item label="Scope">
          <a-input v-model:value="saveForm.scope" placeholder="default" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const ACTION_OPTIONS = ['click', 'type', 'select', 'press', 'scroll', 'wait', 'navigate']

const router = useRouter()
const systems = ref([])
const systemId = ref(undefined)
const screenSessionId = ref('')
const currentUrl = ref('')
const somImage = ref('')
const elements = ref([])
const elementQuery = ref('')
const selectedRef = ref('')
const selectedLabel = ref('')
const trajectory = ref([])
const hitlPending = ref(false)
const hitlApprovalId = ref('')
const observeAlert = ref(null)
const somImgRef = ref(null)
const imgNatural = ref({ w: 0, h: 0 })
const imgDisplay = ref({ w: 0, h: 0 })

const starting = ref(false)
const observing = ref(false)
const acting = ref(false)
const closing = ref(false)
const saving = ref(false)
const saveOpen = ref(false)
const saveForm = ref({ name: '', description: '', scope: 'default' })

const actForm = ref({
  action: 'click',
  value: '',
  note: '',
  markParam: false,
  paramKey: '',
})

const showParamMark = computed(() =>
  ['type', 'fill', 'select'].includes((actForm.value.action || '').toLowerCase()),
)

function suggestParamKey(label) {
  const lab = (label || '').trim()
  const low = lab.toLowerCase()
  if (/搜索|检索|关键词|关键字/.test(lab) || /search|query|keyword/.test(low)) return 'query'
  if (/部门/.test(lab) || /dept|department/.test(low)) return 'dept'
  if (/姓名|人名/.test(lab) || low === 'name') return 'name'
  if (/标题|主题/.test(lab) || /title|subject/.test(low)) return 'title'
  if (/日期/.test(lab) || /date/.test(low)) return 'date'
  const cleaned = lab.replace(/[^\w\u4e00-\u9fff]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')
  if (!cleaned) return 'value'
  // Prefer latin-ish keys; fallback to value
  if (/^[A-Za-z][\w]*$/.test(cleaned)) return cleaned.slice(0, 32)
  return 'value'
}

const systemOptions = computed(() =>
  (systems.value || []).map((s) => ({
    value: s.system_id,
    label: `${s.name} (${s.status || 'ACTIVE'})`,
    disabled: s.status && s.status !== 'ACTIVE',
  })),
)

const elementColumns = [
  { title: 'ref', dataIndex: 'ref', key: 'ref', width: 56 },
  { title: 'label', dataIndex: 'label', key: 'label', ellipsis: true },
  { title: 'role', dataIndex: 'role', key: 'role', width: 72 },
]

const filteredElements = computed(() => {
  const q = (elementQuery.value || '').trim().toLowerCase()
  const list = elements.value || []
  if (!q) return list
  return list.filter((el) => {
    const blob = `${el.ref || ''} ${el.label || ''} ${el.role || ''}`.toLowerCase()
    return blob.includes(q)
  })
})

const selectedSummary = computed(() => {
  if (!selectedRef.value) return '未选择'
  return `${selectedRef.value} ${selectedLabel.value || ''}`.trim()
})

const canAct = computed(() => {
  if (!screenSessionId.value || acting.value) return false
  const action = actForm.value.action
  if (action === 'navigate' || action === 'wait' || action === 'scroll' || action === 'press') {
    return true
  }
  return !!selectedRef.value
})

const somImageSrc = computed(() => {
  if (!somImage.value) return ''
  if (somImage.value.startsWith('data:')) return somImage.value
  return `data:image/png;base64,${somImage.value}`
})

const selectedElement = computed(() => {
  if (!selectedRef.value) return null
  return (elements.value || []).find((el) => el.ref === selectedRef.value) || null
})

/** Highlight overlay in displayed-image CSS pixels */
const selectedHighlight = computed(() => {
  const el = selectedElement.value
  const nw = imgNatural.value.w
  const nh = imgNatural.value.h
  const dw = imgDisplay.value.w
  const dh = imgDisplay.value.h
  if (!el || !nw || !nh || !dw || !dh) return null
  const box = el.box || {}
  const x = Number(box.x) || 0
  const y = Number(box.y) || 0
  const w = Number(box.width) || 0
  const h = Number(box.height) || 0
  if (w <= 0 || h <= 0) return null
  const sx = dw / nw
  const sy = dh / nh
  return {
    left: `${x * sx}px`,
    top: `${y * sy}px`,
    width: `${w * sx}px`,
    height: `${h * sy}px`,
  }
})

function shortId(id) {
  if (!id) return ''
  return id.length > 12 ? `${id.slice(0, 8)}…` : id
}

function filterSystem(input, option) {
  return (option?.label || '').toLowerCase().includes((input || '').toLowerCase())
}

function selectElement(record) {
  selectedRef.value = record.ref
  selectedLabel.value = record.label || ''
  if (showParamMark.value && actForm.value.markParam && !actForm.value.paramKey) {
    actForm.value.paramKey = suggestParamKey(selectedLabel.value)
  }
}

function syncImgMetrics() {
  const img = somImgRef.value
  if (!img) return
  imgNatural.value = { w: img.naturalWidth || 0, h: img.naturalHeight || 0 }
  imgDisplay.value = { w: img.clientWidth || 0, h: img.clientHeight || 0 }
}

function onSomImgLoad() {
  syncImgMetrics()
}

function pointInBox(px, py, box) {
  const x = Number(box?.x) || 0
  const y = Number(box?.y) || 0
  const w = Number(box?.width) || 0
  const h = Number(box?.height) || 0
  if (w <= 0 || h <= 0) return false
  return px >= x && px <= x + w && py >= y && py <= y + h
}

function findElementAtImagePoint(px, py) {
  const hits = (elements.value || []).filter((el) => pointInBox(px, py, el.box))
  if (!hits.length) return null
  // Prefer smallest area (most specific nested target)
  hits.sort((a, b) => {
    const aw = (Number(a.box?.width) || 0) * (Number(a.box?.height) || 0)
    const bw = (Number(b.box?.width) || 0) * (Number(b.box?.height) || 0)
    return aw - bw
  })
  return hits[0]
}

function onSomClick(ev) {
  const img = somImgRef.value
  if (!img) return
  syncImgMetrics()
  const nw = img.naturalWidth
  const nh = img.naturalHeight
  const rect = img.getBoundingClientRect()
  if (!nw || !nh || !rect.width || !rect.height) return
  const px = ((ev.clientX - rect.left) / rect.width) * nw
  const py = ((ev.clientY - rect.top) / rect.height) * nh
  const hit = findElementAtImagePoint(px, py)
  if (!hit) {
    message.info('该位置没有可交互元素')
    return
  }
  selectElement(hit)
}

function applyObserve(res) {
  if (!res?.success) {
    message.error(res?.error || '观测失败')
    return
  }
  currentUrl.value = res.url || ''
  elements.value = res.elements || []
  somImage.value = res.som_image_b64 || res.screenshot_b64 || ''
  // Keep selection if still present
  if (selectedRef.value && !(elements.value || []).some((e) => e.ref === selectedRef.value)) {
    selectedRef.value = ''
    selectedLabel.value = ''
  }
  const warning = (res.warning || '').trim()
  const recovery = (res.recovery_hint || '').trim()
  if (res.risk_blocked || warning) {
    observeAlert.value = {
      type: 'error',
      message: res.risk_blocked
        ? `安全限制（${res.error_code || 'RISK'}）`
        : '观测提示',
      description: [warning, recovery].filter(Boolean).join(' '),
      showSystemsLink: true,
    }
  } else if (res.login_required) {
    observeAlert.value = {
      type: 'warning',
      message: '需要登录',
      description: warning || '页面疑似未登录，请先完成登录后再录制。',
      showSystemsLink: true,
    }
  } else if (!(res.elements || []).length) {
    observeAlert.value = {
      type: 'warning',
      message: '未识别到可交互元素',
      description: '可点击「刷新观测」。若目标站有风控，请在驭屏系统开启「复用本地浏览器」。',
      showSystemsLink: true,
    }
  } else {
    observeAlert.value = null
  }
  nextTick(() => syncImgMetrics())
}

function handleHitl(res) {
  if (res?.hitl_pending) {
    hitlPending.value = true
    hitlApprovalId.value = res.approval_id || ''
    message.warning(res.message || '操作需审批')
    return true
  }
  hitlPending.value = false
  hitlApprovalId.value = ''
  return false
}

async function loadSystems() {
  try {
    systems.value = await screenpilotApi.listSystems()
  } catch (e) {
    message.error(e.message)
  }
}

async function startSession() {
  if (!systemId.value) return
  starting.value = true
  try {
    const res = await screenpilotApi.navigateSession({
      system_id: systemId.value,
      auto_login: true,
    })
    if (handleHitl(res)) {
      if (res.screen_session_id) screenSessionId.value = res.screen_session_id
      return
    }
    if (!res.success) {
      message.error(res.error || '启动会话失败')
      return
    }
    screenSessionId.value = res.screen_session_id || ''
    applyObserve(res)
    await reloadTrajectory()
    message.success('录制会话已启动')
  } catch (e) {
    message.error(e.message)
  } finally {
    starting.value = false
  }
}

async function refreshObserve() {
  if (!screenSessionId.value) return
  observing.value = true
  try {
    const res = await screenpilotApi.observeSession(screenSessionId.value)
    applyObserve(res)
    hitlPending.value = false
  } catch (e) {
    message.error(e.message)
  } finally {
    observing.value = false
  }
}

async function reloadTrajectory() {
  if (!screenSessionId.value) return
  try {
    const res = await screenpilotApi.getTrajectory(screenSessionId.value)
    trajectory.value = res.steps || []
  } catch (e) {
    message.error(e.message)
  }
}

async function doAct() {
  if (!canAct.value) return
  acting.value = true
  try {
    let paramKey = null
    if (showParamMark.value && actForm.value.markParam) {
      paramKey = (actForm.value.paramKey || suggestParamKey(selectedLabel.value)).trim() || null
    }
    const payload = {
      action: actForm.value.action,
      target_ref: selectedRef.value || null,
      value: actForm.value.value || null,
      note: actForm.value.note || null,
      param_key: paramKey,
    }
    const res = await screenpilotApi.actSession(screenSessionId.value, payload)
    if (handleHitl(res)) return
    if (!res.success) {
      message.error(res.error || '动作执行失败')
      return
    }
    if (res.observe) applyObserve({ success: true, ...res.observe })
    else await refreshObserve()
    await reloadTrajectory()
    actForm.value.note = ''
    actForm.value.value = ''
    actForm.value.markParam = false
    actForm.value.paramKey = ''
    message.success('已录制一步')
  } catch (e) {
    message.error(e.message)
  } finally {
    acting.value = false
  }
}

async function updateStepNote(idx, note) {
  const next = trajectory.value.map((s, i) => (i === idx ? { ...s, note } : s))
  trajectory.value = next
  try {
    await screenpilotApi.replaceTrajectory(screenSessionId.value, { steps: next })
  } catch (e) {
    message.error(e.message)
  }
}

async function removeStep(idx) {
  const next = trajectory.value.filter((_, i) => i !== idx).map((s, i) => ({
    ...s,
    step_order: i + 1,
  }))
  trajectory.value = next
  try {
    await screenpilotApi.replaceTrajectory(screenSessionId.value, { steps: next })
  } catch (e) {
    message.error(e.message)
  }
}

async function clearSteps() {
  Modal.confirm({
    title: '清空轨迹？',
    content: '已录制的步骤将被清除，不可恢复。',
    okText: '清空',
    okType: 'danger',
    async onOk() {
      await screenpilotApi.clearTrajectory(screenSessionId.value)
      trajectory.value = []
      message.success('轨迹已清空')
    },
  })
}

function openSave() {
  const sys = systems.value.find((s) => s.system_id === systemId.value)
  const sysName = sys?.name || '目标系统'
  const labels = trajectory.value
    .map((s) => (s.target_label || '').trim())
    .filter(Boolean)
    .slice(0, 3)
  const obj = labels[0] || '常用操作'
  saveForm.value = {
    name: `${sysName}操作${obj}`.slice(0, 32),
    description: labels.length
      ? `${sysName}录制技能；步骤: ${labels.join(' → ')}`
      : `${sysName}录制技能`,
    scope: 'default',
  }
  saveOpen.value = true
}

async function saveSkill(forceCreate = false) {
  if (!saveForm.value.name?.trim()) {
    message.warning('请填写技能名称')
    return
  }
  saving.value = true
  try {
    await screenpilotApi.replaceTrajectory(screenSessionId.value, { steps: trajectory.value })
    const res = await screenpilotApi.compileSkill({
      screen_session_id: screenSessionId.value,
      name: saveForm.value.name.trim(),
      description: saveForm.value.description || '',
      scope: saveForm.value.scope || 'default',
      force_create: !!forceCreate,
    })
    if (res.duplicate_found && !forceCreate) {
      saving.value = false
      Modal.confirm({
        title: '发现相似技能',
        content: res.message || res.error || `已存在相似技能「${res.name}」`,
        okText: '仍要新建',
        cancelText: '复用已有',
        onOk: () => saveSkill(true),
        onCancel: () => {
          saveOpen.value = false
          if (res.skill_id) {
            router.push({ path: '/screenpilot/skills', query: { skill_id: res.skill_id } })
          }
        },
      })
      return
    }
    if (!res.success) {
      message.error(res.error || '编译失败')
      return
    }
    if (res.deduplicated) {
      message.info(res.message || '已复用相似技能')
    } else {
      message.success(`技能已保存（${res.step_count || 0} 步）`)
    }
    saveOpen.value = false
    router.push({ path: '/screenpilot/skills', query: { skill_id: res.skill_id } })
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function endSession() {
  if (!screenSessionId.value) return
  closing.value = true
  try {
    await screenpilotApi.closeSession(screenSessionId.value)
    screenSessionId.value = ''
    elements.value = []
    somImage.value = ''
    trajectory.value = []
    currentUrl.value = ''
    selectedRef.value = ''
    selectedLabel.value = ''
    observeAlert.value = null
    message.success('会话已结束')
  } catch (e) {
    message.error(e.message)
  } finally {
    closing.value = false
  }
}

function onWindowResize() {
  syncImgMetrics()
}

onMounted(() => {
  loadSystems()
  window.addEventListener('resize', onWindowResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  if (screenSessionId.value) {
    screenpilotApi.closeSession(screenSessionId.value).catch(() => {})
  }
})
</script>

<style scoped>
.recorder-page { padding: 0 4px; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 4px;
}
.header-left h2 { margin: 0; }
.recorder-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 12px;
  align-items: stretch;
  min-height: calc(100vh - 200px);
}
@media (max-width: 1100px) {
  .recorder-layout {
    grid-template-columns: 1fr;
  }
}
.panel {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  background: #fff;
  padding: 12px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.observe-panel {
  min-height: 560px;
}
.panel-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.panel-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 8px;
}
.panel-title-row .panel-title { margin-bottom: 0; }
.hint {
  font-size: 12px;
  color: #8c8c8c;
  white-space: nowrap;
}
.meta-line {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #8c8c8c;
  margin-bottom: 8px;
}
.meta-line .url {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.som-wrap {
  flex: 1;
  overflow: auto;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  min-height: 420px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}
.som-stage {
  position: relative;
  display: inline-block;
  max-width: 100%;
  line-height: 0;
}
.som-img {
  max-width: 100%;
  height: auto;
  display: block;
  cursor: crosshair;
  user-select: none;
}
.som-highlight {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid #1677ff;
  background: rgba(22, 119, 255, 0.18);
  pointer-events: none;
  border-radius: 2px;
}
.som-empty, .traj-empty {
  color: #bfbfbf;
  padding: 24px;
  text-align: center;
  width: 100%;
}
.right-rail {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  max-height: calc(100vh - 200px);
}
.act-panel {
  flex: 0 0 auto;
}
.act-form { margin-top: 8px; }
.traj-panel {
  flex: 1 1 auto;
  min-height: 200px;
}
.traj-list {
  overflow: auto;
  flex: 1;
  min-height: 0;
}
.traj-item {
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  padding: 8px;
  margin-bottom: 8px;
}
.traj-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  font-size: 12px;
}
.traj-label {
  color: #595959;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 120px;
}
:deep(.row-selected) td {
  background: #e6f4ff !important;
}
</style>

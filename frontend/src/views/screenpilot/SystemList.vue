<template>
  <div class="screenpilot-page">
    <div class="page-header">
      <h2>驭屏系统管理</h2>
      <a-space>
        <a-tag :color="enabled ? 'green' : 'default'">
          {{ enabled ? 'ScreenPilot 已启用' : 'ScreenPilot 未启用' }}
        </a-tag>
        <a-button type="primary" :disabled="!enabled" @click="openCreate">注册系统</a-button>
      </a-space>
    </div>

    <a-alert
      v-if="!enabled"
      message="请先在「系统配置」中打开驭屏系统（将自动注册 cu_* MCP 工具），并确保已安装 Playwright Chromium"
      type="info"
      show-icon
      style="margin-bottom: 16px;"
    />

    <a-table
      :dataSource="systems"
      :columns="columns"
      rowKey="system_id"
      :loading="loading"
      size="middle"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'default'">
            {{ record.status === 'ACTIVE' ? '已激活' : '未激活' }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space>
            <a @click="openEdit(record)">修改</a>
            <a @click="openCredentials(record)">凭证</a>
            <a v-if="record.status !== 'ACTIVE'" @click="setStatus(record, 'ACTIVE')">激活</a>
            <a v-else @click="setStatus(record, 'INACTIVE')">停用</a>
            <a-popconfirm
              title="确认删除该系统？相关凭据、会话与技能将一并删除。"
              ok-text="删除"
              cancel-text="取消"
              @confirm="removeSystem(record)"
            >
              <a style="color: #b5341c">删除</a>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-drawer
      v-model:open="credDrawerOpen"
      :title="`凭证 — ${credSystemName}`"
      width="480"
      destroyOnClose
    >
      <a-alert
        type="info"
        show-icon
        style="margin-bottom: 16px"
        :message="credHelpText"
      />
      <a-table
        :dataSource="credentials"
        :columns="credColumns"
        rowKey="credential_id"
        :loading="credLoading"
        size="small"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'has_value'">
            <a-tag :color="record.has_value ? 'green' : 'default'">
              {{ record.has_value ? '已设置' : '空' }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'action'">
            <a-space>
              <a @click="openCredEdit(record)">更新</a>
              <a-popconfirm title="确认删除该凭证？" @confirm="removeCredential(record)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
      <a-divider />
      <a-form layout="vertical">
        <a-form-item label="name（键）" required>
          <a-input v-model:value="credForm.name" placeholder="username / password / 其它键" />
        </a-form-item>
        <a-form-item label="value" required>
          <a-input-password
            v-if="isSecretCredName(credForm.name)"
            v-model:value="credForm.value"
            placeholder="明文仅在保存时传输并加密"
          />
          <a-input v-else v-model:value="credForm.value" placeholder="凭证值" />
        </a-form-item>
        <a-button type="primary" :loading="credSaving" @click="saveCredential">
          {{ credEditingId ? '更新凭证' : '新增凭证' }}
        </a-button>
        <a-button v-if="credEditingId" style="margin-left: 8px" @click="resetCredForm">取消编辑</a-button>
      </a-form>
    </a-drawer>

    <a-modal
      v-model:open="modalOpen"
      :title="editingId ? '修改目标系统' : '注册目标系统'"
      @ok="saveSystem"
      :confirmLoading="saving"
      destroyOnClose
    >
      <a-form layout="vertical">
        <a-form-item label="系统名称" required>
          <a-input v-model:value="form.name" placeholder="例如：OA 费控系统" />
        </a-form-item>
        <a-form-item label="入口 URL">
          <a-input v-model:value="form.entry_url" placeholder="https://oa.internal.corp/" />
        </a-form-item>
        <a-form-item label="域名白名单（逗号分隔）">
          <a-input v-model:value="domainsText" placeholder="oa.internal.corp, erp.internal.corp" />
        </a-form-item>
        <a-form-item label="登录类型">
          <a-select v-model:value="form.login_type">
            <a-select-option value="form">表单登录</a-select-option>
            <a-select-option value="sso">SSO</a-select-option>
            <a-select-option value="cas">CAS</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="执行模式">
          <a-select v-model:value="form.exec_mode">
            <a-select-option value="browser">浏览器</a-select-option>
            <a-select-option value="desktop">桌面</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item v-if="editingId" label="状态">
          <a-select v-model:value="form.status">
            <a-select-option value="ACTIVE">已激活</a-select-option>
            <a-select-option value="INACTIVE">未激活</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item>
          <template #label>
            <span class="login-macro-label">
              登录宏 (JSON)
              <a-tooltip title="查看登录宏说明与示例">
                <QuestionCircleOutlined
                  class="login-macro-help-icon"
                  @click.stop="loginMacroHelpOpen = true"
                />
              </a-tooltip>
            </span>
          </template>
          <a-textarea
            v-model:value="loginMacroText"
            :rows="8"
            placeholder='{"steps":[{"action":"fill","selector":"#phone","value":"{{username}}"},{"action":"wait_for_otp","selector":"#code","submit_selector":"#submit","prompt":"请输入短信验证码"}]}'
          />
          <div style="margin-top: 6px; font-size: 12px; color: #888;">
            支持 goto / fill / click / wait / wait_for_otp；变量 &#123;&#123;username&#125;&#125; / &#123;&#123;password&#125;&#125; 从「凭证」读取并解密，勿在宏中写明文密码。
            登录成功后 Cookie 自动保存 24 小时。
          </div>
        </a-form-item>
        <a-form-item label="风险规则 risk_rules (JSON)">
          <a-textarea
            v-model:value="riskRulesText"
            :rows="6"
            placeholder='{"block_url_substrings":["website-login/error"],"block_body_hints":["ip存在风险"],"block_error_code":"RISK_BLOCK","block_message":"页面触发安全限制","recovery_hint":"切换可信网络后重试"}'
          />
          <div style="margin-top: 6px; font-size: 12px; color: #888;">
            站点风控/拦截页配置放这里，引擎不硬编码站点文案。字段：block_url_substrings、block_body_hints、block_error_code、block_message、recovery_hint、t3_labels。
          </div>
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="loginMacroHelpOpen"
      title="登录宏说明"
      :footer="null"
      width="720px"
      destroyOnClose
    >
      <div class="login-macro-help">
        <p>
          登录宏是写在目标系统上的确定性 JSON 流程，由
          <code>cu_navigate(..., auto_login=true)</code>
          执行，不走 LLM。需先为该系统配置凭据；成功后 Cookie 自动保存约 24 小时。
        </p>

        <h4>基本结构</h4>
        <pre>{{ helpStructure }}</pre>

        <h4>支持的 action</h4>
        <a-table
          size="small"
          :pagination="false"
          :columns="helpActionColumns"
          :dataSource="helpActionRows"
          rowKey="action"
        />

        <h4>模板变量</h4>
        <ul>
          <li><code>&#123;&#123;username&#125;&#125;</code>：凭据用户名（可放手机号）</li>
          <li><code>&#123;&#123;password&#125;&#125;</code>：解密后的密码</li>
          <li><code>&#123;&#123;otp&#125;&#125;</code>：OTP 模板占位；真正验证码在 HITL 提交后填入</li>
        </ul>

        <h4>触发说明</h4>
        <ul>
          <li><code>auto_login=true</code> 且存在 <code>steps</code> 时才会跑宏</li>
          <li><code>auto_login=false</code> 时不执行宏，由 Agent 逐步调用 <code>cu_act</code></li>
          <li><code>wait_for_otp</code> 会弹出人工审批，填入验证码后继续后续步骤</li>
          <li><code>selector</code> 使用 Playwright/CSS 选择器，请在目标登录页用 DevTools 核对</li>
        </ul>

        <h4>示例：账号密码登录</h4>
        <pre>{{ helpExamplePassword }}</pre>

        <h4>示例：手机号 + 短信验证码</h4>
        <pre>{{ helpExampleOtp }}</pre>
        <p class="help-note">
          上例 selector 仅为示意；小红书等站点请先确认页面可打开登录表单（非 IP 风控页），再换成真实 DOM 选择器。
        </p>

        <h4>最小联通验证</h4>
        <pre>{{ helpExampleMinimal }}</pre>

        <h4>risk_rules 示例（站点风控外置，勿写进引擎）</h4>
        <pre>{{ helpExampleRiskRules }}</pre>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { screenpilotApi } from '../../api'

const loading = ref(false)
const saving = ref(false)
const enabled = ref(false)
const systems = ref([])
const modalOpen = ref(false)
const loginMacroHelpOpen = ref(false)
const editingId = ref(null)
const domainsText = ref('')
const loginMacroText = ref('{\n  "steps": []\n}')
const riskRulesText = ref('{\n}\n')
const form = ref(emptyForm())

const helpStructure = `{
  "steps": [
    { "action": "...", "selector": "...", "value": "...", "wait_ms": 300 }
  ]
}`

const helpActionColumns = [
  { title: 'action', dataIndex: 'action', key: 'action', width: 120 },
  { title: '作用', dataIndex: 'desc', key: 'desc', width: 140 },
  { title: '关键字段', dataIndex: 'fields', key: 'fields' },
]

const helpActionRows = [
  { action: 'goto', desc: '打开页面', fields: 'value（URL，空则用入口 URL）' },
  { action: 'fill', desc: '填输入框', fields: 'selector + value' },
  { action: 'click', desc: '点击', fields: 'selector' },
  { action: 'wait', desc: '纯等待', fields: 'wait_ms（毫秒，默认 300）' },
  { action: 'wait_for_otp', desc: '暂停等人填验证码', fields: 'selector、可选 submit_selector / prompt' },
]

const helpExamplePassword = `{
  "steps": [
    { "action": "goto", "value": "https://example.com/login", "wait_ms": 500 },
    { "action": "fill", "selector": "#username", "value": "{{username}}" },
    { "action": "fill", "selector": "#password", "value": "{{password}}" },
    { "action": "click", "selector": "button[type=submit]", "wait_ms": 1000 }
  ]
}`

const helpExampleOtp = `{
  "steps": [
    { "action": "goto", "value": "https://example.com/login", "wait_ms": 800 },
    { "action": "click", "selector": "input[type='checkbox']", "wait_ms": 300 },
    { "action": "fill", "selector": "input[type='tel']", "value": "{{username}}" },
    { "action": "click", "selector": "button:has-text('获取验证码')", "wait_ms": 500 },
    {
      "action": "wait_for_otp",
      "selector": "input[placeholder*='验证码']",
      "submit_selector": "button:has-text('登录')",
      "prompt": "请输入短信验证码",
      "wait_ms": 500
    }
  ]
}`

const helpExampleMinimal = `{
  "steps": [
    { "action": "goto", "value": "https://example.com/login", "wait_ms": 1000 },
    { "action": "wait", "wait_ms": 2000 }
  ]
}`

/** Example risk_rules for systems that show IP/security interstitial pages. */
const helpExampleRiskRules = `{
  "block_url_substrings": ["website-login/error", "error_code=300012"],
  "block_body_hints": ["ip存在风险", "安全限制", "切换可靠网络"],
  "block_error_code": "300012",
  "block_message": "检测到当前网络存在风险，登录被拦截",
  "recovery_hint": "关闭 VPN/代理，改用手机热点，并确认 entry_url 指向真实登录页",
  "t3_labels": []
}`

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '入口 URL', dataIndex: 'entry_url', key: 'entry_url', ellipsis: true },
  { title: '登录', dataIndex: 'login_type', key: 'login_type', width: 90 },
  { title: '模式', dataIndex: 'exec_mode', key: 'exec_mode', width: 90 },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 260 },
]

const credColumns = [
  { title: 'name', dataIndex: 'name', key: 'name' },
  { title: '值', key: 'has_value', width: 90 },
  { title: '操作', key: 'action', width: 120 },
]

const credDrawerOpen = ref(false)
const credLoading = ref(false)
const credSaving = ref(false)
const credSystemId = ref('')
const credSystemName = ref('')
const credentials = ref([])
const credEditingId = ref(null)
const credForm = ref({ name: '', value: '' })
const credHelpText =
  '使用 name/value 保存；password 等敏感值加密存储。登录宏中填写 {{username}} / {{password}}，勿写明文。'

function isSecretCredName(name) {
  const n = (name || '').toLowerCase()
  return n.includes('password') || n.includes('secret') || n.includes('token') || n === '密码'
}

function resetCredForm() {
  credEditingId.value = null
  credForm.value = { name: '', value: '' }
}

async function openCredentials(record) {
  credSystemId.value = record.system_id
  credSystemName.value = record.name || ''
  resetCredForm()
  credDrawerOpen.value = true
  await loadCredentials()
}

async function loadCredentials() {
  if (!credSystemId.value) return
  credLoading.value = true
  try {
    credentials.value = await screenpilotApi.listCredentials(credSystemId.value)
  } catch (e) {
    message.error(e.message)
  } finally {
    credLoading.value = false
  }
}

function openCredEdit(record) {
  credEditingId.value = record.credential_id
  credForm.value = { name: record.name || '', value: '' }
}

async function saveCredential() {
  const name = (credForm.value.name || '').trim()
  const value = credForm.value.value || ''
  if (!name) {
    message.warning('请填写 name')
    return
  }
  if (!value) {
    message.warning('请填写 value')
    return
  }
  credSaving.value = true
  try {
    if (credEditingId.value) {
      await screenpilotApi.updateCredential(credEditingId.value, { value })
      message.success('凭证已更新')
    } else {
      await screenpilotApi.createCredential({
        system_id: credSystemId.value,
        name,
        value,
      })
      message.success('凭证已保存')
    }
    resetCredForm()
    await loadCredentials()
  } catch (e) {
    message.error(e.message)
  } finally {
    credSaving.value = false
  }
}

async function removeCredential(record) {
  try {
    await screenpilotApi.deleteCredential(record.credential_id)
    message.success('已删除')
    await loadCredentials()
  } catch (e) {
    message.error(e.message)
  }
}

function emptyForm() {
  return {
    name: '',
    entry_url: '',
    login_type: 'form',
    exec_mode: 'browser',
    status: 'ACTIVE',
  }
}

function parseDomains(text) {
  return text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    const status = await screenpilotApi.status()
    enabled.value = !!status.enabled
    if (enabled.value) {
      systems.value = await screenpilotApi.listSystems()
    } else {
      systems.value = []
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  domainsText.value = ''
  loginMacroText.value = '{\n  "steps": []\n}'
  riskRulesText.value = '{\n}\n'
  modalOpen.value = true
}

function openEdit(record) {
  editingId.value = record.system_id
  form.value = {
    name: record.name || '',
    entry_url: record.entry_url || '',
    login_type: record.login_type || 'form',
    exec_mode: record.exec_mode || 'browser',
    status: record.status || 'ACTIVE',
  }
  domainsText.value = (record.allowed_domains || []).join(', ')
  loginMacroText.value = JSON.stringify(record.login_macro || { steps: [] }, null, 2)
  riskRulesText.value = JSON.stringify(record.risk_rules || {}, null, 2)
  modalOpen.value = true
}

function parseLoginMacro(text) {
  const trimmed = (text || '').trim()
  if (!trimmed) return { steps: [] }
  return JSON.parse(trimmed)
}

function parseRiskRules(text) {
  const trimmed = (text || '').trim()
  if (!trimmed) return {}
  const parsed = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('risk_rules must be an object')
  }
  return parsed
}

async function saveSystem() {
  if (!form.value.name.trim()) {
    message.warning('请填写系统名称')
    return
  }
  saving.value = true
  try {
    const allowed_domains = parseDomains(domainsText.value)
    let login_macro
    let risk_rules
    try {
      login_macro = parseLoginMacro(loginMacroText.value)
    } catch {
      message.error('登录宏 JSON 格式无效')
      saving.value = false
      return
    }
    try {
      risk_rules = parseRiskRules(riskRulesText.value)
    } catch {
      message.error('风险规则 JSON 格式无效')
      saving.value = false
      return
    }
    if (editingId.value) {
      await screenpilotApi.updateSystem(editingId.value, {
        name: form.value.name.trim(),
        entry_url: form.value.entry_url,
        login_type: form.value.login_type,
        exec_mode: form.value.exec_mode,
        allowed_domains,
        status: form.value.status,
        login_macro,
        risk_rules,
      })
      message.success('系统已更新')
    } else {
      await screenpilotApi.createSystem({
        name: form.value.name.trim(),
        entry_url: form.value.entry_url,
        login_type: form.value.login_type,
        exec_mode: form.value.exec_mode,
        allowed_domains,
        login_macro,
        risk_rules,
      })
      message.success('系统已注册')
    }
    modalOpen.value = false
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function setStatus(record, status) {
  try {
    await screenpilotApi.updateSystem(record.system_id, { status })
    message.success(status === 'ACTIVE' ? '已激活' : '已停用')
    await load()
  } catch (e) {
    message.error(e.message)
  }
}

async function removeSystem(record) {
  try {
    await screenpilotApi.deleteSystem(record.system_id)
    message.success('系统已删除')
    await load()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.screenpilot-page {
  padding: 0 4px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 {
  margin: 0;
}
.login-macro-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.login-macro-help-icon {
  color: #8c8c8c;
  cursor: pointer;
  font-size: 14px;
}
.login-macro-help-icon:hover {
  color: #1677ff;
}
.login-macro-help h4 {
  margin: 16px 0 8px;
  font-size: 14px;
}
.login-macro-help p {
  margin: 0 0 8px;
  line-height: 1.6;
  color: #333;
}
.login-macro-help ul {
  margin: 0 0 8px;
  padding-left: 20px;
  line-height: 1.7;
}
.login-macro-help pre {
  margin: 0 0 8px;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.login-macro-help code {
  padding: 1px 4px;
  background: #f5f5f5;
  border-radius: 3px;
  font-size: 12px;
}
.login-macro-help .help-note {
  font-size: 12px;
  color: #888;
}
</style>

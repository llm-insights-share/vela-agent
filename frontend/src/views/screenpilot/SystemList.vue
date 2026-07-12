<template>
  <div class="screenpilot-page">
    <div class="page-header">
      <h2>驭屏系统管理</h2>
      <a-space>
        <a-tag :color="enabled ? 'green' : 'default'">
          {{ enabled ? 'ScreenPilot 已启用' : 'ScreenPilot 未启用' }}
        </a-tag>
        <a-button type="primary" @click="showCreate = true">注册系统</a-button>
      </a-space>
    </div>

    <a-alert
      v-if="!enabled"
      message="后端需设置环境变量 SCREENPILOT_ENABLED=true 并安装 Playwright Chromium"
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
    />

    <a-modal v-model:open="showCreate" title="注册目标系统" @ok="createSystem" :confirmLoading="saving">
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
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const loading = ref(false)
const saving = ref(false)
const enabled = ref(false)
const systems = ref([])
const showCreate = ref(false)
const domainsText = ref('')
const form = ref({
  name: '',
  entry_url: '',
  login_type: 'form',
})

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '入口 URL', dataIndex: 'entry_url', key: 'entry_url', ellipsis: true },
  { title: '登录', dataIndex: 'login_type', key: 'login_type', width: 90 },
  { title: '模式', dataIndex: 'exec_mode', key: 'exec_mode', width: 90 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
]

async function load() {
  loading.value = true
  try {
    const status = await screenpilotApi.status()
    enabled.value = !!status.enabled
    if (enabled.value) {
      systems.value = await screenpilotApi.listSystems()
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function createSystem() {
  if (!form.value.name.trim()) {
    message.warning('请填写系统名称')
    return
  }
  saving.value = true
  try {
    const allowed_domains = domainsText.value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    await screenpilotApi.createSystem({
      ...form.value,
      allowed_domains,
      login_macro: {},
      risk_rules: {},
    })
    message.success('系统已注册')
    showCreate.value = false
    form.value = { name: '', entry_url: '', login_type: 'form' }
    domainsText.value = ''
    await load()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
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
</style>

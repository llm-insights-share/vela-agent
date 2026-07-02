<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">系统配置</h2>
    </div>

    <a-card title="工具配置" style="margin-bottom: 24px;">
      <a-collapse v-model:activeKey="activeKeys">
        <a-collapse-panel key="tavily" header="Tavily Web Search">
          <template #extra>
            <a-tag v-if="tavilyStatus.configured" color="green">已配置</a-tag>
            <a-tag v-else color="orange">未配置</a-tag>
          </template>
          <a-form :model="tavilyForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
            <a-form-item label="API Key">
              <a-input-password
                v-model:value="tavilyForm.api_key"
                placeholder="输入 Tavily API Key"
              />
              <div class="field-hint">
                在 <a href="https://tavily.com/" target="_blank">tavily.com</a> 注册获取 API Key。
                配置后，Agent 可使用内置的 <code>tavily_web_search</code> 工具进行网络搜索。
              </div>
            </a-form-item>
            <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
              <a-button type="primary" :loading="tavilySaving" @click="saveTavily">保存</a-button>
              <a-button style="margin-left: 12px;" @click="testTavily" :loading="tavilyTesting">测试连接</a-button>
            </a-form-item>
          </a-form>
          <div v-if="tavilyTestResult" style="margin-top: 12px;">
            <a-alert
              :type="tavilyTestResult.success ? 'success' : 'error'"
              :message="tavilyTestResult.message"
              show-icon
            />
          </div>
        </a-collapse-panel>
      </a-collapse>
    </a-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { configApi } from '../../api'
import { message } from 'ant-design-vue'

const activeKeys = ref(['tavily'])
const tavilySaving = ref(false)
const tavilyTesting = ref(false)
const tavilyTestResult = ref(null)

const tavilyStatus = reactive({
  configured: false,
})

const tavilyForm = reactive({
  api_key: '',
})

async function fetchConfig() {
  try {
    const res = await configApi.getToolConfig()
    const tavily = res.tavily || {}
    tavilyStatus.configured = !!tavily.api_key
  } catch (e) {
    // ignore
  }
  try {
    const status = await configApi.getTavilyStatus()
    tavilyStatus.configured = status.configured
  } catch (e) {
    // ignore
  }
}

async function saveTavily() {
  if (!tavilyForm.api_key) {
    message.warning('请输入 API Key')
    return
  }
  tavilySaving.value = true
  try {
    await configApi.updateTavily({ api_key: tavilyForm.api_key })
    message.success('Tavily 配置已保存')
    tavilyForm.api_key = ''
    await fetchConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    tavilySaving.value = false
  }
}

async function testTavily() {
  tavilyTesting.value = true
  tavilyTestResult.value = null
  try {
    const status = await configApi.getTavilyStatus()
    if (status.configured) {
      tavilyTestResult.value = { success: true, message: 'API Key 已配置，Tavily Web Search 工具可用' }
    } else {
      tavilyTestResult.value = { success: false, message: 'API Key 未配置，请先保存 API Key' }
    }
  } catch (e) {
    tavilyTestResult.value = { success: false, message: '检查失败: ' + e.message }
  } finally {
    tavilyTesting.value = false
  }
}

onMounted(fetchConfig)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.field-hint {
  font-size: 11px;
  color: #9e9590;
  margin-top: 4px;
  line-height: 1.5;
}
.field-hint code {
  font-size: 11px;
  background: #f3f0e8;
  padding: 1px 5px;
  border-radius: 3px;
  color: #5c5650;
}
</style>

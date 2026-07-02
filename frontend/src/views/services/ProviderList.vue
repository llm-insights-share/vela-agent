<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">模型供应商</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 添加供应商
      </a-button>
    </div>
    <a-card>
      <a-table :columns="columns" :data-source="providers" :loading="loading" row-key="provider_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'red'">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openEdit(record)">编辑</a>
              <a @click="handleSync(record.provider_id)">同步模型</a>
              <a-popconfirm title="确认删除?" @confirm="handleDelete(record.provider_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑供应商' : '添加供应商'" @ok="handleSave" :confirm-loading="saving">
      <a-form :model="form" :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="供应商代码" required>
          <a-input v-model:value="form.provider_code" :disabled="!!editing" placeholder="deepseek / bailian" />
        </a-form-item>
        <a-form-item label="显示名称" required>
          <a-input v-model:value="form.display_name" placeholder="DeepSeek / 阿里云百炼" />
        </a-form-item>
        <a-form-item label="API 端点" required>
          <a-input v-model:value="form.base_url" placeholder="https://api.deepseek.com/v1" />
        </a-form-item>
        <a-form-item label="API Key" required>
          <a-input-password v-model:value="form.api_key" placeholder="sk-..." />
        </a-form-item>
        <a-form-item label="超时(秒)">
          <a-input-number v-model:value="form.timeout_seconds" :min="5" :max="300" style="width: 100%" />
        </a-form-item>
        <a-form-item label="最大重试">
          <a-input-number v-model:value="form.max_retries" :min="0" :max="5" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { providerApi } from '../../api'
import { message } from 'ant-design-vue'

const loading = ref(false)
const providers = ref([])
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)

const columns = [
  { title: '代码', dataIndex: 'provider_code' },
  { title: '名称', dataIndex: 'display_name' },
  { title: 'API 端点', dataIndex: 'base_url', ellipsis: true },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 240 },
]

const form = reactive({
  provider_code: '',
  display_name: '',
  base_url: '',
  api_key: '',
  timeout_seconds: 60,
  max_retries: 2,
})

async function fetchProviders() {
  loading.value = true
  try {
    const res = await providerApi.list({ page_size: 100 })
    providers.value = res.items
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { provider_code: '', display_name: '', base_url: '', api_key: '', timeout_seconds: 60, max_retries: 2 })
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  Object.assign(form, {
    provider_code: record.provider_code,
    display_name: record.display_name,
    base_url: record.base_url,
    api_key: '',
    timeout_seconds: record.timeout_seconds || 60,
    max_retries: record.max_retries || 2,
  })
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      await providerApi.update(editing.value.provider_id, { ...form })
      message.success('更新成功')
    } else {
      await providerApi.create({ ...form })
      message.success('创建成功')
    }
    modalOpen.value = false
    fetchProviders()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleSync(id) {
  try {
    await providerApi.syncModels(id)
    message.success('模型同步完成')
  } catch (e) {
    message.error(e.message)
  }
}

async function handleDelete(id) {
  try {
    await providerApi.delete(id)
    message.success('已删除')
    fetchProviders()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(fetchProviders)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
</style>
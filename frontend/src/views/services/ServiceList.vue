<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">模型服务</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 添加模型服务
      </a-button>
    </div>
    <a-card>
      <div class="filter-bar">
        <span class="filter-label">供应商：</span>
        <a-select
          v-model:value="filterProviderId"
          style="width: 200px"
          placeholder="全部供应商"
          allow-clear
          @change="fetchServices"
        >
          <a-select-option v-for="p in providers" :key="p.provider_id" :value="p.provider_id">
            {{ p.display_name }}
          </a-select-option>
        </a-select>
      </div>
      <a-table :columns="columns" :data-source="services" :loading="loading" row-key="model_service_id" :pagination="false">
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'red'">{{ record.status }}</a-tag>
          </template>
          <template v-if="column.key === 'capabilities'">
            <a-tag v-for="c in record.capabilities || []" :key="c" color="blue">{{ c }}</a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-space>
              <a @click="openEdit(record)">编辑</a>
              <a-popconfirm title="确认删除?" @confirm="handleDelete(record.model_service_id)">
                <a style="color: #b5341c">删除</a>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal v-model:open="modalOpen" :title="editing ? '编辑模型服务' : '添加模型服务'" @ok="handleSave" :confirm-loading="saving">
      <a-form :model="form" :label-col="{ span: 6 }" :wrapper-col="{ span: 16 }">
        <a-form-item label="供应商" required>
          <a-select v-model:value="form.provider_id" placeholder="选择供应商">
            <a-select-option v-for="p in providers" :key="p.provider_id" :value="p.provider_id">{{ p.display_name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="模型名称" required>
          <a-input v-model:value="form.model_name" placeholder="deepseek-chat" />
        </a-form-item>
        <a-form-item label="显示名称" required>
          <a-input v-model:value="form.display_name" placeholder="DeepSeek Chat" />
        </a-form-item>
        <a-form-item label="最大 Token">
          <a-input-number v-model:value="form.max_tokens" :min="100" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { serviceApi, providerApi } from '../../api'
import { message } from 'ant-design-vue'

const loading = ref(false)
const services = ref([])
const providers = ref([])
const filterProviderId = ref('')
const modalOpen = ref(false)
const editing = ref(null)
const saving = ref(false)

const columns = [
  { title: '供应商', dataIndex: 'provider_code', width: 120 },
  { title: '模型名称', dataIndex: 'model_name' },
  { title: '显示名称', dataIndex: 'display_name' },
  { title: '最大 Token', dataIndex: 'max_tokens' },
  { title: '能力', key: 'capabilities' },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 150 },
]

const form = reactive({
  provider_id: '',
  model_name: '',
  display_name: '',
  max_tokens: 4096,
  capabilities: ['text'],
})

async function fetchServices() {
  loading.value = true
  try {
    const params = { page_size: 100 }
    if (filterProviderId.value) {
      params.provider_id = filterProviderId.value
    }
    const res = await serviceApi.list(params)
    services.value = res.items
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const prov = await providerApi.list({ page_size: 100 })
    providers.value = prov.items
    await fetchServices()
  } catch (e) {
    message.error(e.message)
  }
})

function openCreate() {
  editing.value = null
  Object.assign(form, { provider_id: '', model_name: '', display_name: '', max_tokens: 4096, capabilities: ['text'] })
  modalOpen.value = true
}

function openEdit(record) {
  editing.value = record
  Object.assign(form, {
    provider_id: record.provider_id,
    model_name: record.model_name,
    display_name: record.display_name,
    max_tokens: record.max_tokens,
    capabilities: record.capabilities,
  })
  modalOpen.value = true
}

async function handleSave() {
  saving.value = true
  try {
    if (editing.value) {
      await serviceApi.update(editing.value.model_service_id, { ...form })
      message.success('更新成功')
    } else {
      await serviceApi.create({ ...form })
      message.success('创建成功')
    }
    modalOpen.value = false
    await fetchServices()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleDelete(id) {
  try {
    await serviceApi.delete(id)
    message.success('已删除')
    await fetchServices()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.filter-bar { display: flex; align-items: center; margin-bottom: 16px; }
.filter-label { font-size: 13px; color: #3a342e; margin-right: 8px; }
</style>
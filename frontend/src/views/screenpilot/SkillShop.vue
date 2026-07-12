<template>
  <div class="shop-page">
    <div class="page-header">
      <h2>UI 技能商店</h2>
      <a-space>
        <a-input-search
          v-model:value="searchQuery"
          placeholder="搜索已发布技能…"
          style="width: 280px;"
          @search="loadShop"
        />
        <a-select v-model:value="visibilityFilter" style="width: 120px;" @change="loadShop">
          <a-select-option value="">全部</a-select-option>
          <a-select-option value="DEPARTMENT">部门</a-select-option>
          <a-select-option value="PUBLIC">公开</a-select-option>
        </a-select>
        <a-button @click="loadShop">刷新</a-button>
      </a-space>
    </div>

    <a-table
      :dataSource="items"
      :columns="columns"
      rowKey="skill_id"
      :loading="loading"
      size="middle"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, h } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const loading = ref(false)
const items = ref([])
const searchQuery = ref('')
const visibilityFilter = ref('')
const importScope = ref('default')

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: 'Scope', dataIndex: 'scope', key: 'scope', width: 100 },
  { title: '可见性', dataIndex: 'visibility', key: 'visibility', width: 90 },
  { title: '步骤', dataIndex: 'step_count', key: 'step_count', width: 70 },
  {
    title: '操作',
    key: 'action',
    width: 100,
    customRender: ({ record }) =>
      h(
        'a',
        {
          onClick: (e) => {
            e.preventDefault()
            doImport(record)
          },
        },
        '导入'
      ),
  },
]

async function loadShop() {
  loading.value = true
  try {
    const params = { top_k: 30 }
    if (visibilityFilter.value) params.visibility = visibilityFilter.value
    if (searchQuery.value.trim()) params.query = searchQuery.value.trim()
    items.value = await screenpilotApi.listSkillShop(params)
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function doImport(record) {
  Modal.confirm({
    title: `导入技能「${record.name}」`,
    content: '将复制到本地 scope（default）以便在本项目复用。',
    onOk: async () => {
      try {
        const res = await screenpilotApi.importSkill(record.skill_id, {
          target_scope: importScope.value,
        })
        message.success(`已导入为 ${res.name}`)
      } catch (e) {
        message.error(e.message)
      }
    },
  })
}

onMounted(loadShop)
</script>

<style scoped>
.shop-page { padding: 0 4px; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0; }
</style>

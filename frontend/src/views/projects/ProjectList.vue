<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">项目</h2>
      <a-button type="primary" @click="openCreate">
        <PlusOutlined /> 新建项目
      </a-button>
    </div>

    <a-tabs v-model:activeKey="tab" @change="load">
      <a-tab-pane key="active" tab="全部" />
      <a-tab-pane key="starred" tab="收藏" />
      <a-tab-pane key="shared" tab="与我共享" />
      <a-tab-pane key="archived" tab="已归档" />
    </a-tabs>

    <a-spin :spinning="loading">
      <a-row :gutter="[16, 16]" v-if="projects.length">
        <a-col :xs="24" :sm="12" :lg="8" v-for="p in projects" :key="p.project_id">
          <a-card hoverable class="project-card" @click="$router.push(`/projects/${p.project_id}`)">
            <template #title>
              <div class="card-title">
                <span>{{ p.name }}</span>
                <StarFilled v-if="p.starred" class="star-on" @click.stop="toggleStar(p)" />
                <StarOutlined v-else class="star-off" @click.stop="toggleStar(p)" />
              </div>
            </template>
            <p class="desc">{{ p.description || '暂无描述' }}</p>
            <div class="meta">
              <a-tag>{{ roleLabel(p.my_role) }}</a-tag>
              <span>{{ p.file_count }} 文件</span>
              <span>{{ p.session_count }} 会话</span>
              <span>{{ p.member_count }} 成员</span>
            </div>
          </a-card>
        </a-col>
      </a-row>
      <a-empty v-else description="暂无项目" />
    </a-spin>

    <a-modal
      v-model:open="createOpen"
      title="新建项目"
      :confirm-loading="saving"
      @ok="handleCreate"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="form.name" placeholder="例如：产品需求文档" />
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="form.description" :rows="3" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { PlusOutlined, StarOutlined, StarFilled } from '@ant-design/icons-vue'
import { projectApi } from '../../api'

const router = useRouter()
const tab = ref('active')
const loading = ref(false)
const projects = ref([])
const createOpen = ref(false)
const saving = ref(false)
const form = reactive({ name: '', description: '' })

function roleLabel(role) {
  return { owner: '所有者', editor: '可编辑', viewer: '可查看' }[role] || role || ''
}

async function load() {
  loading.value = true
  try {
    const res = await projectApi.list({ tab: tab.value, page_size: 100 })
    projects.value = res.items || []
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.name = ''
  form.description = ''
  createOpen.value = true
}

async function handleCreate() {
  if (!form.name.trim()) {
    message.warning('请填写项目名称')
    return
  }
  saving.value = true
  try {
    const p = await projectApi.create({
      name: form.name.trim(),
      description: form.description || '',
    })
    createOpen.value = false
    message.success('项目已创建')
    router.push(`/projects/${p.project_id}`)
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function toggleStar(p) {
  try {
    if (p.starred) {
      await projectApi.unstar(p.project_id)
      p.starred = false
    } else {
      await projectApi.star(p.project_id)
      p.starred = true
    }
    if (tab.value === 'starred') await load()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  margin: 0;
  font-size: 20px;
}
.project-card .desc {
  color: #6b6560;
  min-height: 40px;
  margin-bottom: 12px;
}
.card-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.star-on {
  color: #faad14;
  cursor: pointer;
}
.star-off {
  color: #bfbfbf;
  cursor: pointer;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #8c8580;
  align-items: center;
}
</style>

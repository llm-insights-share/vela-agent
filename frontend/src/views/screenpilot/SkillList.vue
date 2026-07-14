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
        <template v-if="column.key === 'visibility'">
          <a-tag :color="isPublished(record.visibility) ? 'green' : 'default'">
            {{ isPublished(record.visibility) ? '已发布' : '私有' }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space>
            <a @click="openDetail(record.skill_id)">详情</a>
            <a @click="togglePublish(record)">
              {{ isPublished(record.visibility) ? '下架' : '发布' }}
            </a>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-drawer v-model:open="detailOpen" title="技能详情" width="520">
      <template v-if="detail">
        <p><b>{{ detail.name }}</b></p>
        <p class="desc">{{ detail.description }}</p>
        <a-space>
          <a-tag>scope: {{ detail.scope }}</a-tag>
          <a-tag :color="isPublished(detail.visibility) ? 'green' : 'default'">
            {{ isPublished(detail.visibility) ? '已发布' : '私有' }}
          </a-tag>
        </a-space>
        <a-divider />
        <div v-for="st in detail.steps" :key="st.step_id" class="step-row">
          <a-tag color="blue">{{ st.step_order }}</a-tag>
          <code>{{ st.action }}</code>
          <span v-if="st.target_label"> · {{ st.target_label }}</span>
          <span v-if="st.value_template" class="val"> → {{ st.value_template }}</span>
        </div>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { screenpilotApi } from '../../api'

const loading = ref(false)
const skills = ref([])
const searchResults = ref(null)
const searchQuery = ref('')
const visibilityFilter = ref('all')
const detailOpen = ref(false)
const detail = ref(null)

const columns = [
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
  { title: '步骤数', dataIndex: 'step_count', key: 'step_count', width: 80 },
  { title: 'Scope', dataIndex: 'scope', key: 'scope', width: 100 },
  { title: '状态', key: 'visibility', width: 90 },
  { title: '操作', key: 'action', width: 140 },
]

function isPublished(visibility) {
  return visibility === 'DEPARTMENT' || visibility === 'PUBLIC'
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
      description: `${r.description || ''} (score: ${r.score?.toFixed(3) ?? ''})`,
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
.desc { color: #666; font-size: 13px; }
.step-row { margin-bottom: 8px; font-size: 13px; }
.val { color: #888; }
</style>

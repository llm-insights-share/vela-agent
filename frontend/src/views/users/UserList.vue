<template>
  <div>
    <div class="head">
      <h2>用户管理</h2>
      <a-button type="primary" @click="openCreate">+ 新增用户</a-button>
    </div>
    <a-table :dataSource="rows" :columns="columns" row-key="user_id" :pagination="false" :loading="loading">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'status'">
          <a-tag :color="record.is_active ? 'green' : 'default'">
            {{ record.is_active ? '正常' : '已停用' }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'roles'">
          <a-tag v-for="r in roleList(record.roles)" :key="r">{{ r }}</a-tag>
        </template>
        <template v-else-if="column.key === 'action'">
          <a-space>
            <a-button size="small" @click="openRoleEdit(record)">角色</a-button>
            <a-button
              size="small"
              :disabled="record.user_id === auth.user?.user_id"
              @click="toggleActive(record)"
            >
              {{ record.is_active ? '停用' : '启用' }}
            </a-button>
            <a-popconfirm
              title="确认删除该用户？"
              :disabled="record.user_id === auth.user?.user_id"
              @confirm="remove(record.user_id)"
            >
              <a-button danger size="small" :disabled="record.user_id === auth.user?.user_id">删除</a-button>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-modal v-model:open="openForm" title="新增用户" :confirmLoading="saving" @ok="save">
      <a-form layout="vertical">
        <a-form-item label="邮箱" required>
          <a-input v-model:value="form.email" placeholder="user@example.com" />
        </a-form-item>
        <a-form-item label="用户名" required>
          <a-input v-model:value="form.username" placeholder="username" />
        </a-form-item>
        <a-form-item label="显示名">
          <a-input v-model:value="form.display_name" />
        </a-form-item>
        <a-form-item label="密码" required>
          <a-input-password v-model:value="form.password" placeholder="至少 6 位" />
        </a-form-item>
        <a-form-item label="角色">
          <a-select
            v-model:value="form.roles"
            mode="multiple"
            style="width: 100%"
            :options="roleOpts"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="openRoleForm" title="修改角色" :confirmLoading="savingRole" @ok="saveRoles">
      <a-form layout="vertical">
        <a-form-item label="用户">
          <a-input :value="roleForm.username" disabled />
        </a-form-item>
        <a-form-item label="角色">
          <a-select
            v-model:value="roleForm.roles"
            mode="multiple"
            style="width: 100%"
            :options="roleOpts"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { userApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const savingRole = ref(false)
const rows = ref([])
const openForm = ref(false)
const openRoleForm = ref(false)
const form = reactive({
  email: '',
  username: '',
  display_name: '',
  password: '',
  roles: ['member'],
})
const roleForm = reactive({
  user_id: '',
  username: '',
  roles: ['member'],
})

const roleOpts = [
  { value: 'admin', label: 'admin' },
  { value: 'member', label: 'member' },
]

const columns = [
  { title: '用户名', dataIndex: 'username' },
  { title: '邮箱', dataIndex: 'email' },
  { title: '显示名', dataIndex: 'display_name' },
  { title: '角色', key: 'roles' },
  { title: '状态', key: 'status', width: 100 },
  { title: '操作', key: 'action', width: 220 },
]

function roleList(roles) {
  return (roles || '').split(',').map((r) => r.trim()).filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    rows.value = await userApi.list()
  } catch (e) {
    message.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.email = ''
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.roles = ['member']
  openForm.value = true
}

async function save() {
  if (!form.email || !form.username || !form.password) {
    message.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    await userApi.create({
      email: form.email,
      username: form.username,
      display_name: form.display_name,
      password: form.password,
      roles: form.roles.join(',') || 'member',
    })
    message.success('已创建')
    openForm.value = false
    await load()
  } catch (e) {
    message.error(e?.message || '创建失败')
  } finally {
    saving.value = false
  }
}

function openRoleEdit(record) {
  roleForm.user_id = record.user_id
  roleForm.username = record.username
  roleForm.roles = roleList(record.roles)
  openRoleForm.value = true
}

async function saveRoles() {
  savingRole.value = true
  try {
    await userApi.setRoles(roleForm.user_id, roleForm.roles.join(',') || 'member')
    message.success('角色已更新')
    openRoleForm.value = false
    await load()
  } catch (e) {
    message.error(e?.message || '更新失败')
  } finally {
    savingRole.value = false
  }
}

async function toggleActive(record) {
  try {
    await userApi.setActive(record.user_id, !record.is_active)
    message.success(record.is_active ? '已停用' : '已启用')
    await load()
  } catch (e) {
    message.error(e?.message || '操作失败')
  }
}

async function remove(userId) {
  try {
    await userApi.remove(userId)
    message.success('已删除')
    await load()
  } catch (e) {
    message.error(e?.message || '删除失败')
  }
}

onMounted(load)
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.head h2 {
  margin: 0;
  font-size: 20px;
}
</style>

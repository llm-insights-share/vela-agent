<template>
  <div class="settings-panel">
    <h2>用户设置</h2>
    <div class="avatar-section">
      <a-avatar :size="72" :src="auth.user?.avatar_url || undefined">
        <template #icon><UserOutlined /></template>
      </a-avatar>
      <div class="avatar-actions">
        <a-upload
          :show-upload-list="false"
          :custom-request="uploadAvatar"
          accept="image/png,image/jpeg,image/webp,image/gif"
        >
          <a-button :loading="uploadingAvatar">上传头像</a-button>
        </a-upload>
        <div class="muted">支持 png/jpg/webp/gif，最大 2MB</div>
      </div>
    </div>

    <a-divider style="margin: 20px 0 16px" />

    <h3 class="section-title">基础信息</h3>
    <a-form layout="vertical" style="max-width: 420px">
      <a-form-item label="用户名">
        <a-input :value="auth.user?.username" disabled />
      </a-form-item>
      <a-form-item label="显示名">
        <a-input v-model:value="profile.display_name" />
      </a-form-item>
      <a-form-item label="邮箱">
        <a-input v-model:value="profile.email" />
      </a-form-item>
      <a-button type="primary" :loading="savingProfile" @click="saveProfile">保存资料</a-button>
    </a-form>

    <a-divider style="margin: 24px 0 16px" />

    <h3 class="section-title">重置密码</h3>
    <a-form layout="vertical" style="max-width: 420px">
      <a-form-item label="旧密码">
        <a-input-password v-model:value="pwd.old_password" />
      </a-form-item>
      <a-form-item label="新密码">
        <a-input-password v-model:value="pwd.new_password" />
      </a-form-item>
      <a-form-item label="确认新密码">
        <a-input-password v-model:value="pwd.confirm_password" />
      </a-form-item>
      <a-button type="primary" :loading="savingPwd" @click="savePassword">重置密码</a-button>
    </a-form>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { UserOutlined } from '@ant-design/icons-vue'
import { authApi } from '../../api'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const uploadingAvatar = ref(false)
const savingProfile = ref(false)
const savingPwd = ref(false)

const profile = reactive({
  display_name: '',
  email: '',
})
const pwd = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

function syncProfileFromUser() {
  profile.display_name = auth.user?.display_name || ''
  profile.email = auth.user?.email || ''
}

async function saveProfile() {
  if (!profile.email) {
    message.warning('邮箱不能为空')
    return
  }
  savingProfile.value = true
  try {
    await authApi.updateProfile({
      display_name: profile.display_name,
      email: profile.email,
    })
    await auth.fetchMe()
    syncProfileFromUser()
    message.success('资料已保存')
  } catch (e) {
    message.error(e?.message || '保存失败')
  } finally {
    savingProfile.value = false
  }
}

async function savePassword() {
  if (!pwd.old_password || !pwd.new_password) {
    message.warning('请填写旧密码和新密码')
    return
  }
  if (pwd.new_password.length < 6) {
    message.warning('新密码至少 6 位')
    return
  }
  if (pwd.new_password !== pwd.confirm_password) {
    message.warning('两次新密码不一致')
    return
  }
  savingPwd.value = true
  try {
    await authApi.updatePassword({
      old_password: pwd.old_password,
      new_password: pwd.new_password,
    })
    pwd.old_password = ''
    pwd.new_password = ''
    pwd.confirm_password = ''
    message.success('密码已更新')
  } catch (e) {
    message.error(e?.message || '密码更新失败')
  } finally {
    savingPwd.value = false
  }
}

async function uploadAvatar(options) {
  uploadingAvatar.value = true
  try {
    await authApi.uploadAvatar(options.file)
    await auth.fetchMe()
    message.success('头像已更新')
    options.onSuccess?.()
  } catch (e) {
    message.error(e?.message || '上传失败')
    options.onError?.(e)
  } finally {
    uploadingAvatar.value = false
  }
}

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      /* router guard handles auth */
    }
  }
  syncProfileFromUser()
})
</script>

<style scoped>
.settings-panel {
  max-width: 640px;
}
.settings-panel h2 {
  margin: 0 0 20px;
  font-size: 20px;
}
.avatar-section {
  display: flex;
  align-items: center;
  gap: 16px;
}
.avatar-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.muted {
  font-size: 12px;
  color: #8a8279;
}
.section-title {
  margin: 0 0 12px;
  font-size: 15px;
}
</style>

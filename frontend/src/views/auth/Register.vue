<template>
  <div class="wrap">
    <a-card class="login-card" style="width: 400px">
      <div class="login-brand">
        <div class="logo-dot"></div>
        <div>
          <div class="login-title">注册账号</div>
          <div class="login-sub">邮箱注册，无需验证即可登录</div>
        </div>
      </div>
      <a-form :model="formState" layout="vertical" @finish="onSubmit">
        <a-form-item
          label="邮箱"
          name="email"
          :rules="[
            { required: true, message: '请输入邮箱' },
            { type: 'email', message: '邮箱格式不正确' },
          ]"
        >
          <a-input v-model:value="formState.email" placeholder="you@example.com" />
        </a-form-item>
        <a-form-item
          label="用户名"
          name="username"
          :rules="[
            { required: true, message: '请输入用户名' },
            { pattern: /^[a-zA-Z0-9._-]{2,64}$/, message: '2–64 位字母/数字/._-' },
          ]"
        >
          <a-input v-model:value="formState.username" placeholder="username" />
        </a-form-item>
        <a-form-item label="显示名" name="display_name">
          <a-input v-model:value="formState.display_name" placeholder="可选" />
        </a-form-item>
        <a-form-item
          label="密码"
          name="password"
          :rules="[
            { required: true, message: '请输入密码' },
            { min: 6, message: '至少 6 位' },
          ]"
        >
          <a-input-password v-model:value="formState.password" />
        </a-form-item>
        <a-form-item
          label="确认密码"
          name="confirm"
          :rules="[
            { required: true, message: '请再次输入密码' },
            { validator: validateConfirm },
          ]"
        >
          <a-input-password v-model:value="formState.confirm" />
        </a-form-item>
        <a-button type="primary" html-type="submit" block :loading="loading">注册并登录</a-button>
        <div class="foot">
          已有账号？
          <router-link to="/login">去登录</router-link>
        </div>
      </a-form>
    </a-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const formState = reactive({
  email: '',
  username: '',
  display_name: '',
  password: '',
  confirm: '',
})
const loading = ref(false)

async function validateConfirm(_rule, value) {
  if (value !== formState.password) {
    return Promise.reject('两次密码不一致')
  }
  return Promise.resolve()
}

async function onSubmit() {
  loading.value = true
  try {
    await auth.register({
      email: formState.email,
      username: formState.username,
      password: formState.password,
      display_name: formState.display_name,
    })
    message.success('注册成功')
    router.push('/')
  } catch (e) {
    message.error(e?.message || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.wrap {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: linear-gradient(160deg, #2c2620, #3a342e 45%, #1f1b17);
}
.login-card {
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.logo-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #c2410c;
  flex-shrink: 0;
}
.login-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 20px;
  font-weight: 700;
  color: #1f1b17;
}
.login-sub {
  font-size: 12px;
  color: #8a8279;
}
.foot {
  margin-top: 16px;
  text-align: center;
  color: #8a8279;
  font-size: 13px;
}
</style>

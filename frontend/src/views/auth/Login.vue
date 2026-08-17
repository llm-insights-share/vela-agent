<template>
  <div class="wrap">
    <a-card class="login-card" style="width: 380px">
      <div class="login-brand">
        <div class="logo-dot"></div>
        <div>
          <div class="login-title">Vela · 织帆</div>
          <div class="login-sub">Agent Playground</div>
        </div>
      </div>
      <a-form :model="formState" layout="vertical" @finish="onSubmit">
        <a-form-item label="用户名" name="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <a-input v-model:value="formState.username" placeholder="admin" />
        </a-form-item>
        <a-form-item label="密码" name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="formState.password" placeholder="admin123" />
        </a-form-item>
        <a-alert
          type="info"
          show-icon
          message="默认账号 admin / admin123"
          style="margin-bottom: 12px"
        />
        <a-button type="primary" html-type="submit" block :loading="loading">登录</a-button>
        <div class="foot">
          没有账号？
          <router-link to="/register">注册</router-link>
        </div>
      </a-form>
    </a-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const formState = reactive({
  username: 'admin',
  password: 'admin123',
})
const loading = ref(false)

async function onSubmit() {
  loading.value = true
  try {
    await auth.login(formState.username, formState.password)
    message.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.push(redirect || '/')
  } catch (e) {
    message.error(e?.message || '登录失败')
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
  letter-spacing: 0.05em;
}
.foot {
  margin-top: 16px;
  text-align: center;
  color: #8a8279;
  font-size: 13px;
}
</style>

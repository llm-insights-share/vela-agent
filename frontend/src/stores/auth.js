import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, getToken, setToken, clearToken } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => {
    const roles = (user.value?.roles || '').split(',').map((r) => r.trim())
    return roles.includes('admin')
  })

  async function login(username, password) {
    const data = await authApi.login(username, password)
    token.value = data.access_token
    setToken(data.access_token)
    await fetchMe()
  }

  async function register(payload) {
    const data = await authApi.register({
      email: payload.email,
      username: payload.username,
      password: payload.password,
      display_name: payload.display_name || '',
    })
    token.value = data.access_token
    setToken(data.access_token)
    await fetchMe()
  }

  async function fetchMe() {
    if (!token.value) return
    user.value = await authApi.me()
  }

  function logout() {
    token.value = null
    user.value = null
    clearToken()
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    login,
    register,
    fetchMe,
    logout,
  }
})

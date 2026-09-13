<template>
  <Teleport to="body">
    <button
      v-if="!open"
      type="button"
      class="ops-fab"
      title="应用操作助手"
      aria-label="打开应用操作助手"
      @click="open = true"
    >
      <ThunderboltOutlined class="ops-fab-icon" />
    </button>
    <OpsAgentPanel v-model="open" />
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import { ThunderboltOutlined } from '@ant-design/icons-vue'
import OpsAgentPanel from './OpsAgentPanel.vue'

const open = ref(false)
</script>

<style scoped>
.ops-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  border: 1px solid #ddd8ce;
  background: #1a1714;
  color: #faf8f4;
  cursor: pointer;
  z-index: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 24px rgba(26, 23, 20, 0.22);
  transition: transform 0.15s ease, background 0.15s ease;
}
.ops-fab:hover {
  background: #c2410c;
  transform: translateY(-2px);
}
.ops-fab-icon {
  font-size: 28px;
}
</style>

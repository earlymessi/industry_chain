<script setup>
defineProps({
  tone: { type: String, default: 'default' },
})
</script>

<template>
  <span class="hub-nav-icon">
    <el-icon><slot /></el-icon>
  </span>
</template>

<style scoped>
.hub-nav-icon {
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-right: 12px;
  flex-shrink: 0;
  font-size: 17px;
  color: inherit;
  opacity: 0.9;
}
</style>

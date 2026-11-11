<template>
  <div class="page">
    <el-card shadow="never" class="placeholder-card">
      <el-empty description="物流资源管控模块建设中">
        <template #image>
          <el-icon class="placeholder-icon"><Guide /></el-icon>
        </template>
      </el-empty>
    </el-card>
  </div>
</template>

<script setup>
import { Guide } from '@element-plus/icons-vue'
</script>

<style scoped>
.page {
  min-height: calc(100vh - 55px - 40px);
  padding: 4px;
}

.placeholder-card {
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-icon {
  font-size: 72px;
  color: #c0c4cc;
}
</style>

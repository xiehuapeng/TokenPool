<script setup lang="ts">
import { onMounted, ref } from "vue";
import { meApi } from "@/api";

const models = ref<any[]>([]);
function capabilityNames(capabilities: Record<string, unknown> | null) {
  return Object.entries(capabilities || {})
    .filter(([name, value]) => !name.startsWith("official_") && value === true)
    .map(([name]) => name);
}
onMounted(async () => {
  models.value = (await meApi.models()).data;
});
</script>

<template>
  <div>
    <div class="page-heading"><div><h1>模型列表</h1><p>当前团队已接入和规划中的模型。</p></div></div>
    <el-card shadow="never">
      <el-table :data="models">
        <el-table-column prop="id" label="模型" min-width="200" />
        <el-table-column prop="provider" label="Provider" />
        <el-table-column label="官方同步" width="120">
          <template #default="{ row }">
            <el-tag
              v-if="row.official_available === true"
              type="success"
              effect="plain"
            >
              当前返回
            </el-tag>
            <el-tag
              v-else-if="row.official_available === false"
              type="warning"
              effect="plain"
            >
              当前未返回
            </el-tag>
            <el-tag v-else type="info" effect="plain">尚未同步</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="我的选择" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.selected" type="primary">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="能力" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="name in capabilityNames(row.capabilities)"
              :key="name"
              class="cap-tag"
              effect="plain"
            >
              {{ name }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'enabled' ? 'success' : 'info'">
              {{ row.status === "enabled" ? "启用" : "规划中" }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

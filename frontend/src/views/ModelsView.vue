<script setup lang="ts">
import { onMounted, ref } from "vue";
import { meApi } from "@/api";

const models = ref<any[]>([]);
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
        <el-table-column label="能力" min-width="220">
          <template #default="{ row }">
            <el-tag v-for="(_, name) in row.capabilities" :key="name" class="cap-tag" effect="plain">{{ name }}</el-tag>
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


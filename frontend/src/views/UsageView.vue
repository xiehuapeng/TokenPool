<script setup lang="ts">
import { onMounted, ref } from "vue";
import { meApi } from "@/api";

const data = ref<any>({ today_requests: 0, today_tokens: 0, by_model: [] });
onMounted(async () => {
  data.value = (await meApi.usage()).data;
});
</script>

<template>
  <div>
    <div class="page-heading"><div><h1>个人用量</h1><p>今日概览与最近 30 天模型分布。</p></div></div>
    <el-row :gutter="20">
      <el-col :span="8"><div class="metric-card"><span>今日请求</span><strong>{{ data.today_requests }}</strong></div></el-col>
      <el-col :span="8"><div class="metric-card"><span>今日 Token</span><strong>{{ Number(data.today_tokens).toLocaleString() }}</strong></div></el-col>
      <el-col :span="8"><div class="metric-card"><span>使用模型</span><strong>{{ data.by_model.length }}</strong></div></el-col>
    </el-row>
    <el-card shadow="never" class="section-card">
      <template #header><strong>模型使用分布</strong></template>
      <el-table :data="data.by_model">
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="requests" label="请求次数" />
        <el-table-column label="Token">
          <template #default="{ row }">{{ Number(row.tokens).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="successes" label="成功次数" />
      </el-table>
    </el-card>
  </div>
</template>

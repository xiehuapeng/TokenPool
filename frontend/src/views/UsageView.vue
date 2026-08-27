<script setup lang="ts">
import { onMounted, ref } from "vue";
import { meApi } from "@/api";

const data = ref<any>({
  today_requests: 0,
  today_tokens: 0,
  today_input_tokens: 0,
  today_output_tokens: 0,
  today_cost: 0,
  by_model: [],
});

function formatTokens(value: unknown) {
  return Number(value || 0).toLocaleString();
}

function formatCost(value: unknown) {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return "¥0.00";
  if (num < 0.01) return `¥${num.toFixed(6)}`;
  if (num < 1) return `¥${num.toFixed(4)}`;
  return `¥${num.toFixed(2)}`;
}

onMounted(async () => {
  data.value = (await meApi.usage()).data;
});
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>个人用量</h1>
        <p>今日概览与最近 30 天模型消费明细。</p>
      </div>
    </div>
    <el-row :gutter="20">
      <el-col :span="6">
        <div class="metric-card">
          <span>今日请求</span>
          <strong>{{ formatTokens(data.today_requests) }}</strong>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="metric-card">
          <span>今日 Token</span>
          <strong>{{ formatTokens(data.today_tokens) }}</strong>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="metric-card">
          <span>今日费用</span>
          <strong>{{ formatCost(data.today_cost) }}</strong>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="metric-card">
          <span>使用模型</span>
          <strong>{{ data.by_model.length }}</strong>
        </div>
      </el-col>
    </el-row>
    <el-card shadow="never" class="section-card">
      <template #header><strong>模型消费明细</strong></template>
      <el-table :data="data.by_model">
        <el-table-column prop="model" label="模型" min-width="140" />
        <el-table-column prop="provider" label="Provider" min-width="90" />
        <el-table-column prop="requests" label="请求" width="80" />
        <el-table-column label="输入" align="right" min-width="110">
          <template #default="{ row }">{{ formatTokens(row.input_tokens) }}</template>
        </el-table-column>
        <el-table-column label="输出" align="right" min-width="110">
          <template #default="{ row }">{{ formatTokens(row.output_tokens) }}</template>
        </el-table-column>
        <el-table-column label="缓存命中" align="right" min-width="110">
          <template #default="{ row }">
            {{ formatTokens(row.cached_input_tokens) }}
          </template>
        </el-table-column>
        <el-table-column label="推理" align="right" min-width="100">
          <template #default="{ row }">{{ formatTokens(row.reasoning_tokens) }}</template>
        </el-table-column>
        <el-table-column label="总 Token" align="right" min-width="110">
          <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
        </el-table-column>
        <el-table-column label="费用" align="right" min-width="110">
          <template #default="{ row }">{{ formatCost(row.cost) }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

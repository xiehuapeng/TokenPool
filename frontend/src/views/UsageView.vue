<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { meApi } from "@/api";

const data = ref<any>({
  summary: {},
  by_model: [],
  filter_options: { models: [] },
});

const filters = reactive({
  days: "30",
  model: "",
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

function buildParams() {
  return {
    days: filters.days === "today" ? undefined : Number(filters.days),
    today: filters.days === "today" ? true : undefined,
    model: filters.model || undefined,
  };
}

async function load() {
  data.value = (await meApi.usage(buildParams())).data;
}

async function resetFilters() {
  Object.assign(filters, { days: "30", model: "" });
  await load();
}

onMounted(load);
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>个人用量</h1>
        <p>按时间和模型查看自己的调用明细。</p>
      </div>
    </div>

    <div
      class="usage-filter-bar"
      style="grid-template-columns: 150px minmax(200px, 1fr) auto"
    >
      <el-select v-model="filters.days" class="usage-filter-period">
        <el-option label="今天" value="today" />
        <el-option label="最近 24 小时" value="1" />
        <el-option label="最近 7 天" value="7" />
        <el-option label="最近 30 天" value="30" />
        <el-option label="最近 90 天" value="90" />
        <el-option label="全部时间" value="0" />
      </el-select>
      <el-select
        v-model="filters.model"
        filterable
        clearable
        placeholder="全部实际模型"
      >
        <el-option
          v-for="model in data.filter_options.models"
          :key="model"
          :label="model"
          :value="model"
        />
      </el-select>
      <div class="usage-filter-actions">
        <el-button type="primary" @click="load">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </div>

    <div class="admin-metric-grid">
      <div class="metric-card usage-metric-primary">
        <span>总 Token</span>
        <strong>{{ formatTokens(data.summary.total_tokens) }}</strong>
      </div>
      <div class="metric-card">
        <span>总费用</span>
        <strong>{{ formatCost(data.summary.cost) }}</strong>
      </div>
      <div class="metric-card">
        <span>请求数</span>
        <strong>{{ formatTokens(data.summary.requests) }}</strong>
      </div>
      <div class="metric-card">
        <span>使用模型</span>
        <strong>{{ data.by_model.length }}</strong>
      </div>
    </div>

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

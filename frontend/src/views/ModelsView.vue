<script setup lang="ts">
import { onMounted, ref } from "vue";
import { meApi } from "@/api";

const models = ref<any[]>([]);

function capabilityNames(capabilities: Record<string, unknown> | null) {
  return Object.entries(capabilities || {})
    .filter(([name, value]) => !name.startsWith("official_") && value === true)
    .map(([name]) => name);
}

function formatPrice(value: unknown) {
  if (value == null) return "—";
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : "—";
}

onMounted(async () => {
  models.value = (await meApi.models()).data;
});
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>模型列表</h1>
        <p>当前团队开放使用的模型与计费价格。</p>
      </div>
    </div>
    <el-card shadow="never">
      <el-table :data="models">
        <el-table-column prop="id" label="模型" min-width="180" />
        <el-table-column prop="provider" label="Provider" />
        <el-table-column label="计费价格（元/百万Token）" min-width="240">
          <template #default="{ row }">
            <template v-if="row.pricing">
              <div class="model-price-line">
                输入 {{ formatPrice(row.pricing.input_price) }} · 缓存命中
                {{ formatPrice(row.pricing.cached_input_price) }} · 输出
                {{ formatPrice(row.pricing.output_price) }}
              </div>
              <div
                v-if="
                  row.pricing.peak_input_price != null ||
                  row.pricing.tier_threshold_tokens != null
                "
                class="model-price-tags"
              >
                <el-tag
                  v-if="row.pricing.peak_input_price != null"
                  size="small"
                  effect="plain"
                >
                  峰谷计价
                </el-tag>
                <el-tag
                  v-if="row.pricing.tier_threshold_tokens != null"
                  size="small"
                  effect="plain"
                >
                  超长上下文加价
                </el-tag>
              </div>
            </template>
            <el-tag v-else size="small" type="warning" effect="plain">
              未配置计价
            </el-tag>
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
      </el-table>
    </el-card>
  </div>
</template>

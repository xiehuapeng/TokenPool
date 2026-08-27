<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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

const modelGroups = computed(() => {
  const grouped = new Map<string, any[]>();
  for (const model of models.value) {
    const provider = model.provider || "其他 Provider";
    const providerModels = grouped.get(provider) || [];
    providerModels.push(model);
    grouped.set(provider, providerModels);
  }
  return Array.from(grouped, ([provider, providerModels]) => ({
    provider,
    models: providerModels,
  }));
});

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
    <div class="model-provider-groups">
      <el-card
        v-for="group in modelGroups"
        :key="group.provider"
        shadow="never"
        class="model-provider-card"
      >
        <template #header>
          <div class="card-header model-provider-name">
            <strong>{{ group.provider }}</strong>
            <el-tag size="small" effect="plain">{{ group.models.length }} 个模型</el-tag>
          </div>
        </template>
        <el-table :data="group.models">
          <el-table-column prop="id" label="模型" min-width="180" />
          <el-table-column
            prop="description"
            label="介绍"
            min-width="300"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ row.description || "—" }}
            </template>
          </el-table-column>
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
      <el-empty v-if="!models.length" description="暂无可用模型" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import "element-plus/es/components/message/style/css";
import { meApi } from "@/api";
import { errorMessage } from "@/api/http";

const models = ref<any[]>([]);
const settingModelId = ref<string | null>(null);
const detailVisible = ref(false);
const detailModel = ref<any | null>(null);

const CAPABILITY_LABELS: Record<string, string> = {
  chat: "对话",
  stream: "流式输出",
  tools: "工具调用",
  json: "JSON 输出",
  thinking: "深度思考",
  vision: "图片理解",
};

function capabilityNames(capabilities: Record<string, unknown> | null) {
  return Object.entries(capabilities || {})
    .filter(([name, value]) => !name.startsWith("official_") && value === true)
    .map(([name]) => CAPABILITY_LABELS[name] || name);
}

function formatPrice(value: unknown) {
  if (value == null) return "—";
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : "—";
}

function discountLabel(note: string | null | undefined) {
  if (!note || !note.includes("限时")) return null;
  const base = note.includes("半价") ? "限时半价" : "限时折扣";
  const matched = note.match(/至\s*(\d{4}-\d{1,2}-\d{1,2})/);
  return matched ? `${base} · 至 ${matched[1]}` : base;
}

function hasPeakPricing(pricing: any) {
  return (
    pricing &&
    (pricing.peak_input_price != null ||
      pricing.peak_cached_input_price != null ||
      pricing.peak_output_price != null)
  );
}

function isPeakNow() {
  const now = new Date();
  const beijing = new Date(
    now.getTime() + (now.getTimezoneOffset() + 480) * 60000
  );
  const weekday = beijing.getDay() >= 1 && beijing.getDay() <= 5;
  const hour = beijing.getHours();
  const inSession = (hour >= 9 && hour < 12) || (hour >= 14 && hour < 18);
  return weekday && inSession;
}

const peakNow = ref(isPeakNow());

function priceLines(pricing: any) {
  const line = `输入 ${formatPrice(pricing.input_price)} / 缓存 ${formatPrice(
    pricing.cached_input_price
  )} / 输出 ${formatPrice(pricing.output_price)}`;
  if (hasPeakPricing(pricing)) {
    return peakNow.value
      ? [
          `高峰：输入 ${formatPrice(
            pricing.peak_input_price
          )} / 缓存 ${formatPrice(pricing.peak_cached_input_price)} / 输出 ${formatPrice(
            pricing.peak_output_price
          )}`,
        ]
      : [`空闲：${line}`];
  }
  return [line];
}

function modalityText(row: any) {
  const list = Array.isArray(row.modalities) ? row.modalities : [];
  return list.length ? list.join("、") : "文本";
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

function rowClassName({ row }: { row: any }) {
  return row.selected ? "model-row-selected" : "";
}

async function refreshModels() {
  models.value = (await meApi.models()).data;
}

async function setDefaultModel(row: any) {
  if (row.selected || settingModelId.value != null) return;
  settingModelId.value = row.id;
  try {
    await meApi.updateModelPreference(row.id);
    ElMessage.success(`已将 ${row.id} 设为默认模型`);
    await refreshModels();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    settingModelId.value = null;
  }
}

function showDetail(row: any) {
  detailModel.value = row;
  detailVisible.value = true;
}

onMounted(refreshModels);
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>模型列表</h1>
        <p>当前团队开放使用的模型与计费价格，点击“设为默认”切换默认模型。</p>
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
        <el-table :data="group.models" :row-class-name="rowClassName">
          <el-table-column prop="id" label="模型" min-width="180" />
          <el-table-column
            prop="description"
            label="定位与适用场景"
            min-width="280"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              {{ row.description || "—" }}
            </template>
          </el-table-column>
          <el-table-column label="输入与上下文" min-width="140">
            <template #default="{ row }">
              <div>{{ modalityText(row) }}</div>
              <div v-if="row.context_window" class="model-context-line">
                {{ row.context_window }} 上下文
              </div>
            </template>
          </el-table-column>
          <el-table-column label="计费价格（元/百万 Token）" min-width="270">
            <template #default="{ row }">
              <template v-if="row.pricing">
                <div
                  v-for="(line, index) in priceLines(row.pricing)"
                  :key="index"
                  class="model-price-line"
                >
                  {{ line }}
                </div>
                <div
                  v-if="
                    discountLabel(row.pricing.note) ||
                    row.pricing.tier_threshold_tokens != null ||
                    hasPeakPricing(row.pricing)
                  "
                  class="model-price-tags"
                >
                  <el-tooltip
                    v-if="discountLabel(row.pricing.note)"
                    :content="row.pricing.note"
                    placement="top"
                  >
                    <el-tag size="small" type="danger" effect="plain">
                      {{ discountLabel(row.pricing.note) }}
                    </el-tag>
                  </el-tooltip>
                  <el-tooltip
                    v-if="hasPeakPricing(row.pricing)"
                    content="高峰时段：工作日 9:00-12:00、14:00-18:00（北京时间），其余时间为空闲价"
                    placement="top"
                  >
                    <el-tag
                      size="small"
                      :type="peakNow ? 'warning' : 'info'"
                      effect="plain"
                    >
                      {{ peakNow ? "高峰价生效中" : "空闲价生效中" }}
                    </el-tag>
                  </el-tooltip>
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
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <div class="model-actions">
                <el-tag v-if="row.selected" type="primary">当前使用</el-tag>
                <el-link
                  v-else
                  type="primary"
                  :underline="false"
                  :disabled="settingModelId != null"
                  @click="setDefaultModel(row)"
                >
                  设为默认
                </el-link>
                <el-link :underline="false" @click="showDetail(row)">
                  查看详情
                </el-link>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
      <el-empty v-if="!models.length" description="暂无可用模型" />
    </div>
    <el-dialog
      v-model="detailVisible"
      width="580px"
      :title="detailModel ? `模型详情 · ${detailModel.id}` : '模型详情'"
    >
      <el-descriptions v-if="detailModel" :column="1" border>
        <el-descriptions-item label="模型">
          {{ detailModel.id }}
        </el-descriptions-item>
        <el-descriptions-item label="厂商">
          {{ detailModel.provider || "—" }}
        </el-descriptions-item>
        <el-descriptions-item label="定位与适用场景">
          {{ detailModel.description || "—" }}
        </el-descriptions-item>
        <el-descriptions-item label="输入与上下文">
          {{ modalityText(detailModel) }}
          <template v-if="detailModel.context_window">
            · {{ detailModel.context_window }} 上下文
          </template>
        </el-descriptions-item>
        <el-descriptions-item label="能力">
          <el-tag
            v-for="name in capabilityNames(detailModel.capabilities)"
            :key="name"
            class="cap-tag"
            effect="plain"
          >
            {{ name }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="计费价格（元/百万 Token）">
          <template v-if="detailModel.pricing">
            <div
              v-for="(line, index) in priceLines(detailModel.pricing)"
              :key="index"
              class="model-price-line"
            >
              {{ line }}
            </div>
            <div v-if="detailModel.pricing.note" class="model-detail-note">
              {{ detailModel.pricing.note }}
            </div>
          </template>
          <span v-else>未配置计价</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

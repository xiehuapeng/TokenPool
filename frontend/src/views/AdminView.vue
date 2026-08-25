<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import {
  adminApi,
  type AdminLogFilters,
  type AdminUsageFilters,
} from "@/api";
import { errorMessage } from "@/api/http";
import { formatBeijingTime } from "@/utils/time";
import { copyText } from "@/utils/clipboard";
import { categorizeProviderModels } from "@/utils/modelCategories";

const activeTab = ref("users");
const users = ref<any[]>([]);
const inviteCodes = ref<any[]>([]);
const keys = ref<any[]>([]);
const models = ref<any[]>([]);
const providers = ref<any[]>([]);
const stats = ref<any>({
  summary: {},
  by_user: [],
  by_model: [],
  by_provider: [],
  filter_options: { models: [], providers: [] },
});
const logs = ref<any[]>([]);
const totalLogs = ref(0);
const statsLoading = ref(false);
const logsLoading = ref(false);
const logPage = ref(1);
const logPageSize = ref(50);
const statsFilters = reactive({
  days: 30,
  username: "",
  model: "",
  provider: "",
});
const logFilters = reactive({
  days: 30,
  username: "",
  model: "",
  provider: "",
  status: "",
  request_id: "",
});
const usageDetailVisible = ref(false);
const usageDetailLoading = ref(false);
const usageDetailUser = ref<any>(null);
const usageDetailPeriod = ref("30");
const usageDetail = ref<any>({
  summary: {},
  by_model: [],
  by_day: [],
});
const createUserVisible = ref(false);
const createInviteVisible = ref(false);
const providerModelsVisible = ref(false);
const providerModelsLoading = ref(false);
const selectedProviderCode = ref("deepseek");
const activeModelProvider = ref("");
const activeModelCategories = reactive<Record<string, string>>({});
const availableProviderModels = ref<any[]>([]);
const selectedProviderModels = ref<string[]>([]);
const activeProviderModelCategory = ref("");
const inviteSecretVisible = ref(false);
const inviteSecret = ref("");
const inviteSecretLabel = ref("");
const userForm = reactive({ username: "", password: "", is_admin: false });
const inviteForm = reactive({
  label: "团队邀请码",
  code: "",
  max_uses: 20 as number | null,
  expires_at: "",
});

const usageModelOptions = computed(() =>
  (stats.value.filter_options?.models || []) as string[],
);

const usageProviderOptions = computed(() => {
  const usedProviders = new Set<string>(
    stats.value.filter_options?.providers || [],
  );
  return providers.value
    .filter(
      (provider: any) =>
        !usedProviders.size || usedProviders.has(provider.code),
    )
    .map((provider: any) => ({
      value: provider.code,
      label: provider.display_name,
    }));
});

const maxUserTokens = computed(() =>
  Math.max(
    0,
    ...stats.value.by_user.map((item: any) => Number(item.total_tokens || 0)),
  ),
);

const modelGroups = computed(() => {
  const providerOrder = new Map(
    providers.value.map((provider: any, index: number) => [provider.code, index]),
  );
  const groups = new Map<
    string,
    { code: string; name: string; models: any[]; enabledCount: number }
  >();

  for (const model of models.value) {
    const code = model.provider || "unknown";
    const group = groups.get(code) || {
      code,
      name: model.provider_name || code,
      models: [] as any[],
      enabledCount: 0,
    };
    group.models.push(model);
    if (model.enabled) group.enabledCount += 1;
    groups.set(code, group);
  }

  return Array.from(groups.values()).sort((left, right) => {
    const leftOrder = providerOrder.get(left.code) ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = providerOrder.get(right.code) ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || left.name.localeCompare(right.name);
  });
});

const availableProviderModelCategories = computed(() =>
  categorizeProviderModels(
    selectedProviderCode.value,
    availableProviderModels.value,
  ),
);

const visibleAvailableProviderModels = computed(() => {
  const category = availableProviderModelCategories.value.find(
    (item) => item.key === activeProviderModelCategory.value,
  );
  return category?.models || availableProviderModels.value;
});

function groupModelCategories(group: { code: string; models: any[] }) {
  return categorizeProviderModels(group.code, group.models);
}

function visibleGroupModels(group: { code: string; models: any[] }) {
  if (group.code !== "qwen") return group.models;
  const categories = groupModelCategories(group);
  return (
    categories.find(
      (category) => category.key === activeModelCategories[group.code],
    )?.models || categories[0]?.models || []
  );
}

function initializeModelCategories() {
  for (const group of modelGroups.value) {
    const categories = groupModelCategories(group);
    if (
      !categories.some(
        (category) => category.key === activeModelCategories[group.code],
      )
    ) {
      activeModelCategories[group.code] = categories[0]?.key || "";
    }
  }
}

async function loadAll() {
  try {
    const [u, i, k, m, p, s, l] = await Promise.all([
      adminApi.users(),
      adminApi.inviteCodes(),
      adminApi.keys(),
      adminApi.models(),
      adminApi.providers(),
      adminApi.stats(buildUsageParams(statsFilters)),
      adminApi.logs(buildLogParams()),
    ]);
    users.value = u.data;
    inviteCodes.value = i.data;
    keys.value = k.data;
    models.value = m.data;
    providers.value = p.data;
    if (
      !activeModelProvider.value ||
      !models.value.some(
        (model: any) => model.provider === activeModelProvider.value,
      )
    ) {
      activeModelProvider.value = models.value[0]?.provider || "";
    }
    initializeModelCategories();
    stats.value = s.data;
    logs.value = l.data.items;
    totalLogs.value = l.data.total;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function createUser() {
  if (
    !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$/.test(
      userForm.username.trim(),
    )
  ) {
    ElMessage.warning("用户名格式不符合要求");
    return;
  }
  if (
    userForm.password.length < 8 ||
    userForm.password.length > 64 ||
    !/[A-Za-z]/.test(userForm.password) ||
    !/\d/.test(userForm.password)
  ) {
    ElMessage.warning("密码需为 8–64 位，并且至少包含一个字母和一个数字");
    return;
  }
  try {
    await adminApi.createUser({
      ...userForm,
      username: userForm.username.trim(),
    });
    createUserVisible.value = false;
    Object.assign(userForm, { username: "", password: "", is_admin: false });
    ElMessage.success("用户已创建");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function createInviteCode() {
  if (!/^[a-zA-Z0-9_-]{8,64}$/.test(inviteForm.code.trim())) {
    ElMessage.warning("邀请码需为 8–64 位，仅支持字母、数字、下划线和短横线");
    return;
  }
  try {
    const response = await adminApi.createInviteCode({
      label: inviteForm.label.trim(),
      code: inviteForm.code.trim(),
      max_uses: inviteForm.max_uses || null,
      expires_at: inviteForm.expires_at
        ? new Date(inviteForm.expires_at).toISOString()
        : null,
    });
    createInviteVisible.value = false;
    Object.assign(inviteForm, {
      label: "团队邀请码",
      code: "",
      max_uses: 20,
      expires_at: "",
    });
    inviteSecret.value = response.data.code;
    inviteSecretLabel.value = response.data.label;
    inviteSecretVisible.value = true;
    ElMessage.success("邀请码已创建并加密保存");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function toggleInviteCode(row: any) {
  const next = row.status === "active" ? "disabled" : "active";
  await adminApi.setInviteCodeStatus(row.id, next);
  ElMessage.success(next === "active" ? "邀请码已启用" : "邀请码已停用");
  await loadAll();
}

async function toggleUser(row: any) {
  const next = row.status === "active" ? "disabled" : "active";
  await ElMessageBox.confirm(
    `确定将用户 ${row.username} 设为 ${next}？`,
    "用户状态",
  );
  await adminApi.setUserStatus(row.id, next);
  await loadAll();
}

async function revokeKey(row: any) {
  await ElMessageBox.confirm(
    `确定吊销 ${row.username} 的这个 API Key？`,
    "API Key",
  );
  await adminApi.setKeyStatus(row.id, "revoked");
  await loadAll();
}

async function setModelEnabled(row: any, enabled: boolean) {
  try {
    await adminApi.updateModel(row.id, { enabled });
    ElMessage.success("模型状态已更新");
  } catch (error) {
    row.enabled = !enabled;
    ElMessage.error(errorMessage(error));
  }
}

const pricingDialogVisible = ref(false);
const pricingSaving = ref(false);
const pricingModel = ref<any>(null);
const pricingForm = reactive({
  input_price: null as number | null,
  cached_input_price: null as number | null,
  output_price: null as number | null,
  peak_input_price: null as number | null,
  peak_cached_input_price: null as number | null,
  peak_output_price: null as number | null,
  tier_threshold_tokens: null as number | null,
  high_input_price: null as number | null,
  high_cached_input_price: null as number | null,
  high_output_price: null as number | null,
  enabled: true,
});

function openPricingDialog(row: any) {
  pricingModel.value = row;
  const pricing = row.pricing;
  Object.assign(pricingForm, {
    input_price: pricing?.input_price ?? null,
    cached_input_price: pricing?.cached_input_price ?? null,
    output_price: pricing?.output_price ?? null,
    peak_input_price: pricing?.peak_input_price ?? null,
    peak_cached_input_price: pricing?.peak_cached_input_price ?? null,
    peak_output_price: pricing?.peak_output_price ?? null,
    tier_threshold_tokens: pricing?.tier_threshold_tokens ?? null,
    high_input_price: pricing?.high_input_price ?? null,
    high_cached_input_price: pricing?.high_cached_input_price ?? null,
    high_output_price: pricing?.high_output_price ?? null,
    enabled: pricing ? pricing.enabled : true,
  });
  pricingDialogVisible.value = true;
}

async function savePricing() {
  if (
    pricingForm.input_price == null ||
    pricingForm.cached_input_price == null ||
    pricingForm.output_price == null
  ) {
    ElMessage.warning("输入 / 缓存命中 / 输出单价为必填项");
    return;
  }
  const hasHighPrice =
    pricingForm.high_input_price != null ||
    pricingForm.high_cached_input_price != null ||
    pricingForm.high_output_price != null;
  if (hasHighPrice && pricingForm.tier_threshold_tokens == null) {
    ElMessage.warning("已填写超长上下文单价，请同时设置阈值（输入 Token 数）");
    return;
  }
  if (
    pricingForm.tier_threshold_tokens != null &&
    pricingForm.high_input_price == null
  ) {
    ElMessage.warning("已设置阈值，请至少填写超长上下文输入单价");
    return;
  }
  pricingSaving.value = true;
  try {
    await adminApi.updateModelPricing(pricingModel.value.id, {
      ...pricingForm,
    });
    pricingDialogVisible.value = false;
    ElMessage.success("模型定价已保存");
    const response = await adminApi.models();
    models.value = response.data;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    pricingSaving.value = false;
  }
}

function buildUsageParams(filters: typeof statsFilters): AdminUsageFilters {
  return {
    days: filters.days,
    username: filters.username || undefined,
    model: filters.model || undefined,
    provider: filters.provider || undefined,
  };
}

function buildLogParams(): AdminLogFilters {
  return {
    days: logFilters.days,
    username: logFilters.username || undefined,
    model: logFilters.model || undefined,
    provider: logFilters.provider || undefined,
    status: logFilters.status || undefined,
    request_id: logFilters.request_id.trim() || undefined,
    limit: logPageSize.value,
    offset: (logPage.value - 1) * logPageSize.value,
  };
}

async function loadStats() {
  statsLoading.value = true;
  try {
    const response = await adminApi.stats(buildUsageParams(statsFilters));
    stats.value = response.data;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    statsLoading.value = false;
  }
}

async function loadLogs() {
  logsLoading.value = true;
  try {
    const response = await adminApi.logs(buildLogParams());
    logs.value = response.data.items;
    totalLogs.value = response.data.total;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    logsLoading.value = false;
  }
}

async function applyStatsFilters() {
  await loadStats();
}

async function resetStatsFilters() {
  Object.assign(statsFilters, {
    days: 30,
    username: "",
    model: "",
    provider: "",
  });
  await loadStats();
}

const backfillLoading = ref(false);

async function backfillUsageCosts() {
  let previewData: any;
  try {
    const preview = await adminApi.backfillCosts(true);
    previewData = preview.data;
  } catch (error) {
    ElMessage.error(errorMessage(error));
    return;
  }
  if (!previewData.updated) {
    ElMessage.info("没有需要回填费用的历史日志");
    return;
  }
  const rates = Object.entries(previewData.model_cache_hit_rates || {})
    .map(([model, rate]) => `${model} ${(Number(rate) * 100).toFixed(1)}%`)
    .join("；");
  const globalRate =
    previewData.global_cache_hit_rate != null
      ? `；无自身数据模型按全局平均 ${(Number(previewData.global_cache_hit_rate) * 100).toFixed(1)}% 推算`
      : "";
  try {
    await ElMessageBox.confirm(
      `预览（未落库）：将回填 ${previewData.updated} 条历史日志，估算总费用 ¥${Number(
        previewData.total_estimated_cost
      ).toFixed(4)}` +
        (rates ? `。各模型平均缓存命中率：${rates}${globalRate}` : "") +
        "。回填后的费用会标记为「回填估算」，是否执行？",
      "历史费用回填",
      {
        confirmButtonText: "执行回填",
        cancelButtonText: "取消",
        type: "warning",
      }
    );
  } catch {
    return;
  }
  backfillLoading.value = true;
  try {
    const response = await adminApi.backfillCosts(false);
    const data = response.data;
    ElMessage.success(
      `已回填 ${data.updated} 条历史日志，估算总费用 ¥${Number(
        data.total_estimated_cost
      ).toFixed(4)}`
    );
    await Promise.all([loadStats(), loadLogs()]);
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    backfillLoading.value = false;
  }
}

async function applyLogFilters() {
  logPage.value = 1;
  await loadLogs();
}

async function resetLogFilters() {
  Object.assign(logFilters, {
    days: 30,
    username: "",
    model: "",
    provider: "",
    status: "",
    request_id: "",
  });
  logPage.value = 1;
  await loadLogs();
}

async function showUserLogs(username: string) {
  Object.assign(logFilters, {
    days: statsFilters.days,
    username,
    model: statsFilters.model,
    provider: statsFilters.provider,
    status: "",
    request_id: "",
  });
  logPage.value = 1;
  activeTab.value = "logs";
  await loadLogs();
}

async function loadUsageDetail() {
  if (!usageDetailUser.value) return;
  usageDetailLoading.value = true;
  try {
    const params =
      usageDetailPeriod.value === "today"
        ? { today: true }
        : { days: Number(usageDetailPeriod.value) };
    const response = await adminApi.userUsage(usageDetailUser.value.id, params);
    usageDetail.value = response.data;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    usageDetailLoading.value = false;
  }
}

function openUserUsage(row: any) {
  let target = row;
  if (target.id == null && target.username) {
    target = users.value.find((item: any) => item.username === target.username);
  }
  if (!target?.id) {
    ElMessage.warning("未找到该用户");
    return;
  }
  usageDetailUser.value = target;
  usageDetailPeriod.value = "30";
  usageDetail.value = { summary: {}, by_model: [], by_day: [] };
  usageDetailVisible.value = true;
  loadUsageDetail();
}

function resetUsageDetail() {
  usageDetail.value = { summary: {}, by_model: [], by_day: [] };
  usageDetailUser.value = null;
}

async function changeLogPage(page: number) {
  logPage.value = page;
  await loadLogs();
}

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

function formatPrice(value: unknown) {
  if (value == null) return "—";
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : "—";
}

function costSourceLabel(source: unknown) {
  if (source === "realtime") return "请求完成时实时计价";
  if (source === "estimated") return "回填估算";
  if (source === "bill_allocated") return "厂商账单分摊";
  return String(source || "—");
}

function formatPriceDetail(detail: any) {
  if (!detail) return "—";
  const parts = [
    `输入 ${formatPrice(detail.input_price)}`,
    `缓存 ${formatPrice(detail.cached_input_price)}`,
    `输出 ${formatPrice(detail.output_price)}`,
    "元/百万Token",
  ];
  if (detail.tier === "high") parts.push("超长上下文档");
  if (detail.peak) parts.push("峰时");
  if (detail.estimated) {
    let label = "估算值";
    if (detail.cache_hit_rate != null) {
      const ratePercent = (Number(detail.cache_hit_rate) * 100).toFixed(1);
      const basis = detail.cache_rate_basis === "global_avg"
        ? "全局平均"
        : detail.cache_rate_basis === "provider_bill_day"
          ? "厂商当日账单"
          : "该模型平均";
      label += `（缓存按${basis}命中率 ${ratePercent}% 推算）`;
    }
    if (detail.bill_allocated) label = `厂商账单按Token比例分摊（${label}）`;
    parts.push(label);
  }
  return parts.join(" · ");
}

function userSuccessRate(row: any) {
  return row.requests
    ? Math.round((Number(row.success_requests) / Number(row.requests)) * 1000) /
        10
    : 0;
}

function userTokenPercentage(row: any) {
  return maxUserTokens.value
    ? Math.round((Number(row.total_tokens || 0) / maxUserTokens.value) * 100)
    : 0;
}

function statusTagType(status: string) {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "pending") return "warning";
  return "info";
}

async function revealInviteCode(row: any) {
  try {
    const response = await adminApi.revealInviteCode(row.id);
    inviteSecret.value = response.data.value;
    inviteSecretLabel.value = row.label;
    inviteSecretVisible.value = true;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function copy(value: string) {
  try {
    await copyText(value);
    ElMessage.success("已复制");
  } catch (error) {
    ElMessage.error(
      error instanceof Error ? error.message : "复制失败，请手动选择复制",
    );
  }
}

function selectedProviderName() {
  return (
    providers.value.find(
      (item: any) => item.code === selectedProviderCode.value,
    )?.display_name || selectedProviderCode.value
  );
}

async function openProviderModels(providerCode: string) {
  selectedProviderCode.value = providerCode;
  providerModelsVisible.value = true;
  providerModelsLoading.value = true;
  try {
    const response = await adminApi.providerModels(providerCode);
    availableProviderModels.value = response.data.models;
    selectedProviderModels.value = response.data.models
      .filter((item: any) => item.enabled)
      .map((item: any) => item.id);
    activeProviderModelCategory.value =
      availableProviderModelCategories.value[0]?.key || "";
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    providerModelsLoading.value = false;
  }
}

function visibleCategoryFullySelected() {
  return (
    visibleAvailableProviderModels.value.length > 0 &&
    visibleAvailableProviderModels.value.every((model: any) =>
      selectedProviderModels.value.includes(model.id),
    )
  );
}

function toggleVisibleCategory() {
  const visibleIds = visibleAvailableProviderModels.value.map(
    (model: any) => model.id,
  );
  if (visibleCategoryFullySelected()) {
    const visibleSet = new Set(visibleIds);
    selectedProviderModels.value = selectedProviderModels.value.filter(
      (modelId) => !visibleSet.has(modelId),
    );
    return;
  }
  selectedProviderModels.value = Array.from(
    new Set([...selectedProviderModels.value, ...visibleIds]),
  );
}

async function syncProviderModels() {
  if (!selectedProviderModels.value.length) {
    ElMessage.warning("请至少选择一个模型");
    return;
  }
  providerModelsLoading.value = true;
  try {
    await adminApi.syncProviderModels(selectedProviderCode.value, {
      models: selectedProviderModels.value,
      enable: true,
      default_allowed: true,
    });
    providerModelsVisible.value = false;
    ElMessage.success(`已按 ${selectedProviderName()} 官方列表同步模型`);
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    providerModelsLoading.value = false;
  }
}

onMounted(loadAll);
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>管理后台</h1>
        <p>管理团队访问、邀请码、模型配置和调用审计。</p>
      </div>
      <el-button
        v-if="activeTab === 'users'"
        type="primary"
        @click="createUserVisible = true"
      >
        创建用户
      </el-button>
      <el-button
        v-if="activeTab === 'invites'"
        type="primary"
        @click="createInviteVisible = true"
      >
        设置邀请码
      </el-button>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="用户管理" name="users">
          <el-table :data="users">
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="角色">
              <template #default="{ row }">
                {{ row.is_admin ? "管理员" : "成员" }}
              </template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" min-width="150">
              <template #default="{ row }">
                <el-button link type="primary" @click="openUserUsage(row)">
                  消费明细
                </el-button>
                <el-button link @click="toggleUser(row)">
                  {{ row.status === "active" ? "禁用" : "启用" }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="邀请码" name="invites">
          <el-alert
            title="新创建的邀请码会加密保存，可由管理员重复查看和复制；旧邀请码原文无法恢复。"
            type="info"
            :closable="false"
            show-icon
            class="admin-alert"
          />
          <el-table :data="inviteCodes">
            <el-table-column prop="label" label="用途" />
            <el-table-column prop="code_prefix" label="邀请码摘要" />
            <el-table-column label="使用次数">
              <template #default="{ row }">
                {{ row.usage_count }} / {{ row.max_uses ?? "不限" }}
              </template>
            </el-table-column>
            <el-table-column label="过期时间" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.expires_at, "永久有效") }}
              </template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status === "active" ? "启用" : "停用" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button
                  v-if="row.can_reveal"
                  link
                  type="primary"
                  @click="revealInviteCode(row)"
                >
                  查看/复制
                </el-button>
                <el-tooltip
                  v-else
                  content="该邀请码创建于加密存储启用前，原文无法恢复"
                  placement="top"
                >
                  <el-button link disabled>不可查看</el-button>
                </el-tooltip>
                <el-button link @click="toggleInviteCode(row)">
                  {{ row.status === "active" ? "停用" : "启用" }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="API Key" name="keys">
          <el-table :data="keys">
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="key_prefix" label="Key 前缀" min-width="190" />
            <el-table-column label="创建时间" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="最后使用" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.last_used_at, "从未使用") }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" />
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button
                  v-if="row.status === 'active'"
                  link
                  type="danger"
                  @click="revokeKey(row)"
                >
                  吊销
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="模型管理" name="models">
          <el-alert
            title="可从已启用 Provider 的官方 /models 接口获取当前可用模型。已有旧模型不会被自动删除或停用，避免影响团队现有配置。"
            type="info"
            :closable="false"
            show-icon
            class="admin-alert"
          />
          <el-empty v-if="!modelGroups.length" description="暂无模型配置" />
          <el-tabs v-else v-model="activeModelProvider" class="model-provider-tabs">
            <el-tab-pane
              v-for="group in modelGroups"
              :key="group.code"
              :name="group.code"
            >
              <template #label>
                <span class="model-provider-tab-label">
                  {{ group.name }}
                  <el-tag size="small" effect="plain">{{ group.models.length }}</el-tag>
                </span>
              </template>
              <div class="model-provider-toolbar">
                <div>
                  <strong>{{ group.name }}</strong>
                  <span>
                    共 {{ group.models.length }} 个模型，已启用
                    {{ group.enabledCount }} 个
                  </span>
                </div>
                <el-button
                  v-if="providers.find((item) => item.code === group.code)?.enabled"
                  type="primary"
                  @click="openProviderModels(group.code)"
                >
                  同步 {{ group.name }} 官方模型
                </el-button>
              </div>
              <el-tabs
                v-if="group.code === 'qwen'"
                v-model="activeModelCategories[group.code]"
                class="model-category-tabs"
              >
                <el-tab-pane
                  v-for="category in groupModelCategories(group)"
                  :key="category.key"
                  :name="category.key"
                >
                  <template #label>
                    <span class="model-category-tab-label">
                      {{ category.label }}
                      <el-tag size="small" effect="plain">
                        {{ category.models.length }}
                      </el-tag>
                    </span>
                  </template>
                </el-tab-pane>
              </el-tabs>
              <el-table :data="visibleGroupModels(group)">
                <el-table-column
                  prop="public_model"
                  label="公开模型名"
                  min-width="180"
                />
                <el-table-column
                  prop="upstream_model"
                  label="上游模型名"
                  min-width="180"
                />
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
                <el-table-column label="默认开放" width="100">
                  <template #default="{ row }">
                    {{ row.default_allowed ? "是" : "否" }}
                  </template>
                </el-table-column>
                <el-table-column label="单价（元/百万Token）" min-width="240">
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
                          row.pricing.tier_threshold_tokens != null ||
                          !row.pricing.enabled
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
                        <el-tag
                          v-if="!row.pricing.enabled"
                          size="small"
                          type="info"
                          effect="plain"
                        >
                          计价停用
                        </el-tag>
                      </div>
                    </template>
                    <el-tag v-else size="small" type="warning" effect="plain">
                      未配置计价
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="启用" width="90">
                  <template #default="{ row }">
                    <el-switch
                      v-model="row.enabled"
                      @change="(value) => setModelEnabled(row, Boolean(value))"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="100" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      link
                      type="primary"
                      @click="openPricingDialog(row)"
                    >
                      编辑单价
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="Provider" name="providers">
          <el-table :data="providers">
            <el-table-column prop="display_name" label="Provider" />
            <el-table-column prop="code" label="代码" />
            <el-table-column prop="base_url" label="Base URL" min-width="260" />
            <el-table-column prop="timeout_seconds" label="超时（秒）" />
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'">
                  {{ row.enabled ? "启用" : "未启用" }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="Token 统计" name="stats">
          <div class="usage-filter-bar">
            <el-select v-model="statsFilters.days" class="usage-filter-period">
              <el-option label="最近 24 小时" :value="1" />
              <el-option label="最近 7 天" :value="7" />
              <el-option label="最近 30 天" :value="30" />
              <el-option label="最近 90 天" :value="90" />
              <el-option label="全部时间" :value="0" />
            </el-select>
            <el-select
              v-model="statsFilters.username"
              filterable
              clearable
              placeholder="全部用户"
            >
              <el-option
                v-for="user in users"
                :key="user.id"
                :label="user.username"
                :value="user.username"
              />
            </el-select>
            <el-select
              v-model="statsFilters.model"
              filterable
              clearable
              placeholder="全部实际模型"
            >
              <el-option
                v-for="model in usageModelOptions"
                :key="model"
                :label="model"
                :value="model"
              />
            </el-select>
            <el-select
              v-model="statsFilters.provider"
              clearable
              placeholder="全部 Provider"
            >
              <el-option
                v-for="provider in usageProviderOptions"
                :key="provider.value"
                :label="provider.label"
                :value="provider.value"
              />
            </el-select>
            <div class="usage-filter-actions">
              <el-button type="primary" :loading="statsLoading" @click="applyStatsFilters">
                查询
              </el-button>
              <el-button @click="resetStatsFilters">重置</el-button>
              <el-button
                :loading="backfillLoading"
                @click="backfillUsageCosts"
              >
                历史费用回填
              </el-button>
            </div>
          </div>

          <div class="admin-metric-grid" v-loading="statsLoading">
            <div class="metric-card usage-metric-primary">
              <span>总 Token</span>
              <strong>{{ formatTokens(stats.summary.total_tokens) }}</strong>
              <small>筛选范围内累计消耗</small>
            </div>
            <div class="metric-card">
              <span>总费用</span>
              <strong>{{ formatCost(stats.summary.cost) }}</strong>
              <small>按请求时定价快照计算（人民币）</small>
            </div>
            <div class="metric-card">
              <span>输入 Token</span>
              <strong>{{ formatTokens(stats.summary.input_tokens) }}</strong>
              <small>Prompt 与上下文</small>
            </div>
            <div class="metric-card">
              <span>输出 Token</span>
              <strong>{{ formatTokens(stats.summary.output_tokens) }}</strong>
              <small>模型生成内容</small>
            </div>
            <div class="metric-card">
              <span>请求 / 成功率</span>
              <strong>{{ formatTokens(stats.summary.requests) }}</strong>
              <small>
                成功 {{ stats.summary.success_rate || 0 }}%，未成功
                {{ stats.summary.non_success_requests || 0 }} 次
              </small>
            </div>
            <div class="metric-card">
              <span>活跃用户 / 模型</span>
              <strong>
                {{ stats.summary.active_users || 0 }} / {{ stats.summary.models_used || 0 }}
              </strong>
              <small>发生过调用的用户和模型</small>
            </div>
          </div>

          <section class="usage-section">
            <div class="usage-section-heading">
              <div>
                <h3>成员用量</h3>
                <p>每位成员一行，可直接进入该成员的调用日志。</p>
              </div>
              <el-tag effect="plain">{{ stats.by_user.length }} 人</el-tag>
            </div>
            <el-table :data="stats.by_user" v-loading="statsLoading">
              <el-table-column prop="username" label="用户" min-width="130" fixed="left" />
              <el-table-column label="总 Token" min-width="210" sortable prop="total_tokens">
                <template #default="{ row }">
                  <div class="user-token-cell">
                    <strong>{{ formatTokens(row.total_tokens) }}</strong>
                    <el-progress
                      :percentage="userTokenPercentage(row)"
                      :show-text="false"
                      :stroke-width="5"
                    />
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="输入 / 输出" min-width="170">
                <template #default="{ row }">
                  {{ formatTokens(row.input_tokens) }} / {{ formatTokens(row.output_tokens) }}
                </template>
              </el-table-column>
              <el-table-column label="费用" min-width="115" sortable prop="cost">
                <template #default="{ row }">{{ formatCost(row.cost) }}</template>
              </el-table-column>
              <el-table-column prop="requests" label="请求数" width="100" sortable />
              <el-table-column label="成功率" width="105">
                <template #default="{ row }">{{ userSuccessRate(row) }}%</template>
              </el-table-column>
              <el-table-column label="模型 / Provider" min-width="145">
                <template #default="{ row }">
                  {{ row.models_used }} / {{ row.providers_used }}
                </template>
              </el-table-column>
              <el-table-column label="最近调用" min-width="180">
                <template #default="{ row }">
                  {{ formatBeijingTime(row.last_request_time, "暂无调用") }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openUserUsage(row)">
                    消费明细
                  </el-button>
                  <el-button link type="primary" @click="showUserLogs(row.username)">
                    查看日志
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>

          <div class="usage-breakdown-grid">
            <section class="usage-section">
              <div class="usage-section-heading"><h3>模型用量</h3></div>
              <el-table :data="stats.by_model" max-height="420">
                <el-table-column prop="model" label="实际模型" min-width="160" />
                <el-table-column prop="users" label="用户" width="70" />
                <el-table-column prop="requests" label="请求" width="75" />
                <el-table-column label="Token" min-width="110" align="right">
                  <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
                </el-table-column>
              </el-table>
            </section>
            <section class="usage-section">
              <div class="usage-section-heading"><h3>Provider 用量</h3></div>
              <el-table :data="stats.by_provider" max-height="420">
                <el-table-column prop="provider" label="Provider" min-width="120" />
                <el-table-column prop="users" label="用户" width="70" />
                <el-table-column prop="requests" label="请求" width="75" />
                <el-table-column label="Token" min-width="110" align="right">
                  <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
                </el-table-column>
                <el-table-column label="费用" min-width="100" align="right">
                  <template #default="{ row }">{{ formatCost(row.cost) }}</template>
                </el-table-column>
              </el-table>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`调用日志 (${totalLogs})`" name="logs">
          <div class="usage-filter-bar log-filter-bar">
            <el-select v-model="logFilters.days" class="usage-filter-period">
              <el-option label="最近 24 小时" :value="1" />
              <el-option label="最近 7 天" :value="7" />
              <el-option label="最近 30 天" :value="30" />
              <el-option label="最近 90 天" :value="90" />
              <el-option label="全部时间" :value="0" />
            </el-select>
            <el-select v-model="logFilters.username" filterable clearable placeholder="全部用户">
              <el-option
                v-for="user in users"
                :key="user.id"
                :label="user.username"
                :value="user.username"
              />
            </el-select>
            <el-select v-model="logFilters.model" filterable clearable placeholder="全部实际模型">
              <el-option
                v-for="model in usageModelOptions"
                :key="model"
                :label="model"
                :value="model"
              />
            </el-select>
            <el-select v-model="logFilters.provider" clearable placeholder="全部 Provider">
              <el-option
                v-for="provider in usageProviderOptions"
                :key="provider.value"
                :label="provider.label"
                :value="provider.value"
              />
            </el-select>
            <el-select v-model="logFilters.status" clearable placeholder="全部状态">
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
              <el-option label="客户端断开" value="client_disconnected" />
              <el-option label="处理中" value="pending" />
            </el-select>
            <el-input
              v-model="logFilters.request_id"
              clearable
              placeholder="Request ID（精确）"
              @keyup.enter="applyLogFilters"
            />
            <div class="usage-filter-actions">
              <el-button type="primary" :loading="logsLoading" @click="applyLogFilters">
                查询
              </el-button>
              <el-button @click="resetLogFilters">重置</el-button>
            </div>
          </div>
          <div class="log-result-summary">
            当前筛选共 <strong>{{ formatTokens(totalLogs) }}</strong> 条调用记录
          </div>
          <el-table :data="logs" v-loading="logsLoading">
            <el-table-column type="expand" width="44">
              <template #default="{ row }">
                <div class="log-detail-grid">
                  <span>Request ID</span><code>{{ row.request_id }}</code>
                  <span>调用方式</span><span>{{ row.stream ? "SSE 流式" : "非流式" }}</span>
                  <span>HTTP 状态</span><span>{{ row.http_status ?? "—" }}</span>
                  <span>Usage 来源</span><span>{{ row.usage_source || "—" }}</span>
                  <span>缓存命中 Token</span><span>{{ row.cached_input_tokens ?? "—" }}</span>
                  <span>推理 Token</span><span>{{ row.reasoning_tokens ?? "—" }}</span>
                  <span>费用</span>
                  <span>
                    {{ row.cost != null ? formatCost(row.cost) : "—" }}
                    <template v-if="row.cost != null">
                      （{{ costSourceLabel(row.cost_source) }}）
                    </template>
                  </span>
                  <span>计价明细</span><span>{{ formatPriceDetail(row.price_detail) }}</span>
                  <span>错误信息</span><span>{{ row.error_message || row.error_code || "—" }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="北京时间" min-width="190">
              <template #default="{ row }">
                {{ formatBeijingTime(row.request_time) }}
              </template>
            </el-table-column>
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="requested_model" label="请求模型" min-width="140" />
            <el-table-column prop="model" label="实际模型" min-width="150" />
            <el-table-column prop="provider" label="Provider" />
            <el-table-column label="输入 / 输出" min-width="150">
              <template #default="{ row }">
                {{ formatTokens(row.input_tokens) }} / {{ formatTokens(row.output_tokens) }}
              </template>
            </el-table-column>
            <el-table-column label="总 Token" min-width="105" align="right">
              <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
            </el-table-column>
            <el-table-column label="费用" min-width="110" align="right">
              <template #default="{ row }">
                {{ row.cost != null ? formatCost(row.cost) : "—" }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" effect="plain">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="latency_ms" label="耗时（ms）" />
          </el-table>
          <div class="log-pagination">
            <el-pagination
              v-model:current-page="logPage"
              :page-size="logPageSize"
              :total="totalLogs"
              layout="total, prev, pager, next"
              background
              @current-change="changeLogPage"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="createUserVisible" title="创建用户" width="480px">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" />
          <div class="form-tip">
            3–64 位，以字母或数字开头和结尾；不区分大小写且不能重名
          </div>
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="userForm.password" type="password" show-password />
          <div class="form-tip">8–64 位，至少包含一个字母和一个数字</div>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="userForm.is_admin">管理员</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createUserVisible = false">取消</el-button>
        <el-button type="primary" @click="createUser">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createInviteVisible" title="设置邀请码" width="520px">
      <el-form label-position="top">
        <el-form-item label="用途说明">
          <el-input v-model="inviteForm.label" placeholder="例如：研发团队七月入组" />
        </el-form-item>
        <el-form-item label="邀请码">
          <el-input
            v-model="inviteForm.code"
            placeholder="8–64 位字母、数字、下划线或短横线"
            show-word-limit
            maxlength="64"
          />
          <div class="form-tip">
            原文将加密保存，后续可在邀请码列表中再次查看和复制
          </div>
        </el-form-item>
        <el-form-item label="最大使用次数">
          <el-input-number
            v-model="inviteForm.max_uses"
            :min="1"
            :max="10000"
          />
          <span class="form-inline-tip">留空表示不限制</span>
        </el-form-item>
        <el-form-item label="过期时间（可选）">
          <el-date-picker
            v-model="inviteForm.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="不设置则永久有效"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createInviteVisible = false">取消</el-button>
        <el-button type="primary" @click="createInviteCode">创建邀请码</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="inviteSecretVisible"
      :title="`查看邀请码：${inviteSecretLabel}`"
      width="560px"
      :close-on-click-modal="false"
      @closed="inviteSecret = ''"
    >
      <el-alert type="warning" :closable="false">
        邀请码允许注册团队账号，请仅提供给可信成员。
      </el-alert>
      <div class="secret-value"><code>{{ inviteSecret }}</code></div>
      <template #footer>
        <el-button type="primary" @click="copy(inviteSecret)">
          复制邀请码
        </el-button>
        <el-button @click="inviteSecretVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="providerModelsVisible"
      :title="`同步 ${selectedProviderName()} 官方模型`"
      width="620px"
    >
      <el-alert
        :title="`列表实时来自已配置的 ${selectedProviderName()} Provider。勾选后会创建或启用对应的网关模型名。`"
        type="info"
        :closable="false"
        show-icon
        class="admin-alert"
      />
      <div v-loading="providerModelsLoading" class="provider-model-list">
        <el-empty
          v-if="!providerModelsLoading && !availableProviderModels.length"
          description="未获取到可用模型"
        />
        <template v-else>
          <el-tabs
            v-if="selectedProviderCode === 'qwen'"
            v-model="activeProviderModelCategory"
            class="model-category-tabs provider-sync-category-tabs"
          >
            <el-tab-pane
              v-for="category in availableProviderModelCategories"
              :key="category.key"
              :name="category.key"
            >
              <template #label>
                <span class="model-category-tab-label">
                  {{ category.label }}
                  <el-tag size="small" effect="plain">
                    {{ category.models.length }}
                  </el-tag>
                </span>
              </template>
            </el-tab-pane>
          </el-tabs>
          <div class="provider-model-category-toolbar">
            <span>
              当前分类 {{ visibleAvailableProviderModels.length }} 个模型，已选
              {{ selectedProviderModels.length }} 个
            </span>
            <el-button link type="primary" @click="toggleVisibleCategory">
              {{ visibleCategoryFullySelected() ? "取消本类全选" : "选择本类全部" }}
            </el-button>
          </div>
        <el-checkbox-group v-model="selectedProviderModels">
          <div
            v-for="model in visibleAvailableProviderModels"
            :key="model.id"
            class="provider-model-item"
          >
            <el-checkbox :value="model.id">
              <code>{{ model.id }}</code>
            </el-checkbox>
            <div class="provider-model-tags">
              <el-tag v-if="model.configured" size="small" type="info">
                已配置
              </el-tag>
              <el-tag v-if="model.enabled" size="small" type="success">
                已启用
              </el-tag>
            </div>
          </div>
        </el-checkbox-group>
        </template>
      </div>
      <template #footer>
        <el-button @click="providerModelsVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="providerModelsLoading"
          @click="syncProviderModels"
        >
          同步所选模型
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="pricingDialogVisible"
      :title="`编辑定价：${pricingModel?.public_model || ''}`"
      width="680px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="单价单位为 元/百万Token。修改只影响之后的请求，历史记录的费用不变；留空表示清除该项。"
        type="info"
        :closable="false"
        show-icon
        class="admin-alert"
      />
      <el-form label-position="top" class="pricing-form">
        <div class="pricing-form-grid">
          <el-form-item label="输入单价（必填）">
            <el-input-number
              v-model="pricingForm.input_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="缓存命中单价（必填）">
            <el-input-number
              v-model="pricingForm.cached_input_price"
              :min="0"
              :step="0.1"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="输出单价（必填）">
            <el-input-number
              v-model="pricingForm.output_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
        </div>
        <div class="pricing-form-section-title">
          峰时单价（可选，适用于分峰谷计价的模型：北京时间工作日 9–12 点、14–18 点）
        </div>
        <div class="pricing-form-grid">
          <el-form-item label="峰时输入">
            <el-input-number
              v-model="pricingForm.peak_input_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="峰时缓存命中">
            <el-input-number
              v-model="pricingForm.peak_cached_input_price"
              :min="0"
              :step="0.1"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="峰时输出">
            <el-input-number
              v-model="pricingForm.peak_output_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
        </div>
        <div class="pricing-form-section-title">
          超长上下文加价档（可选：输入 Token 超过阈值时按本档单价计费）
        </div>
        <div class="pricing-form-grid">
          <el-form-item label="阈值（输入 Token）">
            <el-input-number
              v-model="pricingForm.tier_threshold_tokens"
              :min="1"
              :step="1000"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="加价档输入">
            <el-input-number
              v-model="pricingForm.high_input_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
          <el-form-item label="加价档缓存命中">
            <el-input-number
              v-model="pricingForm.high_cached_input_price"
              :min="0"
              :step="0.1"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
        </div>
        <div class="pricing-form-grid">
          <el-form-item label="加价档输出">
            <el-input-number
              v-model="pricingForm.high_output_price"
              :min="0"
              :step="0.5"
              controls-position="right"
              class="pricing-input"
            />
          </el-form-item>
        </div>
        <el-form-item>
          <el-checkbox v-model="pricingForm.enabled">
            启用该定价（取消勾选后不再计算费用）
          </el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pricingDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="pricingSaving" @click="savePricing">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="usageDetailVisible"
      :title="`消费明细：${usageDetailUser?.username || ''}`"
      width="920px"
      :close-on-click-modal="false"
      @closed="resetUsageDetail"
    >
      <div class="usage-detail-toolbar">
        <span>统计周期</span>
        <el-select v-model="usageDetailPeriod" @change="loadUsageDetail">
          <el-option label="今天" value="today" />
          <el-option label="最近 7 天" value="7" />
          <el-option label="最近 30 天" value="30" />
          <el-option label="最近 90 天" value="90" />
          <el-option label="全部时间" value="0" />
        </el-select>
      </div>

      <div class="admin-metric-grid" v-loading="usageDetailLoading">
        <div class="metric-card usage-metric-primary">
          <span>总 Token</span>
          <strong>{{ formatTokens(usageDetail.summary.total_tokens) }}</strong>
          <small>筛选范围内累计消耗</small>
        </div>
        <div class="metric-card">
          <span>总费用</span>
          <strong>{{ formatCost(usageDetail.summary.cost) }}</strong>
          <small>人民币</small>
        </div>
        <div class="metric-card">
          <span>请求数</span>
          <strong>{{ formatTokens(usageDetail.summary.requests) }}</strong>
          <small>累计调用次数</small>
        </div>
        <div class="metric-card">
          <span>活跃天数</span>
          <strong>{{ usageDetail.summary.active_days || 0 }}</strong>
          <small>发生调用的天数</small>
        </div>
      </div>

      <section class="usage-section">
        <div class="usage-section-heading">
          <div>
            <h3>各模型消费</h3>
            <p>该用户按实际模型汇总的请求、Token 与费用。</p>
          </div>
        </div>
        <el-table
          :data="usageDetail.by_model"
          v-loading="usageDetailLoading"
          max-height="360"
        >
          <el-table-column prop="model" label="实际模型" min-width="160" />
          <el-table-column prop="provider" label="Provider" min-width="110" />
          <el-table-column prop="requests" label="请求" width="90" />
          <el-table-column label="输入 / 输出" min-width="150">
            <template #default="{ row }">
              {{ formatTokens(row.input_tokens) }} / {{ formatTokens(row.output_tokens) }}
            </template>
          </el-table-column>
          <el-table-column label="总 Token" min-width="110" align="right">
            <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
          </el-table-column>
          <el-table-column label="费用" min-width="110" align="right">
            <template #default="{ row }">{{ formatCost(row.cost) }}</template>
          </el-table-column>
        </el-table>
      </section>

      <section class="usage-section">
        <div class="usage-section-heading">
          <div>
            <h3>按天消费</h3>
            <p>按北京时间自然日汇总的请求、Token 与费用。</p>
          </div>
        </div>
        <el-table
          :data="usageDetail.by_day"
          v-loading="usageDetailLoading"
          max-height="360"
        >
          <el-table-column prop="date" label="日期" min-width="120" />
          <el-table-column prop="requests" label="请求" width="90" />
          <el-table-column label="输入 / 输出" min-width="150">
            <template #default="{ row }">
              {{ formatTokens(row.input_tokens) }} / {{ formatTokens(row.output_tokens) }}
            </template>
          </el-table-column>
          <el-table-column label="总 Token" min-width="110" align="right">
            <template #default="{ row }">{{ formatTokens(row.total_tokens) }}</template>
          </el-table-column>
          <el-table-column label="费用" min-width="110" align="right">
            <template #default="{ row }">{{ formatCost(row.cost) }}</template>
          </el-table-column>
        </el-table>
      </section>
    </el-dialog>
  </div>
</template>

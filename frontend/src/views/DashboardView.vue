<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import { meApi, type ApiKeyItem } from "@/api";
import { errorMessage } from "@/api/http";
import { copyText } from "@/utils/clipboard";
import { preloadAuthenticatedViewsWhenIdle } from "@/router/viewLoaders";
import { formatBeijingTime } from "@/utils/time";

const baseUrl = ref("");
const keys = ref<ApiKeyItem[]>([]);
const loading = ref(true);
const generatedKey = ref("");
const keyDialogVisible = ref(false);
const keyDialogTitle = ref("API Key");
const models = ref<any[]>([]);
const selectedModel = ref("");
const savedSelectedModel = ref("");
const gatewayModel = ref("team-coding");
const savingModel = ref(false);
const activeModels = computed(() =>
  models.value.filter((item) => item.status === "enabled"),
);
const modelGroups = computed(() => {
  const grouped = new Map<string, any[]>();
  for (const model of activeModels.value) {
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
const isLegacyModel = computed(() =>
  ["deepseek-chat", "deepseek-reasoner"].includes(selectedModel.value),
);
const curlExample = computed(() => `curl ${baseUrl.value}/chat/completions \\
  -H "Authorization: Bearer ${generatedKey.value || "sk-team-your-key"}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${gatewayModel.value}",
    "messages": [{"role": "user", "content": "你好"}]
  }'`);

async function load() {
  loading.value = true;
  try {
    const [config, keyList, modelList, preference] = await Promise.all([
      meApi.config(),
      meApi.keys(),
      meApi.models(),
      meApi.modelPreference(),
    ]);
    baseUrl.value = config.data.base_url;
    keys.value = keyList.data;
    models.value = modelList.data;
    gatewayModel.value = preference.data.gateway_model;
    const preferredModel = preference.data.selected_model;
    selectedModel.value = activeModels.value.some(
      (item) => item.id === preferredModel,
    )
      ? preferredModel || ""
      : activeModels.value[0]?.id || "";
    savedSelectedModel.value = selectedModel.value;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    loading.value = false;
    const currentUser = JSON.parse(localStorage.getItem("user") || "null");
    preloadAuthenticatedViewsWhenIdle(Boolean(currentUser?.is_admin));
  }
}

async function saveModelPreference(value: string) {
  if (!value || value === savedSelectedModel.value) return;
  const previous = savedSelectedModel.value;
  savingModel.value = true;
  try {
    const response = await meApi.updateModelPreference(value);
    selectedModel.value = response.data.selected_model || value;
    savedSelectedModel.value = selectedModel.value;
    ElMessage.success("实际调用模型已更新，下一次调用生效");
  } catch (error) {
    selectedModel.value = previous;
    ElMessage.error(errorMessage(error));
  } finally {
    savingModel.value = false;
  }
}

async function createKey() {
  try {
    const { value } = await ElMessageBox.prompt("为这个 Key 填写名称", "生成 API Key", {
      inputValue: "Coding tools",
      inputPattern: /^.{1,80}$/,
    });
    const { data } = await meApi.createKey(value);
    generatedKey.value = data.key;
    keyDialogTitle.value = "API Key 已生成";
    keyDialogVisible.value = true;
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(errorMessage(error));
  }
}

async function revealKey(row: any) {
  try {
    const { data } = await meApi.revealKey(row.id);
    generatedKey.value = data.value;
    keyDialogTitle.value = `查看 API Key：${row.name}`;
    keyDialogVisible.value = true;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function revoke(id: number) {
  await ElMessageBox.confirm("吊销后该 Key 将立即失效并从工作台移除，且无法恢复。", "确认吊销", {
    type: "warning",
  });
  await meApi.revokeKey(id);
  ElMessage.success("API Key 已吊销并移除");
  await load();
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

onMounted(load);
</script>

<template>
  <div v-loading="loading">
    <div class="page-heading">
      <div><h1>工作台</h1><p>配置 Coding 工具并管理你的访问凭证。</p></div>
      <el-button type="primary" @click="createKey">生成 API Key</el-button>
    </div>

    <el-row :gutter="20">
      <el-col :span="10">
        <el-card shadow="never" class="hero-card">
          <span class="eyebrow">OPENAI COMPATIBLE</span>
          <h3>API Base URL</h3>
          <div class="copy-value">
            <code>{{ baseUrl }}</code>
            <el-button link @click="copy(baseUrl)">复制</el-button>
          </div>
          <p>在 Cursor、Trae、Qoder、Continue、Cline 中使用此地址。</p>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <strong>我的实际调用模型</strong>
              <el-button link @click="copy(gatewayModel)">复制固定模型 ID</el-button>
            </div>
          </template>
          <el-select
            v-model="selectedModel"
            class="model-select"
            placeholder="选择实际调用模型"
            aria-label="选择实际调用模型"
            :disabled="savingModel"
            @change="saveModelPreference"
          >
            <el-option-group
              v-for="group in modelGroups"
              :key="group.provider"
              :label="group.provider"
            >
              <el-option
                v-for="model in group.models"
                :key="model.id"
                :label="model.display_name || model.id"
                :value="model.id"
              />
            </el-option-group>
          </el-select>
          <div class="model-provider-groups">
            <section
              v-for="group in modelGroups"
              :key="group.provider"
              class="model-provider-group"
            >
              <div class="model-provider-name">{{ group.provider }}</div>
              <div class="model-pills">
                <el-tag
                  v-for="model in group.models"
                  :key="model.id"
                  size="large"
                  effect="plain"
                >
                  {{ model.id }}
                </el-tag>
              </div>
            </section>
            <el-empty
              v-if="!activeModels.length"
              description="暂无可用模型"
              :image-size="42"
            />
          </div>
          <p class="muted compact">
            Trae 等工具始终填写 <code>{{ gatewayModel }}</code>。修改这里后，
            下一次请求会自动路由到所选真实模型。
          </p>
          <el-alert
            v-if="isLegacyModel"
            title="这是 DeepSeek 兼容旧别名，建议将 Coding 工具模型改为 deepseek-v4-flash 或 deepseek-v4-pro。"
            type="warning"
            :closable="false"
            show-icon
            class="compact"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header"><strong>我的 API Keys</strong><span>完整 Key 加密保存，可重复查看</span></div>
      </template>
      <el-table :data="keys" empty-text="尚未生成 API Key">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="key_prefix" label="Key 前缀" min-width="190" />
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">
            {{ formatBeijingTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="last_used_at" label="最后使用" min-width="180">
          <template #default="{ row }">
            {{ formatBeijingTime(row.last_used_at, "从未使用") }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button
              v-if="row.can_reveal"
              link
              type="primary"
              @click="revealKey(row)"
            >
              查看/复制
            </el-button>
            <el-tooltip
              v-else
              content="该 Key 创建于加密存储启用前，原文无法恢复"
              placement="top"
            >
              <el-button link disabled>不可查看</el-button>
            </el-tooltip>
            <el-button v-if="row.status === 'active'" link type="danger" @click="revoke(row.id)">吊销</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <strong>Curl 快速验证</strong>
          <el-button link @click="copy(curlExample)">复制 Curl</el-button>
        </div>
      </template>
      <pre class="code-block">{{ curlExample }}</pre>
      <p class="muted compact">
        完整 API Key 使用服务端加密保存；认证仍只通过哈希校验。
      </p>
    </el-card>

    <el-dialog
      v-model="keyDialogVisible"
      :title="keyDialogTitle"
      width="620px"
      :close-on-click-modal="false"
      @closed="generatedKey = ''"
    >
      <el-alert type="warning" :closable="false">
        完整 Key 属于敏感凭证，请勿发送到公开聊天或截图中。
      </el-alert>
      <div class="secret-value"><code>{{ generatedKey }}</code></div>
      <template #footer>
        <el-button type="primary" @click="copy(generatedKey)">复制 API Key</el-button>
        <el-button @click="copy(curlExample)">复制含此 Key 的 Curl</el-button>
        <el-button @click="keyDialogVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

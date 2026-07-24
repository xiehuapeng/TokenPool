<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { meApi } from "@/api";
import { copyText } from "@/utils/clipboard";

const baseUrl = ref("http://localhost:8000/v1");
const models = ref<any[]>([]);
const selectedModel = ref("");
const defaultModel = computed(
  () => selectedModel.value || models.value[0]?.id || "deepseek-v4-flash",
);
const curl = computed(() => `curl ${baseUrl.value}/chat/completions \\
  -H "Authorization: Bearer sk-team-xxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${defaultModel.value}",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'`);

onMounted(async () => {
  const [configResponse, modelsResponse] = await Promise.all([
    meApi.config(),
    meApi.models(),
  ]);
  baseUrl.value = configResponse.data.base_url;
  models.value = modelsResponse.data.filter((item: any) => item.status === "enabled");
  const savedModel = localStorage.getItem("preferred_model");
  selectedModel.value = models.value.some((item: any) => item.id === savedModel)
    ? String(savedModel)
    : models.value[0]?.id || "";
});

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

function saveSelectedModel(value: string) {
  localStorage.setItem("preferred_model", value);
}

const tools = [
  {
    name: "Cursor",
    steps: [
      "打开 Cursor Settings，进入 Models 或 Provider 配置。",
      "选择 OpenAI Compatible 或 Override OpenAI Base URL。",
      "填写下方 Base URL、个人 API Key 和模型名。",
    ],
  },
  {
    name: "Trae",
    steps: [
      "进入 AI 模型或自定义模型设置。",
      "Provider 选择 OpenAI Compatible。",
      "填写 Base URL、个人 API Key，并添加下方选择的模型名。",
    ],
  },
  {
    name: "Qoder",
    steps: [
      "进入模型服务配置，添加自定义 OpenAI Compatible 服务。",
      "填写网关 Base URL 和个人 API Key。",
      "选择或手动填写下方选择的模型名。",
    ],
  },
];
</script>

<template>
  <div>
    <div class="page-heading"><div><h1>接入指南</h1><p>Cursor、Trae、Qoder 统一使用 OpenAI Compatible 配置。</p></div></div>
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <strong>统一配置</strong>
          <el-button link @click="copy(baseUrl)">复制 Base URL</el-button>
        </div>
      </template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="Provider"><code>OpenAI Compatible</code></el-descriptions-item>
        <el-descriptions-item label="Base URL"><code>{{ baseUrl }}</code></el-descriptions-item>
        <el-descriptions-item label="API Key"><code>工作台生成的个人 Key</code></el-descriptions-item>
        <el-descriptions-item label="Model">
          <el-select
            v-model="selectedModel"
            class="model-select"
            @change="saveSelectedModel"
          >
            <el-option
              v-for="model in models"
              :key="model.id"
              :label="model.display_name || model.id"
              :value="model.id"
            />
          </el-select>
          <code class="selected-model-code">{{ defaultModel }}</code>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header><strong>Coding 工具配置</strong></template>
      <el-tabs>
        <el-tab-pane v-for="tool in tools" :key="tool.name" :label="tool.name">
          <ol class="guide-steps">
            <li v-for="step in tool.steps" :key="step">{{ step }}</li>
          </ol>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <strong>Curl 示例</strong>
          <el-button link @click="copy(curl)">复制 Curl</el-button>
        </div>
      </template>
      <pre class="code-block">{{ curl }}</pre>
    </el-card>
    <el-alert class="section-card" type="info" :closable="false">
      Base URL 已包含 /v1，工具中不要重复填写 /v1/v1。
    </el-alert>
    <el-alert
      v-if="['deepseek-chat', 'deepseek-reasoner'].includes(defaultModel)"
      class="section-card"
      type="warning"
      :closable="false"
      title="当前选择的是 DeepSeek 兼容旧别名，建议改用 deepseek-v4-flash 或 deepseek-v4-pro。"
    />
  </div>
</template>

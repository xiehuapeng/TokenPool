<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { meApi } from "@/api";

const baseUrl = ref("http://localhost:8000/v1");
const curl = computed(() => `curl ${baseUrl.value}/chat/completions \\
  -H "Authorization: Bearer sk-team-xxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "deepseek-chat",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'`);

onMounted(async () => {
  baseUrl.value = (await meApi.config()).data.base_url;
});

async function copy(value: string) {
  await navigator.clipboard.writeText(value);
  ElMessage.success("已复制");
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
      "填写 Base URL、个人 API Key，并添加 deepseek-chat。",
    ],
  },
  {
    name: "Qoder",
    steps: [
      "进入模型服务配置，添加自定义 OpenAI Compatible 服务。",
      "填写网关 Base URL 和个人 API Key。",
      "选择或手动填写 deepseek-chat。",
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
        <el-descriptions-item label="Model"><code>deepseek-chat</code></el-descriptions-item>
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
  </div>
</template>

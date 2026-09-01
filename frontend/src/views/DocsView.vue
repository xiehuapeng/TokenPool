<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import "element-plus/es/components/message/style/css";
import { meApi } from "@/api";
import { errorMessage } from "@/api/http";
import { copyText } from "@/utils/clipboard";

const baseUrl = ref("http://localhost:8000/v1");
const gatewayModel = ref("team-coding");
const selectedModel = ref("");
const curl = computed(() => `curl ${baseUrl.value}/chat/completions \\
  -H "Authorization: Bearer sk-team-xxxx" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${gatewayModel.value}",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'`);

onMounted(async () => {
  try {
    const [configResponse, preferenceResponse] = await Promise.all([
      meApi.config(),
      meApi.modelPreference(),
    ]);
    baseUrl.value = configResponse.data.base_url;
    gatewayModel.value = preferenceResponse.data.gateway_model;
    selectedModel.value = preferenceResponse.data.selected_model || "暂未选择";
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
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

const tools = [
  {
    name: "Trae",
    link: "https://www.trae.cn/work",
    linkText: "下载 Trae（TRAE Work 桌面端）",
    steps: [
      "打开设置：进入 TRAE Work 的「设置 → 模型」页面。",
      "添加模型：点击「添加模型」，API 格式选择「OpenAI Chat Completions 格式」。",
      "填写参数：请求地址填上方 Base URL，模型 ID 填 team-coding，API 密钥填工作台生成的个人 Key。",
      "保存测试：点击「添加模型」保存，选择 team-coding 发送一条短消息验证连接。",
      "切换模型：回到工作台选择需要使用的真实模型，下一次调用生效。",
    ],
  },
  {
    name: "WorkBuddy",
    link: "https://www.workbuddy.cn/events/invite?inviteCode=nr0vcytear025",
    linkText: "获取 WorkBuddy",
    steps: [
      "打开设置：进入 WorkBuddy 的「设置 → 模型」页面。",
      "添加模型：点击「添加模型」，按上方统一配置填写自定义模型（OpenAI Compatible）参数。",
      "保存使用：保存后选择 team-coding 即可开始对话。",
      "切换模型：真实模型在工作台选择，下一次调用生效。",
    ],
  },
];
</script>

<template>
  <div>
    <div class="page-heading"><div><h1>接入指南</h1><p>Trae、WorkBuddy 统一使用 OpenAI Compatible 配置。</p></div></div>
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
          <code class="selected-model-code">{{ gatewayModel }}</code>
          <span class="muted">当前实际路由：{{ selectedModel }}</span>
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
          <el-link :href="tool.link" target="_blank" type="primary" class="tool-link">{{ tool.linkText }}</el-link>
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
      class="section-card"
      type="success"
      :closable="false"
      title="Trae、WorkBuddy 只需配置一次 team-coding；以后在工作台切换真实模型即可。"
    />
  </div>
</template>

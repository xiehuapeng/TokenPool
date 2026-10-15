<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import "element-plus/es/components/message/style/css";
import { meApi } from "@/api";
import { errorMessage } from "@/api/http";
import { copyText } from "@/utils/clipboard";
import { chatCompletionsUrl } from "@/utils/requestUrls";

const baseUrl = ref("");
const fullRequestUrl = computed(() => chatCompletionsUrl(baseUrl.value));
const gatewayModel = ref("team-coding");
const selectedModel = ref("");
const curl = computed(() => `curl ${fullRequestUrl.value} \\
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
    images: [],
    steps: [
      "打开设置：进入 TRAE Work 的「设置 → 模型」页面。",
      "添加模型：点击「添加模型」，API 格式选择「OpenAI Chat Completions 格式」。",
      "填写地址：开启「完整 URL」时，复制上方完整 URL（以 /v1/chat/completions 结尾）；关闭时，复制 Base URL（以 /v1 结尾），由 TRAE 拼接路径。",
      "填写其余参数：模型 ID 填 team-coding，API 密钥填工作台生成的个人 Key。",
      "保存测试：点击「添加模型」保存，选择 team-coding 发送一条短消息验证连接。",
      "切换模型：回到工作台选择需要使用的真实模型，下一次调用生效。",
    ],
  },
  {
    name: "WorkBuddy",
    link: "https://www.workbuddy.cn/events/invite?inviteCode=nr0vcytear025",
    linkText: "获取 WorkBuddy",
    images: [],
    steps: [
      "打开设置：进入 WorkBuddy 的「设置 → 模型」页面。",
      "添加模型：点击「添加模型」，按上方统一配置填写自定义模型（OpenAI Compatible）参数。",
      "保存使用：保存后选择 team-coding 即可开始对话。",
      "切换模型：真实模型在工作台选择，下一次调用生效。",
    ],
  },
  {
    name: "MobileWork",
    link: "",
    linkText: "",
    steps: [
      "打开 MobileWork 的「设置 → 模型」，在「本地配置文件」中点击「添加模型」。",
      "提供商选择「自定义」；接口地址填写上方 Base URL（以 /v1 结尾），不要填写完整的 /v1/chat/completions 地址。",
      "鉴权方式选择「Bearer Token（MoMA / OpenAI 兼容）」；在「Bearer Token（API KEY）」中填入本网站工作台生成的个人 Key，不要填写登录密码或上游厂商 Key。",
      "模型名称填写 team-coding。需要处理图片时可勾选「图片输入」；输入、输出上限没有明确要求时保留默认值。MAF 防护按组织要求设置，不必为接入中转站特意关闭。",
      "点击「保存」，确认「已保存模型」中出现并启用「自定义 · team-coding」。回到会话选择该模型，发送一条不含敏感信息的短消息，确认得到回复。",
      "到本网站「用量统计」核对请求数和实际模型；以后在工作台切换真实模型，下一次 team-coding 调用生效。",
    ],
    images: [
      {
        src: "/guides/mobilework-model-settings.png",
        alt: "MobileWork 设置页面中的模型入口、添加模型按钮与已启用的 team-coding",
        caption: "设置 → 模型：点击添加模型；保存后在已保存模型中确认启用。点击图片可查看原图。",
      },
      {
        src: "/guides/mobilework-custom-model-form.png",
        alt: "MobileWork 自定义模型配置示例，展示接口地址、鉴权方式和模型名称",
        caption: "字段示例：截图来自修改模型界面；接口地址以本页当前 Base URL 为准，密钥使用自己的个人 Key。点击图片可查看原图。",
      },
    ],
  },
];
</script>

<template>
  <div>
    <div class="page-heading"><div><h1>接入指南</h1><p>Trae、WorkBuddy、MobileWork 统一使用 OpenAI Compatible 配置。</p></div></div>
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <strong>统一配置</strong>
          <el-button link :disabled="!baseUrl" @click="copy(baseUrl)">复制 Base URL</el-button>
        </div>
      </template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="Provider"><code>OpenAI Compatible</code></el-descriptions-item>
        <el-descriptions-item label="Base URL（关闭完整 URL）"><code>{{ baseUrl || '加载中' }}</code></el-descriptions-item>
        <el-descriptions-item label="完整 URL（开启完整 URL）">
          <code>{{ fullRequestUrl || '加载中' }}</code>
          <el-button link :disabled="!fullRequestUrl" @click="copy(fullRequestUrl)">复制完整 URL</el-button>
        </el-descriptions-item>
        <el-descriptions-item label="API Key"><code>工作台生成的个人 Key</code></el-descriptions-item>
        <el-descriptions-item label="Model">
          <code class="selected-model-code">{{ gatewayModel }}</code>
          <span class="muted">当前实际路由：{{ selectedModel }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header><strong>客户端接入配置</strong></template>
      <el-tabs>
        <el-tab-pane v-for="tool in tools" :key="tool.name" :label="tool.name">
          <ol class="guide-steps">
            <li v-for="step in tool.steps" :key="step">{{ step }}</li>
          </ol>
          <el-link v-if="tool.link" :href="tool.link" target="_blank" type="primary" class="tool-link">{{ tool.linkText }}</el-link>
          <div v-if="tool.images.length" class="guide-screenshots">
            <figure v-for="image in tool.images" :key="image.src" class="guide-screenshot">
              <a :href="image.src" target="_blank" rel="noopener noreferrer">
                <img :src="image.src" :alt="image.alt" loading="lazy" />
              </a>
              <figcaption>{{ image.caption }}</figcaption>
            </figure>
          </div>
          <p v-if="tool.name === 'MobileWork'" class="guide-note">
            截图仅用于辨认设置项；若本页显示的是 HTTP 地址，Bearer Token 会随请求传输，请仅在可信网络或获准的安全通道中使用。
          </p>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <strong>Curl 示例</strong>
          <el-button link :disabled="!fullRequestUrl" @click="copy(curl)">复制 Curl</el-button>
        </div>
      </template>
      <pre class="code-block">{{ curl }}</pre>
    </el-card>
    <el-alert class="section-card" type="info" :closable="false">
      TRAE 开启「完整 URL」后不会拼接路径，仅填 /v1 会返回 404。关闭时使用 Base URL，避免重复填写 /v1/v1。
    </el-alert>
    <el-alert
      class="section-card"
      type="success"
      :closable="false"
      title="Trae、WorkBuddy、MobileWork 只需配置一次 team-coding；以后在工作台切换真实模型即可。"
    />
    <el-alert class="section-card" type="info" :closable="false">
      team-coding 可在图片请求中自动选择有权限的视觉模型。显式填写真实模型 ID 时，
      若该模型不支持图片，将返回 400 提示；历史消息中的图片也会触发检查。
      此时请选择视觉模型，或新建纯文本会话。管理后台调用日志可查看实际模型及切换原因。
    </el-alert>
  </div>
</template>

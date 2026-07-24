<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { meApi, type ApiKeyItem } from "@/api";
import { errorMessage } from "@/api/http";
import { copyText } from "@/utils/clipboard";

const baseUrl = ref("");
const keys = ref<ApiKeyItem[]>([]);
const loading = ref(true);
const generatedKey = ref("");
const keyDialogVisible = ref(false);
const models = ref<any[]>([]);
const activeModels = computed(() =>
  models.value.filter((item) => item.status === "enabled"),
);
const defaultModel = computed(() => activeModels.value[0]?.id || "deepseek-chat");
const curlExample = computed(() => `curl ${baseUrl.value}/chat/completions \\
  -H "Authorization: Bearer ${generatedKey.value || "sk-team-your-key"}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${defaultModel.value}",
    "messages": [{"role": "user", "content": "你好"}]
  }'`);

async function load() {
  loading.value = true;
  try {
    const [config, keyList, modelList] = await Promise.all([
      meApi.config(),
      meApi.keys(),
      meApi.models(),
    ]);
    baseUrl.value = config.data.base_url;
    keys.value = keyList.data;
    models.value = modelList.data;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    loading.value = false;
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
    keyDialogVisible.value = true;
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") ElMessage.error(errorMessage(error));
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
              <strong>当前支持模型</strong>
              <el-button link @click="copy(defaultModel)">复制默认模型</el-button>
            </div>
          </template>
          <div class="model-pills">
            <el-tag
              v-for="model in activeModels"
              :key="model.id"
              size="large"
              effect="plain"
            >
              {{ model.id }}
            </el-tag>
            <el-empty
              v-if="!activeModels.length"
              description="暂无可用模型"
              :image-size="42"
            />
          </div>
          <p class="muted compact">
            Provider 选择 OpenAI Compatible，模型名称必须与此处完全一致。
          </p>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-header"><strong>我的 API Keys</strong><span>完整 Key 仅生成时展示</span></div>
      </template>
      <el-table :data="keys" empty-text="尚未生成 API Key">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="key_prefix" label="Key 前缀" min-width="190" />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column prop="last_used_at" label="最后使用" min-width="180">
          <template #default="{ row }">{{ row.last_used_at || "从未使用" }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
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
        出于安全考虑，已关闭页面的完整 API Key 无法再次读取；遗失后请吊销并重新生成。
      </p>
    </el-card>

    <el-dialog
      v-model="keyDialogVisible"
      title="API Key 已生成"
      width="620px"
      :close-on-click-modal="false"
      @closed="generatedKey = ''"
    >
      <el-alert type="warning" :closable="false">这是唯一一次显示完整 Key，请立即复制并妥善保存。</el-alert>
      <div class="secret-value"><code>{{ generatedKey }}</code></div>
      <template #footer>
        <el-button type="primary" @click="copy(generatedKey)">复制 API Key</el-button>
        <el-button @click="copy(curlExample)">复制含此 Key 的 Curl</el-button>
        <el-button @click="keyDialogVisible = false">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

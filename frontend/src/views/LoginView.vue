<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { authApi } from "@/api";
import { errorMessage } from "@/api/http";

const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "" });
const apiConfigured =
  Boolean(import.meta.env.VITE_API_URL) ||
  !window.location.hostname.endsWith("github.io");

async function submit() {
  loading.value = true;
  try {
    const { data } = await authApi.login(form.username, form.password);
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("user", JSON.stringify(data.user));
    router.push("/");
  } catch (error) {
    ElMessage.error(errorMessage(error));
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-intro">
      <div class="brand-mark large">AI</div>
      <h1>团队统一模型入口</h1>
      <p>一个 API Key，连接团队可用的 Coding 模型。</p>
      <div class="signal-line"><span /> Secure · Observable · Compatible</div>
    </section>
    <el-card class="login-card" shadow="never">
      <h2>登录 Gateway</h2>
      <p class="muted">使用管理员分配的团队账号</p>
      <el-alert
        v-if="!apiConfigured"
        class="pages-notice"
        type="warning"
        :closable="false"
        title="GitHub Pages 已发布，但尚未配置公网后端地址。"
      />
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" size="large" autofocus />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            show-password
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="full-width"
          :loading="loading"
          :disabled="!apiConfigured"
          @click="submit"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { authApi } from "@/api";
import { errorMessage } from "@/api/http";

const router = useRouter();
const loading = ref(false);
const mode = ref<"login" | "register">("login");
const form = reactive({
  username: "",
  password: "",
  confirmPassword: "",
  inviteCode: "",
});
const apiConfigured =
  Boolean(import.meta.env.VITE_API_URL) ||
  !window.location.hostname.endsWith("github.io");

async function submit() {
  if (!apiConfigured) return;
  const username = form.username.trim();
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$/.test(username)) {
    ElMessage.warning(
      "用户名需为 3–64 位，以字母或数字开头和结尾，中间可使用 . _ -",
    );
    return;
  }
  if (
    form.password.length < 8 ||
    form.password.length > 64 ||
    !/[A-Za-z]/.test(form.password) ||
    !/\d/.test(form.password)
  ) {
    ElMessage.warning("密码需为 8–64 位，并且至少包含一个字母和一个数字");
    return;
  }
  if (mode.value === "register" && form.password !== form.confirmPassword) {
    ElMessage.warning("两次输入的密码不一致");
    return;
  }
  if (
    mode.value === "register" &&
    !/^[a-zA-Z0-9_-]{8,64}$/.test(form.inviteCode.trim())
  ) {
    ElMessage.warning("请输入管理员提供的有效邀请码");
    return;
  }
  loading.value = true;
  try {
    const { data } =
      mode.value === "register"
        ? await authApi.register(
            username,
            form.password,
            form.inviteCode.trim(),
          )
        : await authApi.login(username, form.password);
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("user", JSON.stringify(data.user));
    if (mode.value === "register") ElMessage.success("注册成功");
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
      <el-tabs v-model="mode" stretch>
        <el-tab-pane label="登录" name="login" />
        <el-tab-pane label="注册" name="register" />
      </el-tabs>
      <h2>{{ mode === "login" ? "登录 Gateway" : "创建团队账号" }}</h2>
      <p class="muted">
        {{
          mode === "login"
            ? "登录后管理个人 API Key"
            : "需要管理员提供的邀请码"
        }}
      </p>
      <el-alert
        v-if="!apiConfigured"
        class="pages-notice"
        type="warning"
        :closable="false"
        title="当前静态页面尚未配置可访问的后端地址"
      />
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input
            v-model="form.username"
            size="large"
            autofocus
            placeholder="3–64 位，字母/数字开头和结尾"
          />
          <div v-if="mode === 'register'" class="form-tip">
            支持字母、数字、点、下划线和短横线；用户名不区分大小写且不能重名
          </div>
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            show-password
            placeholder="8–64 位，至少包含字母和数字"
            @keyup.enter="mode === 'login' && submit()"
          />
          <div v-if="mode === 'register'" class="form-tip">
            可使用特殊符号；请勿与其他网站使用相同密码
          </div>
        </el-form-item>
        <el-form-item v-if="mode === 'register'" label="确认密码">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            size="large"
            show-password
          />
        </el-form-item>
        <el-form-item v-if="mode === 'register'" label="邀请码">
          <el-input
            v-model="form.inviteCode"
            size="large"
            placeholder="请向管理员获取"
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
          {{ mode === "login" ? "登录" : "注册并登录" }}
        </el-button>
      </el-form>
    </el-card>
  </main>
</template>

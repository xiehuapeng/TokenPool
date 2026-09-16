<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import "element-plus/es/components/message/style/css";
import { authApi } from "@/api";
import { errorMessage } from "@/api/http";
import { preloadDashboardWhenIdle } from "@/router/viewLoaders";
import { validateCredentials, validateInviteCode } from "@/utils/authValidation";

const router = useRouter();
const loading = ref(false);
const mode = ref<"login" | "register" | "reset">("login");
const form = reactive({
  username: "",
  password: "",
  confirmPassword: "",
  inviteCode: "",
});
const apiConfigured =
  Boolean(import.meta.env.VITE_API_URL) ||
  !window.location.hostname.endsWith("github.io");

// Register and reset share the same credential rules and both require an
// invite code, so derive the variants once instead of nesting ternaries.
const isLogin = computed(() => mode.value === "login");
const needsInvite = computed(() => mode.value !== "login");
const heading = computed(() => {
  if (mode.value === "login") return "登录 Gateway";
  return mode.value === "register" ? "创建团队账号" : "重置密码";
});
const subheading = computed(() => {
  if (mode.value === "login") return "登录后管理个人 API Key";
  return mode.value === "register"
    ? "需要管理员提供的邀请码"
    : "使用管理员提供的邀请码设置新密码";
});
const submitLabel = computed(() => {
  if (mode.value === "login") return "登录";
  return mode.value === "register" ? "注册并登录" : "重置并登录";
});

onMounted(preloadDashboardWhenIdle);

async function submit() {
  if (!apiConfigured || loading.value) return;
  const username = form.username.trim();
  const validationError = validateCredentials(mode.value, username, form.password);
  if (validationError) {
    ElMessage.warning(validationError);
    return;
  }
  if (needsInvite.value && form.password !== form.confirmPassword) {
    ElMessage.warning("两次输入的密码不一致");
    return;
  }
  if (needsInvite.value) {
    const inviteError = validateInviteCode(form.inviteCode);
    if (inviteError) {
      ElMessage.warning(inviteError);
      return;
    }
  }
  loading.value = true;
  try {
    const { data } = isLogin.value
      ? await authApi.login(username, form.password)
      : mode.value === "register"
        ? await authApi.register(username, form.password, form.inviteCode.trim())
        : await authApi.resetPassword(
            username,
            form.password,
            form.inviteCode.trim(),
          );
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("user", JSON.stringify(data.user));
    if (mode.value === "register") ElMessage.success("注册成功");
    if (mode.value === "reset") ElMessage.success("密码已重置");
    await router.push("/");
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
        <el-tab-pane label="重置密码" name="reset" />
      </el-tabs>
      <h2>{{ heading }}</h2>
      <p class="muted">{{ subheading }}</p>
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
            :placeholder="isLogin ? '请输入用户名' : '3–64 位，字母/数字开头和结尾'"
          />
          <div v-if="needsInvite" class="form-tip">
            支持字母、数字、点、下划线和短横线；用户名不区分大小写且不能重名
          </div>
        </el-form-item>
        <el-form-item :label="mode === 'reset' ? '新密码' : '密码'">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            show-password
            :placeholder="isLogin ? '请输入密码' : '8–64 位，至少包含字母和数字'"
            @keyup.enter="isLogin && submit()"
          />
          <div v-if="needsInvite" class="form-tip">
            可使用特殊符号；请勿与其他网站使用相同密码
          </div>
        </el-form-item>
        <el-form-item v-if="needsInvite" label="确认密码">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            size="large"
            show-password
          />
        </el-form-item>
        <el-form-item v-if="needsInvite" label="邀请码">
          <el-input
            v-model="form.inviteCode"
            size="large"
            placeholder="请向管理员获取"
            @keyup.enter="submit"
          />
          <div v-if="mode === 'reset'" class="form-tip">
            重置密码不会消耗邀请码的使用次数
          </div>
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="full-width"
          :loading="loading"
          :disabled="!apiConfigured"
          @click="submit"
        >
          {{ submitLabel }}
        </el-button>
      </el-form>
    </el-card>
  </main>
</template>

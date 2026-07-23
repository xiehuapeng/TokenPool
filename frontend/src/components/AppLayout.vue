<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const user = computed(() => JSON.parse(localStorage.getItem("user") || "null"));

function logout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("user");
  router.push("/login");
}
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <span class="brand-mark">AI</span>
        <div>
          <strong>Team Gateway</strong>
          <small>AI Coding Platform</small>
        </div>
      </div>
      <el-menu
        router
        :default-active="route.path"
        background-color="transparent"
        text-color="#aeb9ce"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/">工作台</el-menu-item>
        <el-menu-item index="/docs">接入指南</el-menu-item>
        <el-menu-item index="/models">模型列表</el-menu-item>
        <el-menu-item index="/usage">用量统计</el-menu-item>
        <el-menu-item v-if="user?.is_admin" index="/admin">管理后台</el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <div>
          <strong>{{ user?.username }}</strong>
          <small>{{ user?.is_admin ? "管理员" : "团队成员" }}</small>
        </div>
        <el-button link @click="logout">退出</el-button>
      </div>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <span>{{ route.meta.title || "内部 AI Coding Gateway" }}</span>
        <el-tag effect="plain" type="success">Internal</el-tag>
      </el-header>
      <el-main class="content"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

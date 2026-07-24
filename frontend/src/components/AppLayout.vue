<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();
const mobileMenuVisible = ref(false);
const user = computed(() => JSON.parse(localStorage.getItem("user") || "null"));

const menuItems = computed(() => [
  { index: "/", label: "工作台" },
  { index: "/docs", label: "接入指南" },
  { index: "/models", label: "模型列表" },
  { index: "/usage", label: "用量统计" },
  ...(user.value?.is_admin
    ? [{ index: "/admin", label: "管理后台" }]
    : []),
]);

function logout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("user");
  mobileMenuVisible.value = false;
  router.push("/login");
}
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="232px" class="sidebar desktop-sidebar">
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
        <el-menu-item
          v-for="item in menuItems"
          :key="item.index"
          :index="item.index"
        >
          {{ item.label }}
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <div>
          <strong>{{ user?.username }}</strong>
          <small>{{ user?.is_admin ? "管理员" : "团队成员" }}</small>
        </div>
        <el-button link @click="logout">退出</el-button>
      </div>
    </el-aside>

    <el-container class="main-shell">
      <el-header class="topbar">
        <div class="topbar-title">
          <el-button
            class="mobile-menu-button"
            text
            aria-label="打开导航菜单"
            @click="mobileMenuVisible = true"
          >
            <span class="hamburger">☰</span>
          </el-button>
          <span>{{ route.meta.title || "内部 AI Coding Gateway" }}</span>
        </div>
        <el-tag effect="plain" type="success">Internal</el-tag>
      </el-header>
      <el-main class="content"><router-view /></el-main>
    </el-container>

    <el-drawer
      v-model="mobileMenuVisible"
      direction="ltr"
      size="82%"
      :with-header="false"
      class="mobile-drawer"
    >
      <div class="mobile-sidebar-content">
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
          @select="mobileMenuVisible = false"
        >
          <el-menu-item
            v-for="item in menuItems"
            :key="item.index"
            :index="item.index"
          >
            {{ item.label }}
          </el-menu-item>
        </el-menu>
        <div class="sidebar-footer">
          <div>
            <strong>{{ user?.username }}</strong>
            <small>{{ user?.is_admin ? "管理员" : "团队成员" }}</small>
          </div>
          <el-button link @click="logout">退出</el-button>
        </div>
      </div>
    </el-drawer>
  </el-container>
</template>

import { createRouter, createWebHashHistory } from "vue-router";
import LoginView from "@/views/LoginView.vue";
import AppLayout from "@/components/AppLayout.vue";
import DashboardView from "@/views/DashboardView.vue";
import DocsView from "@/views/DocsView.vue";
import ModelsView from "@/views/ModelsView.vue";
import UsageView from "@/views/UsageView.vue";
import AdminView from "@/views/AdminView.vue";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: LoginView, meta: { public: true } },
    {
      path: "/",
      component: AppLayout,
      children: [
        { path: "", component: DashboardView },
        { path: "docs", component: DocsView },
        { path: "models", component: ModelsView },
        { path: "usage", component: UsageView },
        { path: "admin", component: AdminView, meta: { admin: true } },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const token = localStorage.getItem("access_token");
  const user = JSON.parse(localStorage.getItem("user") || "null");
  if (!to.meta.public && !token) return "/login";
  if (to.meta.admin && !user?.is_admin) return "/";
  if (to.path === "/login" && token) return "/";
});

export default router;

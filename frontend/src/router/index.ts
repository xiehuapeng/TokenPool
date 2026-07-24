import { createRouter, createWebHashHistory } from "vue-router";
import {
  loadAdminView,
  loadAppLayout,
  loadDashboardView,
  loadDocsView,
  loadLoginView,
  loadModelsView,
  loadUsageView,
} from "./viewLoaders";

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/login", component: loadLoginView, meta: { public: true } },
    {
      path: "/",
      component: loadAppLayout,
      children: [
        { path: "", component: loadDashboardView },
        { path: "docs", component: loadDocsView },
        { path: "models", component: loadModelsView },
        { path: "usage", component: loadUsageView },
        { path: "admin", component: loadAdminView, meta: { admin: true } },
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

import type { Component } from "vue";

type ViewLoader = () => Promise<{ default: Component }>;

export const loadLoginView: ViewLoader = () => import("@/views/LoginView.vue");
export const loadAppLayout: ViewLoader = () =>
  import("@/components/AppLayout.vue");
export const loadDashboardView: ViewLoader = () =>
  import("@/views/DashboardView.vue");
export const loadDocsView: ViewLoader = () => import("@/views/DocsView.vue");
export const loadModelsView: ViewLoader = () =>
  import("@/views/ModelsView.vue");
export const loadUsageView: ViewLoader = () => import("@/views/UsageView.vue");
export const loadAdminView: ViewLoader = () => import("@/views/AdminView.vue");

function whenBrowserIsIdle(task: () => void, timeout = 1500) {
  const browserWindow = window as Window & {
    requestIdleCallback?: (
      callback: () => void,
      options?: { timeout: number },
    ) => number;
  };
  if (browserWindow.requestIdleCallback) {
    browserWindow.requestIdleCallback(task, { timeout });
    return;
  }
  window.setTimeout(task, Math.min(timeout, 500));
}

export function preloadDashboardWhenIdle() {
  whenBrowserIsIdle(() => {
    void Promise.allSettled([loadAppLayout(), loadDashboardView()]);
  }, 800);
}

export function preloadAuthenticatedViewsWhenIdle(isAdmin: boolean) {
  whenBrowserIsIdle(() => {
    const loaders = [loadDocsView(), loadModelsView(), loadUsageView()];
    if (isAdmin) loaders.push(loadAdminView());
    void Promise.allSettled(loaders);
  }, 1800);
}

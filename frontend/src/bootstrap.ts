import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import "./styles.css";

export async function mountApplication() {
  const [{ default: ElementPlus }] = await Promise.all([
    import("element-plus"),
    import("element-plus/dist/index.css"),
  ]);
  createApp(App).use(router).use(ElementPlus).mount("#app");
}

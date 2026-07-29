import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [
      vue(),
      Components({
        resolvers: [ElementPlusResolver()],
        dts: "src/components.d.ts",
      }),
    ],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(moduleId) {
            const id = moduleId.replace(/\\/g, "/");
            if (!id.includes("/node_modules/")) return undefined;
            if (
              id.includes("/vue/") ||
              id.includes("/@vue/") ||
              id.includes("/vue-router/")
            ) {
              return "vue-core";
            }
            if (id.includes("/axios/")) return "http-client";
            if (
              id.includes("/element-plus/") ||
              id.includes("/@element-plus/") ||
              id.includes("/@vueuse/") ||
              id.includes("/async-validator/") ||
              id.includes("/dayjs/") ||
              id.includes("/lodash-") ||
              id.includes("/memoize-one/") ||
              id.includes("/normalize-wheel-es/") ||
              id.includes("/escape-html/") ||
              id.includes("/@ctrl/tinycolor/")
            ) {
              return undefined;
            }
            return "vendor";
          },
        },
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": "http://localhost:8000",
        "/v1": "http://localhost:8000",
        "/health": "http://localhost:8000",
      },
    },
  };
});

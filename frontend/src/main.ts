const retryKey = "tokenpool_bootstrap_retry";

async function startApplication() {
  try {
    const { mountApplication } = await import("./bootstrap");
    await mountApplication();
    sessionStorage.removeItem(retryKey);
  } catch (error) {
    console.error("Frontend bootstrap failed", error);
    if (!sessionStorage.getItem(retryKey)) {
      sessionStorage.setItem(retryKey, "1");
      window.setTimeout(() => window.location.reload(), 800);
      return;
    }
    const root = document.querySelector<HTMLDivElement>("#app");
    if (root) {
      root.innerHTML =
        '<main style="max-width:520px;margin:15vh auto;padding:24px;font-family:sans-serif">' +
        "<h2>页面资源加载失败</h2>" +
        "<p>网络连接可能暂时不稳定，请稍后刷新页面。</p>" +
        '<button onclick="location.reload()" style="padding:10px 18px">重新加载</button>' +
        "</main>";
    }
  }
}

void startApplication();

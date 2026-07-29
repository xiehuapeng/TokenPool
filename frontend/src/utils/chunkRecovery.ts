const retryStorageKey = "tokenpool_chunk_reload";
const retryWindowMs = 2 * 60 * 1000;
const errorPanelId = "tokenpool-chunk-error";

interface ChunkRetryState {
  path: string;
  attemptedAt: number;
}

function errorText(error: unknown): string {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return String(error ?? "");
}

export function isChunkLoadError(error: unknown): boolean {
  const message = errorText(error).toLowerCase();
  return [
    "failed to fetch dynamically imported module",
    "error loading dynamically imported module",
    "importing a module script failed",
    "failed to load module script",
    "chunkloaderror",
    "loading chunk",
    "load failed",
  ].some((pattern) => message.includes(pattern));
}

function readRetryState(): ChunkRetryState | null {
  try {
    const value = sessionStorage.getItem(retryStorageKey);
    if (!value) return null;
    const state = JSON.parse(value) as Partial<ChunkRetryState>;
    if (typeof state.path !== "string" || typeof state.attemptedAt !== "number") {
      return null;
    }
    return { path: state.path, attemptedAt: state.attemptedAt };
  } catch {
    return null;
  }
}

function writeRetryState(path: string) {
  sessionStorage.setItem(
    retryStorageKey,
    JSON.stringify({ path, attemptedAt: Date.now() }),
  );
}

function showRecoveryPanel() {
  if (document.getElementById(errorPanelId)) return;

  const overlay = document.createElement("div");
  overlay.id = errorPanelId;
  overlay.setAttribute("role", "alert");
  overlay.style.cssText =
    "position:fixed;inset:0;z-index:10000;display:grid;place-items:center;" +
    "padding:24px;background:rgba(15,23,42,.72);font-family:system-ui,sans-serif";

  const panel = document.createElement("section");
  panel.style.cssText =
    "width:min(460px,100%);padding:28px;border-radius:16px;background:#fff;" +
    "box-shadow:0 24px 80px rgba(15,23,42,.28);color:#172033";

  const title = document.createElement("h2");
  title.textContent = "页面模块加载失败";
  title.style.cssText = "margin:0 0 12px;font-size:22px";

  const description = document.createElement("p");
  description.textContent =
    "网络连接可能暂时不稳定。系统已经自动重试过一次，请检查网络后重新加载。";
  description.style.cssText =
    "margin:0 0 22px;color:#667085;line-height:1.7";

  const retryButton = document.createElement("button");
  retryButton.type = "button";
  retryButton.textContent = "重新加载";
  retryButton.style.cssText =
    "border:0;border-radius:8px;padding:11px 20px;background:#3157d5;" +
    "color:#fff;font-size:15px;font-weight:600;cursor:pointer";
  retryButton.addEventListener("click", () => {
    sessionStorage.removeItem(retryStorageKey);
    window.location.reload();
  });

  panel.append(title, description, retryButton);
  overlay.append(panel);
  document.body.append(overlay);
  retryButton.focus();
}

export function recoverChunkLoad(error: unknown, targetPath: string): boolean {
  if (!isChunkLoadError(error)) return false;

  console.error("Page module load failed", {
    targetPath,
    error: errorText(error),
  });

  const state = readRetryState();
  const retryIsRecent =
    state?.path === targetPath && Date.now() - state.attemptedAt < retryWindowMs;

  if (!retryIsRecent) {
    writeRetryState(targetPath);
    window.location.reload();
    return true;
  }

  showRecoveryPanel();
  return true;
}

export function clearChunkLoadRetry(path: string) {
  const state = readRetryState();
  if (state?.path === path) sessionStorage.removeItem(retryStorageKey);
  document.getElementById(errorPanelId)?.remove();
}

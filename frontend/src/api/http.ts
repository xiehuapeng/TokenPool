import axios from "axios";

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "",
  timeout: 30000,
});

let redirectingToLogin = false;

function redirectToLogin() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("user");
  if (redirectingToLogin || window.location.hash === "#/login") return;

  redirectingToLogin = true;
  const loginUrl = new URL(import.meta.env.BASE_URL, window.location.origin);
  loginUrl.hash = "/login";
  window.location.replace(loginUrl.toString());
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes("/login")) {
      redirectToLogin();
    }
    return Promise.reject(error);
  },
);

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return (
      error.response?.data?.error?.message ||
      error.response?.data?.detail ||
      error.message
    );
  }
  return error instanceof Error ? error.message : "请求失败";
}

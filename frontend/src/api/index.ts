import { http } from "./http";

export interface CurrentUser {
  id: number;
  username: string;
  status: string;
  is_admin: boolean;
  created_at: string;
}

export interface ApiKeyItem {
  id: number;
  name: string;
  key_prefix: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post("/api/auth/login", { username, password }),
  me: () => http.get<CurrentUser>("/api/auth/me"),
};

export const meApi = {
  config: () => http.get<{ base_url: string }>("/api/me/config"),
  keys: () => http.get<ApiKeyItem[]>("/api/me/api-keys"),
  createKey: (name: string) => http.post("/api/me/api-keys", { name }),
  revokeKey: (id: number) => http.delete(`/api/me/api-keys/${id}`),
  models: () => http.get("/api/me/models"),
  usage: () => http.get("/api/me/usage/summary"),
};

export const adminApi = {
  users: () => http.get("/api/admin/users"),
  createUser: (body: object) => http.post("/api/admin/users", body),
  setUserStatus: (id: number, status: string) =>
    http.patch(`/api/admin/users/${id}/status`, { status }),
  keys: () => http.get("/api/admin/api-keys"),
  setKeyStatus: (id: number, status: string) =>
    http.patch(`/api/admin/api-keys/${id}/status`, { status }),
  models: () => http.get("/api/admin/models"),
  updateModel: (id: number, body: object) =>
    http.patch(`/api/admin/models/${id}`, body),
  providers: () => http.get("/api/admin/providers"),
  stats: () => http.get("/api/admin/stats"),
  logs: () => http.get("/api/admin/usage-logs"),
};


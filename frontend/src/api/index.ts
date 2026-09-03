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
  can_reveal: boolean;
  preferred_model_id: number | null;
  preferred_model: string | null;
}

export interface ModelPreference {
  gateway_model: string;
  selected_model: string | null;
  selection_source: "user" | "default";
}

export interface AdminUsageFilters {
  days?: number;
  username?: string;
  model?: string;
  provider?: string;
  today?: boolean;
}

export interface AdminLogFilters extends AdminUsageFilters {
  limit?: number;
  offset?: number;
  request_id?: string;
  status?: string;
  today?: boolean;
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post("/api/auth/login", { username, password }),
  register: (username: string, password: string, inviteCode: string) =>
    http.post("/api/auth/register", {
      username,
      password,
      invite_code: inviteCode,
    }),
  me: () => http.get<CurrentUser>("/api/auth/me"),
};

export const meApi = {
  config: () =>
    http.get<{ base_url: string; max_api_keys: number }>("/api/me/config"),
  keys: () => http.get<ApiKeyItem[]>("/api/me/api-keys"),
  createKey: (name: string) => http.post("/api/me/api-keys", { name }),
  revealKey: (id: number) =>
    http.get<{ value: string }>(`/api/me/api-keys/${id}/secret`),
  revokeKey: (id: number) => http.delete(`/api/me/api-keys/${id}`),
  updateKeyPreferredModel: (id: number, model: string | null) =>
    http.patch<ApiKeyItem>(`/api/me/api-keys/${id}/preferred-model`, {
      model,
    }),
  models: () => http.get("/api/me/models"),
  modelPreference: () =>
    http.get<ModelPreference>("/api/me/model-preference"),
  updateModelPreference: (model: string) =>
    http.put<ModelPreference>("/api/me/model-preference", { model }),
  usage: (params: { days?: number; today?: boolean; model?: string } = {}) =>
    http.get("/api/me/usage/summary", { params }),
};

export const adminApi = {
  users: () => http.get("/api/admin/users"),
  createUser: (body: object) => http.post("/api/admin/users", body),
  inviteCodes: () => http.get("/api/admin/invite-codes"),
  createInviteCode: (body: object) =>
    http.post("/api/admin/invite-codes", body),
  revealInviteCode: (id: number) =>
    http.get<{ value: string }>(`/api/admin/invite-codes/${id}/secret`),
  setInviteCodeStatus: (id: number, status: string) =>
    http.patch(`/api/admin/invite-codes/${id}/status`, { status }),
  deleteInviteCode: (id: number) =>
    http.delete(`/api/admin/invite-codes/${id}`),
  setUserStatus: (id: number, status: string) =>
    http.patch(`/api/admin/users/${id}/status`, { status }),
  keys: () => http.get("/api/admin/api-keys"),
  setKeyStatus: (id: number, status: string) =>
    http.patch(`/api/admin/api-keys/${id}/status`, { status }),
  models: () => http.get("/api/admin/models"),
  updateModel: (id: number, body: object) =>
    http.patch(`/api/admin/models/${id}`, body),
  updateModelPricing: (id: number, body: object) =>
    http.patch(`/api/admin/models/${id}/pricing`, body),
  providers: () => http.get("/api/admin/providers"),
  providerModels: (code: string) =>
    http.get(`/api/admin/providers/${code}/available-models`),
  syncProviderModels: (code: string, body: object) =>
    http.post(`/api/admin/providers/${code}/sync-models`, body),
  stats: (params: AdminUsageFilters = {}) =>
    http.get("/api/admin/stats", { params }),
  userUsage: (userId: number, params: { days?: number; today?: boolean }) =>
    http.get(`/api/admin/users/${userId}/usage`, { params }),
  logs: (params: AdminLogFilters = {}) =>
    http.get("/api/admin/usage-logs", { params }),
  backfillCosts: (dryRun = false) =>
    http.post("/api/admin/usage-logs/backfill-costs", null, {
      params: { dry_run: dryRun },
    }),
};

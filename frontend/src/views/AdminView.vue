<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { adminApi } from "@/api";
import { errorMessage } from "@/api/http";

const activeTab = ref("users");
const users = ref<any[]>([]);
const inviteCodes = ref<any[]>([]);
const keys = ref<any[]>([]);
const models = ref<any[]>([]);
const providers = ref<any[]>([]);
const stats = ref<any>({ by_user: [], by_model: [] });
const logs = ref<any[]>([]);
const totalLogs = ref(0);
const createUserVisible = ref(false);
const createInviteVisible = ref(false);
const userForm = reactive({ username: "", password: "", is_admin: false });
const inviteForm = reactive({
  label: "团队邀请码",
  code: "",
  max_uses: 20 as number | null,
  expires_at: "",
});

async function loadAll() {
  try {
    const [u, i, k, m, p, s, l] = await Promise.all([
      adminApi.users(),
      adminApi.inviteCodes(),
      adminApi.keys(),
      adminApi.models(),
      adminApi.providers(),
      adminApi.stats(),
      adminApi.logs(),
    ]);
    users.value = u.data;
    inviteCodes.value = i.data;
    keys.value = k.data;
    models.value = m.data;
    providers.value = p.data;
    stats.value = s.data;
    logs.value = l.data.items;
    totalLogs.value = l.data.total;
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function createUser() {
  if (
    !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}[a-zA-Z0-9]$/.test(
      userForm.username.trim(),
    )
  ) {
    ElMessage.warning("用户名格式不符合要求");
    return;
  }
  if (
    userForm.password.length < 8 ||
    userForm.password.length > 64 ||
    !/[A-Za-z]/.test(userForm.password) ||
    !/\d/.test(userForm.password)
  ) {
    ElMessage.warning("密码需为 8–64 位，并且至少包含一个字母和一个数字");
    return;
  }
  try {
    await adminApi.createUser({
      ...userForm,
      username: userForm.username.trim(),
    });
    createUserVisible.value = false;
    Object.assign(userForm, { username: "", password: "", is_admin: false });
    ElMessage.success("用户已创建");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function createInviteCode() {
  if (!/^[a-zA-Z0-9_-]{8,64}$/.test(inviteForm.code.trim())) {
    ElMessage.warning("邀请码需为 8–64 位，仅支持字母、数字、下划线和短横线");
    return;
  }
  try {
    await adminApi.createInviteCode({
      label: inviteForm.label.trim(),
      code: inviteForm.code.trim(),
      max_uses: inviteForm.max_uses || null,
      expires_at: inviteForm.expires_at
        ? new Date(inviteForm.expires_at).toISOString()
        : null,
    });
    createInviteVisible.value = false;
    Object.assign(inviteForm, {
      label: "团队邀请码",
      code: "",
      max_uses: 20,
      expires_at: "",
    });
    ElMessage.success("邀请码已创建，请将刚才设置的完整邀请码提供给团队成员");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function toggleInviteCode(row: any) {
  const next = row.status === "active" ? "disabled" : "active";
  await adminApi.setInviteCodeStatus(row.id, next);
  ElMessage.success(next === "active" ? "邀请码已启用" : "邀请码已停用");
  await loadAll();
}

async function toggleUser(row: any) {
  const next = row.status === "active" ? "disabled" : "active";
  await ElMessageBox.confirm(
    `确定将用户 ${row.username} 设为 ${next}？`,
    "用户状态",
  );
  await adminApi.setUserStatus(row.id, next);
  await loadAll();
}

async function revokeKey(row: any) {
  await ElMessageBox.confirm(
    `确定吊销 ${row.username} 的这个 API Key？`,
    "API Key",
  );
  await adminApi.setKeyStatus(row.id, "revoked");
  await loadAll();
}

async function setModelEnabled(row: any, enabled: boolean) {
  try {
    await adminApi.updateModel(row.id, { enabled });
    ElMessage.success("模型状态已更新");
  } catch (error) {
    row.enabled = !enabled;
    ElMessage.error(errorMessage(error));
  }
}

onMounted(loadAll);
</script>

<template>
  <div>
    <div class="page-heading">
      <div>
        <h1>管理后台</h1>
        <p>管理团队访问、邀请码、模型配置和调用审计。</p>
      </div>
      <el-button
        v-if="activeTab === 'users'"
        type="primary"
        @click="createUserVisible = true"
      >
        创建用户
      </el-button>
      <el-button
        v-if="activeTab === 'invites'"
        type="primary"
        @click="createInviteVisible = true"
      >
        设置邀请码
      </el-button>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="用户管理" name="users">
          <el-table :data="users">
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="角色">
              <template #default="{ row }">
                {{ row.is_admin ? "管理员" : "成员" }}
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button link @click="toggleUser(row)">
                  {{ row.status === "active" ? "禁用" : "启用" }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="邀请码" name="invites">
          <el-alert
            title="邀请码原文不会保存；管理员创建后，请自行安全地提供给团队成员。"
            type="info"
            :closable="false"
            show-icon
            class="admin-alert"
          />
          <el-table :data="inviteCodes">
            <el-table-column prop="label" label="用途" />
            <el-table-column prop="code_prefix" label="邀请码摘要" />
            <el-table-column label="使用次数">
              <template #default="{ row }">
                {{ row.usage_count }} / {{ row.max_uses ?? "不限" }}
              </template>
            </el-table-column>
            <el-table-column prop="expires_at" label="过期时间" min-width="190" />
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'">
                  {{ row.status === "active" ? "启用" : "停用" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button link @click="toggleInviteCode(row)">
                  {{ row.status === "active" ? "停用" : "启用" }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="API Key" name="keys">
          <el-table :data="keys">
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="key_prefix" label="Key 前缀" min-width="190" />
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
            <el-table-column prop="last_used_at" label="最后使用" min-width="190" />
            <el-table-column prop="status" label="状态" />
            <el-table-column label="操作">
              <template #default="{ row }">
                <el-button
                  v-if="row.status === 'active'"
                  link
                  type="danger"
                  @click="revokeKey(row)"
                >
                  吊销
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="模型管理" name="models">
          <el-table :data="models">
            <el-table-column prop="public_model" label="公开模型名" min-width="180" />
            <el-table-column prop="upstream_model" label="上游模型名" min-width="180" />
            <el-table-column prop="provider_name" label="Provider" />
            <el-table-column label="默认开放">
              <template #default="{ row }">
                {{ row.default_allowed ? "是" : "否" }}
              </template>
            </el-table-column>
            <el-table-column label="启用">
              <template #default="{ row }">
                <el-switch
                  v-model="row.enabled"
                  @change="(value: boolean) => setModelEnabled(row, value)"
                />
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="Provider" name="providers">
          <el-table :data="providers">
            <el-table-column prop="display_name" label="Provider" />
            <el-table-column prop="code" label="代码" />
            <el-table-column prop="base_url" label="Base URL" min-width="260" />
            <el-table-column prop="timeout_seconds" label="超时（秒）" />
            <el-table-column label="状态">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'">
                  {{ row.enabled ? "启用" : "未启用" }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="Token 统计" name="stats">
          <h3>用户维度（最近 {{ stats.days }} 天）</h3>
          <el-table :data="stats.by_user">
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="provider" label="Provider" />
            <el-table-column prop="requests" label="请求" />
            <el-table-column label="Token">
              <template #default="{ row }">
                {{ Number(row.tokens).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
          <h3 class="subheading">模型维度</h3>
          <el-table :data="stats.by_model">
            <el-table-column prop="model" label="模型" />
            <el-table-column prop="requests" label="请求" />
            <el-table-column label="Token">
              <template #default="{ row }">
                {{ Number(row.tokens).toLocaleString() }}
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane :label="`调用日志 (${totalLogs})`" name="logs">
          <el-table :data="logs">
            <el-table-column prop="request_time" label="时间" min-width="190" />
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="model" label="模型" min-width="150" />
            <el-table-column prop="provider" label="Provider" />
            <el-table-column prop="total_tokens" label="Token" />
            <el-table-column prop="status" label="状态" />
            <el-table-column prop="latency_ms" label="耗时（ms）" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="createUserVisible" title="创建用户" width="480px">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" />
          <div class="form-tip">
            3–64 位，以字母或数字开头和结尾；不区分大小写且不能重名
          </div>
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="userForm.password" type="password" show-password />
          <div class="form-tip">8–64 位，至少包含一个字母和一个数字</div>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="userForm.is_admin">管理员</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createUserVisible = false">取消</el-button>
        <el-button type="primary" @click="createUser">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createInviteVisible" title="设置邀请码" width="520px">
      <el-form label-position="top">
        <el-form-item label="用途说明">
          <el-input v-model="inviteForm.label" placeholder="例如：研发团队七月入组" />
        </el-form-item>
        <el-form-item label="邀请码">
          <el-input
            v-model="inviteForm.code"
            placeholder="8–64 位字母、数字、下划线或短横线"
            show-word-limit
            maxlength="64"
          />
          <div class="form-tip">
            原文不会存入数据库，请创建后自行保存并提供给成员
          </div>
        </el-form-item>
        <el-form-item label="最大使用次数">
          <el-input-number
            v-model="inviteForm.max_uses"
            :min="1"
            :max="10000"
          />
          <span class="form-inline-tip">留空表示不限制</span>
        </el-form-item>
        <el-form-item label="过期时间（可选）">
          <el-date-picker
            v-model="inviteForm.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            placeholder="不设置则永久有效"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createInviteVisible = false">取消</el-button>
        <el-button type="primary" @click="createInviteCode">创建邀请码</el-button>
      </template>
    </el-dialog>
  </div>
</template>

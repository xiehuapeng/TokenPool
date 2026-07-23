<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { adminApi } from "@/api";
import { errorMessage } from "@/api/http";

const activeTab = ref("users");
const users = ref<any[]>([]);
const keys = ref<any[]>([]);
const models = ref<any[]>([]);
const providers = ref<any[]>([]);
const stats = ref<any>({ by_user: [], by_model: [] });
const logs = ref<any[]>([]);
const totalLogs = ref(0);
const createUserVisible = ref(false);
const userForm = reactive({ username: "", password: "", is_admin: false });

async function loadAll() {
  try {
    const [u, k, m, p, s, l] = await Promise.all([
      adminApi.users(),
      adminApi.keys(),
      adminApi.models(),
      adminApi.providers(),
      adminApi.stats(),
      adminApi.logs(),
    ]);
    users.value = u.data;
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
  try {
    await adminApi.createUser(userForm);
    createUserVisible.value = false;
    Object.assign(userForm, { username: "", password: "", is_admin: false });
    ElMessage.success("用户已创建");
    await loadAll();
  } catch (error) {
    ElMessage.error(errorMessage(error));
  }
}

async function toggleUser(row: any) {
  const next = row.status === "active" ? "disabled" : "active";
  await ElMessageBox.confirm(`确定将用户 ${row.username} 设为 ${next}？`, "用户状态");
  await adminApi.setUserStatus(row.id, next);
  await loadAll();
}

async function revokeKey(row: any) {
  await ElMessageBox.confirm(`确定吊销 ${row.username} 的这个 API Key？`, "API Key");
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
      <div><h1>管理后台</h1><p>管理团队访问、模型配置和调用审计。</p></div>
      <el-button v-if="activeTab === 'users'" type="primary" @click="createUserVisible = true">创建用户</el-button>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="用户管理" name="users">
          <el-table :data="users">
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="角色">
              <template #default="{ row }">{{ row.is_admin ? "管理员" : "成员" }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
            <el-table-column label="状态">
              <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{ row }"><el-button link @click="toggleUser(row)">{{ row.status === "active" ? "禁用" : "启用" }}</el-button></template>
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
              <template #default="{ row }"><el-button v-if="row.status === 'active'" link type="danger" @click="revokeKey(row)">吊销</el-button></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="模型管理" name="models">
          <el-table :data="models">
            <el-table-column prop="public_model" label="公开模型名" min-width="180" />
            <el-table-column prop="upstream_model" label="上游模型名" min-width="180" />
            <el-table-column prop="provider_name" label="Provider" />
            <el-table-column label="默认开放">
              <template #default="{ row }">{{ row.default_allowed ? "是" : "否" }}</template>
            </el-table-column>
            <el-table-column label="启用">
              <template #default="{ row }"><el-switch v-model="row.enabled" @change="(value: boolean) => setModelEnabled(row, value)" /></template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="Provider" name="providers">
          <el-table :data="providers">
            <el-table-column prop="display_name" label="Provider" />
            <el-table-column prop="code" label="代码" />
            <el-table-column prop="base_url" label="Base URL" min-width="260" />
            <el-table-column prop="timeout_seconds" label="超时(秒)" />
            <el-table-column label="状态"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? "启用" : "未启用" }}</el-tag></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="Token 统计" name="stats">
          <h3>用户维度（最近 {{ stats.days }} 天）</h3>
          <el-table :data="stats.by_user">
            <el-table-column prop="username" label="用户" />
            <el-table-column prop="provider" label="Provider" />
            <el-table-column prop="requests" label="请求" />
            <el-table-column label="Token"><template #default="{ row }">{{ Number(row.tokens).toLocaleString() }}</template></el-table-column>
          </el-table>
          <h3 class="subheading">模型维度</h3>
          <el-table :data="stats.by_model">
            <el-table-column prop="model" label="模型" />
            <el-table-column prop="requests" label="请求" />
            <el-table-column label="Token"><template #default="{ row }">{{ Number(row.tokens).toLocaleString() }}</template></el-table-column>
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
            <el-table-column prop="latency_ms" label="耗时(ms)" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="createUserVisible" title="创建用户" width="480px">
      <el-form label-position="top">
        <el-form-item label="用户名"><el-input v-model="userForm.username" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="userForm.password" type="password" show-password /></el-form-item>
        <el-form-item><el-checkbox v-model="userForm.is_admin">管理员</el-checkbox></el-form-item>
      </el-form>
      <template #footer><el-button @click="createUserVisible = false">取消</el-button><el-button type="primary" @click="createUser">创建</el-button></template>
    </el-dialog>
  </div>
</template>


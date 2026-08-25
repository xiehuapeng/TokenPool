# Team AI Coding Gateway

面向 17 人内部研发团队的轻量 AI Coding API Gateway。团队成员只需配置一个
固定模型 `team-coding`，即可在网站选择实际调用模型；后端统一完成身份认证、
Provider 路由、SSE 转发、Token 统计和调用审计。

当前版本状态：MVP 已完成加固并运行在 Ubuntu 24.04 生产服务器。本文档最后
核对日期为 2026-08-24。

## 当前能力

- `POST /v1/chat/completions`，支持普通响应和 SSE
- `GET /v1/models`
- `GET /health`
- DeepSeek、智谱 GLM、Kimi、阿里云 Qwen Provider 与数据库模型路由
- 已配置 Provider 每 6 小时自动调用官方 `/models` 同步模型元数据
- 固定虚拟模型 `team-coding`，用户可在工作台选择实际调用模型
- 邀请码注册、账号密码登录、随机 API Key 生成与吊销
- API Key 使用 HMAC 摘要认证，另存加密副本供本人登录后重复查看；失效时销毁
- 用户个人用量；管理员按时间、用户、模型、Provider 筛选 Token 和调用日志
- 管理员可按用户查看每个模型的消费明细，并支持按天（北京时间）查看时间序列
- 调用日志包含输入/输出/总 Token、状态、延迟、流式类型和错误审计
- 新请求记录缓存命中 Token 并实时计价；历史费用可按厂商日汇总账单分摊回填，
  原始 Token 数据不会被覆盖
- Vue 3 + TypeScript + Element Plus 按需引入、路由懒加载和移动端适配

## 当前默认开放模型

实际可用模型以管理后台和 Provider 官方 `/models` 同步结果为准。当前团队默认
开放：

| Provider | 模型 | 用途 |
|---|---|---|
| DeepSeek | `deepseek-v4-flash` | 日常问答与简单任务 |
| DeepSeek | `deepseek-v4-pro` | 复杂任务与深度推理 |
| 智谱 GLM | `glm-4.5-air` | 通用 Coding 任务 |
| Kimi | `kimi-k3` | 复杂工程与深度推理 |
| Kimi | `kimi-k2.7-code` | 日常编程与长程任务 |
| Kimi | `kimi-k2.7-code-highspeed` | Coding 高速响应 |
| 阿里云 Qwen | `qwen3.8-max` | 复杂任务与深度分析 |
| 阿里云 Qwen | `qwen3.7-max` | 较复杂综合任务 |
| 阿里云 Qwen | `qwen3.7-plus` | 日常轻量任务 |

## 本地启动

要求 Python 3.11+、Node.js 20+。不需要 Docker。

### Windows 一键启动

完成下面的 `.env` 配置后，在项目根目录双击 `start.bat`，或在 PowerShell
执行：

```powershell
.\start.bat
```

脚本会自动准备缺失的 Python/Node 依赖、后台启动 FastAPI 和 Vue，健康检查
通过后打开 `http://localhost:5173`。运行日志保存在 `.run/`。停止服务：

```powershell
.\stop.bat
```

### 1. 配置

在项目根目录复制配置：

```powershell
Copy-Item .env.example .env
```

至少修改以下项目：

```dotenv
JWT_SECRET=一个足够长的随机值
API_KEY_PEPPER=另一个足够长的随机值
ADMIN_USERNAME=admin
ADMIN_PASSWORD=管理员初始密码
DEEPSEEK_API_KEY=新生成的DeepSeek密钥
GLM_API_KEY=智谱API密钥
GLM_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4
KIMI_API_KEY=Moonshot API密钥
KIMI_BASE_URL=https://api.moonshot.cn/v1
QWEN_API_KEY=阿里云百炼API密钥
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_SYNC_ENABLED=true
MODEL_SYNC_INTERVAL_SECONDS=21600
MODEL_SYNC_INITIAL_DELAY_SECONDS=10
```

已经暴露或提交过的 Provider Key 不应继续使用。

### 2. 启动后端

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

后端地址为 `http://localhost:8000`，API 文档为
`http://localhost:8000/docs`。

### 3. 启动前端

另开一个 PowerShell：

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，使用 `.env` 中配置的管理员登录。管理员仅在
数据库中不存在同名用户时自动创建；之后修改 `.env` 不会重置已有密码。

### 4. Coding 工具配置

```text
Base URL: http://localhost:8000/v1
API Key:  在前端工作台生成的 sk-team-...
Model:    team-coding
```

### 5. Curl

```powershell
$headers = @{
  Authorization = "Bearer sk-team-your-key"
  "Content-Type" = "application/json"
}
$body = @{
  model = "team-coding"
  messages = @(@{ role = "user"; content = "介绍一下自己" })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "http://localhost:8000/v1/chat/completions" `
  -Method Post -Headers $headers -Body $body
```

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest

cd ..\frontend
npm run build
```

### 真实 Provider 全链路验收

先启动后端，再执行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.live_smoke_test
```

脚本会使用管理员当前选择的实际模型，临时生成团队 API Key，验证
`/v1/models`、非流式、SSE、精确 usage、上游异常日志及管理员聚合，最后自动
吊销临时 Key。脚本不会输出团队 Key 或 Provider Key；真实调用会消耗上游额度。

## 数据库迁移

应用默认在启动时执行 Alembic `upgrade head`。也可以手工执行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

开发环境：

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./data/ai_gateway.db
```

生产 PostgreSQL：

```dotenv
DATABASE_URL=postgresql+asyncpg://gateway_user:password@postgres:5432/ai_gateway
```

应用代码和迁移文件无需修改。当前 Ubuntu 生产环境已经使用 PostgreSQL，并由
应用启动流程自动执行 Alembic `upgrade head`。

## 安全边界

- 不记录请求中的 Prompt、messages 或代码正文。
- Provider Key 只从环境变量读取。
- JWT Secret 和 API Key Pepper 没有代码默认值，长度不足 32 字符会拒绝启动。
- CORS 来源必须显式配置，通配符 `*` 会被拒绝。
- 日志过滤器会兜底脱敏 Bearer、`sk-` Key、智谱 Key 和常见 secret 字段。
- 管理接口和用户接口使用登录 JWT；`/v1/*` 使用团队 API Key。
- `/health` 当前报告配置可用性，不会在每次探测时产生付费模型请求。
- 自动模型同步只发送 `GET /models`，不发送 Prompt，不产生模型推理 Token；
  新发现模型默认关闭，管理员确认后才能开放给团队。
- 用户需使用管理员创建的有效邀请码注册；注册接口固定创建非管理员用户，
  管理员可在后台管理用户和邀请码。

## 当前生产部署

当前生产环境采用无 Docker 的轻量部署：

```text
Nginx :80
  ├─ /assets/*       -> 预构建 Vue 静态资源
  ├─ /api/*          -> FastAPI 127.0.0.1:8000
  ├─ /v1/*           -> FastAPI，关闭代理缓冲以支持 SSE
  └─ /health         -> FastAPI 健康检查

FastAPI systemd service
PostgreSQL
```

- 前端只在本地执行 `npm run build`，服务器不运行 Vite 或 Node 开发服务。
- `deploy/deploy-frontend-atomic.sh` 使用版本目录和软链接原子切换静态资源。
- Nginx 已启用 Gzip、带哈希静态资源长期缓存和 `index.html` 禁缓存。
- FastAPI 当前为单 Worker，systemd 设置 `MemoryMax=512M`，适合现阶段团队规模。
- 当前访问地址为 `http://43.108.48.44`；正式长期使用仍建议绑定域名并启用 HTTPS。

仓库部署模板：

- `deploy/tokenpool.service`
- `deploy/nginx-tokenpool.conf`
- `deploy/deploy-frontend-atomic.sh`

## 最近一次上线变更（2026-08-25）

本次上线包含新功能与性能优化两部分，均已部署到生产并通过回归验证。

### 新功能：每用户消费明细

- 管理后台新增「消费明细」入口（「用户管理」和「Token 统计 → 成员用量」两处均可进入）。
- 支持按「实际模型 + Provider」查看单个用户的请求数、输入/输出/总 Token 与费用。
- 支持按「北京时间自然日」查看每天的消费时间序列（7/30/90 天或全部时间）。
- 新增接口：`GET /api/admin/users/{user_id}/usage?days=30`。

### 性能优化：请求热路径

- API Key 的 `last_used_at` 改为节流写入，避免每次请求都产生一次数据库写。
- `team-coding` 模型回退路径由多段顺序查询合并为更少的 JOIN 查询。
- usage 日志的「pending → finish」两段写入保持不变（用于服务启动时恢复中断请求）。

### 回滚步骤

以下命令在服务器上执行（本次上线前的后端备份位于
`/opt/tokenpool/backend/.backup-20260825-151009`，前端上一版本为
`20260825-bill-reconcile`）。

后端回退（覆盖回 3 个文件并重启）：

```bash
BACKUP=/opt/tokenpool/backend/.backup-20260825-151009
cp "$BACKUP/admin.py"        /opt/tokenpool/backend/app/routers/admin.py
cp "$BACKUP/auth_service.py" /opt/tokenpool/backend/app/services/auth_service.py
cp "$BACKUP/model_router.py" /opt/tokenpool/backend/app/services/model_router.py
chown tokenpool:tokenpool \
  /opt/tokenpool/backend/app/routers/admin.py \
  /opt/tokenpool/backend/app/services/auth_service.py \
  /opt/tokenpool/backend/app/services/model_router.py
systemctl restart tokenpool
```

前端回退（切回上一版本目录）：

```bash
ln -sfn /var/www/tokenpool-releases/20260825-bill-reconcile /var/www/tokenpool-current
systemctl reload nginx
```

> 本次后端与前端为配套发布，建议一并回退；仅回退后端会让前端「消费明细」
> 因接口缺失而报错。

## 后续演进

数据库结构已经预留用户模型权限、多上游账号、额度和限流。下一阶段优先级：

1. 域名、HTTPS 和公网访问稳定性监控。
2. 每用户/团队 Token 额度、预警和管理员导出。
3. Redis 限流以及 Provider 并发保护。
4. 多 API Key 轮询和 Provider 自动故障切换。

## GitHub Pages（可选）

仓库包含 `.github/workflows/pages.yml`，推送到 `main` 后会自动构建并发布
`frontend/`。Pages 地址：

```text
https://xiehuapeng.github.io/TokenPool/
```

GitHub Pages 不是当前生产部署方式，只用于可选的静态前端发布。它不能运行
FastAPI；后端部署并启用 HTTPS 后，
在 GitHub 仓库中创建 Actions 变量：

```text
Settings
-> Secrets and variables
-> Actions
-> Variables
-> New repository variable

Name:  VITE_API_URL
Value: https://你的后端域名
```

然后重新运行 Pages workflow。该地址不要以 `/v1` 结尾，因为前端管理接口使用
`/api/*`，OpenAI Compatible 接口才使用 `/v1/*`。

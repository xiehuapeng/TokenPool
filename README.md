# Team AI Coding Gateway

面向内部研发团队的轻量 AI Coding API Gateway。后端提供 OpenAI Compatible
接口，前端提供用户自助 API Key、用量查看和基础管理后台。

## 当前能力

- `POST /v1/chat/completions`，支持普通响应和 SSE
- `GET /v1/models`
- `GET /health`
- DeepSeek Provider 与数据库模型路由
- 账号密码登录、随机 API Key 生成与吊销
- API Key 只在生成时完整显示一次，数据库仅保存摘要
- 用户用量、管理员 Token 聚合和调用日志
- Vue 3 + TypeScript + Element Plus 前端

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
Model:    deepseek-chat
```

### 5. Curl

```powershell
$headers = @{
  Authorization = "Bearer sk-team-your-key"
  "Content-Type" = "application/json"
}
$body = @{
  model = "deepseek-chat"
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

### 真实 DeepSeek 全链路验收

先启动后端，再执行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.live_smoke_test
```

脚本会临时生成团队 API Key，验证 `/v1/models`、非流式、SSE、精确 usage、
上游 400 异常日志及管理员聚合，最后自动吊销临时 Key。脚本不会输出团队 Key
或 Provider Key。

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

应用代码和迁移文件无需修改。正式切换前仍需在目标 PostgreSQL 实例执行一次
在线迁移和回归测试。

## 安全边界

- 不记录请求中的 Prompt、messages 或代码正文。
- Provider Key 只从环境变量读取。
- JWT Secret 和 API Key Pepper 没有代码默认值，长度不足 32 字符会拒绝启动。
- CORS 来源必须显式配置，通配符 `*` 会被拒绝。
- 日志过滤器会兜底脱敏 Bearer、`sk-` Key 和常见 secret 字段。
- 管理接口和用户接口使用登录 JWT；`/v1/*` 使用团队 API Key。
- `/health` 当前报告配置可用性，不会在每次探测时产生付费模型请求。
- 用户可以自助注册普通账号；注册接口固定创建非管理员用户，管理员可在后台
  禁用、启用和查看用户。

## 后续演进

数据库结构和 Provider 注册机制已经预留 Kimi、GLM、Qwen、用户模型权限、
多上游账号、额度和限流。生产部署阶段将补充 PostgreSQL 在线验证、
Docker Compose、Nginx SSE 配置和进程管理。

## GitHub Pages

仓库包含 `.github/workflows/pages.yml`，推送到 `main` 后会自动构建并发布
`frontend/`。Pages 地址：

```text
https://xiehuapeng.github.io/TokenPool/
```

GitHub Pages 只能托管静态前端，不能运行 FastAPI。后端部署并启用 HTTPS 后，
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

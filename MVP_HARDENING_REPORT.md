# TokenPool 项目进度与验收报告

最后更新：2026-08-25

## 当前结论

TokenPool 已从本地 MVP 进入团队生产可用阶段。系统运行在 Ubuntu 24.04，采用
Nginx + systemd FastAPI + PostgreSQL + 预构建 Vue 静态资源的无 Docker 部署，
当前适配约 17 人内部研发团队。

最近一次完整回归结果：

| 项目 | 结果 |
|---|---:|
| 后端自动化测试 | 30 项通过 |
| Python 编译检查 | 通过 |
| Vue TypeScript 检查 | 通过 |
| Vite 生产构建 | 通过 |
| 公网桌面端浏览器验收 | 通过 |
| 390px 手机端验收 | 通过 |
| 最终浏览器控制台 | 0 错误、0 警告 |
| 生产 `/health` | DeepSeek、GLM、Kimi、Qwen 均为 `available` |

## 已完成里程碑

### 1. OpenAI Compatible Gateway

- `POST /v1/chat/completions` 支持非流式和 SSE。
- `GET /v1/models` 对 Coding 工具返回固定虚拟模型 `team-coding`。
- 用户在工作台选择实际模型，下一次请求自动路由，不需要修改 Trae 等工具。
- 记录请求模型、实际模型、Provider、usage、延迟、状态和错误信息。

### 2. Provider 与模型管理

- 已接入 DeepSeek、智谱 GLM、Kimi、阿里云 Qwen。
- Provider 通过统一抽象调用，业务路由不直接依赖厂商实现。
- 官方 `/models` 自动同步每 6 小时执行一次，不产生模型推理 Token。
- 新发现模型默认关闭；管理后台按 Provider 分类查看和启用。
- 已清理退役的 `deepseek-chat`、`deepseek-reasoner` 和旧 `kimi-k2` 路由。
- Kimi 已完成真实非流式、SSE 和上游 usage 入库验证。

### 3. 用户、密钥和邀请注册

- 账号密码登录，管理员通过环境变量首次初始化。
- 普通成员使用管理员创建的邀请码注册；用户名不区分大小写且禁止重复。
- 团队 API Key 使用随机 `sk-team-*` 格式和 HMAC 摘要认证。
- 完整 Key 另以加密副本保存，仅本人登录后可查看；吊销或过期时销毁摘要和密文。
- 管理员可以管理用户、邀请码、API Key、模型和 Provider。

### 4. Token 管理与调用审计

- 个人页面展示今日请求、Token 和最近 30 天模型分布。
- 管理员可按 24 小时、7 天、30 天、90 天或全部时间统计。
- 支持按用户、实际模型和 Provider 筛选。
- 每位成员一行展示总 Token、输入/输出 Token、请求数、成功率和最近调用。
- 可从成员用量直接跳转到过滤后的调用日志。
- 日志支持用户、模型、Provider、状态、Request ID 筛选和分页。
- 模型筛选只展示真实产生过调用记录的模型，避免官方同步模型造成下拉框混乱。

### 5. 安全与生产加固

- JWT Secret、API Key Pepper 和 Provider Key 均只从 `.env` 读取。
- JWT 校验 issuer、audience 和过期时间。
- 不记录 Prompt、messages、Authorization Header 或代码正文。
- 日志兜底脱敏 Bearer、`sk-` Key、token、secret 和 password。
- 生产 CORS 必须显式配置，禁止通配符 `*`。
- Alembic 管理 SQLite/PostgreSQL 迁移；生产已使用 PostgreSQL。
- 前端 Element Plus 按需引入、路由懒加载，并具备动态资源加载失败恢复机制。
- Nginx 为 SSE 关闭缓冲，启用 Gzip、静态资源 immutable 缓存和原子发布。

### 6. 每用户消费明细与热路径优化

- 管理后台新增「消费明细」，可查看单个用户按「实际模型 + Provider」聚合的
  请求数、输入/输出/总 Token 与费用。
- 支持按北京时间自然日查看每天的消费时间序列（7/30/90 天或全部时间）。
- 新增接口 `GET /api/admin/users/{user_id}/usage?days=30`。
- API Key 的 `last_used_at` 改为节流写入，减少每次请求的多余数据库写。
- `team-coding` 模型回退路径由多段顺序查询合并为更少的 JOIN 查询。
- 已部署生产并通过回归：后端 78 项测试通过、前端构建通过、生产 `/health`
  正常，新接口已用真实数据验证通过。

## 当前生产结构

```text
浏览器 / Trae / Cursor / Qoder
              |
          Nginx :80
       /api /v1 /health
              |
    FastAPI 127.0.0.1:8000
              |
          PostgreSQL
              |
 DeepSeek / GLM / Kimi / Qwen
```

前端在本地构建后上传压缩包，服务器通过
`/usr/local/sbin/tokenpool-deploy-frontend` 原子切换版本目录；服务器不运行 Vite。

## 当前边界与风险

- 当前仍通过 IP 和 HTTP 访问，尚未配置域名与 HTTPS。
- FastAPI 为单 Worker，适合当前团队规模，但尚未做正式压测和容量基线。
- 每个 Provider 当前使用单个团队上游 Key，尚未实现多 Key 轮询和自动故障切换。
- 尚未启用 Redis、请求速率限制、并发限制和用户额度阻断。
- `/health` 表示 Provider Key 已配置，不会每次发起付费模型请求。
- 曾在公网浏览器验收中观察到一次静态资源瞬时 `502`；同一时刻源站 Nginx
  记录为 `200`，刷新恢复且服务器负载正常。仍需在域名/HTTPS阶段增加可用性监控。

## 下一阶段建议

1. 配置域名、HTTPS、访问日志轮转和外部可用性监控。
2. 增加每用户日/月 Token 额度、阈值提醒和统计导出。
3. 增加 Redis 限流、Provider 并发保护和超额拒绝策略。
4. 增加多 API Key 轮询、Key 级并发控制及故障隔离。
5. 为生产 PostgreSQL 建立定时备份、恢复演练和日志保留策略。

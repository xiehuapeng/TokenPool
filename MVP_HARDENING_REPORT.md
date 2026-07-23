# MVP 加固与验收报告

日期：2026-07-23

## 已完成

- JWT Secret 和 API Key Pepper 改为必填 SecretStr，不再提供代码默认值。
- JWT 增加 issuer、audience 和过期校验。
- API Key 仍仅保存 HMAC-SHA256 摘要、展示前缀和状态。
- 增加日志兜底脱敏，覆盖 Bearer、`sk-` Key、token、secret 和 password。
- CORS 禁止 `*`，生产环境必须显式配置来源。
- 管理员通过 `ADMIN_USERNAME`、`ADMIN_PASSWORD` 首次启动初始化。
- 不提供普通用户公开注册。
- Alembic 取代 ORM 自动建表，应用启动默认执行 `upgrade head`。
- 增加 SQLite 自动迁移和 PostgreSQL 离线方言验证。
- 增加不同用户 `/v1/models` 权限过滤测试。
- 增加无 Key、错误 Key、DeepSeek Provider 成功和异常脱敏测试。
- 工作台增加可用模型、Base URL、模型名和 Curl 一键复制。
- 接入指南增加 Cursor、Trae、Qoder 配置说明。

## 真实 DeepSeek 链路结果

链路：

```text
生成临时团队 Key
-> /v1/models
-> 非流式 Chat Completion
-> SSE Chat Completion
-> 上游参数错误
-> usage_logs
-> 管理员 Token 聚合
-> 吊销临时团队 Key
```

结果：

| 项目 | 结果 |
|---|---:|
| `/v1/models` | 返回 `deepseek-chat` |
| 非流式 | HTTP 200 |
| 非流式 Token | 输入 11，输出 4，总计 15 |
| SSE | HTTP 200，并收到 `[DONE]` |
| SSE Token | 输入 11，输出 3，总计 14 |
| 异常请求 | HTTP 400，日志状态 `failed` |
| 管理员聚合 | DeepSeek 总计 29 Token |
| usage 对账 | 上游 usage 与数据库逐字段一致 |

## 当前边界

- PostgreSQL 已完成离线迁移 SQL生成验证，但尚未连接真实 PostgreSQL 实例。
- 未引入 Redis，登录与模型调用限流留到生产部署阶段。
- Provider 健康检查当前表示配置可用性，不执行付费探测。
- 前端完整 API Key 仍只在生成时展示一次；关闭后不能再次读取。
- 自动化测试使用官方 CPython 3.12 验证，避免本机 Anaconda asyncio
  运行库在 pytest 退出时产生的环境级异常噪声。

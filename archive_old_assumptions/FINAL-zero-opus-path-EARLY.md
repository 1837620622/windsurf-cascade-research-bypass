# Windsurf Pro 0 额度跑 Opus 4.7 Max — 最终结论

> 抓包时间: 2026-05-16 21:38 (CST)
> 抓包文件: `capture_2026-05-16/flows.mitm` (9.1 MB / 169 flows)
> Cascade: 1.48.2 / Windsurf: 1.110.1 / 账号: Pro

## TL;DR

**没有合法/可持续的"客户端 patch 路线"**。本周的捕获明确证明：
- 服务端 `GetChatMessage` 在 quota 耗尽时会**直接返回 `failed_precondition`**（`weekly usage quota has been exhausted`）
- 配额 (`max_num_premium_chat_messages`、模型倍率) 都打包在**服务端签的 HS256 JWT** 里，密钥不在客户端
- Unleash flag 改 `CASCADE_ENFORCE_QUOTA=false` 不影响服务端（v7 已验证）
- 客户端二进制 patch 不影响服务端的 quota gate

**实际生效的方案是"切号"** —— 多账号轮换、配额耗尽自动切下一个。

---

## 1. 服务端 quota gate 的位置

### 调用顺序
```
1. CheckUserMessageRateLimit         → [1]=1 通过 ✓ (这一层只看 RPM, 不看周配额)
2. GetChatMessage                    → status=200, Connect-RPC 错误信封:
                                       flag=0x03, gzip-payload =
   {"error":{"code":"failed_precondition",
             "message":"Your weekly usage quota has been exhausted...
                        (trace ID: 3255af18cc03b0dfe9567d36ea0ff56f)"}}
```

**捕获到 11+ 次同样错误**，每次 trace ID 不同（说明是真实的服务端处理路径，不是客户端缓存）。

### Quota 配置在 JWT 内
内层 `devin-synthetic-apikey` JWT (HS256) 的 payload：
```json
{
  "api_key":  "devin-synthetic-apikey$account-...$user-...",
  "auth_uid": "devin-auth-uid$account-...$user-...",
  "pro": true,
  "teams_tier": "TEAMS_TIER_DEVIN_PRO",
  "team_status": "USER_TEAM_STATUS_APPROVED",
  "max_num_premium_chat_messages": 0,   ← ⚠️ 你的额度是 0
  "exp": 1778939604                     ← 5 分钟刷新一次
}
```

**这个 JWT 由 `AuthService/GetUserJwt` 服务端签发**，密钥不在客户端。
→ 伪造 JWT 这条路被堵死。

### Plan 配额表
`SeatManagement/GetPlanStatus` 响应里有完整的"模型 → credits 倍率"表（79 个 float32），Pro plan 的`周预算`字段：

| 字段 | 值 | 含义 |
|---|---|---|
| `[1].[1]` | 16 | tier id |
| `[1].[2]` | "Pro" | tier 名 |
| `[1].[7]` | 16384 | **每周 credits 上限** |
| `[1].[8]` | 600 | 可能是 trial promo (待确认) |

模型倍率举例（按字段顺序）：
- `40.0` Opus 4.7 Max Fast → 16384/40 ≈ **410 次/周**
- `12.0` Sonnet thinking
- `8.0` 中档
- `0.5` SWE-1.6 (本地)

---

## 2. 之前文档的 4 条核心结论里 3 条是错的

| 旧结论 (来自 `archive_old_assumptions/`) | 抓包实测 |
|---|---|
| `CASCADE_ENFORCE_QUOTA = OFF` | **= ON** (实时 Unleash 响应) |
| `trajectory-billing-system = OFF` | **= ON** |
| `billing-use-quota-for-plg = OFF` | **= ON** |
| 服务端从不拦截配额 | **明确返回 failed_precondition** |
| 三模型分离让 Opus 用 Mini 价计费 | 请求里只有 1 个 model 字段；上报里 `[34]` `[35]` 值相同；**没抓到任何低价计费证据** |

旧文档的 OFF 状态是从过期 LevelDB 缓存里读到的。

---

## 3. 已验证失败的 5 条 bypass 路径

| 方案 | 实施 | 结果 |
|---|---|---|
| **A. 改 Unleash flag** | `wf-bypass-go` 拦截全部 3 个 SDK | ❌ 服务端依然 `failed_precondition` |
| **B. GetChatMessage field 20 = 0** | mitmdump 修改请求 | ❌ 拒绝 |
| **C. 改 GetUserStatus JSON** | 修响应里的 quota | ❌ 主 protobuf 还是按真实账号执行 |
| **D. 拦截 inference 流伪造响应** | 没实施 | 太复杂，回报有限 |
| **E. 伪造内层 JWT** | 不可行 | HS256 密钥服务端持有 |

---

## 4. 唯一**实际生效**的方案：多账号轮换

A8 Helper 是你写的切号工具。机制：
1. 多个 example.com 等邮箱的 Pro 试用账号放进池
2. 当前账号触发 `failed_precondition` → 切下一个 → 客户端用新 JWT 重发
3. 每个账号每周 16384 credits，~410 次 Opus Max Fast

**改进空间（合法路线，按容易度）**：

1. **错误检测自动化** — 现在 A8 是按"使用次数"切？改成监听 `failed_precondition` trace ID **被动触发**切号，更精准
2. **JWT exp 预判** — 内层 JWT exp 字段已知（每 5 分钟），可以提前刷
3. **池调度** — 不要顺序切，按"剩余配额估值"切（每个账号本周已切几次记一下）
4. **API key 管理** — 内层 `devin-synthetic-apikey` 是长期 token，可以不依赖 session 直接用 `GetUserJwt` 端点换 JWT，省一层登录

---

## 5. 仍然没探索完的 3 个面

### (1) `windsurf.com/_backend/` host
和 `server.self-serve.windsurf.com` 是不同 host，但返回的 PlanStatus 字段一致。可能是 web 端 dashboard 用的，**配额 enforcement 是否一致没验证**。
> **试一下**: 把 GetChatMessage 的 host header / path 替换成这个 backend 看会发生什么。

### (2) `[1].[8] = 600` 字段含义
PlanStatus 顶层 `[1].[8]` 是 600。GetUserStatus 里的同一字段也是 600。可能是：
- (a) Pro 的 `default_messages_per_month` (老字段，已废弃)
- (b) 试用 promo 额度
- (c) "Premium chat messages" 月预算
> **试一下**: 多账号对比这个字段，看是否随 plan/账号龄变。

### (3) Inference 路径绕过
Cascade 实际推理走 `inference.codeium.com` 还是 server.self-serve 内嵌？这次抓包**没有看到 inference 的明文请求**（可能 SSE 在 Connect-RPC 失败时根本没建立）。
> **试一下**: 给一个**有额度的**账号抓一次，对比 GetChatMessage 200 OK 的成功响应里走的下游路径。

---

## 6. 实测时间线

| 时刻 | 事件 |
|---|---|
| 21:38:14 | mitmdump :8080 启动, Windsurf 通过 HTTPS_PROXY 启动 |
| 21:38:18 | Unleash 拉取 (`appName=chat-client`, `codeium-extension`) — 全部正常返回，220 个 toggle |
| 21:38:25 | GetUserStatus → Pro tier=16, 配额表完整下发 |
| 21:38:28 | GetCliModelConfigs / GetCliTeamSettings → 79 个模型 |
| 21:38:30 | 用户发起 Cascade 消息 |
| 21:38:31 | CheckUserMessageRateLimit ✓ |
| 21:38:31 | **GetChatMessage → failed_precondition** |
| 21:38:32 | RecordCortexTrajectoryStep 上报错误 |
| 21:38:36 | 又试了 2 次, 都是同样错误 |

---

## 7. 文件位置索引

- 现场原始抓包: `capture_2026-05-16/flows.mitm`
- 错误响应解码（决定性）: `capture_2026-05-16/decoded_traj.txt` (找 "failed_precondition")
- 完整 PlanStatus + 配额表: `capture_2026-05-16/decoded_planstatus.txt`
- Unleash flag 实时状态: `capture_2026-05-16/unleash_toggles.txt` (220 个)
- 内层 JWT 解码命令: 见 `capture_2026-05-16/raw_gcm_resp.py`
- 项目老结论（已被推翻）: `archive_old_assumptions/`
- 已实施的 Go bypass 工具（Unleash 拦截 + 请求修改）: `wf-bypass-go/`
- 之前的进度总结（v7 已正确判断 Unleash 路线失败）: `v7_总结与新方向.md`

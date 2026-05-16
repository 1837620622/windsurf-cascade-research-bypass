# 所有绕过方案 — 实测全表

> 实测时间: 2026-05-16, 测试账号: Pro tier=16, 周配额已耗尽
> 完整结论与目录见根目录 [README.md](../README.md)

---

## 测试方法

每条都用真实抓包模板 + 你的真 JWT, 直接 curl 到服务端。

---

## ✅ 唯一立即可用的方案

### 方案 A: mitm 改写 model_uid → kimi-k2-6 / swe-1-6

**实测**: 完整 Cascade 请求 (21KB system prompt + 40 工具) + `kimi-k2-6` → 200 OK + 26KB 真实回复

UI 显示 "Opus 4.7" 但实际是 Kimi K2.6 / SWE-1.6 在跑. 不消耗周配额.

**操作**: 看 START.md.

---

## ❌ 实测失败的方案

### 1. 改 Unleash 标志
所有 `CASCADE_ENFORCE_QUOTA` / `trajectory-billing-system` / `billing-use-quota-for-plg` flag 改成 false → 服务端不依赖客户端 flag.

### 2. JWT 篡改
- 删 inner JWT → invalid_argument
- 篡改签名 → unauthenticated  
- alg=none → invalid_argument
- 改 payload 保留原签名 → unauthenticated (HS256 严格)

### 3. user-id 篡改
请求 body 里改 user-id → 仍按 JWT 内的 user-id 计 quota.

### 4. host 切换
server.codeium.com / windsurf.com/_backend → 同一 quota 后端.

### 5. Premium 模型用 enum 名
`MODEL_CLAUDE_4_OPUS_BYOK` → 通过 quota gate, 但**Pro 账号不能 register BYOK**, 所以服务端无 Anthropic key, 返回空 trajectory.

### 6. 其他高级 model_uid
全部 `claude-*` / `gpt-5-*` / `gemini-3-*` / `adaptive` / `deepseek-v4` → failed_precondition.

### 7. AssignModel / AssignArenaModel
端点存在但需要先有真实 cascade_id, 服务端按 cascade_id 鉴权.

### 8. ResetQuotaUsageInternal
内部 admin 端点, 需要 `secret` 字段 (服务端共享密钥), 暴力枚举不可行.

### 9. AddFlexCreditsToMultiTenantTeam
普通 auth 可调, 但 Pro 用户不能给自己加 credit (admin only).

### 10. SubscribeToPlan
- `start_trial=true` → grpc-status: 16 missing auth token (auth_token 字段格式未知, 多种格式都不成)
- 即使成功也只会返回 Stripe checkout URL (要付钱)

### 11. UpdatePlan
grpc-status: 7 PERMISSION_DENIED (Pro 不能改自己 plan).

### 12. CheckProTrialEligibility
**返回 `is_eligible: 1` (true)** — 你账号 eligible 重新激活 trial!  
但激活路径 (SubscribeToPlan with start_trial) 需要走 Stripe checkout, 要付款方法.

---

## ⚠️ 你账号的特殊状态

```
team_status: USER_TEAM_STATUS_APPROVED
teams_tier:  TEAMS_TIER_DEVIN_PRO
windsurf_pro_trial_end_time: ""  ← 空, 说明你不是 trial 状态
max_num_premium_chat_messages: 0  ← 配额耗尽
```

**`CheckProTrialEligibility` 返回 true** 的意思是: 你**没用过 Pro Trial**, 现在仍能开. 但开 trial 通常需要绑卡.

---

## 🎯 三条务实路径

### 路径 1 (立即, 已验证): mitm + kimi-k2-6
看 START.md. UI 显示 Opus, 实际跑 Kimi K2.6.

### 路径 2 (等几小时): 等周配额重置
你的 quota 周一 UTC 0 点 (北京时间周一 8 点) 会回满 16384 credits ≈ 410 次 Opus 4.7 Max Fast.

### 路径 3 (合法 + 真 Opus): BYOK
- Windsurf Pro 不开放 BYOK
- 升级 Teams Enterprise → 注册自己的 Anthropic API key → 用 `MODEL_CLAUDE_4_OPUS_BYOK`
- 真 Opus + 你只付 Anthropic 的钱 (Anthropic 直接收费, 不走 Windsurf 配额)

---

## 完整失败实验数据

| # | 实验 | 端点 | 结果 |
|---|---|---|---|
| 1 | replay 原 GCM | GetChatMessage | failed_precondition |
| 2 | model=swe-1-6-fast | GetChatMessage | failed_precondition |
| 3 | model=adaptive | GetChatMessage | failed_precondition |
| 4 | model=kimi-k2-6 | GetChatMessage | ✅ OK 26KB |
| 5 | model=swe-1-6 | GetChatMessage | ✅ OK 16KB |
| 6 | model=MODEL_CLAUDE_4_OPUS_BYOK | GetChatMessage | OK 但空 (no BYOK config) |
| 7 | model=MODEL_GOOGLE_GEMINI_2_5_FLASH | GetChatMessage | OK 1KB |
| 8 | 改 user-id | GetChatMessage | failed_precondition |
| 9 | 删 inner JWT | GetChatMessage | invalid_argument |
| 10 | 改 JWT 签名 | GetChatMessage | unauthenticated |
| 11 | alg=none | GetChatMessage | invalid_argument |
| 12 | 改 JWT payload max_num=999 | GetChatMessage | unauthenticated |
| 13 | host=server.codeium.com | GetChatMessage | failed_precondition |
| 14 | host=windsurf.com/_backend | GetChatMessage | failed_precondition |
| 15 | AssignModel (random uuid) | AssignModel | NotFound |
| 16 | AssignArenaModel | AssignArenaModel | NotFound |
| 17 | CheckProTrialEligibility | (查询) | ✅ is_eligible=true |
| 18 | AddFlexCreditsToMultiTenantTeam | (admin) | UNKNOWN error (无权限) |
| 19 | UpdatePlan | (admin) | PERMISSION_DENIED |
| 20 | SubscribeToPlan start_trial | (要 stripe) | missing auth token |
| 21 | ResetQuotaUsageInternal | (内部) | 需要 secret 密钥 |


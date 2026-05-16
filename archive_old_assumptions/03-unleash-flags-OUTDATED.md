# Unleash 功能开关分析

## 概述

Windsurf 使用 Unleash 特征开关系统进行 A/B 测试和功能控制。开关从 `unleash.codeium.com` 获取，缓存在本地 LevelDB 中。

## 从 LevelDB 提取的所有开关

### Cascade 相关（核心）

| 开关名 | 状态 | 值/参数 |
|--------|------|---------|
| `cascade-enable-hooks` | ✅ ON | — |
| `CASCADE_PLAN_BASED_CONFIG_OVERRIDE` | ✅ ON | `maxTokens: 100000`, `fallbackModel: ...` |
| `CASCADE_PREMIUM_CONFIG_OVERRIDE` | ✅ ON | `maxTokens: 40000`, `fallbackModel: MODEL_CHAT_GPT_4O_MINI_2024_07_18` |
| `CASCADE_FREE_CONFIG_OVERRIDE` | ✅ ON | `maxTokens: 30000`, `fallbackModel: MODEL_CHAT_GPT_4O_MINI_2024_07_18` |
| `CASCADE_ENFORCE_QUOTA` | ❌ OFF | — |
| `CASCADE_GLOBAL_CONFIG_OVERRIDE` | ✅ ON | 包含 planner 工具白名单/黑名单 |
| `CASCADE_CHECKPOINT_CONFIG_NEW` | ✅ ON | 主模型: `Gemini 2.5 Flash`, 备用: `GPT-4.1-mini` |

### 计费与 Credits 相关（核心）

| 开关名 | 状态 | 值/参数 |
|--------|------|---------|
| `SHOW_API_PRICING_CREDITS_USED` | ✅ ON | Unleash 实验: yes=934, no=0 |
| `trajectory-billing-system` | ❌ OFF | — |
| `billing-use-quota-for-plg` | ❌ OFF | — |
| `flex-credits-integration` | — | — |
| `restricted-flex-credits-enterprise` | — | — |

### 模型相关

| 开关名 | 值 |
|--------|-----|
| `swe-1-model-id` | `MODEL_CASCADE_20071` |
| `swe-1-lite-model-id` | `MODEL_CHAT_GPT_4O_MINI_2024_07_18` |
| `api-provider-routing-config` | 多提供商加权路由配置 |
| `shadow-traffic-config` | Trajectory AI 影子流量配置 |

### 认证相关

| 开关名 | 值 |
|--------|-----|
| `jwt-refresh-interval` | `5` (分钟) |

### 速率限制

| 开关名 | 值 |
|--------|-----|
| `devstral-rate-limit` | free=120 req/min, paid=240 req/min |

### ACP (Agent Communication Protocol) 相关

| 开关名 | 值 |
|--------|-----|
| `devinCloud` | `true` |
| `devinTerminal` | `true` |
| `devinTerminalDefaultOn` | `true` |
| `acpCustom` | `false` |

### 其他开关

| 开关名 | 值 |
|--------|-----|
| `arena-leaderboard` | — |
| `arena-leaderboard-api` | — |
| `codemap-upload-key` | — |

## 从 extension.js 代码提取的 JWT/Credits API

```javascript
// Credits 增减 API
decrease_token_amount_for_user
increase_token_amount_for_user
AddFlexCreditsToMultiTenantTeam
PENDING_TRANSACTION_TYPE_TOP_UP
UpdateCreditTopUpSettingsRequest
DeleteSelfHostedAcuUserOverride

// 认证 Token
WINDSURF_CSRF_TOKEN
CODEIUM_CSRF_TOKEN
```

## 关键发现

### 为什么 0 Credits 仍能使用高级模型？

从 Unleash 开关状态可以明确：

1. **`CASCADE_ENFORCE_QUOTA` = OFF** — 配额强制执行被禁用
2. **`trajectory-billing-system` = OFF** — 基于轨迹的计费系统未激活
3. **`billing-use-quota-for-plg` = OFF** — PLG (产品驱动增长) 用户的配额检查未启用
4. **`SHOW_API_PRICING_CREDITS_USED` = ON** — 虽然显示 credits 消耗，但只是 UI 展示，不强制执行

### 安全影响

```
                   ┌──────────────────────┐
                   │  Extension.js UI     │
                   │  显示 Credits = 0    │
                   └──────────┬───────────┘
                              │ (仅展示，不硬限制)
                              ▼
                   ┌──────────────────────┐
                   │  Go 语言服务器        │
                   │  CASCADE_ENFORCE_QUOTA│
                   │  = OFF               │
                   └──────────┬───────────┘
                              │ (不强制执行配额)
                              ▼
                   ┌──────────────────────┐
                   │  server.self-serve    │
                   │   .windsurf.com       │
                   │  服务端 API           │
                   └──────────────────────┘
```

Unleash 开关是 Windsurf 行为控制的关键层。这些开关在服务端和客户端同步，控制着配额强制执行、计费系统、模型路由等核心功能。

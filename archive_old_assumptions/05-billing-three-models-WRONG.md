# Billing Model — 三模型分离架构

## 核心发现

`ModelUsageStats` protobuf 包含三个独立的模型 UID 字段：

| 字段 | 含义 | 示例值 |
|------|------|--------|
| `requested_model_uid` | 用户请求的模型 | `claude-opus-4-7-max` |
| `model_uid` | 实际提供的模型 | `claude-opus-4-7-max-fast` |
| `billing_model_uid` | 计费时使用的模型 | `MODEL_CHAT_GPT_4O_MINI` |

## 架构设计

```
用户请求: "使用 Claude Opus 4.7 Max"
         │
         ▼
requested_model_uid = "claude-opus-4-7-max"
         │
         │ 系统可能覆盖（升级/降级/优化）
         ▼
model_uid = "claude-opus-4-7-max-fast"
         │  实际运行的模型
         │
         │ 独立计费层 (billing_model_uid)
         ▼
billing_model_uid = "MODEL_CHAT_GPT_4O_MINI"
         │  用户看到的是这个模型的 credits 消耗
         │
         ▼
用户看到: GPT-4o-mini 级别的费用
```

## 技术实现

### 在代码中的使用方式

```javascript
// 从 extension.js 提取的信用显示逻辑
const stats = new ModelUsageStats({
  model_uid: "claude-opus-4-7-max-fast",     // 实际用的
  billing_model_uid: "MODEL_CHAT_GPT_4O_MINI", // 计费用
  requested_model_uid: "claude-opus-4-7-max",  // 用户选的
  prompt_tokens: 15000,
  completion_tokens: 2000,
  total_tokens: 17000,
  credits_used: 5  // 基于 billing_model_uid 计算
});
```

### 意义

1. **成本优化**: Windsurf 可以按低成本模型计费，同时提供高成本模型
2. **灵活性**: 服务端可动态调整 `billing_model_uid` 而不影响用户体验
3. **0 Credits 分析**: 即使 credits=0，只要 `billing_model_uid` 设为 0 成本的模型（或配额检查被禁用），用户就能继续使用

## 与 Unleash 特征开关的配合

```
billing_model_uid 分离
         │
         ├── trajectory-billing-system = OFF
         │    (不使用轨迹计费系统)
         │
         ├── CASCADE_ENFORCE_QUOTA = OFF
         │    (配额强制执行被禁用)
         │
         └── billing-use-quota-for-plg = OFF
              (PLG 用户配额检查关闭)
```

这三个开关关闭时，计费系统虽然存在，但不会被强制执行。

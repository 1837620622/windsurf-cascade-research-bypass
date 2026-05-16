# archive_old_assumptions/

**已被实测推翻的旧推论**和**中间过渡脚本**。保留作为研究历史，警示后人不要再走这些死路。

## 旧推论文档（按"错误程度"标注）

| 文件 | 错误点 |
|---|---|
| `02-protobuf-protocol-analysis.md` | schema 推断有偏差，`ModelUsageStats` 三字段被误以为是 GetChatMessage 请求字段 |
| `03-unleash-flags-OUTDATED.md` | 写"`CASCADE_ENFORCE_QUOTA = OFF`"，实测 = ON |
| `04-api-traffic-analysis.md` | 端点列表不全，新版见 docs/00-architecture.md |
| `05-billing-three-models-WRONG.md` | 推测三模型分离让 Opus 用 Mini 价计费——抓包没找到证据 |
| `06-mitm-issues-log.md` | 早期抓包问题记录 |
| `07-feasibility-plan.md` | 早期方案规划，部分已实施部分作废 |
| `08-flow-data-summary.md` | 早期流量数据摘要 |
| `09-test-log.md` | 第一轮 mitmdump 验证日志 |
| `11-zero-quota-theory-WRONG.md` | 基于 03/05 的错误推论展开 |
| `12-zero-quota-final-WRONG.md` | 基于 11 的错误展开（"拦 Unleash 让 ENFORCE_QUOTA=false 即可"，实测无效） |
| `FINAL-zero-opus-path-EARLY.md` | 早期"final"结论，后被 02-bypass-options-tested.md 取代 |
| `REAL_BYPASS_FINDINGS_old.md` | 早期实测发现，已合并入主 README |
| `v7-summary.md` | 第 7 轮总结，已被根 README 取代 |
| `README_old.md` | 旧版根 README |

## 旧脚本（`old_scripts_capture/`）

被 `tools/` 里干净版本取代：
- `decode_flow.py`、`dump_flow.py`、`dump_unleash.py`、`inventory.py`、`probe_unleash.py`、`raw_gcm_resp.py`、`tag.py`

## `wf-bypass-go/`

第 v7 轮的 Go 工具，用 goproxy 拦截 Unleash + 改 GetUserStatus + 改 GetChatMessage。**所有路线均无效**（v7-summary.md 自己也确认）。源码留作参考，已删编译产物。

## 教训

1. **不要相信本地缓存的 feature flag**——服务端有自己的 enforcement
2. **不要假设客户端 protobuf 字段就是请求 schema**——`ModelUsageStats` 是上报结构，不是请求结构
3. **HS256 JWT 是服务端签的**——任何客户端 patch 改不动
4. **服务端只看 JWT 里的 user-id 查实时数据库**——改 body 没用

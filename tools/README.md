# tools/

可执行工具集。所有脚本都是纯 Python（依赖 `mitmproxy` Python 包）。

## 工具表

| 文件 | 类型 | 用途 |
|---|---|---|
| `rewrite_model.py` | mitm addon | **主工具**。请求改写 (Opus → kimi-k2-6) + 响应回写。挂在 mitmdump 上。 |
| `plan_rewrite_addon.py` | mitm addon | 实验：改 GetUserStatus 响应里 `plan_name` `Pro→Max`。**实测无效**（客户端 UI 变化但 quota gate 不动）。 |
| `gcm_tool.py` | CLI | GetChatMessage 改装。`decode <bin>` 看顶层字段；`swap <in> <old> <new> <out>` 替换字符串字段。 |
| `extract_creds.py` | CLI | 从 mitm 抓包里抽最新的内层 JWT (devin-synthetic-apikey)。 |
| `scan_chat.py` | CLI | 扫描抓包文件，列出所有 chat 端点 + 状态码统计 + 真实回复 (resp>1KB) 数量。 |
| `full_compare.py` | CLI | 对成功 vs 失败的 GetChatMessage 请求做顶层字段 diff。 |

## 用法

```bash
# 启 mitm 加载主 addon（kimi-k2-6 模式）
mitmdump --listen-port 8080 -s tools/rewrite_model.py --set http2=true

# 解 GetChatMessage protobuf
python3 tools/gcm_tool.py decode original_gcm_req.bin

# 替换字符串字段（同长度直接替换；变长度自动重打 protobuf 长度前缀）
python3 tools/gcm_tool.py swap in.bin claude-opus-4-7-max-fast kimi-k2-6 out.bin

# 列抓包里的端点
python3 tools/scan_chat.py /tmp/wf_run/flows.mitm

# 找最新 inner JWT（用于手工 curl 测试）
python3 tools/extract_creds.py /tmp/wf_run/flows.mitm

# 成功/失败 diff
python3 tools/full_compare.py /tmp/wf_run/flows.mitm
```

## 依赖

```bash
pip install mitmproxy   # 12.x
# brotli 需要时装: pip install brotli
```

## 安全说明

- `extract_creds.py` 输出真 JWT。**不要 commit 输出！**
- 所有工具都假设你是**自己账号**做研究，不是攻击别人账号

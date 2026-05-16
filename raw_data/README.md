# raw_data/

原始抓包数据 + 解码产物。**所有文件已通过根 `.gitignore` 排除**（含真实凭据）。

## 内容

| 文件 | 大小 | 内容 |
|---|---|---|
| `original_getchatmessage_req.bin` | 46 KB | 一次完整的 GetChatMessage 请求体（已解码 protobuf） |
| `unleash_features.json` | 790 KB | 一次完整的 Unleash feature flag 响应 |
| `capture_2026-05-16/` | 11 MB | 整轮抓包 + 各端点解码结果 |

## capture_2026-05-16/ 文件

| 文件 | 内容 |
|---|---|
| `flows.mitm` | 169 个 flow 的完整 mitm 抓包 |
| `mitm.log` | mitmdump 实时事件日志 |
| `decoded_gcm.txt` | 3 次 GetChatMessage 详细解码（含 21KB Cascade 系统提示、40+ 工具定义） |
| `decoded_traj.txt` | 含 `failed_precondition: weekly usage quota has been exhausted` 错误 |
| `decoded_planstatus.txt` | Pro 配额表 + 79 个模型的 float32 倍率 |
| `decoded_status.txt` | GetUserStatus 完整响应（plan=Pro tier=16 quota=16384） |
| `decoded_userstatus_codeium.txt` | server.codeium.com 的 GetUserStatus 47KB 版本（含模型映射） |
| `decoded_generator.txt` | RecordCortexGeneratorMetadata（含 `[34]/[35]` model_uid 双字段） |
| `decoded_unleash.txt` | Unleash 响应解码 |
| `unleash_toggles.txt` | 220 个 toggle 的 ON/OFF 状态及 payload |

## 复现

```bash
# 启 mitmdump
mitmdump --listen-port 8080 -w flows.mitm --set http2=true

# 用代理变量启 Windsurf 触发流量
HTTPS_PROXY=http://127.0.0.1:8080 /Applications/Windsurf.app/Contents/MacOS/Windsurf
# 在 Cascade 发消息

# 用项目工具解码
python3 ../tools/scan_chat.py flows.mitm
python3 ../tools/gcm_tool.py decode some_request.bin
```

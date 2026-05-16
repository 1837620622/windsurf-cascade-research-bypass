# evidence/

实测抓包文件（`.mitm`）目录。**因含真实 JWT / account-id / email，已通过根 `.gitignore` 排除，不会提交到 GitHub**。

## 本目录文件（本地保留）

- `2026-05-16_final_with_rewrite.mitm`（8.8 MB）
  最终一轮 mitm + `rewrite_model.py` 改写后的真实流量。证明 `kimi-k2-6` 改写返回 OK 26KB 真实回复。
- `legacy/2026-05-16_initial_rewrite.mitm`（6.9 MB）
  第一轮实验，target=`MODEL_CHAT_GPT_4_1_2025_04_14`。GCM 收到 `failed_precondition`，证明只换 enum 名不够。
- `legacy/2026-05-16_v2_with_fresh_jwt.mitm`（30 MB）
  第二轮，包含新 JWT 取证 + AssignModel/AssignArenaModel/SubscribeToPlan 等多端点暴力测试痕迹。

## 复现

要在自己机器上生成等价数据：

```bash
mitmdump --listen-port 8080 -w your-capture.mitm -s ../tools/rewrite_model.py --set http2=true &
HTTPS_PROXY=http://127.0.0.1:8080 /Applications/Windsurf.app/Contents/MacOS/Windsurf
# 在 Cascade 里发消息
```

## 解析

使用 `tools/scan_chat.py` 列端点统计；`tools/full_compare.py` 对成功/失败请求做 diff；`tools/gcm_tool.py decode <bin>` 看 protobuf 顶层字段。

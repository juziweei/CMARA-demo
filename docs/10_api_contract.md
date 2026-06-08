# 10 · Demo HTTP API 契约

> 这是当前服务器 demo 后端已经提供的最小 HTTP 接口。
> 它是给前端展示层接入用的，不是通用多租户服务。

---

## 1. 启动方式

服务器：

```bash
ssh -p 57003 root@114.215.186.130
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

默认监听：

```text
http://127.0.0.1:8010
```

---

## 2. 约束

- 当前只支持一个 demo session：`session_id="default"`
- 当前接口没有鉴权
- 当前接口允许跨域：`Access-Control-Allow-Origin: *`
- 当前接口响应都是 `application/json`

---

## 3. 路由总览

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `GET` | `/preferences` | 读取当前结构化偏好表 |
| `POST` | `/turn` | 提交用户一轮输入 |
| `POST` | `/clarification` | 回答上一轮追问 |
| `POST` | `/summarize` | 对当前 session 做离线偏好抽取 |
| `POST` | `/reset` | 清空 demo 数据并重建 runtime |

---

## 4. 端点详情

### 4.1 `GET /health`

请求：

```bash
curl http://127.0.0.1:8010/health
```

响应：

```json
{
  "status": "ok",
  "session_id": "default"
}
```

### 4.2 `GET /preferences`

请求：

```bash
curl http://127.0.0.1:8010/preferences
```

响应：

```json
{
  "session_id": "default",
  "preferences": [],
  "count": 0
}
```

每条 preference 的关键字段包括：

- `id`
- `preference`
- `value`
- `condition`
- `status`
- `source`
- `evidence`
- `lightmem_ref`

### 4.3 `POST /turn`

请求：

```bash
curl -X POST http://127.0.0.1:8010/turn \
  -H 'Content-Type: application/json' \
  -d '{"text":"周末一家人出去玩，好热啊。","session_id":"default"}'
```

请求体：

```json
{
  "text": "周末一家人出去玩，好热啊。",
  "session_id": "default"
}
```

响应核心字段：

- `status`
- `assistant_text`
- `decision`
- `tool_result`
- `retrieval_hits`
- `retrieved_preferences`
- `pending`
- `learned_preference`
- `expired_preferences`
- `decision_trace`

如果本轮需要继续追问，`status` 会是 `needs_user_input`，`pending` 结构如下：

```json
{
  "pending_id": "7ef8c5...",
  "question": "您感冒好些了吗？好了我设25度，还没好我设26.5度。",
  "original_context": "周末一家人出去玩，好热啊。"
}
```

如果本轮已直接执行，`status` 会是 `acted`。

### 4.4 `POST /clarification`

请求：

```bash
curl -X POST http://127.0.0.1:8010/clarification \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default","pending_id":"<上一轮返回的pending_id>","answer":"好多了，今天基本恢复了。"}'
```

请求体：

```json
{
  "session_id": "default",
  "pending_id": "<pending_id>",
  "answer": "好多了，今天基本恢复了。"
}
```

成功时会返回新的 turn result。若这次回答让系统学到了新偏好，会在响应里出现：

- `learned_preference`
- `expired_preferences`

### 4.5 `POST /summarize`

请求：

```bash
curl -X POST http://127.0.0.1:8010/summarize \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

响应：

```json
{
  "session_id": "default",
  "added_preferences": [],
  "count": 0
}
```

作用：

- 读取当前 session 的消息
- 调用 `DirectPreferenceExtractor(Qwen)`
- 写入 `PreferenceTable`

### 4.6 `POST /reset`

请求：

```bash
curl -X POST http://127.0.0.1:8010/reset \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

响应：

```json
{
  "session_id": "default",
  "status": "reset"
}
```

作用：

- 清空 `data/preferences.json`
- 清空 `data/qdrant`
- 删除 `data/history.db`
- 重建 runtime

---

## 5. 错误响应

错误响应统一是：

```json
{
  "error": "..."
}
```

典型情况：

- 空 `text`
- 空 `pending_id`
- 无效 JSON body
- 传入了非 `default` 的 `session_id`
- 找不到待回答的 `pending_id`

---

## 6. 前端接入建议

最小闭环只需要这 4 步：

1. 页面加载时先调 `GET /preferences`
2. 用户输入后调 `POST /turn`
3. 如果返回 `needs_user_input`，把下一次输入发到 `POST /clarification`
4. 展示结束后，按需调 `POST /summarize` 和 `POST /reset`

前端不需要保存 Python 内部对象，只要保存：

- 最近一次返回的 `pending.pending_id`
- 当前聊天记录
- 当前偏好表
- 当前 `decision_trace`

# 12 · 给别人使用的完整运行文档

> 这份文档面向第一次接触项目的人。
> 默认你已经拿到了这个仓库，并且站在仓库根目录执行命令。
> 文档只使用相对路径、环境变量和终端命令，不依赖作者个人机器路径。

---

## 1. 你会得到什么

这个项目提供两部分：

1. 一个车载长期记忆后端 demo
2. 一个可直接打开的静态前端演示页

它演示的是这条闭环：

```text
用户输入
-> 检索历史记忆与结构化偏好
-> 判断直接执行还是先追问
-> 用户回答追问
-> 系统学习新偏好
-> 下次相似场景减少重复追问
```

---

## 2. 仓库结构

在仓库根目录下，最常用的是：

```text
src/        后端代码
scripts/    启动脚本和场景脚本
frontend/   静态前端页面
docs/       文档
tests/      回归测试
data/       demo 运行时数据
```

---

## 3. 运行前准备

### 3.1 Python

要求：

```bash
python3 --version
```

建议使用 Python 3.10 或更高版本。

### 3.2 安装依赖

如果你使用当前环境中的 Python：

```bash
python3 -m pip install -e .
```

如果你使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

### 3.3 准备环境变量

复制模板：

```bash
cp .env.example .env
```

这个 demo 最关键的环境变量是：

```bash
export DEMO_LLM_BASE_URL=http://127.0.0.1:7200/v1
export DEMO_LLM_MODEL=Qwen2.5-14B-Instruct
export DEMO_LLM_API_KEY=EMPTY
export DEMO_QWEN_MODEL_PATH=<你的Qwen路径>
export DEMO_EMBEDDING_MODEL_PATH=<你的embedding模型路径>
export DEMO_LLMLINGUA_MODEL_PATH=<你的llmlingua模型路径>
```

如果你的环境已经能直接读取这些默认值，也可以不额外导出。

---

## 4. 先做环境检查

在仓库根目录执行：

```bash
python3 scripts/check_runtime.py
```

如果检查失败，先修复：

- `DEMO_LLM_BASE_URL`
- `DEMO_QWEN_MODEL_PATH`
- `DEMO_EMBEDDING_MODEL_PATH`
- `DEMO_LLMLINGUA_MODEL_PATH`

只有这一步通过，后面的 API 和前端才有意义。

---

## 5. 启动后端 API

在仓库根目录执行：

```bash
python3 scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

另开一个终端做健康检查：

```bash
curl http://127.0.0.1:8010/health
```

期望返回：

```json
{"status":"ok","session_id":"default"}
```

---

## 6. 启动前端页面

在仓库根目录执行：

```bash
cd frontend
python3 -m http.server 8080
```

然后浏览器打开：

```text
http://127.0.0.1:8080
```

页面默认会连接：

```text
http://127.0.0.1:8010
```

---

## 7. 一键演示全流程

前端里有一个按钮：

```text
一键全流程
```

它会自动做这些事：

1. 调用 `POST /demo/family_trip`
   - 重置 demo 数据
   - 播种 Day 0 的基础空调偏好
2. 送入一段家庭出游对话
3. 调用 `POST /summarize`
   - 写入家庭出游偏好
4. 发送“好热啊”
   - 触发追问
5. 自动回答“好多了，今天基本恢复了。”
   - 触发澄清学习
6. 再发送相似场景
   - 验证系统直接执行，不再重复问

这就是当前最稳的对外演示方式。

---

## 8. 普通用户自由对话

这个页面不只是演示按钮。

你也可以直接在输入框里自由输入，例如：

```text
今天路上有点无聊，放点轻音乐吧。
```

或者：

```text
今天天气怎么样？
```

页面会自动：

1. 调 `POST /turn`
2. 如果后端返回 `needs_user_input`
   - 下一条输入自动走 `POST /clarification`
3. 如果返回 `acted` 或 `replied`
   - 直接展示 assistant 回复和 trace

所以普通用户是可以直接交流的，不需要手动切换模式。

补充说明：

- 明确车控请求，优先走偏好决策与工具执行链路
- 普通提问、解释、闲聊，直接走 LLM 回复链路
- 像“我妻子不舒服，车里别太冷”这类语境，澄清学习会优先沉淀成 `passenger_health_state`

---

## 9. API 调用示例

### 9.1 健康检查

```bash
curl http://127.0.0.1:8010/health
```

### 9.2 看偏好表

```bash
curl http://127.0.0.1:8010/preferences
```

### 9.3 发一轮普通输入

```bash
curl -X POST http://127.0.0.1:8010/turn \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default","text":"周末一家人要去海边了，好热啊。"}'
```

### 9.4 回答追问

```bash
curl -X POST http://127.0.0.1:8010/clarification \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default","pending_id":"<pending_id>","answer":"好多了，今天基本恢复了。"}'
```

### 9.5 手动做离线总结

```bash
curl -X POST http://127.0.0.1:8010/summarize \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

### 9.6 重置 demo

```bash
curl -X POST http://127.0.0.1:8010/reset \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

### 9.7 播种一键演示初始状态

```bash
curl -X POST http://127.0.0.1:8010/demo/family_trip \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

---

## 10. 纯终端跑完整场景

如果你不想开前端，也可以直接在终端跑完整脚本：

```bash
python3 scripts/run_family_trip_scenario.py --reset
```

或者跑更长的多天场景：

```bash
python3 scripts/run_full_scenario.py --reset
```

---

## 11. 回归测试

最小建议先跑：

```bash
pytest tests/test_api_service.py
```

完整回归：

```bash
pytest
```

---

## 12. 别人拿到仓库后的最短路径

如果你要把这个项目交给别人，最短操作顺序就是：

1. 克隆仓库
2. 安装依赖
3. 配好 `.env` / `DEMO_*`
4. 运行：

```bash
python3 scripts/check_runtime.py
python3 scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

5. 新开一个终端运行：

```bash
cd frontend
python3 -m http.server 8080
```

6. 浏览器打开：

```text
http://127.0.0.1:8080
```

7. 点击：

```text
一键全流程
```

---

## 13. 常见问题

### 13.1 `check_runtime.py` 失败

先看是不是以下变量没配对：

```bash
DEMO_LLM_BASE_URL
DEMO_QWEN_MODEL_PATH
DEMO_EMBEDDING_MODEL_PATH
DEMO_LLMLINGUA_MODEL_PATH
```

### 13.2 前端显示离线

先确认后端健康检查：

```bash
curl http://127.0.0.1:8010/health
```

再确认你是否真的在 `frontend/` 目录启动了静态服务：

```bash
cd frontend
python3 -m http.server 8080
```

### 13.3 一键全流程按钮没反应

先确认 API 已包含这个端点：

```bash
curl -X POST http://127.0.0.1:8010/demo/family_trip \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

如果返回 `route not found`，说明你跑的不是当前仓库代码，或者 API 服务需要重启。

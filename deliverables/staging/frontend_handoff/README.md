# CMARA Demo

一个面向演示的车载长期记忆系统。

它要展示的不是“车控功能很多”，而是下面这条完整闭环：

```text
用户当前输入
-> 检索历史记忆与结构化偏好
-> 判断应该直接执行，还是先追问
-> 用户回答追问后，学习新偏好
-> 当天对话结束后，离线抽取可复用偏好
-> 下次相似场景再来时，减少重复追问
```

这个仓库服务的是 demo 展示，不是论文评测管线。目标是把“系统为什么这样决策、学到了什么、下次为什么不再问”这件事做得真实、稳定、可解释。

## 1. 这个 demo 在演什么

最核心的能力是三件事：

1. 能记住用户偏好  
2. 不确定时会主动追问，而不是瞎猜  
3. 追问得到回答后，能把这次结果学成下次可复用的偏好  

典型场景：

```text
用户之前说过：
- 平时空调 25 度舒服
- 感冒没好时 26.5 度更舒服

后来用户上车说：
- “好热啊”

系统会发现：
- 历史里有两条都相关，但当前缺一个关键条件：感冒好了没

所以系统不会直接猜，而是会问：
- “您感冒好些了吗？好了我设 25 度，还没好我设 26.5 度。”

如果用户回答：
- “好多了，今天基本恢复了”

系统会：
- 执行 `set_ac_temperature(25)`
- 学到一条新偏好：`health_state == recovering -> 25`
- 把旧的 `health_state == sick -> 26.5` 标记为过期
```

这就是这个 demo 最有说服力的地方。

## 1.1 明天展示材料

如果目标是面向前端展示、论文/技术路线说明、投资人或资源方沟通，先看：

- [docs/13_showcase_technical_route_and_resource_plan.md](docs/13_showcase_technical_route_and_resource_plan.md)

这份文档已经把 2026-07-02 展示需要的内容串起来：

- 前端现场展示流程
- 30 秒 / 2 分钟 / 5 分钟讲解词
- 从论文角度包装的技术问题
- 与 RAG、长期记忆、Agent memory 工作的关系
- 后续需要的算力、云服务、数据、标注、人力和车载合作资源
- 可直接放进 PPT 的结构
- 展示前检查清单

## 2. 当前已经完成什么

当前后端已经完成并验证过的能力：

- LightMem 记忆存储与检索
- 结构化偏好表
- `Policy` 的 ACT / ASK 决策
- 澄清回答后的偏好学习
- `DirectPreferenceExtractor(Qwen)` 离线偏好抽取
- 面向前端接入的最小 HTTP API
- 服务器侧运行文档与接手文档

目前这条后端闭环已经在服务器上跑通：

- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `GET /preferences`
- `POST /reset`
- `POST /demo/family_trip`

## 3. 当前没有做什么

这几个边界是刻意保留的：

- `music_mode` 能被记住、检索、展示，但还没有真实执行工具
- API 目前是单 session demo 形态，固定 `session_id="default"`
- condition schema 还比较窄，只覆盖当前 demo 需要的关键维度
- 这个仓库不包含完整的 benchmark 真值维护和论文实验管线

换句话说，这是一套“演示闭环已经完整”的工程，而不是“产品已经完整”的工程。

## 4. 系统结构

```text
src/
  action/         工具函数与 LLM client
  interface/      session runtime、API service、HTTP API、CLI
  memory/         LightMem 封装、偏好表、澄清学习、离线总结
  policy/         ACT / ASK 决策层
scripts/          场景脚本、benchmark、API 启动脚本
docs/             架构、运行手册、交接文档、API 契约
tests/            后端回归测试
```

最关键的几个入口：

- 会话状态机：`src/interface/session.py`
- 共享 runtime：`src/interface/runtime.py`
- API service：`src/interface/api_service.py`
- HTTP API：`src/interface/http_api.py`
- API 启动脚本：`scripts/run_api_server.py`

## 5. 运行前提

默认假设你站在仓库根目录执行命令。

关键环境变量：

- `DEMO_LLM_BASE_URL`
- `DEMO_LLM_MODEL`
- `DEMO_QWEN_MODEL_PATH`
- `DEMO_EMBEDDING_MODEL_PATH`
- `DEMO_LLMLINGUA_MODEL_PATH`

可先复制模板：

```bash
cp .env.example .env
```

建议先做 runtime 检查：

```bash
python3 scripts/check_runtime.py
```

如果你需要服务器侧的固定运行事实，见 [docs/07_server_runbook.md](docs/07_server_runbook.md)。

## 6. 快速运行

### 6.1 启动 HTTP API

```bash
python3 scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/health
```

### 6.2 运行 CLI

```bash
python3 src/interface/cli.py --debug
```

### 6.3 运行主场景

```bash
python3 scripts/run_family_trip_scenario.py --reset
```

### 6.4 启动静态前端

```bash
cd frontend
python3 -m http.server 8080
```

浏览器打开：

```text
http://127.0.0.1:8080
```

## 7. HTTP API

服务地址：

```text
http://127.0.0.1:8010
```

接口：

- `GET /health`
- `GET /preferences`
- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `POST /reset`
- `POST /demo/family_trip`

最小接入流程：

1. 前端发送 `POST /turn`
2. 如果返回 `needs_user_input`，保存 `pending.pending_id`
3. 用户下一次回答发到 `POST /clarification`
4. 用 `GET /preferences` 展示结构化偏好
5. 用 `POST /summarize` 在一段对话结束后抽取可复用偏好

如果你要做“一键全流程”按钮，先调用：

- `POST /demo/family_trip`

完整字段契约见 [docs/10_api_contract.md](docs/10_api_contract.md)。

## 8. 当前验证状态

本地已验证：

- `pytest`
- 最近一次结果：`34 passed`

服务器已验证：

- runtime 检查通过
- HTTP 真机闭环通过：
  - `reset`
  - `turn`
  - `summarize`
  - `turn`
  - `clarification`
  - `preferences`

最近一次服务器观测结果：

- 一段长家庭出游对话可以离线抽出 3 条结构化偏好
- 后续“好热啊”的场景会先 ASK
- 回答“好多了，今天基本恢复了”后，系统会：
  - 执行 `set_ac_temperature(value=25)`
  - 学到 `health_state == recovering`
  - 让旧的 `health_state == sick` 偏好过期

## 9. 如果你要接手

建议先看这几份文档：

- [docs/06_backend_closure.md](docs/06_backend_closure.md)
- [docs/07_server_runbook.md](docs/07_server_runbook.md)
- [docs/08_frontend_handoff.md](docs/08_frontend_handoff.md)
- [docs/10_api_contract.md](docs/10_api_contract.md)
- [docs/11_next_goal.md](docs/11_next_goal.md)
- [docs/12_runbook_for_others.md](docs/12_runbook_for_others.md)
- [docs/13_showcase_technical_route_and_resource_plan.md](docs/13_showcase_technical_route_and_resource_plan.md)

如果你是做前端展示层，优先接现有 HTTP API，不要先重写后端状态机。

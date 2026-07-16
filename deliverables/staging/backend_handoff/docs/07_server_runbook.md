# 07 · 服务器运行手册（可复现版）

> 这份手册只写服务器侧事实，供接手人直接登录服务器复现 demo。
> 不包含本地开发路径。

---

## 1. 登录与项目位置

SSH：

```bash
ssh -p 57003 root@114.215.186.130
```

项目根目录：

```bash
/root/vehicle_memory_demo
```

进入项目后的标准前置命令：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
```

Python 解释器固定使用：

```bash
/data/miniconda3/envs/lightmem/bin/python
```

LightMem 源码路径：

```bash
/data/vmr_project/external/LightMem/src
```

---

## 2. 当前运行环境

### 2.1 LLM 服务

当前后端默认连接：

```bash
http://127.0.0.1:7200/v1
```

模型名：

```bash
Qwen2.5-14B-Instruct
```

可直接检查模型服务：

```bash
curl http://127.0.0.1:7200/v1/models
```

如果服务正常，响应里会看到：

```text
Qwen2.5-14B-Instruct
```

### 2.2 本地模型路径

Qwen 路径：

```bash
/data/cache/modelscope/hub/models/Qwen/Qwen2.5-14B-Instruct
```

Embedding 模型路径：

```bash
/data/cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/c9745ed1d9f207416be6d2e6f8de32d1f16199bf
```

LLMLingua 路径：

```bash
/data/cache/huggingface/hub/models--microsoft--llmlingua-2-bert-base-multilingual-cased-meetingbank/snapshots/5f0c82792b7ea14c6484e015b6a072009496b7f2
```

---

## 3. 配置文件

服务器上最重要的配置相关文件：

- `/root/vehicle_memory_demo/.env.example`
- `/root/vehicle_memory_demo/src/config.py`
- `/root/vehicle_memory_demo/scripts/check_runtime.py`

当前服务器没有依赖额外导出的 `DEMO_*` 环境变量，主要使用的是 `src/config.py` 默认值。

当前关键默认值：

```text
DEMO_LLM_BASE_URL=http://127.0.0.1:7200/v1
DEMO_LLM_MODEL=Qwen2.5-14B-Instruct
DEMO_LLM_API_KEY=EMPTY
DEMO_LIGHTMEM_UPDATE=offline
DEMO_LIGHTMEM_EXTRACTION_MODE=flat
DEMO_LIGHTMEM_PRE_COMPRESS=true
DEMO_LIGHTMEM_MAX_TOKENS=512
DEMO_LIGHTMEM_EXTRACT_THRESHOLD=0.1
DEMO_LIGHTMEM_COMPRESS_RATE=1.0
DEMO_PREFERENCES_PATH=data/preferences.json
DEMO_QDRANT_PATH=data/qdrant
DEMO_HISTORY_DB_PATH=data/history.db
```

---

## 4. 目录结构（只列接手时最常用的）

```text
/root/vehicle_memory_demo
├── src/
│   ├── action/
│   ├── interface/
│   ├── memory/
│   └── policy/
├── scripts/
├── data/
├── docs/
└── tests/
```

### 4.1 核心后端文件

- `/root/vehicle_memory_demo/src/interface/session.py`
- `/root/vehicle_memory_demo/src/interface/runtime.py`
- `/root/vehicle_memory_demo/src/interface/api_service.py`
- `/root/vehicle_memory_demo/src/interface/http_api.py`
- `/root/vehicle_memory_demo/src/policy/policy.py`
- `/root/vehicle_memory_demo/src/memory/lightmem_store.py`
- `/root/vehicle_memory_demo/src/memory/preference_table.py`
- `/root/vehicle_memory_demo/src/memory/clarification_learner.py`
- `/root/vehicle_memory_demo/src/memory/direct_preference_extractor.py`
- `/root/vehicle_memory_demo/src/memory/offline_summarizer.py`
- `/root/vehicle_memory_demo/src/action/car_functions.py`

### 4.2 主要脚本

- `/root/vehicle_memory_demo/scripts/check_runtime.py`
- `/root/vehicle_memory_demo/scripts/run_family_trip_scenario.py`
- `/root/vehicle_memory_demo/scripts/run_full_scenario.py`
- `/root/vehicle_memory_demo/scripts/run_api_server.py`
- `/root/vehicle_memory_demo/scripts/benchmark_qwen_preference_extraction.py`
- `/root/vehicle_memory_demo/scripts/benchmark_long_dialogue.py`

### 4.3 注意

项目根目录下还有这些同名文件：

- `/root/vehicle_memory_demo/config.py`
- `/root/vehicle_memory_demo/session.py`
- `/root/vehicle_memory_demo/check_runtime.py`

接手时优先以 `src/` 和 `scripts/` 为准，不要把根目录同名文件当主入口。

---

## 5. 数据位置

默认数据目录：

```bash
/root/vehicle_memory_demo/data
```

当前主要数据文件/目录：

- 结构化偏好表：`/root/vehicle_memory_demo/data/preferences.json`
- Qdrant 数据：`/root/vehicle_memory_demo/data/qdrant`
- history db：`/root/vehicle_memory_demo/data/history.db`

当前还能看到的 benchmark/实验目录：

- `/root/vehicle_memory_demo/data/benchmark_lightmem_fact_ab`
- `/root/vehicle_memory_demo/data/qdrant_debug_force`
- `/root/vehicle_memory_demo/data/qdrant_debug_force2`

---

## 6. 最常用命令

### 6.1 运行 runtime 检查

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/check_runtime.py
```

### 6.2 跑 family trip demo 场景

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_family_trip_scenario.py --reset
```

### 6.3 跑完整多天场景

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_full_scenario.py --reset
```

### 6.4 跑直接偏好抽取 benchmark

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/benchmark_qwen_preference_extraction.py --days 3 --drives-per-day 2 --target-chars 2200 --show-drives --show-items 2
```

### 6.5 跑长对话查找 benchmark

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/benchmark_long_dialogue.py --reset --dataset scale_15d --days 15 --drives-per-day 2 --target-chars 2200 --repeat 8 --warmup 1
```

### 6.6 运行 CLI

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python src/interface/cli.py --debug
```

### 6.7 启动 HTTP API

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/health
```

如果前端和服务都在服务器上，这个端口就够用了。
如果前端跑在别的机器上，需要再确认安全组/端口暴露策略。

### 6.8 常用 API 调试命令

完整字段契约见：

```bash
/root/vehicle_memory_demo/docs/10_api_contract.md
```

重置 demo：

```bash
curl -X POST http://127.0.0.1:8010/reset \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

发送一轮用户输入：

```bash
curl -X POST http://127.0.0.1:8010/turn \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default","text":"周末一家人出去玩，好热啊。"}'
```

查看结构化偏好：

```bash
curl http://127.0.0.1:8010/preferences
```

做离线偏好抽取：

```bash
curl -X POST http://127.0.0.1:8010/summarize \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default"}'
```

回答上一轮追问：

```bash
curl -X POST http://127.0.0.1:8010/clarification \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"default","pending_id":"<上一轮返回的pending_id>","answer":"好多了，今天基本恢复了。"}'
```

---

## 7. 当前最值得前端复现的脚本

优先推荐：

```bash
scripts/run_family_trip_scenario.py --reset
```

原因：

- 它能完整演示离线偏好抽取
- 能演示 ASK -> 用户回答 -> 学到新偏好
- 能演示旧偏好过期
- 能演示下一次相似场景少问

如果前端只做一个 demo 页面，建议就围绕这条场景链展示。

---

## 8. reset 相关

`run_family_trip_scenario.py --reset` 和 `run_full_scenario.py --reset` 会清理：

- `preferences.json`
- `qdrant` 目录下的内容
- `history.db`

所以在演示前，若想得到稳定初始状态，直接跑带 `--reset` 的场景脚本。

---

## 9. 常见排障

### 9.1 `scripts/check_runtime.py` 失败

先看：

```bash
curl http://127.0.0.1:7200/v1/models
```

如果连不上，说明 vLLM 服务没起或端口不对。

### 9.2 Python 包或模型路径问题

先跑：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/check_runtime.py
```

它会打印：

- Qwen 路径
- Embedding 路径
- LLMLingua 路径
- 模型是否存在
- 可见模型列表

### 9.3 benchmark 或 scenario 首次运行慢

这是正常的。当前慢的主要不是检索，而是：

- LightMem 的离线处理
- Qwen 的直接偏好抽取

查找本身在 benchmark 里是毫秒级。

### 9.4 LightMem JSON 抽取报错

当前应用层已经做了 JSON salvage / retry 包装，位置：

```bash
/root/vehicle_memory_demo/src/memory/lightmem_store.py
```

所以如果日志里看到一次 JSON decode error，不代表整条链直接失败，需要看最终是否仍产出了 `cleaned_result`。

---

## 10. 一句话总结

要在服务器上复现当前 demo，记住三件事就够了：

1. 用固定 Python：`/data/miniconda3/envs/lightmem/bin/python`
2. 先设 `PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo`
3. 从 `scripts/run_family_trip_scenario.py --reset` 开始跑

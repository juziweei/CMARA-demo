# 04 · 搭建指南（给实现 agent）

> 先读完 `00`~`03`。本文件是动手步骤：目录结构、依赖、搭建顺序、怎么跑起来。

---

## 1. 总原则（再强调一次）

- **不造轮子**：记忆/检索用 LightMem（现成）；LLM 用服务器上的 Qwen（现成）；embedding 用 MiniLM（现成）。
- **只新写三块**：决策层 Policy、车控函数(mock)+ask_user、交互层(CLI)。
- **真实结构**：记忆真存 LightMem、检索真用 embedding、决策真用 LLM。不许硬编一个假 demo。
- **不碰论文管线**：不做评测/基线/risk-coverage。

---

## 2. 前置条件（人工在服务器准备，agent 不负责起服务）

> ⚠️ **运行环境与开发环境分离**：
> - **Demo 运行在服务器**（有 GPU）：vLLM、LightMem 的离线抽取（memory_manager 调 Qwen）、embedding 都在服务器跑。
> - **写代码的 agent 在本地**：agent 负责写/改代码、通过 ssh 操作服务器上的工程目录、在服务器上跑 demo。
> - **关键限制**：agent 在本地起不了服务器的 GPU 服务。vLLM 服务由**人工**在服务器起；agent 写好的 demo 代码也**在服务器上运行**（不是在本地跑），所以 demo 进程本身能直接访问服务器 GPU。

**人工准备（在服务器）**：
1. 起一个带 tool-calling 的 Qwen 服务（14B 优先），供 demo 的决策层调用：
   ```
   CUDA_VISIBLE_DEVICES=<空卡> vllm serve /data/cache/modelscope/hub/models/Qwen/Qwen2.5-14B-Instruct \
     --port 7200 --enable-auto-tool-choice --tool-call-parser hermes \
     --served-model-name Qwen2.5-14B-Instruct --max-model-len 32768 --gpu-memory-utilization 0.6
   ```
   （tmux 起、detach；端口 7200 避开论文实验端口）
2. 确认服务器本机 `curl http://127.0.0.1:7200/v1/models` 能返回。

**Demo 代码的运行位置**：
- Demo **在服务器上运行**（agent 在本地写代码、push/同步到服务器、在服务器执行）。
- 因为 demo 在服务器跑，它的决策层直接连服务器本机的 `http://127.0.0.1:7200/v1`（不需要隧道）。
- **LightMem 的 memory_manager** 直接用服务器本地 Qwen 路径（`/data/cache/modelscope/hub/models/Qwen/...`），离线总结/抽取在服务器 GPU 上跑——这是离线总结能力的前提（见 `05_memory_lifecycle.md §3`）。
- **embedding（MiniLM）** 跑 CPU 即可（现成脚本就是 `device:cpu`）。

> 给本地的 agent：你写代码在本地，但 demo 跑在服务器。涉及"运行 demo / 跑测试"的命令要在服务器上执行（通过 ssh）。LightMem 的离线抽取需要 GPU——因为 demo 在服务器跑，这一步没问题，正常配 memory_manager 指向本地 Qwen 即可。不要假设 demo 在本地无 GPU 环境跑。

---

## 3. 目录结构

```
vehicle_memory_demo/
├── docs/                          # 本套文档
│   ├── 00_overview.md
│   ├── 01_architecture.md
│   ├── 02_memory_schema.md
│   ├── 03_decision_policy.md
│   ├── 04_build_guide.md
│   └── 05_memory_lifecycle.md     # 三条记忆路径(即时/离线总结/澄清学习)
├── src/
│   ├── memory/
│   │   ├── lightmem_store.py      # 封装 LightMem（add/retrieve/离线抽取）
│   │   ├── preference_table.py    # 结构化偏好表（condition/status/source/过期）
│   │   ├── offline_summarizer.py  # ② 离线总结：从当天对话归纳偏好
│   │   └── clarification_learner.py  # ③ 澄清学习：把"情景+选择"沉淀成偏好
│   ├── action/
│   │   ├── car_functions.py       # mock 车控函数 + ask_user + TOOLS_META
│   │   └── llm_client.py          # 连 vLLM 的客户端（tool-calling）
│   ├── policy/
│   │   └── policy.py              # ★ 决策层 Policy.decide()
│   ├── interface/
│   │   └── cli.py                 # 主循环 + /memory + /forget + /summarize
│   └── config.py                  # 模型路径、端口、embedding路径等
├── data/
│   └── preferences.json           # 结构化偏好表持久化（demo 用）
├── scripts/
│   └── run_full_scenario.py       # 跑多天完整场景（含离线总结+澄清学习）
├── tests/
│   └── test_policy.py             # 03§4 + 05§8 的验收测试
├── .env                           # 模型路径、API地址等（不进git）
├── pyproject.toml / requirements.txt
└── README.md
```

---

## 4. 搭建顺序（自底向上，每步可独立验证）

### Step 1 · 配置 + LLM 客户端
- `config.py`：填 vLLM 地址(`http://127.0.0.1:7200/v1`)、模型名、Qwen路径、MiniLM路径、qdrant目录。
- `llm_client.py`：封装对 vLLM 的 chat 调用，支持 `tools` + `tool_choice="auto"`，能解析返回的 `tool_calls`。
- **验证**：打一条带 tools 的请求，确认能拿到 tool_calls（参考论文项目里验证 tool-calling 的 curl）。

### Step 2 · 车控函数（mock）
- `car_functions.py`：定义 `set_ac_temperature` / `set_seat_heating` / `ask_user`，执行时只 print/记录，返回结构化结果。定义 `TOOLS_META`（cost/reversible）和 OpenAI tools schema。
- **验证**：手动调用每个函数，确认返回格式正确。

### Step 3 · 记忆层（含三条写入路径，见 `05_memory_lifecycle.md`）
- `lightmem_store.py`：照 `00_overview §5` 的配置创建 LightMemory，封装：
  - `add(messages)` — 积累对话（路径①②的输入）
  - `retrieve(query)` — embedding 检索
  - `offline_extract(messages)` — 触发离线抽取（`force_segment=True, force_extract=True`，配置用 aggressive 模式）
- `preference_table.py`：结构化偏好表（JSON 持久化），实现 `add_preference(含source字段)`、`get_active`、`mark_expired`、`find_relevant(query, lightmem)`。
- `offline_summarizer.py`（路径②）：输入当天对话 → 调 lightmem 离线抽取 + LLM 归纳 → 产出 `source=offline_summary` 的偏好，写入偏好表。详见 `05 §3`。
- `clarification_learner.py`（路径③）：输入"一次ASK的情景 + 用户回答" → 组装成 `source=learned_from_clarification` 的新偏好（condition 取关键决定因素，见 `05 §4`）→ 写入偏好表。
- **验证**：
  - 存两条偏好（默认25 / 感冒26.5），retrieve "好热" 能召回。
  - 喂一段含多次"关音乐"的对话 → `offline_extract` 能归纳出"偏好安静"（真 LLM 总结，非硬编）。

### Step 4 · 决策层（核心）
- `policy.py`：实现 `Policy.decide(context, retrieved_prefs) -> Decision`，按 `03_decision_policy.md`。
- 决策层**不区分偏好 source**（user_stated / offline_summary / learned 一视同仁参与判断，见 `05 §5`）。
- **验证**：跑 `03 §4` 的四个测试（该问/不该问/换场景/补全后执行）。**Demo 真假的判定关。**

### Step 5 · 交互层（CLI）
- `cli.py`：主循环——读输入 → find_relevant → policy.decide → 执行(ACT/ASK) → 若ASK得到回答则**调 clarification_learner 沉淀偏好**(路径③) → 必要时 mark_expired → 回复。
- 命令：`/memory`（看偏好表，区分显示三种 source）、`/forget <id>`（删/过期）、`/summarize`（手动触发离线总结，路径②，显式打印总结出的偏好，见 `05 §3`）。
- **验证**：完整走一遍多天场景（`05 §7`）。

### Step 6 · 验收
- `scripts/run_full_scenario.py`：脚本化跑 `05 §7` 的多天场景，确认每一幕行为正确。
- 跑 `tests/test_policy.py`（含 `03 §4` 决策测试 + `05 §8` 记忆路径测试）。

---

## 5. 依赖（requirements）

复用现成，主要是：
```
lightmem            # 记忆（作者已用过，确认版本与现成脚本一致）
qdrant-client       # LightMem 的向量后端（本地模式）
sentence-transformers  # MiniLM embedding（或 LightMem 通过 huggingface 间接用）
openai              # 连 vLLM 的 OpenAI 兼容接口（或用 requests）
pydantic            # 数据结构
```
> 版本对齐：LightMem 的具体版本和依赖，以作者现成脚本 `run_lightmem_vehiclemem_minimal.py` 跑通时的环境为准。先确认那个环境能复现，再在其上搭 demo。
> LightMem 的 memory_manager（离线总结用）直接指向服务器本地 Qwen 路径——因为 demo 在服务器跑，这一步有 GPU 可用。

---

## 6. 验收标准（Demo 合格的定义）

1. **多天场景完整跑通**（`05 §7`）：即时存偏好 → 离线总结 → 热天询问 → 澄清后执行+过期+学习 → 下次同情景不再问。
2. **决策层真实**：`03 §4` 四个测试全过（尤其"换场景不崩"和"可辨识时不多问"）。
3. **三条记忆路径都真实工作**（`05 §8`）：
   - ① 即时陈述：用户明说当场存。
   - ② **离线总结**：`/summarize` 能从一段对话**真的用 LLM 归纳**出新偏好（非硬编），显式展示。
   - ③ **澄清学习**：同情景出现两次，**第一次问、第二次直接执行不问**。
4. **记忆真实**：偏好真存 LightMem + 结构化表，retrieve 真走 embedding，不是硬编字典。
5. **记忆可见可改**：`/memory` 能看到偏好表（区分三种 source），`/forget` 能改。
6. **不依赖论文管线**：没有 import 论文的评测/诊断代码。

全部满足 = Demo 合格：一个有真实技术结构支撑、覆盖三条记忆路径（即时/离线总结/澄清学习）、能演完整长期记忆闭环、且换场景也成立的车载长期记忆系统。

---

## 7. 不要做的事

- ❌ 不要用 if-else 关键词匹配冒充检索（必须真用 LightMem embedding）。
- ❌ 不要在代码里写死"第三轮就问"这类硬编决策（必须真用 LLM 判断）。
- ❌ 不要硬编离线总结的结果（必须真的用 LLM 从对话归纳，否则路径②是假的）。
- ❌ 不要接入论文的 risk-coverage / 三层失败诊断 / scaling 实验。
- ❌ 不要把 Demo 扩成"大而全的规则系统"（保持最小、聚焦那条闭环）。
- ❌ 起 vLLM 服务是人工的事（agent 在本地起不了 GPU 服务）；demo 代码在服务器上运行，运行/测试命令通过 ssh 在服务器执行。

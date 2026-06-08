# 00 · 项目总览:车载长期记忆 Demo

> 这是一份给 Claude Code（实现 agent）的工程文档。先整篇读完 docs/ 下所有文件再动手。
> **本工程是 Demo，不是论文实验**。两者目标不同、代码独立，详见 §4。

---

## 1. 这个 Demo 要演什么

一个**有真实技术结构支撑**的车载长期记忆助手，演示一条完整闭环：

```
[初始] 用户：「我觉得空调 25 度比较舒服」
        → 系统记住：{空调温度=25, 条件=默认}
        → 回复：「好的，记住了，默认 25 度。」

[5.3]  用户：「我感冒了」
        → 系统记住：{空调温度=26.5, 条件=感冒时}
        → 回复：「了解，感冒期间我会调高到 26.5 度。」

[5.5]  天气很热，用户上车：「好热啊」
        → 系统检索到两条相关偏好：{25,默认} 和 {26.5,感冒时}
        → 系统判断：无法从当前对话确定「感冒好了没」→ 不确定 → 不自动设温度
        → 系统询问：「您感冒好些了吗？好了我设 25 度，还没好设 26.5 度。」
        → 用户：「好多了」
        → 系统：set_ac(25) + 把「感冒」那条偏好标记为过期
        → 回复：「给您设 25 度。已经把感冒期间的偏好取消了。」
```

**核心看点**：系统在「不确定该套用哪条偏好」时**主动询问，而不是瞎猜**；询问后**更新记忆**（感冒好了→过期）；整个过程记忆**可见、可改**。

**更进一步——这是一个"长期记忆"系统，记忆有三条写入路径（详见 `05_memory_lifecycle.md`）**：
1. **即时陈述**：用户明说"我感冒了" → 当场存。
2. **离线总结**：当天对话结束后，从整段对话**用 LLM 归纳**出用户没明说的偏好（如多次关音乐 → "爱安静"）。这是长期记忆的灵魂。
3. **澄清学习**：一次询问得到回答后，把"情景+选择"沉淀成偏好 → **下次同情景不用再问**（记得上次用户的选择）。

这三条路径让 Demo 是一个**真正会积累、会消化、越用越懂用户**的长期记忆系统，而不是只存聊天记录。

---

## 2. 一条铁律：Demo 必须有真实结构，不许"演出来好看"

这个 Demo **不是** 用一段 prompt 硬编一个假装智能的对话。它必须由真实组件支撑：

- 记忆是**真的存进 LightMem**（带 embedding 向量），不是写死在代码里的字典。
- 检索是**真的 embedding 检索**（LightMem + qdrant + MiniLM），不是 if-else 匹配关键词。
- 决策（该 ACT 还是该 ASK）是**真的 LLM 判断**（Qwen 看检索结果做决定），不是脚本里写死"第三轮就问"。
- 车控动作是**真的函数调用**（LLM tool-calling 触发）。

判定标准：**换一组新的偏好和场景（不是感冒/空调），系统应该照样能跑出"不确定就问"的行为**。如果换个场景就崩，说明是硬编的假 demo，不合格。

---

## 3. 技术栈（全部有现成依据，不造轮子）

| 组件 | 用什么现成技术 | 依据 |
|---|---|---|
| LLM | Qwen2.5-7B 或 14B-Instruct，vLLM 起服务，支持 tool-calling | 已在服务器验证 hermes parser 可用 |
| 记忆存储 | **LightMem** (`lightmem.memory.lightmem.LightMemory`) | 见 §5 现成脚本 |
| 检索 | LightMem 内置 embedding 检索 + qdrant + all-MiniLM-L6-v2 (384维) | 同上，LightMem 自带，无需另搭 |
| 决策层 (ACT/ASK) | Qwen + 结构化 system prompt | 本工程新写，是唯一核心 |
| 车控动作 | Python 函数（mock 执行）+ ask_user | 本工程新写 |
| 交互 | CLI（第一版）/ 简单网页（第二版） | 本工程新写 |

**只有"决策层 + 车控动作 + 交互"是新写的，其余全部复用现成。**

---

## 4. 与论文工程的关系（重要：两者独立）

本 Demo 和作者的论文项目（VehicleMemBench 上的条件偏好研究）**共享底层事实资产**（同样的 LightMem、同样的 Qwen 模型、同样的车载偏好概念），但：

- **目标不同**：Demo 求"演得真实可用"；论文求"证明现象、跑评测、抵御审稿人"。
- **代码独立**：Demo 不接入论文的评测管线（risk-coverage / 三层失败诊断 / scaling 曲线），论文不接入 Demo 的交互层。
- **决策层不同**：Demo 的决策用 LLM+prompt 实现（够演就行）；论文的决策是可量化的算法（另一套）。

**因此本工程不要去 import 论文项目的评测代码，也不要做评测/基线/对比实验。** 那是论文的事。Demo 只负责把那条交互闭环跑成一个真实的小系统。

---

## 5. 已有的现成参考（照着用，别重写）

作者已有一份**能跑通的 LightMem 用法脚本**，接口、配置、模型路径都在里面。实现时照它的接口用：

```python
from lightmem.memory.lightmem import LightMemory

# 创建（配置见 02_architecture.md / 03_memory_schema.md）
lightmem = LightMemory.from_config(config)

# 存记忆：messages 是 [{"role":"user"/"assistant", "content":..., "time_stamp":...}, ...]
result = lightmem.add_memory(messages=turn_messages, force_segment=..., force_extract=...)

# 检索：返回相关记忆列表
memories = lightmem.retrieve(query_text, limit=5)
```

关键配置项（来自现成脚本，可直接复用）：
- `memory_manager`: `{"model_name": "transformers", "configs": {"model": <Qwen路径>, "num_gpu": -1, "max_tokens": 512}}`
- `text_embedder`: `{"model_name": "huggingface", "configs": {"model": <MiniLM路径>, "embedding_dims": 384, "model_kwargs": {"device": "cpu"}}}`
- `embedding_retriever`: `{"model_name": "qdrant", "configs": {"collection_name": ..., "embedding_model_dims": 384, "path": <qdrant本地目录>}}`
- `index_strategy`: `"embedding"`，`retrieve_strategy`: `"embedding"`

模型路径（服务器上已有）：
- Qwen: `/data/cache/modelscope/hub/models/Qwen/Qwen2.5-14B-Instruct`（或 7B 同目录）
- MiniLM embedding: `/data/cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/<snapshot>`

---

## 6. 读完本文档后，接着读

- `01_architecture.md` — 四层架构 + 数据流（先读这个）
- `02_memory_schema.md` — 记忆/偏好的数据结构（含 condition 设计、三种来源）
- `03_decision_policy.md` — 决策层 prompt 设计 + 澄清学习（Demo 的核心，最详细）
- `04_build_guide.md` — 搭建步骤、目录结构、怎么跑起来
- `05_memory_lifecycle.md` — 记忆生命周期：三条写入路径（即时陈述 / 离线总结 / 澄清学习）+ 检索 + 过期

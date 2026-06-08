# 06 · 后端闭环收口说明（以服务器当前状态为准）

> 这份文档不是早期设计稿，而是 2026-06-08 面向当前 demo 后端实现的收口说明。
> 目标是回答三件事：
> 1. 这个后端闭环到底包含什么；
> 2. 哪些部分已经做完并验证过；
> 3. 哪些问题仍存在，但不阻塞 demo 展示。

---

## 1. 这轮后端闭环的定义

demo 后端的核心闭环定义为：

1. 用户当前输入进入系统；
2. 系统检索历史记忆和结构化偏好；
3. `Policy` 判断当前轮应该直接执行还是追问；
4. 若追问，用户回答后系统能学习新偏好；
5. 当天对话结束后，系统能从整段对话离线抽取结构化偏好；
6. 下次相似场景再来时，系统能利用历史偏好减少重复追问。

这轮不追求：

- 完整产品化后端
- 所有偏好对象都能真实执行
- benchmark 100% exact match
- 完整 condition 逻辑表达

这轮追求的是：**工程闭环可跑、行为可解释、服务器上可复现。**

---

## 2. 当前后端主链路

服务器项目根目录：

```bash
/root/vehicle_memory_demo
```

后端主链路入口是：

```bash
/root/vehicle_memory_demo/src/interface/session.py
```

其中 `DemoSession` 是整个 demo 的状态机。它负责把一次用户输入走完以下链路：

```text
用户输入
  -> 写入 session messages
  -> 从 LightMem 检索相关历史对话
  -> 从 PreferenceTable 检索结构化偏好
  -> Policy 决定 ACT / ASK
  -> 执行工具或发起追问
  -> 若追问后成功执行，则 ClarificationLearner 学到新偏好
```

核心模块位置：

- 会话状态机：`/root/vehicle_memory_demo/src/interface/session.py`
- API service：`/root/vehicle_memory_demo/src/interface/api_service.py`
- HTTP 入口：`/root/vehicle_memory_demo/src/interface/http_api.py`
- API 启动脚本：`/root/vehicle_memory_demo/scripts/run_api_server.py`
- 决策层：`/root/vehicle_memory_demo/src/policy/policy.py`
- LightMem 包装：`/root/vehicle_memory_demo/src/memory/lightmem_store.py`
- 结构化偏好表：`/root/vehicle_memory_demo/src/memory/preference_table.py`
- 澄清学习：`/root/vehicle_memory_demo/src/memory/clarification_learner.py`
- 直接偏好抽取器：`/root/vehicle_memory_demo/src/memory/direct_preference_extractor.py`
- 离线总结入口：`/root/vehicle_memory_demo/src/memory/offline_summarizer.py`

---

## 3. 后端六个闭环节点

### 3.1 用户输入

用户输入从 `DemoSession.handle_user_message(text)` 进入。

当前轮会先生成一条：

```python
{"role": "user", "content": text, "time_stamp": ...}
```

这条消息会进入：

- `self.session_messages`
- 后续 LightMem 写入队列

这一步已经实现。

---

### 3.2 记忆检索

当前请求会先走两层检索：

1. `LightMemStore.retrieve_records(context, limit=...)`
2. `PreferenceTable.find_relevant_matches(query_text=context, lightmem_hits=...)`

含义是：

- LightMem 负责从历史原始对话里找相近记忆；
- PreferenceTable 负责从结构化偏好里找和当前请求最相关的候选偏好。

当前实现里，结构化偏好检索并不直接“判断条件是否成立”，而是：

- 先按文本相关性召回；
- 再交给 `Policy` 做 ACT / ASK 判定。

这一步已经实现。

---

### 3.3 追问决策

决策层入口：

```bash
/root/vehicle_memory_demo/src/policy/policy.py
```

`Policy` 当前做的事：

1. 解析当前上下文
2. 提取显式参数
3. 归一化当前轮已知事实
4. 过滤和当前动作无关的偏好
5. 合并“多条记录但动作相同”的偏好
6. 判断当前是否缺关键维度
7. 通过 tool-calling 让 Qwen 选择：
   - `ACT`
   - `ASK`

当前提示词规则已经支持这些关键判断：

- 当前明确参数优先于历史偏好
- 具体条件偏好优先于 default
- 多条偏好动作相同则直接执行
- 只有缺关键区分信息时才追问
- 对上一轮澄清回答，不重复追问同一维度

这一步已经实现，并且本地测试覆盖了典型场景。

---

### 3.4 澄清学习

如果 `Policy` 返回 `ASK`，前端或脚本需要继续调用：

```python
DemoSession.handle_clarification(pending, answer)
```

这一步做的事：

1. 把用户回答追加进 session
2. 将“原问题 + 系统追问 + 用户回答”拼成组合上下文
3. 再次检索并决策
4. 若本轮最终成功执行：
   - 用 `ClarificationLearner.learn_from_dialogue(...)` 产出新偏好
   - 将这条偏好写入 `PreferenceTable`
   - 必要时把旧偏好标记为 `expired`

当前已经验证过的典型路径：

- “好热啊” -> 系统追问“感冒好些了吗”
- 用户回答“好多了，今天基本恢复了”
- 系统执行 `set_ac_temperature`
- 学到 `health_state == recovering`
- 将旧的 `health_state == sick` 温度偏好过期

这一步已经实现。

---

### 3.5 离线偏好抽取

当天对话结束后，不再走旧的 “LightMem extract -> 通用 summary -> 规范化” 链路。

现在的离线偏好抽取是：

```text
当天对话 -> DirectPreferenceExtractor(Qwen) -> PreferenceTable
```

对应入口：

```bash
/root/vehicle_memory_demo/src/memory/offline_summarizer.py
```

`OfflineSummarizer` 只做两件事：

1. 调 `DirectPreferenceExtractor.extract(messages)`
2. 将通过校验的结构化偏好 `upsert` 进 `PreferenceTable`

LightMem 在这里仍保留“存储和检索”角色，但**不再承担结构化偏好主抽取任务**。

这一步已经实现。

---

### 3.6 下次复用偏好

当相似场景下次再来时：

1. `LightMem` 会召回相关历史对话
2. `PreferenceTable` 会召回已学到的结构化偏好
3. `Policy` 会将这些偏好作为候选
4. 如果当前条件足够清楚，系统就不再重复问

服务器上已验证的场景：

- Day 2 第一次热场景：追问
- 回答“恢复了”后学到 `recovering`
- Day 9 相似热场景：直接执行，不再重复追问

这一步已经实现。

---

## 4. 当前支持的对象和动作边界

### 4.1 能抽取进结构化偏好表的对象

当前只支持三类偏好对象：

- `ac_temperature`
- `seat_heating`
- `music_mode`

### 4.2 当前能真实执行的工具

当前只有三种工具：

- `set_ac_temperature`
- `set_seat_heating`
- `ask_user`

因此要特别注意：

- `music_mode` 现在能被抽取、存储、检索、参与冲突分析；
- 但它**没有真实执行工具**；
- 所以前端展示时，`music_mode` 应被视为“记忆中的偏好”，不是“当前 demo 已能直接控制的功能”。

---

## 5. 当前支持的 condition 边界

当前 DirectPreferenceExtractor 允许落盘的 condition 集合是：

- `default`
- `health_state == sick`
- `fatigue_state == sleepy`
- `weather_state == rainy`
- `trip_scene == family_trip`

这套 schema 足够支撑当前 demo，但仍然有边界：

- 不能表达复杂组合条件
- 不能很好表达否定条件（如“不是很困也不是带孩子”）
- 容易把本该“更细”的条件压成 `default`

因此这轮的策略不是追求 condition 完美，而是先把闭环跑稳。

---

## 6. 已验证的服务器行为

### 6.1 runtime 检查

可用命令：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/check_runtime.py
```

最近一次检查确认：

- Qwen 服务可连
- Embedding 模型存在
- LLMLingua 模型存在
- `Qwen2.5-14B-Instruct` 模型可见

### 6.2 family trip 场景

命令：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_family_trip_scenario.py --reset
```

最近一次验证结果：

- Day 1 会从家庭出游对话中离线抽出 `music_mode = silent @ trip_scene == family_trip`
- Day 2 热场景会先追问
- 回答“好多了，今天基本恢复了”后会：
  - 执行温度设置
  - 学到 `health_state == recovering`
  - 将 `health_state == sick` 的旧偏好过期
- Day 9 相似场景会直接执行，不再重复问

### 6.3 直接偏好抽取 benchmark

命令：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/benchmark_qwen_preference_extraction.py --days 3 --drives-per-day 2 --target-chars 2200 --show-drives --show-items 2
```

最近一次结果：

- `exact_match_rate = 83.33%`
- `object_match_rate = 100.00%`
- `parse_failures = 0`
- `retry_used = 0`

### 6.4 长对话查找 benchmark

命令：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/benchmark_long_dialogue.py --reset --dataset scale_15d --days 15 --drives-per-day 2 --target-chars 2200 --repeat 8 --warmup 1
```

最近一次结果：

- `days = 15`
- `drives_total = 30`
- `dialogue_chars_total = 70836`
- `exact_match_rate = 81.67%`
- `object_match_rate = 100.00%`
- 检索总耗时约 `14ms - 16ms / query`

这说明当前 demo 的主要瓶颈不在检索，而在离线抽取质量和 condition 定义。

### 6.5 HTTP API 闭环

当前服务器已经验证过最小 HTTP API：

- `GET /health`
- `GET /preferences`
- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `POST /reset`

最近一次顺序验证结果：

1. `POST /turn` 输入长对话后，系统会先 ASK；
2. `POST /summarize` 能写入 3 条结构化偏好：
   - `music_mode = light @ trip_scene == family_trip`
   - `ac_temperature = 25 @ default`
   - `ac_temperature = 26.5 @ health_state == sick`
3. 之后再发“周末一家人出去玩，好热啊”，系统会再次 ASK 健康状态；
4. `POST /clarification` 回答“好多了，今天基本恢复了”后：
   - 系统执行 `set_ac_temperature(value=25)`
   - 学到 `ac_temperature = 25 @ health_state == recovering`
   - 将 `health_state == sick` 那条旧偏好标记为 `expired`

这说明面向前端接入的后端闭环也已经在服务器上打通。

---

## 7. 这轮后端已经做完的部分

按闭环目标看，当前已完成：

- 用户输入写入记忆
- 历史记忆检索
- 结构化偏好召回
- ACT / ASK 决策
- 澄清回答后的偏好学习
- 旧偏好过期
- 离线偏好抽取
- 下次相似场景复用偏好
- 最小 HTTP API
- 本地 pytest 通过
- 服务器关键 scenario / benchmark 能复现

---

## 8. 当前仍存在但不阻塞 demo 的问题

1. `music_mode` 没有真实执行工具  
   这意味着它只能做“记忆和展示”，不能做“真实动作控制”。

2. benchmark ground truth 尚未全部人工裁定  
   主要卡在某些 condition 应视为 `default` 还是场景条件。

3. condition schema 较窄  
   对否定条件、组合条件支持不足。

4. `music_mode` 的某些条目仍可能冲突  
   当前只能先靠候选合并和 LLM 决策兜住，不是彻底的规则化冲突解决。

---

## 9. 推荐的后续顺序

如果继续做后端，建议顺序是：

1. 先裁 benchmark 中有争议的 condition 真值
2. 再决定 `music_mode` 是：
   - 加真实执行工具
   - 还是明确降级为“只展示，不执行”
3. 最后再考虑 condition schema 是否扩展

如果继续做前端，建议直接以 `DemoSession` 为核心包一层 API，不要先重构后端。
如果继续做前端，建议直接接现有 HTTP API，不要再重复包一层新的后端壳子。

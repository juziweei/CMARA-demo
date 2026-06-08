# 01 · 架构设计

> 先读 `00_overview.md`。本文件定义四层架构、每层职责、数据如何流动。

---

## 1. 四层架构

Demo 分四层，每层职责单一。**只有"决策层"是新写的核心，其余尽量复用现成。**

```
┌─────────────────────────────────────────────────┐
│ 第4层  交互层 (Interface)                          │  CLI / 网页
│   接收用户输入、展示回复、可视化+编辑记忆库          │
├─────────────────────────────────────────────────┤
│ 第3层  决策层 (Policy)        ★ Demo 唯一核心       │
│   输入: 当前对话 + 检索到的偏好                     │
│   输出: ACT(调车控函数) / ASK(调ask_user)          │
│   实现: Qwen + 结构化 system prompt                │
├─────────────────────────────────────────────────┤
│ 第2层  记忆层 (Memory)                             │  ← 复用 LightMem
│   存偏好 / embedding检索 / 更新状态(过期)           │
├─────────────────────────────────────────────────┤
│ 第1层  执行层 (Action)                             │
│   车控函数(mock) + ask_user + LLM(vLLM tool-calling)│
└─────────────────────────────────────────────────┘
```

---

## 2. 各层职责与实现

### 第1层 · 执行层 (Action)

**职责**：定义"车能做什么"，并由 LLM 通过 tool-calling 调用。

**车控函数（mock，只记录不真控车）**：
```python
def set_ac_temperature(value: float) -> dict: ...   # 设空调温度
def set_seat_heating(level: int) -> dict: ...        # 座椅加热（演示扩展用）
def ask_user(question: str) -> dict: ...             # ★ 关键：把"询问"做成一个动作
```
每个函数带元信息（给决策层用，也为将来扩展）：
```python
TOOLS_META = {
    "set_ac_temperature": {"cost": "low",  "reversible": True},
    "set_seat_heating":   {"cost": "low",  "reversible": True},
    "ask_user":           {"cost": "zero", "reversible": True},
}
```

**LLM 调用**：连服务器上的 vLLM 服务（Qwen 7B/14B），用标准 OpenAI 兼容接口 + `tools` + `tool_choice="auto"`。服务由人工在服务器起（见 04），Demo 通过 `http://127.0.0.1:<port>/v1` 调。

**实现量**：小。函数是 mock 的，LLM 调用是标准 tool-calling。

---

### 第2层 · 记忆层 (Memory) — 复用 LightMem

**职责**：存条件性偏好、embedding 检索相关偏好、更新偏好状态。

**用 LightMem 实现（接口见 00_overview §5）**：
- 存：`lightmem.add_memory(messages=...)` —— 把用户陈述偏好的对话存进去。
- 检索：`lightmem.retrieve(query, limit=5)` —— 当前 query 检索相关偏好（embedding 检索）。
- 更新（过期）：见下方说明。

**关键适配点 —— 偏好的"条件"和"状态"**：
LightMem 原生存的是对话文本片段。Demo 需要在它之上维护一个**结构化偏好层**（见 `02_memory_schema.md`），记录每条偏好的 `condition`（触发条件）和 `status`（active/expired）。

实现方式（两选一，推荐 A）：
- **方案A（推荐，简单）**：用 LightMem 存对话原文做检索召回；同时在 Demo 侧维护一个轻量的结构化偏好表（JSON / sqlite），存 `{preference, value, condition, status, evidence, lightmem_ref}`。检索时先用 LightMem 召回相关记忆，再映射到结构化偏好表。"更新过期"在结构化表上做。
- **方案B**：完全用 LightMem 的 metadata 能力存 condition——但 LightMem 的 metadata 支持有限，且"标记过期"不好做，不推荐 demo 用。

**为什么需要结构化偏好层**：决策层（第3层）要判断"当前情境能不能确定 condition 成立"，必须能读到结构化的 condition，而不是一段自由文本。详见 `02_memory_schema.md`。

**实现量**：LightMem 复用现成；结构化偏好层是薄薄一层 JSON/sqlite 封装。

---

### 第3层 · 决策层 (Policy) — Demo 唯一核心，重点写

**职责**：拿到 [当前用户对话 + 检索到的偏好列表]，决定 **ACT 还是 ASK**。

**核心逻辑（两步）**：
```
输入: current_context (用户当前说的话 + 可见情境)
      retrieved_prefs (从记忆层检索到的结构化偏好列表)

步骤1 可辨识性判断:
  - 只有一条相关偏好，其 condition 在当前情境下明确成立  → 可辨识 → ACT
  - 多条偏好的 condition 互相冲突 / 都可能适用，当前情境无法区分 → 不可辨识 → ASK
  - 偏好的 condition 依赖某个信息，但当前情境里没有       → 不可辨识 → ASK

步骤2 代价加权（可选，演示扩展）:
  - 即使可辨识，若动作 high-cost 且不可逆 → 仍 ASK 确认
  - low-cost 可逆动作 → 直接 ACT
```

**实现：Qwen + 结构化 system prompt**（不训练、不写算法）。完整 prompt 设计见 `03_decision_policy.md`。本质是把上面的判断逻辑写成 system prompt，让 Qwen 在看到检索结果后，自己决定调 `ask_user` 还是调车控函数。

**关键设计 —— 接口隔离**：决策层封装成一个清晰的函数/类：
```python
class Policy:
    def decide(self, context: str, retrieved_prefs: list[dict]) -> Decision:
        """返回 Decision(action="ACT"|"ASK", tool_call=..., question=...)"""
```
这样将来若要换更讲究的实现，只动这一个类，上下层不变。**Demo 阶段就用 prompt 实现这个 decide。**

**实现量**：中。逻辑不复杂，但 prompt 要反复调，确保"不确定就问"在真实检索结果上稳定触发。

---

### 第4层 · 交互层 (Interface)

**职责**：主循环——接收输入、驱动下面三层、展示结果；可视化记忆库并允许编辑。

**第一版：CLI**
- 命令行对话。
- 一个命令（如 `/memory`）打印当前结构化偏好表（让记忆"可见"）。
- 一个命令（如 `/edit`、`/forget <id>`）编辑/删除偏好（让记忆"可改"）。

**第二版（可选）：简单网页**
- 左边对话框，右边记忆库面板（实时显示偏好表，可点击编辑/删除）。
- 像 ChatGPT 的 memory 面板那样。

**实现量**：CLI 小；网页中等。先做 CLI。

---

## 3. 一次完整的数据流（感冒场景 5.5 那一幕）

```
用户输入「好热啊」
   │
   ▼
[第4层] 主循环接收，调下面流程
   │
   ▼
[第2层] lightmem.retrieve("好热啊") 
        → 召回相关记忆 → 映射到结构化偏好表
        → [{ac:25, cond:默认, active}, {ac:26.5, cond:感冒时, active}]
   │
   ▼
[第3层] Policy.decide(context="好热啊", prefs=上面两条)
        Qwen 看到：两条偏好，一条 condition=默认、一条 condition=感冒时，
        当前对话「好热啊」无法确定感冒好没好
        → 判定不可辨识 → 决定调 ask_user
        → Decision(action="ASK", question="您感冒好些了吗？好了设25，没好设26.5")
   │
   ▼
[第1层] 执行 ask_user(...) → 把问题返回给交互层
   │
   ▼
[第4层] 展示问题，等用户回答 → 用户「好多了」
   │
   ▼
[第3层] Policy.decide(context="好多了"(+上文), prefs=同上)
        Qwen：现在能确定 condition=感冒已好 → 可辨识 → ACT
        → Decision(action="ACT", tool_call=set_ac_temperature(25))
   │
   ▼
[第1层] 执行 set_ac_temperature(25)
[第2层] 更新结构化偏好表：把「感冒时」那条 status 改为 expired
   │
   ▼
[第4层] 回复「给您设25度，已取消感冒期间的偏好」
```

---

## 4. 设计原则小结

1. **创新单点化**：所有"智能"集中在第3层决策层，其余是标准组件。
2. **真实支撑**：记忆真存 LightMem、检索真用 embedding、决策真用 LLM——不许硬编。
3. **决策层接口隔离**：`Policy.decide()` 封装好，将来可替换。
4. **condition 结构化**：第2层维护结构化偏好（带 condition + status），这是决策层能工作的前提。
5. **不碰论文管线**：不做评测/基线/risk-coverage，那是论文工程的事。

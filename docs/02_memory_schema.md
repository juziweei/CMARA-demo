# 02 · 记忆 / 偏好数据结构

> 先读 `01_architecture.md`。本文件定义 Demo 的结构化偏好长什么样，以及它和 LightMem 的关系。

---

## 1. 为什么需要"结构化偏好层"

LightMem 负责存对话、做 embedding 检索召回。但它召回的是**文本片段**，而决策层（第3层）需要判断"当前情境能不能确定某条偏好的**触发条件**成立"——这要求每条偏好的 `condition` 是**结构化、可读取**的，不是一段自由文本。

所以 Demo 在 LightMem 之上，额外维护一张**结构化偏好表**。两者分工：
- **LightMem**：存原始对话 + embedding 检索（召回"哪些记忆和当前 query 相关"）。
- **结构化偏好表**：存每条偏好的结构化信息（值、条件、状态），供决策层判断和"过期"更新。

---

## 2. 结构化偏好条目的数据结构

每条偏好一条记录（JSON 或 sqlite 一行）：

```json
{
  "id": 2,
  "preference": "ac_temperature",
  "value": 26.5,
  "condition": {
    "type": "health_state",
    "operator": "==",
    "target": "sick"
  },
  "status": "active",
  "source": "user_stated",
  "evidence": "用户在 5.3 说『我感冒了，调高一点』",
  "lightmem_ref": "<对应 LightMem 记忆的 id 或检索 key>",
  "timestamp": "2026-05-03"
}
```

字段说明：

| 字段 | 含义 | 为什么需要 |
|---|---|---|
| `preference` | 关于什么（空调温度/座椅加热…） | 标识偏好对象，对应车控函数 |
| `value` | 偏好值 | ACT 时要设的值 |
| `condition` | **结构化的触发条件** | ★ 决策层判断"当前情境是否满足/能否确定"的依据 |
| `status` | active / expired | 实现"记忆可更新"（感冒好了→expired） |
| `source` | **三种来源之一**（见 §2.1） | 来源透明，且决定该偏好可信度/展示方式 |
| `evidence` | 原话/出处 | 记忆"可解释"，展示给用户看（像 ChatGPT memory sources） |
| `lightmem_ref` | 指回 LightMem 的记忆 | 关联两层，检索召回后能映射到结构化条目 |
| `timestamp` | 时间 | 排序、展示 |

---

## 2.1 偏好的三种来源（`source` 字段）— 长期记忆的核心

一个真实的长期记忆系统，偏好不止一个来源。Demo 必须体现**三条记忆写入路径**，这正是"长期记忆系统"区别于"聊天记录"的地方：

| source 值 | 来源 | 何时产生 | 例子 |
|---|---|---|---|
| `user_stated` | ① 用户即时陈述 | 用户明说时，当场存 | "我感冒了，空调调高点" → 当场存 {26.5, 感冒时} |
| `offline_summary` | ② **离线总结** | 当天对话结束后，回看整段对话用 LLM 归纳 | 用户白天3次说"关音乐/太吵" → 离线总结出 {music=off, 默认} |
| `learned_from_clarification` | ③ 澄清学习 | 一次 ASK 得到回答后，把"情景+选择"沉淀 | 5.5天热问"感冒好没"→用户答"好了选25" → 存 {25, 天热+感冒恢复} |

三条路径的详细生命周期见 `05_memory_lifecycle.md`。这里先记住：**每条偏好都要标明它从哪条路径来**，因为：
- 展示给用户时要说清依据（`user_stated` 是"您说过"，`offline_summary` 是"我从您的习惯总结的"，`learned_from_clarification` 是"上次您选过"）。
- `offline_summary` 和 `learned_from_clarification` 是系统**推断/学习**来的，可信度低于用户明说的，用户可以在记忆面板里修正或删除（呼应"记忆可改"）。

---

## 3. `condition` 字段怎么设计（Demo 够用即可）

`condition` 不用做得很复杂，Demo 阶段支持几种简单类型就够演：

```json
// 类型1：默认（无条件，兜底）
{"type": "default"}

// 类型2：状态等于某值
{"type": "health_state", "operator": "==", "target": "sick"}

// 类型3：环境阈值（演示扩展用）
{"type": "weather", "operator": ">", "target": 30, "unit": "celsius"}
```

**关键**：condition 的 `type`（如 `health_state`）代表"判断这条偏好适不适用，需要知道哪个信息"。决策层就是看**当前对话/情境里有没有提供这个信息**：
- 当前对话明确说了"感冒好了" → `health_state` 可确定 → 该偏好的 condition 可判定。
- 当前对话只说"好热"，没提健康状态 → `health_state` 无法从当前情境确定 → 不可辨识 → ASK。

这就是 condition 结构化的意义：它让"能不能确定该用这条偏好"变成一个**可判断**的问题，而不是模糊的感觉。

---

## 4. 感冒场景下，偏好表的演变

```
[初始] 用户说"空调25度舒服"
偏好表:
  [{id:1, pref:ac_temperature, value:25, condition:{type:default}, status:active,
    evidence:"用户说25度舒服", ts:初始}]

[5.3] 用户说"我感冒了，调高点"
偏好表:
  [{id:1, ac, 25, default, active, ...},
   {id:2, ac, 26.5, {type:health_state,==,sick}, active,
    evidence:"用户5.3说感冒了调高", ts:5.3}]

[5.5] 用户说"好多了"(回答询问后)
偏好表:
  [{id:1, ac, 25, default, active, ...},
   {id:2, ac, 26.5, {...sick}, EXPIRED,  ← 状态更新为过期
    ...}]
```

"记忆可更新"就体现在 id:2 的 `status` 从 active 改成 expired。

---

## 5. 检索如何映射到结构化偏好（两层怎么连）

流程：
1. 用户当前说话 → `lightmem.retrieve(query, limit=5)` 召回相关 LightMem 记忆。
2. 通过 `lightmem_ref` 把召回的记忆映射到结构化偏好表里的条目。
3. **只取 status=active 的条目**交给决策层（expired 的不参与，因为已经过期）。
4. 决策层拿到的就是：`[{pref, value, condition, evidence}, ...]` 这样一组结构化偏好。

> 实现简化提示：Demo 数据量很小（一个用户、几条偏好），方案A 里"先 LightMem 召回再映射"如果觉得绕，**也可以直接遍历结构化偏好表做相关性匹配**（结合 LightMem 的 embedding 分数）。重点是决策层最终拿到的是结构化偏好。Demo 不追求检索规模，追求结构真实。

---

## 6. 与论文 schema 的关系（参考，不强制对齐）

论文工程里已有 `schema.py`（`SelectiveActivationEvalSample` 含 `expected_behavior: apply/abstain/clarify`）。Demo 的结构化偏好**思路一致**（都有 condition、都支持 abstain/clarify 概念），但 Demo 不需要严格复用论文 schema——Demo 是面向交互的，论文 schema 是面向评测的。**借鉴其 condition + abstain 的思路即可，不必 import。**

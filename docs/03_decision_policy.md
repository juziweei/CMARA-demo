# 03 · 决策层设计（Demo 的核心）

> 先读 `01_architecture.md` 和 `02_memory_schema.md`。
> 这一层是 Demo 唯一的"智能核心"。写得好不好，直接决定 Demo 是"真实可信"还是"硬编作假"。

---

## 1. 决策层要做的事

输入：
- `context`：用户当前说的话（+ 必要的上文 / 可见情境）
- `retrieved_prefs`：从记忆层检索到的、status=active 的结构化偏好列表

输出：一个决策
- `ACT`：直接执行 → 调某个车控函数（如 `set_ac_temperature(25)`）
- `ASK`：不确定 → 调 `ask_user(question)` 向用户澄清

**判据（必须由 LLM 基于真实检索结果判断，不许写死）**：
1. 检索到**唯一**一条相关偏好，且其 condition 在当前情境下**明确成立** → ACT
2. 检索到**多条**偏好，condition 互相冲突 / 都可能适用，当前情境**无法区分** → ASK
3. 偏好的 condition 依赖某信息，但当前情境**没有提供** → ASK

---

## 2. 实现方式：Qwen + 结构化 System Prompt

不训练模型、不写规则引擎。把上面的判据写进 system prompt，让 Qwen 看到检索结果后自己决定调哪个 tool。

### System Prompt（草案，实现时按需微调）

```
你是一个车载智能助手的决策模块。你的任务是：根据用户当前说的话，以及系统从长期记忆中
检索到的相关用户偏好，决定现在应该「直接执行某个车控操作」还是「先向用户询问澄清」。

# 你会收到
1. 用户当前说的话
2. 检索到的相关偏好列表，每条包含：偏好对象、偏好值、触发条件(condition)、来源证据

# 你的决策规则（严格遵守）
- 如果只有一条相关偏好，且它的触发条件在当前情境下明确成立 → 调用对应的车控函数执行。
- 如果有多条相关偏好，它们的触发条件互相冲突或都可能适用，而你无法从用户当前的话里
  确定该用哪一条 → 不要猜，调用 ask_user 向用户询问，问清楚那个能区分它们的关键信息。
- 如果某条偏好的触发条件依赖某个信息（比如"是否还在感冒"），而用户当前的话里没有提供
  这个信息 → 不要假设，调用 ask_user 询问。
- 询问时，问题要具体，并说明不同回答会导致的不同操作（例如："您感冒好些了吗？
  好了我设25度，还没好我设26.5度"）。

# 重要
- 当你不确定时，询问永远比猜错好。车控操作有真实代价，设错温度会打扰用户、损害信任。
- 不要编造偏好里没有的信息。只基于检索到的偏好和用户的话做判断。

# 可用的车控函数
（这里列出 tools：set_ac_temperature, set_seat_heating, ask_user ...）
```

### 用户消息（每轮动态拼装）

```
用户当前说：「{context}」

系统检索到以下相关偏好：
1. 偏好：空调温度 = 25 度；触发条件：默认（无特殊条件）；来源：用户说25度舒服
2. 偏好：空调温度 = 26.5 度；触发条件：用户处于感冒状态时；来源：用户5.3说感冒了要调高

请根据决策规则，决定调用哪个函数。
```

LLM 看到这个，理想行为：识别出两条偏好都关于空调温度、一条要 25 一条要 26.5、区别在"感冒好没好"、而用户只说了"好热"没说健康状态 → 调 `ask_user("您感冒好些了吗？……")`。

---

## 3. 决策层的代码封装

```python
from dataclasses import dataclass

@dataclass
class Decision:
    action: str          # "ACT" or "ASK"
    tool_name: str = ""  # ACT 时：要调的车控函数名
    tool_args: dict = None  # ACT 时：参数
    question: str = ""   # ASK 时：要问的问题

class Policy:
    def __init__(self, llm_client, tools_schema):
        self.llm = llm_client          # 连 vLLM 的客户端
        self.tools = tools_schema      # tool-calling 的 tools 定义

    def decide(self, context: str, retrieved_prefs: list[dict]) -> Decision:
        system = build_system_prompt(self.tools)
        user = build_user_prompt(context, retrieved_prefs)
        resp = self.llm.chat(
            messages=[{"role":"system","content":system},
                      {"role":"user","content":user}],
            tools=self.tools,
            tool_choice="auto",
        )
        tool_call = parse_tool_call(resp)   # 从返回里取 tool_calls
        if tool_call.name == "ask_user":
            return Decision(action="ASK", question=tool_call.args["question"])
        else:
            return Decision(action="ACT", tool_name=tool_call.name,
                            tool_args=tool_call.args)
```

**这个 `Policy` 类就是 Demo 的核心。** 接口固定（`decide(context, prefs) -> Decision`），实现是 LLM+prompt。将来若要换更讲究的判断逻辑，只改这个类内部，主循环不动。

---

## 4. 如何确保"不是硬编作假"（验收标准）

实现完后，用这几个测试验证决策层是真的在判断、不是写死：

**测试1（基本场景）**：感冒场景，5.5 那一幕，系统应该 ASK 而不是直接设温度。

**测试2（可辨识应该 ACT）**：只有一条偏好（"默认25度"），用户说"好热"，没有冲突偏好 → 系统应该直接 ACT 设 25，**不该**多此一举地问。（验证它不是"无脑都问"。）

**测试3（换场景不崩）**：换一组完全不同的偏好——比如"用户喜欢听轻音乐"+"开车犯困时听提神音乐"，用户上车说"出发吧"，没说困不困 → 系统应该 ASK 问"您现在需要提神音乐还是轻音乐？"。**如果换了场景就崩或乱答，说明是硬编，不合格。**

**测试4（信息补全后 ACT）**：测试1 之后用户回答"好多了" → 系统应该 ACT 设 25 并把感冒偏好标记过期。

这四个测试覆盖：该问时问、不该问时不问、换场景仍работает、补全信息后正确执行+更新记忆。**全过才算决策层真实可用。**

---

## 4.5 澄清之后：把这次询问沉淀成长期记忆（路径③）

决策层 ASK 并拿到用户回答后，**不只是执行，还要学习**——把"当时的情景 + 用户的选择"沉淀成一条新偏好，让**下次同情景不用再问**。这是长期记忆的关键一环，详见 `05_memory_lifecycle.md §4`。

在主循环里，ASK 得到回答后调 `clarification_learner`：
```
ASK("感冒好了吗？好了25，没好26.5") → 用户答"好了"
  → 执行 set_ac(25)
  → clarification_learner.learn(
        context="天热 + 感冒恢复",        # 当时情景
        question_dimension="health_state",  # 询问的关键维度
        user_choice={"ac_temperature": 25, "health_state": "recovering"}
     )
  → 写入新偏好 {ac:25, condition:{health_state==recovering},
               source:"learned_from_clarification",
               evidence:"5.5天热且感冒恢复时，询问后用户选25"}
```

**condition 取"询问的那个关键维度"**：系统这次问的就是"感冒好没好"，所以关键维度=health_state，learned 偏好的 condition 就锁定在它上，忽略"天热/下午"等次要维度（见 `05 §4` 的设计取舍）。

下次同情景，这条 learned 偏好被检索召回，决策层判定可辨识 → 直接 ACT，不再问。**决策层代码不用改**——它只是多了一条能匹配的偏好。

---

## 5. 调 prompt 的注意事项

- **最容易出的问题**：模型倾向于"自己猜一个"而不是调 ask_user。要在 prompt 里强调"不确定时询问优于猜测"，必要时给一两个 few-shot 例子。
- **第二个问题**：模型可能"无脑都问"（连可辨识的也问）。要在 prompt 里强调"条件明确成立时直接执行，不要多余询问"，并用测试2 验证。
- **few-shot**：如果纯指令不稳定，在 system prompt 里加 1-2 个示例（一个该ACT、一个该ASK），通常能显著稳定行为。
- **模型选择**：7B 可能判断力不够稳，14B 更稳。先用 14B 把行为调对，再看 7B 够不够。

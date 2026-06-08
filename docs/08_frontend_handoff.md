# 08 · 给前端接手同事的项目说明（服务器视角）

> 这份文档不是给算法工程师的，而是给负责做 demo 展示层的同事。
> 目标是让接手人先理解“后端已经做到了什么”，再决定前端怎么接。

---

## 1. 你接手的是一个什么 demo

这是一个车载长期记忆 demo，不是完整产品。

这个 demo 想展示的不是“车控功能很多”，而是：

```text
系统能记住偏好
-> 在不确定时主动追问
-> 用户回答后学到新偏好
-> 下次相似场景更少追问
```

所以前端展示时，真正的重点是：

- 当前用户说了什么
- 系统召回了哪些历史偏好
- 为什么这次 ASK / 为什么这次 ACT
- 系统刚学到了什么
- 哪条旧偏好失效了

而不是做一个很复杂的车机 UI。

---

## 2. 后端现在已经完成了什么

当前后端已经完成的闭环：

1. 用户输入会进入长期记忆系统
2. 系统会检索历史记忆和结构化偏好
3. 系统会决定当前是直接执行还是先追问
4. 用户回答追问后，系统会把这次选择学成新偏好
5. 当天对话结束后，系统会把整段对话离线抽成结构化偏好
6. 下次相似情景再来时，系统会利用已学到的偏好减少重复追问

当前已经在服务器脚本里验证过。

---

## 3. 后端没有完成什么

这些是你做前端时要知道的边界：

1. `music_mode` 现在没有真实执行工具  
   它可以被记住、被展示、被检索，但不能像空调那样真实执行动作。

2. 后端现在有一个最小 HTTP API  
   它是 demo 用的单 session 服务，不是完整产品后端。

3. benchmark 还不是最终论文级严谨状态  
   但足够支撑 demo 演示。

4. condition schema 还比较窄  
   当前重点是闭环，不是把所有条件表达做满。

---

## 4. 你最应该接的后端入口

如果你是展示层接入，最重要的入口文件是：

```bash
/root/vehicle_memory_demo/src/interface/http_api.py
/root/vehicle_memory_demo/src/interface/api_service.py
/root/vehicle_memory_demo/scripts/run_api_server.py
```

如果你要继续理解内部状态机，再看：

```bash
/root/vehicle_memory_demo/src/interface/session.py
```

里面的 `DemoSession` 是整个 demo 的核心状态机。

它已经封装好了：

- 记忆检索
- 偏好召回
- 决策
- 工具执行
- 追问后的学习

你不要从 LightMem 直接开始接，也不要自己重写策略层。

优先接 `DemoSession`。

---

## 5. 你最应该理解的返回状态

当前 HTTP API 对一轮输入返回的结果里，最重要的两种状态是：

1. `acted`
2. `needs_user_input`

你做前端时，界面核心应该围绕这两个状态切换。

### 5.1 `acted`

表示：

- 系统已经有足够信息
- 已直接执行动作

前端应展示：

- assistant 文本
- 执行动作
- 本轮决策 trace

### 5.2 `needs_user_input`

表示：

- 当前信息不足
- 系统选择追问

前端应展示：

- 追问内容
- 待回答状态
- 用户下一条输入要作为澄清回答继续送回系统

---

## 6. 前端最薄的接法

当前后端已经包好了这层薄 API。

当前可直接调用的接口就是：

- `POST /turn`
- `POST /clarification`
- `POST /summarize`
- `GET /preferences`
- `POST /reset`
- `GET /health`

服务固定是单 session，默认 `session_id="default"`。

推荐启动命令：

```bash
ssh -p 57003 root@114.215.186.130
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
/data/miniconda3/envs/lightmem/bin/python scripts/run_api_server.py --host 0.0.0.0 --port 8010
```

完整字段见：

```bash
/root/vehicle_memory_demo/docs/10_api_contract.md
```

这里先说前端最该关心的语义：

### `POST /turn`

输入：

```json
{"text": "周末一家人要去海边了，好热啊。", "session_id": "default"}
```

返回：

- `status`
- `assistant_text`
- `tool_result`
- `decision_trace`
- 如果需要追问，返回 `pending`

### `POST /clarification`

输入：

- 上一轮返回的 `pending.pending_id`
- 用户回答文本

返回：

- 新一轮 `TurnResult`
- 若有学习结果，返回 `learned_preference`
- 若有过期偏好，返回 `expired_preferences`

### `POST /summarize`

作用：

- 对当前 session 的整段对话做离线偏好抽取

### `GET /preferences`

作用：

- 拉当前结构化偏好表，用于侧栏展示

### `POST /reset`

作用：

- 清空 demo 数据，回到可复现初始状态

---

## 7. 前端页面最该展示什么

如果只做一页 demo，建议最少做这 5 块：

1. 聊天区
2. 当前系统状态区
3. 偏好表侧栏
4. 决策 trace 面板
5. 控制按钮区

### 7.1 聊天区

展示：

- 用户消息
- assistant 回复
- 当前是否在“等待澄清回答”

### 7.2 当前系统状态区

展示：

- `acted` / `needs_user_input`
- 当前轮触发的工具
- 若是追问，显示缺失维度

### 7.3 偏好表侧栏

展示：

- `preference`
- `value`
- `condition`
- `status`
- `source`
- `evidence`

最重要的是让用户能看见系统“记住了什么”。

### 7.4 决策 trace 面板

展示：

- 当前上下文
- 召回了哪些 LightMem 命中
- 哪些偏好进入了候选
- 为什么 ASK / 为什么 ACT
- tool result 是什么

这是 demo 最有说服力的部分。

### 7.5 控制按钮区

建议至少有：

- `Reset`
- `Run Scenario`
- `Summarize`
- `Show Trace`

---

## 8. 最适合前端演示的场景

不要一开始就试图把所有脚本都做成 UI。

优先只接这一条：

```bash
/root/vehicle_memory_demo/scripts/run_family_trip_scenario.py
```

这条最适合展示闭环，因为它自然分成几幕：

### Day 1

- 一段家庭出游对话
- 夜间离线总结
- 学到家庭出游偏好

### Day 2

- 用户说“好热啊”
- 系统发现默认和特殊条件冲突
- 系统追问健康状态

### Day 2 回答后

- 用户回答“好多了，今天基本恢复了”
- 系统执行空调动作
- 学到 `recovering`
- 把 `sick` 旧偏好过期

### Day 9

- 相似场景再次出现
- 系统直接执行，不再重复问

这条链非常适合用前端做“分幕式”展示。

---

## 9. 服务器上你最常用的命令

先登录：

```bash
ssh -p 57003 root@114.215.186.130
```

进入项目：

```bash
cd /root/vehicle_memory_demo
export PYTHONPATH=/data/vmr_project/external/LightMem/src:/root/vehicle_memory_demo
```

跑主场景：

```bash
/data/miniconda3/envs/lightmem/bin/python scripts/run_family_trip_scenario.py --reset
```

跑 runtime 检查：

```bash
/data/miniconda3/envs/lightmem/bin/python scripts/check_runtime.py
```

跑长对话 benchmark：

```bash
/data/miniconda3/envs/lightmem/bin/python scripts/benchmark_long_dialogue.py --reset --dataset scale_15d --days 15 --drives-per-day 2 --target-chars 2200 --repeat 8 --warmup 1
```

---

## 10. 你做前端时，先不要做什么

1. 不要先扩 LightMem
2. 不要先重写 Policy
3. 不要先补复杂 condition schema
4. 不要先碰 benchmark 真值
5. 不要先把页面做成完整产品壳子

先把 demo 的可见性做好。

---

## 11. 建议的前端实现顺序

最稳的顺序是：

1. 先包一层后端薄 API
2. 先做聊天 + 状态切换
3. 再接偏好表和 trace 展示
4. 最后再美化交互和布局

如果时间有限，最小可演示版本其实只要：

- 输入框
- 聊天输出
- 追问回答
- 偏好表
- trace 面板

这样就足够把后端价值展示出来。

---

## 12. 一句话给前端同事

你不是来“补完后端”的。  
你要做的是：**把现在已经跑通的后端闭环，变成一个能看懂、能演示、能解释系统为什么这么做的前端。**

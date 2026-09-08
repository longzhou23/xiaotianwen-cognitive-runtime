# 小天文下一代记忆与认知行为框架备忘

> 状态：讨论整理 / 架构冻结稿（v0.1）
> 更新时间：2026-09-02
> 主题：从 Iris 记忆系统出发，扩展到身份、视角、经历、关系、情绪、触发、决策、行为复盘与长期行为学习。

---

# 0. 当前最核心的问题

最初的问题是：

> **为什么“小天文记得很多”，却仍然没有明显的“我”的概念，也没有真正从经历中学会怎么行动？**

逐步讨论后，问题被拆成了几个不同层次：

```text
谁是谁
  ↓
这件事对“我”意味着什么
  ↓
我记住了什么 / 我现在什么情绪 / 我和谁是什么关系
  ↓
这件事值不值得启动一次行为决策
  ↓
现在应该怎么做
  ↓
实际产生了什么结果
  ↓
事后复盘
  ↓
长期形成行为倾向
```

因此，新系统已经不再只是“更好的 RAG / Memory”。

它逐渐变成：

> **以主体经历为中心的认知—行为闭环。**

---

# 1. 当前约定好的顶层架构

```text
                         ┌─────────────────────┐
                         │   AstrBot Persona   │
                         │   “小天文是谁”       │
                         │ 唯一自然语言人格定义  │
                         └──────────┬──────────┘
                                    │
                                    ▼

原始对话 / 图片 / @ / 回复 / 工具结果 / 定时事件
                        │
                        ▼
┌──────────────────────────────────────────────┐
│                ① 身份解析                    │
│                                              │
│ mention / nickname / alias / UID / 共指       │
│                    ↓                         │
│              Canonical Entity                │
│                                              │
│ 解决：多个称呼到底是不是同一个人             │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│                ② 视角解析                    │
│                                              │
│ SELF 是谁？                                  │
│ 谁是“我 / 你 / 他 / 我们”？                   │
│ 某条经历和 SELF 是什么关系？                  │
│                                              │
│ agent:xiaotianwen == SELF                    │
└──────────────────────┬───────────────────────┘
                       ▼
                ③ 规范化经历
             Canonical Experience
                       │
          ┌────────────┼────────────┬──────────────┐
          │            │            │              │
          ▼            ▼            ▼              ▼
       ④ 记忆       ⑤ 情绪       ⑥ 关系       ⑦ 触发判断
          │            │            │              │
          ▼            ▼            ▼              │
        认知        当前情绪      关系状态          │
       /信念         +基线       +关系证据          │
          │            │            │              │
          └────────────┴────────────┘              │
                       │                           │
                       │                    是否值得启动
                       │                     一次行为循环？
                       │                           │
                       │                ┌──────────┴─────────┐
                       │                │                    │
                       │               否                   是
                       │                │                    │
                       ▼                ▼                    ▼
                更新内部状态后结束   到此结束          ⑧ 构建当前情境
                                                          Situation
                                                             │
                                               ┌─────────────┼─────────────┐
                                               │             │             │
                                               ▼             ▼             ▼
                                             记忆          情绪           关系
                                               │             │             │
                                               └──────┬──────┴──────┬──────┘
                                                      │             │
                                                      ▼             ▼
                                                  行为倾向       Persona
                                                      │             │
                                                      └──────┬──────┘
                                                             ▼
                                                        ⑨ 行为决策
                                                             │
                                        ┌────────────────────┼──────────────────┐
                                        ▼                    ▼                  ▼
                                      沉默                  回复                行动
                                    SILENCE                 REPLY              ACTION
                                                             │
                                                             ▼
                                                        ⑩ 实际执行
                                                             │
                                                             ▼
                                                      环境反馈 / 后果
                                                             │
                                                             ▼
                                                等待形成完整互动片段
                                                          Episode
                                                             │
                                                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         ⑪ 行为复盘                                      │
│                                                                          │
│ 看的是整个：                                                             │
│ 情境 → 当时状态 → 决策 → 实际输出 → 对方回应 → 后续发展                  │
│                                                                          │
│ 而不是单独评价一句话。                                                   │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  ▼
                              观察结果
                                  │
                                  ▼
                               ⑫ 巩固
                          多次类似证据聚合
                                  │
                                  ▼
                              行为倾向
                          Behavioral Prior
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
                    ▼                            ▼
              调整未来触发                 调整未来决策
              “什么时候醒”                 “醒来后怎么做”
```

---

# 2. Persona：只保留一套

AstrBot Persona 继续负责：

> **“小天文是谁。”**

新系统不再额外注入第二套 Persona。

因此：

```text
Persona = Host 侧唯一自然语言人格定义
Identity = 机器内部主体绑定
```

推荐内部表示：

```yaml
identity:
  self_entity: agent:xiaotianwen
```

核心原则：

> **Persona establishes SELF once.
> Memory system preserves that perspective.**

---

# 3. Iris 的根本问题之一：Mention ≠ Entity

Iris 目前更像在存：

> mention（提及）

而不是：

> entity（实体）

因此同一个人可能被拆成多个节点：

```text
“龙洲”
“longz”
“龙舟”
“龙妹”
某个 QQ 昵称
某个 UID
……
```

系统如果把这些直接当节点 ID：

```text
node_A != node_B != node_C
```

那么同一个人的经历就会被拆散。

---

# 4. Entity Resolution：名字不能等于实体

未来必须先有：

```text
Mention
“龙洲”
“longz”
“龙妹”
        │
        ▼
Entity Resolver
        │
        ▼
Canonical Entity

person:xxxxxxxx
```

平台 UID 应优先作为稳定标识：

```text
QQ UID
↓
Canonical Entity
↓
nickname / card / alias
```

原则：

> **Identity 稳定，Name 可以变化。**

---

# 5. Alias 不等于 Coreference

需要区分：

```text
龙洲 / longz / 龙妹
→ Alias Resolution

我 / 你 / 他 / 她
→ Coreference Resolution

妈妈 / 老师 / 群主
→ Relationship-term Resolution
```

未来可拆成：

```text
Mention Resolution
├─ Named Alias Resolution
├─ Platform Identity Resolution
├─ Coreference Resolution
└─ Relationship-term Resolution
```

并且所有 merge 都应保留：

- evidence
- confidence
- provenance
- rollback

---

# 6. SELF：重点不是再造 Persona，而是维持视角

真正需要的是：

```text
subject == agent:xiaotianwen
        ↓
subject == SELF
        ↓
autobiographical memory
```

数据库可以第三人称保存：

```yaml
event:
  actor: agent:xiaotianwen
  action: 和 user:niceick 玩梗
```

但运行时应该投影成：

```text
[你的经历]
你以前和 NICEICK……
```

而不是：

```text
[记忆]
小天文以前和 NICEICK……
```

核心 invariant：

> **Every memory must know whose memory it is.**

进一步：

> **Every retrieved memory must know how it relates to SELF.**

---

# 7. Memory Perspective（主体视角）

建议未来显式区分：

```yaml
perspective:
  autobiographical
  interpersonal
  shared_group
  world_fact
  hearsay
```

对应：

```text
autobiographical
→ “我经历过”

interpersonal
→ “我和这个人之间……”

shared_group
→ “我们群里的共同语境”

world_fact
→ 普通知识

hearsay
→ “我听说 / 有人说过”
```

黑话库也应按 shared_group / cultural knowledge 理解：

> **文化记忆应该被使用，而不是被复述。**

---

# 8. Iris 的新定位

Iris 不需要整个推翻。

它应该收缩为：

```text
Iris / Memory Core
├─ Experience
├─ Memory
├─ Belief
├─ Retrieval
├─ Provenance
└─ Relationship Evidence
```

这些功能则逐步拆出去：

```text
主动接话
关系数值直接驱动台词
好感度直接报告
行为控制
情绪状态
```

一句话：

> **Iris 从“脑子”退回真正的“记忆与经验基础设施”。**

---

# 9. Internal State ≠ Dialogue Content

例如：

```yaml
affinity: 0.86
```

应该影响：

```text
称呼熟悉度
接梗概率
调侃边界
陌生人式客套程度
共同经历引用概率
```

而不是：

```text
“我对你的好感度是 86。”
```

核心原则：

> **内部状态应该被表现出来，而不是被报告出来。**

---

# 10. 默认值不是关系

例如：

```text
unknown_user_affinity = 78
```

只能理解成 prior，而不是已经形成的真实关系。

推荐：

```yaml
affinity:
  prior: 0.78
  evidence_count: 0
  confidence: 0.05
```

原则：

```text
UNKNOWN ≠ DEFAULT RELATIONSHIP
prior ≠ experience
```

---

# 11. Relationship：独立成权威关系状态

未来最好只有一个 authoritative Relationship Model。

```yaml
RelationshipState:
  subject: user_x
  familiarity:
    value: 0.81
    confidence: 0.92
  affinity:
    value: 0.76
    confidence: 0.84
  trust:
    value: 0.69
    confidence: 0.71
  evidence_count: 37
```

Iris：

```text
提供关系证据
```

Relationship Engine：

```text
维护关系状态
```

Affect Engine：

```text
读取关系状态
```

避免 Iris 和情绪插件分别维护两份互相冲突的长期关系数值。

---

# 12. 情绪插件的融合方式

现有情绪插件的核心思路保留：

```text
current state
↓
随时间衰减
↓
baseline
```

未来抽象成：

```text
unconscious_llm
→ Affect Interpreter

current_libido_*
current_aggression_*
→ Affect State

base_libido_*
base_aggression_*
→ Affect Baseline

衰减逻辑
→ State Dynamics

idle check
→ Synthetic Event
```

它不再是孤立插件，而成为统一系统中的：

> **Affect Engine**

---

# 13. 多时间尺度状态

```text
秒～分钟
Situation State
Current Affect

小时～天
Temporary Behavioral State

天～周
Relationship State
Behavioral Prior

周～月
Affect Baseline
Belief / Stable Impression

非常慢
Stable Traits

原则上不自动修改
Core Identity / Persona
```

也就是说：

> **经历先造成短期激活，只有反复强化后才可能长期巩固。**

---

# 14. 记忆、情绪、关系：并行解释同一次 Experience

完成：

```text
Identity Resolution
↓
Perspective Resolution
↓
Canonical Experience
```

之后：

```text
Memory
Affect
Relationship
```

基本并行更新。

同一次经历可以同时导致：

```text
Memory
→ 记录发生过什么

Affect
→ 当前情绪变化

Relationship
→ 形成新的关系证据
```

它们不需要严格串行。

---

# 15. 模块之间允许读，但不要互相乱写

推荐：

```text
各模块拥有自己的 authoritative state

允许：
read other state

禁止：
directly mutate other state
```

例如 Affect Engine 可以读取 RelationshipState，但不能直接修改它。

如果发现关系证据，只产出：

```yaml
evidence:
  type: relationship_signal
```

由 Relationship Engine 决定是否接受。

---

# 16. 行为层拆成两个东西

## 16.1 Behavioral Prior（行为倾向）

决策前已存在：

```yaml
behavioral_prior:
  casual_chat:
    verbosity: low
    unsolicited_followup: avoid
```

它影响下一次行为。

## 16.2 Behavior Review（行为复盘）

发生在：

```text
Decision
↓
Action
↓
Outcome
↓
Review
```

它负责修改 Behavioral Prior。

因此 Review **不与 Memory / Affect / Relationship 并排**。

---

# 17. 行为复盘的单位是 Episode

Review 不评价单句，而评价：

```text
情境
+
当时内部状态
+
决策
+
实际输出
+
别人如何回应
+
话题如何发展
+
结果
```

这整个互动片段称为：

```text
Episode
```

---

# 18. Situation Model：我们现在正在经历什么

未来应维护一个短期情境状态。

例如：

```yaml
situation:
  shared_focus:
    type: image_event
    summary: "群友正在围观某个反常场景"

  mode: casual_group_chat

  active_participants: [...]

  agent_state:
    already_commented: true
```

它回答：

> **“我们现在正在共同经历什么？”**

而不是只看单条 current message。

---

# 19. SILENCE 必须是一等 Action

Action Space 不能只有回复。

至少包括：

```text
SILENCE
REACTION
WAIT
REPLY
ACTION
```

原则：

> **“我理解这件事”不等于“我需要说一句”。**

---

# 20. Trigger：什么引发一次决策循环

不是每个 Event 都应该进入 Decision。

需要先判断：

> **“这件事值得我现在启动一次行为决策吗？”**

```text
Event
↓
Trigger Evaluation
↓
YES / NO
```

Trigger：

> **什么时候值得醒过来。**

Decision：

> **醒来以后做什么。**

因此允许：

```text
Trigger = YES
Decision = SILENCE
```

也允许：

```text
Trigger = NO
```

---

# 21. Trigger 不应每次调用 LLM

推荐：

```text
事件
  ↓
第 0 层：硬规则
  ↓
第 1 层：轻量状态机 / score
  ↓
只有模糊场景
  ↓
第 2 层：轻量 LLM classifier
  ↓
必要时启动主 Agent
```

例如：

```text
私聊
→ 强触发

明确 @ 小天文
→ 强触发

回复小天文
→ 强触发

普通群聊
→ 弱触发

刚主动说过且无人回应
→ 强抑制
```

目标：

> **绝大多数 Trigger evaluation 不经过 LLM。**

---

# 22. Trigger / Decision / Execution 三层行为系统

```text
Activation
什么时候值得醒过来

Decision
醒来以后做什么

Execution
决定之后具体怎么做
```

中文：

```text
触发层
决策层
执行层
```

Behavioral Learning 可以逐渐调整：

```text
触发阈值
行为选择偏好
行为表现方式
```

---

# 23. “主动接话”应该放在哪里

主动接话不再属于 Iris。

它更准确的位置是：

> **主动触发策略（Proactive Trigger Policy）**

可能读取：

```text
Memory relevance
Relationship motivation
Personal interest
Affect
Situation
Behavioral Prior
```

然后判断：

```text
是否值得启动一次决策循环
```

因此：

> **Memory relevance ≠ action permission.**

---

# 24. Memory is retrieved. Policy is compiled.

事实记忆可以按需检索：

```text
Memory
→ relevance
→ retrieve
```

行为策略如果要稳定影响行为，则需要由长期 observation 编译成小而稳定的 Policy。

```text
Review Observations
        ↓
Aggregation
        ↓
Deduplication
        ↓
Confidence
        ↓
Decay
        ↓
Abstraction
        ↓
Compact Behavioral Policy
```

原则：

> **Memory is retrieved. Policy is compiled.**

---

# 25. 长期学习链

```text
Raw Event
   ↓
Episodic Memory
   ↓
Interpretation
   ↓
Pattern
   ↓
Generalization
   ↓
Behavioral Prior
```

但 Behavioral Prior 的更新必须尽量依赖：

```text
Action
↓
Outcome
↓
Review
```

不能只凭：

```text
发生了 X
→ 所以以后应该 Y
```

---

# 26. Reinterpretation：经历的意义可以被重新解释

原始事实：

```text
某人没有回复我
```

可以存在：

```text
Interpretation v1
→ negative social feedback

Interpretation v2
→ unrelated external cause
```

原始 Experience 不变。

Behavioral Policy 应依据：

> **当前最可信解释**

而不是直接拿 Raw Event 训练。

---

# 27. Canonical Memory 与 Derived Structure 分离

底层原始记录尽量稳定：

```text
MemoryRecord
- id
- timestamp
- source
- subject_entity
- content
- confidence
- provenance
- embedding
```

上层允许：

```text
merge
split
abstract
link
cluster
hierarchy
timeline
graph
```

演化优先发生在：

> **Derived Structure / View**

而不是破坏 Canonical Memory。

---

# 28. Structure Evolution 的两个维度

## Topology Evolution

```text
list
timeline
graph
hierarchy
topic cluster
entity view
```

## Semantic / Functional Evolution

```text
Raw Event
   ↓
Episodic Memory
   ↓
Pattern
   ↓
Abstract Knowledge
   ↓
Behavioral Rule
   ↓
Adaptive Policy
```

核心：

> **Agent 的记忆不仅应该换结构，还应该换角色。**

---

# 29. Iris L1-L3 的未来定位

现有：

```text
L1：信息缓存 / 瞬时记忆
L2：事实提取 / 长时记忆
L3：关系认识
```

未来可保留为：

> **Legacy / Baseline View**

例如：

```text
Memory Views
├─ Iris L1-L3 View
├─ Timeline View
├─ Entity Graph View
├─ Topic Hierarchy View
└─ Behavioral Pattern View
```

不需要一开始修改生产存储。

---

# 30. Fast Adaptation 与 Slow Consolidation

短期适应：

```text
低权重
带 TTL
快速衰减
```

长期巩固要求：

```text
多次出现
跨会话
跨用户
跨时间
高置信度
```

Core Persona 原则上：

> **不自动修改。**

---

# 31. Behavioral Policy 必须有 Scope

建议：

```text
global
group:<id>
relationship:<class>
topic:technical
topic:casual
context:meme
context:observing
```

不同场景允许形成不同倾向，而不是全局一刀切。

---

# 32. Review 不能把回复数量简单当 Reward

禁止：

```text
reply_count ↑
= 行为更好
```

Review 应结合：

```text
上下文
回复内容
是否延续话题
是否引用小天文
后续语气
多用户证据
重复次数
时间跨度
```

它产生的是：

> **weak behavioral evidence**

而不是立即形成永久规则。

---

# 33. 当前推荐的最小数据对象

```yaml
Entity:
  id:
  aliases:
  platform_ids:
```

```yaml
Identity:
  self_entity:
```

```yaml
Experience:
  id:
  actor:
  event:
  timestamp:
  source:
  salience:
```

```yaml
Interpretation:
  experience_id:
  observer:
  meaning:
  confidence:
  version:
```

```yaml
RelationshipState:
  subject:
  familiarity:
  affinity:
  trust:
  evidence_count:
  confidence:
```

```yaml
BehavioralPrior:
  scope:
  tendency:
  strength:
  confidence:
  evidence:
  decay:
```

---

# 34. 当前 P0 优先级

在做 Graph / Hierarchy / Review Agent 之前，先保证地基：

```text
P0.1 Entity Registry
稳定实体 ID

P0.2 Alias / Identity Resolution
多个名字 → 同一实体

P0.3 Coreference Resolution
我 / 你 / 他 / 昵称 → entity

P0.4 SELF Binding
SELF → canonical entity

P0.5 Perspective Projection
自己的记忆 → autobiographical
别人 → interpersonal / world knowledge

P0.6 Provenance
为什么认为 A 和 B 是同一个人
```

否则后面会出现：

> Evolution Engine 很先进地把同一个人的三个马甲演化成三个完整人格。（

---

# 35. 一个关键测试

```text
Given:
  SELF = agent:xiaotianwen

When:
  retrieve(memory.subject == agent:xiaotianwen)

Then:
  runtime representation MUST be autobiographical
  and MUST NOT describe 小天文 as an external third-person entity.
```

即：

```text
数据库可以第三人称存储
↓
Runtime 必须正确投影成第一人称经历
```

---

# 36. Write Path 与 Read Path

## Experience / Learning Path

```text
Event
 ↓
Entity Resolution
 ↓
Perspective Resolution
 ↓
Canonical Experience
 ↓
┌────────┬──────────┬──────────────┐
Memory   Affect   Relationship
 ↓         ↓          ↓
长期独立演化 / consolidation / decay
```

行为学习单独：

```text
Action
↓
Outcome
↓
Review
↓
Behavioral Prior
```

## Runtime / Action Path

```text
Current Event
        ↓
Trigger
        ↓
Situation Model
        │
        ├── Retrieved Memory
        ├── Relationship State
        ├── Affect State
        ├── Behavioral Prior
        └── AstrBot Persona
        │
        ▼
Decision
        ↓
SILENCE / REPLY / ACTION
```

两个路径最终形成闭环：

```text
Experience
   ↓
内部状态变化
   ↓
Action
   ↓
Outcome
   ↓
New Experience
```

---

# 37. 当前还没有冻结的部分

1. Situation Model 是否始终维护极轻量版本，还是 Trigger 后才正式构建。
2. Trigger 使用事件前状态，还是等待 Affect / Relationship 更新后的统一快照。
3. Belief 第一版是否单独建模，还是先作为 Memory 的 Derived View。
4. RelationshipState 第一版保留哪些维度。
5. Episode 如何判定结束。
6. Review 在 Episode 结束后等待多久。
7. Behavioral Prior 用自然语言规则、数值参数，还是混合形式。
8. Entity Resolution 中规则、UID、LLM 各承担多少职责。
9. 旧 Iris 数据如何映射到新的 Entity / Perspective。
10. 情绪插件 affection 与 Iris affinity 的迁移策略。

---

# 38. 脑子过载时只记这一版

```text
谁是谁
  ↓
这件事对“我”意味着什么
  ↓
它改变了我的记忆 / 情绪 / 关系
  ↓
值不值得启动行为决策
  ↓
现在怎么做
  ↓
发生了什么结果
  ↓
事后复盘
  ↓
慢慢形成行为倾向
```

---

# 39. 当前最重要的四句话

> **Memory：我经历了什么。**

> **Policy：我从经历中学会了什么。**

> **Persona：无论经历什么，我仍然是谁。**

> **Identity 决定谁是谁，Perspective 决定这些经历是不是“我的经历”。**

---

# 40. 当前核心研究问题

> **智能体如何把长期积累的经历转化为可泛化的行为策略，同时保持核心人格与主体视角稳定？**

英文：

> **How should an agent transform accumulated experiences into adaptive behavioral policies without destabilizing its core identity and self-perspective?**

---

# 41. 一句话总结

> **下一代系统不是让小天文“拿到更多关于小天文的资料”，而是让经历真正成为属于“我”的经历，并让这些经历以受控、可解释、可回滚的方式逐渐改变“我以后怎么做”。**

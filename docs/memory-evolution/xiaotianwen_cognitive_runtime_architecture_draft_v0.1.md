# 小天文认知运行时与 Iris 兼容层开发设计

> **状态：Architecture Draft v0.1 — Review / Implementation Planning**
> **目标：** 冻结模块职责、数据契约、执行路径、Iris 兼容边界与开发阶段。
> **约束：** 当前阶段不迁移生产 Iris 数据，不重写现有 L1–L3，不重复定义 AstrBot Persona，不提前绑定数据库技术栈。

---

# 1. 目标

当前 Iris 已经能够提供 L1–L3 记忆、长期事实、关系认知、黑话等能力，但存在几个结构性问题：

- 同一人物的多个称呼无法稳定归并为同一实体；
- 小天文自身的记忆经常仍以“小天文”“助手”等第三人称形式进入上下文；
- Memory、关系、情绪、主动回复与 Persona 之间职责混杂；
- 内部关系数值、人物总结容易直接泄露为台词；
- 当前主动回复系统主要解决“这一轮是否说话”，缺少 `Action → Outcome → Review → Learning`；
- 回复生成缺少明确的“为什么说这句话”的发言意图层；
- Agent 默认倾向于“既然进入 Loop，就生成一点东西”，产生稳定的通用聊天模型味。

本项目目标不是重新实现一个 Memory Database，而是建立：

> **以主体经历为中心的 Cognitive Runtime，并复用 Iris 作为 L1–L3 Memory Backend。**

核心原则：

> **沉默是默认状态；发言必须有理由。**
> **Silence is the default. Speech must have an intent.**

---

# 2. 非目标

第一阶段明确不做：

- 不迁移现有 Iris 数据；
- 不重写 Iris L1–L3；
- 不替换 AstrBot Persona；
- 不自动修改 Core Persona；
- 不把所有模块都实现成 LLM Agent；
- 不立即决定 SQL / Graph DB / Vector DB 等底层存储技术；
- 不在 P0 实现完整 Structure-Evolving Memory；
- 不让 Behavior Review 直接修改 Persona、RelationshipState 或 AffectState；
- 不要求一次性清洗全部历史 Iris 数据。

---

# 3. 总体架构

```text
                    ┌─────────────────────┐
                    │   AstrBot Persona   │
                    │   “小天文是谁”       │
                    │ 唯一自然语言人格定义  │
                    └──────────┬──────────┘
                               │
                               │
原始消息 / 图片 / @ / Reply / Tool / Timer / System Event
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Event Normalizer  │
                    │     事件规范化       │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │  Identity Resolver  │
                    │ UID / Alias / Mention│
                    │ Coreference → Entity│
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │Perspective Resolver │
                    │ SELF / 你 / 他 / 我们 │
                    └──────────┬──────────┘
                               ▼
                      Canonical Experience
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌────────────┐   ┌────────────┐  ┌────────────┐
        │ Iris L1-L3 │   │Affect Engine│  │Relationship│
        │ Memory     │   │             │  │ Engine     │
        └─────┬──────┘   └─────┬──────┘  └─────┬──────┘
              │                │               │
              ▼                ▼               ▼
         Memory View       AffectState    RelationshipState
              │                │               │
              └────────────────┼───────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Trigger Controller  │
                    │ 值得启动行为 Loop？ │
                    └──────────┬──────────┘
                         NO    │    YES
                         ↓     │
                        END    ▼
                    ┌─────────────────────┐
                    │ Situation Builder   │
                    │ 当前共同情境         │
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Participation Gate  │
                    │   是否需要参与？     │
                    └──────────┬──────────┘
                         NO    │
                         ↓     ▼
                        END
                    ┌─────────────────────┐
                    │    Intent Gate      │
                    │ 我想干什么？         │
                    │ 为什么？             │
                    │ 对谁？               │
                    │ 依据是什么？         │
                    └──────────┬──────────┘
                         无明确 Intent
                               │
                               ├──────────→ END
                               ▼
                    ┌─────────────────────┐
                    │   Grounding Gate    │
                    │事实 / SELF / 关系依据│
                    └──────────┬──────────┘
                         无依据 │
                   END / 降级   │
                               ▼
                    ┌─────────────────────┐
                    │ Response Realizer   │
                    │Persona + Intent→Text│
                    └──────────┬──────────┘
                               ▼
                              SEND
                               │
                               ▼
                       Episode Tracker
                               │
                               ▼
                         Outcome Window
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Behavior Reviewer   │
                    │ 复盘整个 Episode    │
                    └──────────┬──────────┘
                               ▼
                       Review Evidence
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Consolidator      │
                    └──────────┬──────────┘
                               ▼
                       Behavioral Prior
                         │             │
                         ▼             ▼
                   未来 Trigger    未来 Decision
```

---

# 4. Persona、Identity 与 Perspective 的边界

## 4.1 Persona

继续完全由 AstrBot 负责。

```text
你叫小天文，是……
```

这是唯一自然语言人格来源。

新的 Runtime 禁止再次定义一套 Persona。

## 4.2 Identity

只负责机器级身份：

```yaml
self_entity: agent:xiaotianwen
```

它回答：

> 谁是小天文？

## 4.3 Perspective

回答：

> 当前这条 Experience 与 SELF 是什么关系？

例如：

```yaml
subject: agent:xiaotianwen
```

由于：

```text
agent:xiaotianwen == SELF
```

因此 Runtime 中必须投影为：

```text
[你的经历]
你以前……
```

而不是：

```text
小天文以前……
```

硬性 invariant：

```text
数据库可以第三人称存储。
Runtime 不得把 SELF 当成外部第三人称实体。
```

---

# 5. Entity Resolution

名字不能作为实体本身。

```text
“龙洲”
“longz”
“龙妹”
某 QQ 群名片
      │
      ▼
person:<canonical-id>
```

优先级原则：

```text
稳定平台 ID
    >
已有明确 Identity Binding
    >
已确认 Alias
    >
上下文 Coreference
    >
LLM 推断
```

LLM 推断不得直接不可逆 Merge。

所有 Identity Merge 至少需要：

```yaml
IdentityClaim:
  mention:
  candidate_entity:
  evidence:
  confidence:
  source:
  created_at:
```

支持：

```text
CONFIRMED
POSSIBLE
REJECTED
REVOKED
```

---

# 6. Iris 的职责

Iris 第一阶段继续负责：

```text
L1：短时 / 当前信息
L2：长期事实 / Event / Knowledge
L3：关系认知 / Relationship Evidence
```

Iris 回答：

> **“我记得什么？”**

它不再负责最终决定：

```text
我要不要说话
我现在是什么情绪
我应该采用什么社交行为
我刚才表现得好不好
```

尤其需要逐步取消：

```text
memory relevance
→ therefore reply
```

改为：

```text
memory relevance
→ Trigger / Decision 的一个输入
```

---

# 7. Iris Adapter

## 7.1 写入前置层

```text
Raw Event
↓
Entity Resolution
↓
Perspective Resolution
↓
Iris Preprocessor
↓
Iris
```

即使 Iris 暂时只能接自然语言，Adapter 也应保留结构化 metadata。

## 7.2 检索后置层

```text
Iris Result
↓
Canonicalization Overlay
↓
Perspective Projection
↓
Runtime Memory View
```

例如：

```text
Iris:
“小天文曾经和 NICEICK……”
```

转换：

```text
[你的经历]
你曾经和 NICEICK……
```

---

# 8. 历史错乱记忆：Memory Repair Overlay

不直接洗库。

```text
Raw Iris Memory
      ↓
Repair Metadata
      ↓
Canonical Memory View
      ↓
Runtime
```

建议：

```yaml
RepairMetadata:
  memory_id:
  canonical_subject:
  canonical_objects:
  perspective:
  status:
  confidence:
  duplicate_group:
  conflict_set:
  superseded_by:
  repair_reason:
  repair_version:
  provenance:
```

`status` 可包括：

```text
ACTIVE
DUPLICATE
CONFLICTED
STALE
INVALID
UNRESOLVED
```

处理优先级：

```text
SELF 相关历史记忆
↓
高频人物实体归一
↓
L3 关系记忆
↓
黑话 / Shared Group Culture
↓
低频普通事实
```

支持：

```text
Lazy Repair
第一次读取旧记忆时修复

Offline Repair
后台逐步扫描高价值历史数据
```

Raw Memory 保持不变，因此可以 rollback。

---

# 9. Relationship Engine

Iris L3 逐步定位为：

> **Relationship Evidence**

而不是最终 authoritative state。

新的 Runtime 维护：

```yaml
RelationshipState:
  subject_entity:
  familiarity:
    value:
    confidence:

  affinity:
    value:
    confidence:

  trust:
    value:
    confidence:

  evidence_count:
  version:
  updated_at:
```

第一版字段必须保持少量，避免重新制造几十参数“人物卡”。

---

# 10. Affect Engine

现有情绪插件的核心模型保留：

```text
Current Affect
      ↓ decay
Affect Baseline
```

大致映射：

```text
current_libido_*
current_aggression_*
→ AffectState

base_libido_*
base_aggression_*
→ AffectBaseline

衰减
→ State Dynamics

idle_check
→ Synthetic Event
```

原来的长期 `affection` 不再作为第二套权威 RelationshipState。

Affect 可以：

```text
READ RelationshipState
```

但不能：

```text
WRITE RelationshipState
```

---

# 11. 状态所有权

| 状态 | Owner | 可读取 | 可直接修改 |
|---|---|---|---|
| Entity Registry | Identity | 全部模块 | Identity |
| Raw Memory | Iris | Runtime | Iris |
| Repair Metadata | Iris Adapter | Runtime | Repair Layer |
| RelationshipState | Relationship Engine | Affect / Decision / Intent | Relationship Engine |
| AffectState | Affect Engine | Decision / Intent | Affect Engine |
| Situation | Situation Builder | Behavior Runtime | Situation Builder |
| BehavioralPrior | Behavioral Runtime | Trigger / Decision / Intent | Consolidator |
| Persona | AstrBot | Realizer / Decision | AstrBot 配置 |
| ReviewEvidence | Reviewer | Consolidator | Reviewer |

原则：

> **模块可以读取其他模块状态，但不能跨边界直接修改。**

---

# 12. Trigger Controller

Trigger 只回答：

> **值不值得启动一次行为决策 Loop？**

它不回答：

> 要说什么？

分三级：

```text
Level 0
确定性规则

↓ 模糊

Level 1
轻量状态机 / Score

↓ 仍模糊

Level 2
轻量 LLM Classifier
```

典型硬信号：

```text
私聊                         +++
明确 @SELF                    +++
reply_to_self                +++
正在继续 SELF 发起的问题      ++
重要 Tool Result              +++

普通群聊                     +
刚主动说过且没人回应           ---
快速 human↔human 对话          --
重复内容                       --
```

目标：

> **绝大多数 Trigger 判断不调用 LLM。**

---

# 13. Situation Model

回答：

> **我们现在正在共同经历什么？**

建议最小结构：

```yaml
Situation:
  episode_id:

  shared_focus:
    type:
    summary:

  mode:
    # casual_group_chat / technical / private / ...

  active_entities: []

  current_topic: []

  self_participation:
    already_spoke:
    last_action:
    last_action_at:

  unresolved_items: []

  updated_at:
```

Situation 是短生命周期状态，不等同于长期 Memory。

---

# 14. Participation Gate

Trigger YES 仅代表：

> 值得醒过来看一眼。

不代表：

> 必须参与。

Participation 可以直接输出：

```text
PARTICIPATE
SILENCE
WAIT
```

因此：

```text
Trigger = YES
Decision = SILENCE
```

是合法结果。

---

# 15. Intent Gate

只有决定参与后，才进入 Intent。

最小 Contract：

```yaml
Intent:
  action:
  target:
  reason_for_action:
  basis:
  confidence:
```

必须能够回答：

```text
我现在想干什么？
为什么？
对谁？
依据是什么？
```

但无需生成自然语言长解释。

例如：

```yaml
action: ACKNOWLEDGE
target: person:123
reason_for_action: social_acknowledgement
basis:
  - current_event
confidence: 0.91
```

如果无法形成明确 Intent：

```text
NO_INTENT
→ END LOOP
```

核心原则：

> **进入 Agent Loop 不意味着必须生成文字。**

以及：

> **Silence is the default. Speech must have an intent.**
> **沉默是默认状态；发言必须有理由。**

---

# 16. Social Action Space

第一版建议保持有限：

```text
ACKNOWLEDGE
ASK
CLARIFY
INFORM
SHARE
TEASE
CONTINUE_JOKE
DISAGREE
SUPPORT
CORRECT
REACT
SILENCE
```

避免一开始扩展出几十种行为类型。

---

# 17. Grounding Gate

Intent 回答：

> 为什么行动？

Grounding 回答：

> 有没有资格说具体内容？

二者必须分开。

例如：

```text
用户：今晚几点观测？

Intent：
INFORM
因为对方明确提问
```

即使系统不知道时间，Intent 依然成立。

Grounding：

```text
当前没有可靠时间信息
```

因此可能：

```text
调用工具
或者
明确表达不知道
```

而不是 `NO_INTENT`。

Grounding 重点防止：

```text
Persona 临时虚构自传
Persona 临时虚构关系
语言风格反向制造 Internal State
Profile Summary 直接变成人物评价台词
```

原则：

> **Internal State ≠ Dialogue Content.**

以及：

> **Dialogue Style ≠ Internal State Evidence.**

---

# 18. Response Realizer

只有到这里才真正负责：

> **怎么说。**

输入：

```text
Intent
+
Grounding Result
+
Persona
+
Affect
+
Relationship
+
Situation
```

输出：

```text
Text / Reaction / Tool Action
```

Persona 在这里影响：

```text
措辞
语气
长度
幽默方式
表达习惯
```

而不是负责决定整个行为意图。

---

# 19. 多个合法退出点

Runtime 必须 fail-closed。

```text
Event
↓
Trigger
├─ TRIGGER_NO → END
▼
Situation
↓
Participation
├─ NO_PARTICIPATION → END
▼
Intent
├─ NO_INTENT → END
▼
Grounding
├─ GROUNDING_FAILED → END / DEGRADED
▼
Decision
├─ SILENCE_SELECTED → END
▼
Realization
├─ REALIZATION_FAILED → END
▼
SEND
```

这些 Exit Reason 必须在日志中区分。

禁止全部统一叫：

```text
skip
```

---

# 20. Episode Tracker

Review 的最小单位：

> **Episode，而不是 Utterance。**

一个 Episode 应至少保存：

```yaml
Episode:
  id:

  situation_snapshot:
  state_snapshot:

  trigger:
  participation:
  intent:
  grounding:

  action:
  actual_output:

  subsequent_events: []

  outcome:
  started_at:
  closed_at:
```

Episode 如何结束目前尚未冻结。

候选条件：

```text
topic changed
timeout
new episode begins
explicit interaction closure
```

---

# 21. Behavior Review

Review 发生在：

```text
Action
↓
Outcome
↓
Review
```

而不是收到输入后马上运行。

Reviewer 应能够区分：

```text
Trigger 错了吗？
Participation 错了吗？
Intent 选错了吗？
Grounding 错了吗？
Realization 写坏了吗？
Outcome 实际怎么样？
```

例如：

```yaml
ReviewEvidence:
  episode_id:

  trigger_quality:
  participation_quality:

  intent:
    selected:
    assessment:

  grounding_quality:
  realization_quality:

  outcome_summary:

  behavioral_pattern:
  confidence:

  scope:
```

它产出 Evidence，不直接修改行为参数。

---

# 22. Behavioral Prior

多次 ReviewEvidence：

```text
Evidence
↓
Aggregation
↓
Confidence
↓
Decay
↓
Consolidation
↓
BehavioralPrior
```

例如：

```yaml
BehavioralPrior:
  scope:
    mode: fast_group_chat

  tendency:
    unsolicited_followup: -0.35

  confidence: 0.81

  evidence:
    - episode_12
    - episode_51
    - episode_74

  version:
  decay:
```

它可以影响：

```text
Trigger threshold
Participation preference
Intent preference
Expression tendency
```

不能直接修改 Core Persona。

---

# 23. Memory 与 Policy

继续采用：

> **Memory is retrieved. Policy is compiled.**

Memory：

```text
按需检索历史事实与经历
```

Behavioral Policy：

```text
由大量 Review Evidence 编译为紧凑 Runtime State
```

禁止：

```text
把 200 条 Review Observation 全塞进 Prompt
```

---

# 24. 同步快路径与异步慢路径

## 同步快路径

必须保证当前响应：

```text
Event Normalize
→ Identity
→ Perspective
→ Trigger
→ Situation
→ Participation
→ Intent
→ Grounding
→ Realization
→ SEND / END
```

## 异步慢路径

原则上不得阻塞正常回复：

```text
复杂 Memory 抽取
Historical Repair
Relationship Consolidation
Affect Baseline Consolidation
Episode Review
Behavior Evidence Consolidation
Structure Evolution
```

---

# 25. 当前 Iris 主动回复如何复用

现有 Iris 已经拥有：

```text
激活
评估
意愿
阈值
退避
连续
跳过
话题偏移
```

第一阶段不删除。

将其视作：

```text
Legacy Trigger
+
Immediate Decision Guard
```

新的系统在外面补：

```text
Action
↓
Outcome
↓
Review
↓
Learning
```

逐步让：

```text
人工阈值
```

变成：

```text
base threshold
+
BehavioralPrior modifier
+
Situation modifier
```

---

# 26. P0 / P1 / P2

## P0 — 地基 + 最小闭环

必须实现：

```text
Entity Registry
Alias / UID Resolution
Coreference 基础能力
SELF Binding
Perspective Projection
Provenance
Iris Adapter
Situation
Trigger
Intent Gate
Grounding
END / SEND
Episode
ReviewEvidence
```

最小 Vertical Slice：

```text
群消息
↓
Entity / SELF
↓
Situation
↓
Trigger
↓
Intent
↓
Grounding
↓
Reply / END
↓
Episode
↓
ReviewEvidence
```

P0 暂时可以不让 Review 真正自动改变 Prior。

---

## P1 — 状态融合与行为学习

加入：

```text
RelationshipState
Affect Engine Adapter
BehavioralPrior
Consolidator
Trigger Prior Modifier
Intent Preference
Lazy Memory Repair
```

实现：

```text
Outcome
→ Review
→ Evidence
→ Prior
→ 影响下一次行为
```

---

## P2 — Structure Evolution

再进入：

```text
Timeline View
Entity Graph
Hierarchy
Topic Cluster
merge / split / abstract / link
Retrieval Planner
Topology Evolution
```

P2 不应成为 P0/P1 的硬依赖。

---

# 27. 测试策略

需要四层：

```text
Unit Test
Contract Test
Conversation Replay
Differential / Ablation Test
```

其中最重要的是历史真实群聊 Replay。

关键 invariant：

```text
Given:
SELF = agent:xiaotianwen

When:
retrieve(memory.subject == SELF)

Then:
Runtime representation MUST be autobiographical.

不得输出：
“小天文曾经……”

应表示：
“你曾经……”
```

另外需要专门测试：

```text
Alias → Entity
旧昵称变化
UID 稳定
错误 Merge rollback
NO_INTENT
Grounding failure
Trigger NO
Trigger YES + SILENCE
Episode closure
Review 不跨模块写状态
```

---

# 28. Baseline / Ablation

至少保留：

```text
A
现有 Iris 主动回复

B
Iris + Identity/Perspective Adapter

C
B + Trigger/Intent/Grounding

D
C + Episode Review

E
D + BehavioralPrior

F
E + Structure Evolution
```

建议观察：

```text
无效插话率
generic assistant 回复比例
无依据 Self/Relationship 声明
被继续互动率
重复/多余发言率
NO_INTENT 正确退出率
人工偏好
主体连续性
历史经历引用正确率
```

---

# 29. 可观测性

每个 Loop 至少记录：

```yaml
event_id:
episode_id:

resolved_entities:
self_entity:

trigger:
  decision:
  reason:

participation:
  decision:

intent:
  action:
  target:
  reason_for_action:
  basis:

grounding:
  status:
  sources:

exit_reason:

response:

review:
```

以后看到一句怪话，必须能追：

> 到底是哪一层把它搞怪了？

而不是只剩：

```text
LLM output weird
```

---

# 30. 当前未冻结的问题

目前仍需专门设计：

1. Situation 是否所有消息都维护轻量版本；
2. Trigger 使用事件更新前还是更新后的 Affect/Relationship snapshot；
3. Episode 的结束条件；
4. RelationshipState 第一版最少字段；
5. AffectState 与 RelationshipState 的精确交互；
6. BehavioralPrior 第一版使用数值、规则还是混合；
7. Intent Planner 是否需要 LLM，以及何时可以确定性完成；
8. Grounding Gate 是否规则优先 + LLM fallback；
9. 老 Iris 中“助手”“小天文”等错误 SELF 记录如何自动判定；
10. 黑话库应该作为 `shared_group` memory 还是独立 Cultural View；
11. Iris 现有 L3 哪部分保留为 evidence、哪部分逐步退役；
12. 当前主动回复“后判定”具体应放在新 Trigger / Participation 哪一层。

---

# 31. 推荐 Codex 实施顺序

```text
Phase 1
定义 contracts，不写业务逻辑

Phase 2
Entity Registry + SELF + Perspective

Phase 3
Iris Pre/Post Adapter

Phase 4
Replay 验证旧记忆第一人称投影

Phase 5
Situation + Trigger + Exit Reasons

Phase 6
Participation + Intent Gate

Phase 7
Grounding + Response Realizer

Phase 8
Episode Tracker

Phase 9
ReviewEvidence

Phase 10
Relationship / Affect Adapter

Phase 11
BehavioralPrior + Consolidation

Phase 12
渐进 Memory Repair

Phase 13
再考虑 Structure Evolution
```

---

# 32. P0 Definition of Done

P0 完成时，给任意一条历史群聊消息，系统必须能够回答：

```text
这条消息中的人分别是谁？

哪一个是 SELF？

这件事和 SELF 是什么关系？

是否值得启动行为 Loop？

如果启动，为什么要参与？

想做什么社会行为？

针对谁？

为什么？

依据是什么？

如果想不出来，是否正确 END？

如果发言，这句话引用的事实/关系依据是什么？

最终为什么 SEND / END？

这个 Action 属于哪个 Episode？

Episode 后产生了什么 ReviewEvidence？
```

并满足：

> **任何一步无法形成可靠结论时，优先退出或降级，而不是让 LLM 凭空补全。**

---

# 33. 模型分工建议

> 本节是工程执行建议，不属于架构硬约束。原则是：**强模型负责定边界和处理高风险歧义；中档模型负责常规实现；高吞吐模型负责确定性施工、测试与重复劳动。**

## 33.1 Sol：架构、难题、最终 Review

适合：

- Phase 1：contracts、模块边界、状态所有权最终冻结；
- Entity Resolution 中最棘手的语义边界设计；
- Perspective / SELF invariant 设计；
- Trigger / Participation / Intent / Grounding 的职责边界；
- Episode / Review / BehavioralPrior 学习闭环设计；
- 并发、状态一致性、循环依赖等复杂问题；
- 难复现 bug 的根因分析；
- P0 / P1 阶段最终架构验收；
- P2 Structure Evolution 的核心算法与实验设计；
- 跨 Iris / AstrBot / Cognitive Runtime 的最终 Review。

不建议：

- 批量改字段名；
- 大量简单 DTO/schema；
- 重复写测试 fixture；
- 普通文档整理；
- 机械性迁移代码。

一句话：

> **Sol 用来决定“应该怎么建”和“为什么坏了”，不要拿来批量拧螺丝。**

## 33.2 Terra：常规多文件实现与中等复杂重构

适合：

- Phase 2–11 中大部分常规实现；
- contracts 落地；
- Adapter 层；
- Entity Registry；
- Situation Builder；
- Trigger 状态机；
- Intent / Grounding contract；
- Episode Tracker；
- Relationship/Affect Adapter；
- BehavioralPrior / Consolidator 的第一版；
- 中等规模跨文件 refactor；
- 根据 Sol 已冻结架构完成完整 feature slice。

当任务具备：

```text
边界已经明确
+
需要多文件实现
+
仍有一定设计判断
```

时优先 Terra。

一句话：

> **Terra 是主力施工队。**

## 33.3 Luna：高吞吐施工、探索、测试和验收

适合：

- repo exploration / 文件搜索；
- 根据明确 contract 写 DTO、schema、adapter boilerplate；
- 批量单元测试；
- replay fixture；
- 日志与 observability；
- 简单规则、枚举、exit reason；
- 文档同步；
- 重复性 refactor；
- lint / type / unit test 修复；
- 大量历史对话 replay；
- P0/P1 长时间验收；
- 收集失败 case、最小复现、diff 和日志。

Luna 不应单独决定：

- Identity / SELF 的语义规则；
- Review 学习目标；
- Persona / Policy 边界；
- 跨模块状态所有权；
- 模糊并发或高风险数据修复策略。

一句话：

> **Luna 负责把已经想清楚的东西快速做完，并把坏掉的地方证据化。**

---

# 34. 按阶段推荐模型

| 阶段 | 主要任务 | 首选模型 | 推荐方式 |
|---|---|---|---|
| 架构冻结 | Contracts、状态所有权、模块边界 | **Sol** | Sol 主导，必要时 Luna 探索代码 |
| Phase 2 Entity/SELF | Registry、Alias、Perspective | **Terra + Sol Review** | Terra 实现，Sol 验语义不变量 |
| Phase 3 Iris Adapter | Pre/Post Adapter、projection | **Terra** | Luna 可补测试和样例 |
| Phase 4 Replay | 第一人称投影、历史 case | **Luna** | 大量 replay，失败 case 再交 Sol |
| Phase 5 Trigger | 状态机、score、exit reason | **Terra** | Luna 批量测试；模糊策略 Sol 定边界 |
| Phase 6 Intent | Intent contract、Participation | **Sol 设计 + Terra 实现** | 这是“非人感”核心，不宜完全交低档模型 |
| Phase 7 Grounding | 事实/关系/SELF 依据检查 | **Sol/Terra** | 规则优先；高风险边界 Sol Review |
| Phase 8 Episode | Tracker、生命周期 | **Terra** | Luna 补 fixture、超时/闭环测试 |
| Phase 9 ReviewEvidence | Review schema、诊断维度 | **Sol 设计 + Terra 实现** | 避免退化成一句话打分器 |
| Phase 10 Affect/Relationship | 旧插件兼容、状态拆分 | **Terra + Sol Review** | 重点审 authoritative state 边界 |
| Phase 11 BehavioralPrior | Consolidation、scope、decay | **Sol 主导设计** | Terra 实现；Luna 做长期 replay |
| Phase 12 Memory Repair | lazy/offline repair | **Terra** | Luna 批处理；错误 merge/冲突交 Sol |
| Phase 13 Structure Evolution | graph/hierarchy/merge/split/abstract | **Sol** | 先实验设计，再 Terra/Luna 施工 |
| P0 验收 | Contract、Replay、Invariant | **Luna + Sol Final Review** | Luna 跑全量，Sol 看 blockers/diff |
| P1 验收 | Outcome→Review→Prior 闭环 | **Luna + Sol Final Review** | 长跑交 Luna，学习语义交 Sol |
| 文档/机械维护 | docs、fixtures、日志、枚举 | **Luna** | 不浪费强模型 |

---

# 35. 推荐开发循环

每个 feature 建议采用：

```text
Sol
定义边界 / 高风险 invariant
        ↓
Terra
实现主要 feature
        ↓
Luna
补测试 / replay / 日志 / 大量验收
        ↓
发现明确 blocker
        ↓
Sol
根因分析 / 架构修正
        ↓
Terra 或 Luna
按修正方案落地
        ↓
Sol
阶段 Final Review
```

如果任务本身已经非常清晰，则可跳过 Terra：

```text
Sol 定 contract
↓
Luna 实现
↓
Luna 测试
↓
Sol Review
```

不要形成：

```text
Luna 猜架构
→ 写一堆
→ Sol 推翻
```

也不要形成：

```text
Sol 从建 DTO 到补 fixture 全包
```

---

# 36. 开发阶段模型使用原则

## 强模型升级条件

出现以下情况，应从 Luna/Terra 升级到 Sol：

- 两次实现仍无法稳定通过同一 invariant；
- 数据所有权出现循环依赖；
- SELF / Entity / Perspective 语义不确定；
- 同一输入在不同路径产生不同 authoritative state；
- Episode 无法稳定闭合；
- Review 学出的 Policy 出现人格漂移；
- Grounding 与 Persona 冲突；
- Memory Repair 有不可逆风险；
- 并发、重入、状态竞争难以定位；
- 修改会跨 Iris / AstrBot / Runtime 三个系统。

## 不升级条件

以下问题优先留给 Luna/Terra：

- 单测失败原因明确；
- DTO / schema 字段缺失；
- fixture / replay 补齐；
- lint/type error；
- 日志字段缺失；
- 简单 adapter；
- 已有规则的批量实现；
- 文档与代码同步。

---

# 37. 总设计原则

> **Persona 决定“我是谁”。**
> **Identity 决定“谁是我”。**
> **Memory 记录“我经历了什么”。**
> **Relationship / Affect 描述“这些经历让我现在处于什么状态”。**
> **Trigger 决定“我是否值得醒来”。**
> **Intent 决定“我为什么行动”。**
> **Grounding 决定“我有没有资格这么说”。**
> **Realizer 决定“我要怎么表达”。**
> **Review 决定“这次行为教会了我什么”。**

最终形成：

```text
经历
↓
成为“我的经历”
↓
改变内部状态
↓
产生行动理由
↓
行动
↓
产生后果
↓
形成新的经验
↓
逐渐改变以后怎么做
```

而不是：

```text
收到消息
↓
检索几条记忆
↓
以小天文风格生成一句话
```

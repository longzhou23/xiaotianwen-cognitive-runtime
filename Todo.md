# 小天文项目 TODO：实现备忘录，减少重复设计

更新：2026-09-07。当前目标：保留项目，精简新增认知层，让小天文认得人、以自己的视角记忆、保持人格，并从经历中受控调整行为。

需求来源：[下一代记忆与认知行为框架备忘](../../projects/xiaotianwen_memory_evolution_memo/xiaotianwen_memory_evolution_memo_v2.md)。备忘录是功能方向；其中“未来”“建议”“未冻结”不代表已经实现或可以自行决定。

## 给执行模型的规则

1. 每轮只完成下面一项的一个可验收子任务。先读指定入口、调用者和相关测试；已有功能通过验收即勾选，不再建同名框架。
2. 开始先看 Git 状态，保留已有未提交改动。默认只改源码、相关测试和本 TODO；提交、推送、部署、删除线上数据需要用户明确要求。
3. 首选现有函数、配置、数据对象。新增模块前必须指出现有模块为何无法承担；禁止为了阶段编号新增 manager/authority/archive/registry。
4. 修复需有具体输入与预期结果。测试正常例、反例、必要的历史兼容例；先跑关联测试，跨模块再扩大。不要反复重审已验收架构。
5. 完成后只报告改了什么、相关测试、用户可见效果、未验证项，并更新当前任务。测试通过不等于线上验证通过。
6. 涉及人格定义、关系状态 owner、自动学习批准方式的未冻结决策，列出具体问题并停下该部分；继续不依赖决策的工作。

## 代码入口与责任（路径相对仓库）

以下 `I` 指 `plugins/upstream/astrbot_plugin_iris_memory`，`C` 指 `I/iris_memory/cognitive`。

| 功能 | 优先使用的入口 | 不重复建设 |
|---|---|---|
| 人格 | AstrBot Persona；`I/iris_memory/core/persona.py` | 第二套人格提示词、自动改核心 Persona |
| 身份、自己的记忆 | `C/identity.py`、`perspective.py`、`iris_adapter.py` | 第二个实体注册表、重写 Iris 原始记录 |
| 参与与行为 | `C/trigger.py`、`situation.py`、`behavior.py`；插件 `main.py` | 每个事件都调用决策 LLM、第二套发送链 |
| 互动与复盘 | `C/episode_*`、`outcome*`、`review*` | 第二套会话结束判定、Review 存储 |
| 精确纠正证据 | `C/reply_link_*`、`inbound_semantic_authority.py`、`explicit_correction_rule.py`、`promotion_infrastructure.py` | 新证据库、重复执行分类、关键词替代精确关联 |
| 展示 | `I/iris_memory/web` | 从日志重造历史、浏览触发写入 |

## 执行顺序与完成标准

### 1. 身份与 SELF：先让记忆真的属于“小天文”

- [ ] 验收 `identity.py`：同一平台 UID 换昵称仍是同一实体；重名不同 UID 不合并；无依据代词保持未解析。缺什么修什么。
- [ ] 验收 `iris_adapter.py` → `perspective.py` 的实际检索注入：自己的经历按主体视角表达，别人说过的话保留来源，普通知识不冒充亲历；原始 Iris 记录不变。
- [ ] 验证注册信息的真实持久化/重启路径；如果只是内存注册，先写清实际缺失，再选现有存储扩展，不另起数据库。
- 完成证据：一份固定输入输出样例 + 相关 identity/perspective/adapter 测试；不得仅测试独立投影函数。

### 2. 唯一人格和最小状态：减少重复注入

- [ ] 追踪一次最终 Provider 请求里 Persona、Iris 用户画像、关系和情绪的来源；输出“来源 → 注入位置 → 消费者”清单，不记录私密原文。
- [ ] 删除已证明重复的提示词拼接或纯转发接口。人格仍由 AstrBot Persona 定义；画像、经历与人格不能混成同一种事实。
- [ ] 关系/情绪先核对 Iris 现有实现与现用情绪插件：列出同义字段、实际写入者和配置；仅保留一个明确 owner 的方案需先冻结，之后才迁移代码。
- 完成证据：普通请求每种信息只注入一次；未知用户不被当成已经熟悉；数值状态不会直接变成“好感度 86”台词。

### 3. 行为：让现有触发链可解释

- [ ] 追踪私聊、@、精确回复、普通群聊四种实际路径，核实 Trigger/Participation/Intent 哪些只是 shadow、哪些实际控制回复。
- [ ] 找出重复的冷却、接话、沉默判断，删除没有消费者的重复计算；多个插件实际拥有同一决策时先明确唯一 owner，再做切换。
- [ ] 保留 SILENCE/WAIT，避免把理解消息等同于必须回复。普通触发不增加模型调用。
- 完成证据：四种输入各一条实际 hook 回归，记录为何回复/沉默；不改变工具、发送和图片能力。

### 4. 复盘：先让人能看懂现有结果

- [ ] 验收 Dashboard 的真实 Review 内容：Finding、关联 Episode/Outcome、证据、未生成证据的原因；已有展示直接使用。
- [ ] 检查 `review_service.py` → completion coordinator → archive → promoter 的职责，删除确定无人调用的参数和重复适配层；历史读取/重放所需校验保留。
- [ ] 不增加第二条 promotion rule；确认当前纠正证据只表示“用户明确纠正了所回复的输出”，不推导模型客观错误、偏好或奖励。
- 完成证据：可读的一条复盘样例；无数据与不可用分开；查看无写入；重复完成不重复产生证据。

### 5. 最小行为适应：让备忘录闭环产生可见价值

- [ ] 先盘点现有 Evidence 的数量、scope、内容和是否足以支持任何倾向，仅使用授权可读的样例；没有证据就明确缺口。
- [ ] 冻结一个最小试验的具体决策：聚合单位、最少独立证据、作用范围、过期、冲突处理、人工批准和撤销入口。不要让模型自己发明阈值。
- [ ] 决策冻结后，优先用现有存储和配置实现“一条候选倾向 → 人工批准 → 有范围与有效期的行为参数”；每个候选保留证据来源。
- [ ] 用对照样例验证批准前后行为，以及撤销/过期恢复。用户纠正不自动等于“以后必须查工具/保持沉默”。
- 此项尚未授权实现学习或改变生产行为；先交付可审阅的小合同。无需先建设通用 Consolidation、规则 VM、图结构演化引擎。

## 本轮精简记录与后续删除清单

- [x] 删除 Review 中无人调用的 `_default_scope` 与从未使用的 `scope_factory` 参数，移除对应类型依赖。
- [x] 修正文档中“所有 production promotion 仍关闭”的过时注释：Review 只产出 Run，生产完成路径另行决定 promotion。
- [ ] 旧 `promote_finding_to_evidence()` 是 fail-closed 兼容入口，仅有测试/导出引用：后续可废弃，但先处理公开导出与兼容测试，不将其接回生产。
- [ ] 清理只服务于已取消方案的代码：必须搜索静态调用、配置/动态导入、公开导出和重放格式；测试独占引用不是单独删除依据。
- [ ] 对重复序列化/哈希代码先比较固定历史样例；字节协议不同不能直接合并。统一内部实现不得改变已持久化身份。

旧大计划保存在 [历史 TODO](docs/archive/Todo-20260831.md)。其中阶段编号与状态仅用于追溯，执行入口以本文件为准。

## 当前工作区与完成边界

已有 P2x.3 连续对话与 ContextAware 未提交候选是独立工作，保留其改动，不作为本次认知层精简主线。前一轮 ContextBridge 小清理不算认知层重构完成。

本 TODO 不宣称整个库已清理完。已接入的持久化事实、Episode/Review、精确回复和证据链保留；删除目标是重复职责和无用途设计。每批完成上面的一个可见功能后，再决定下一批代码是否仍有必要。

## 详细任务卡：直接交给执行模型

上面的五项目标是方向，下面的任务卡是实际执行单位。任务编号只用于勾选，不是新架构阶段；不要为每张卡建立新模块或新文档目录。

状态约定：未勾选表示待验证/待完成，不代表功能不存在。只有代码、测试和调用链证据齐全才勾选。涉及线上效果时另写 `live=未验证/通过`。

推荐下一轮执行 **T00**，然后 **T01 → T02**。用户需要立即看 Review 时可以先做 **T08**。T03 与 T08 不依赖行为适应，可独立完成。

### T00 — 给当前认知层做一次有边界的去留清单

- [ ] 状态：待执行。对应备忘录 §8、§15、§36。
- 读取：`I/main.py` 的认知组件构造/启动/停止，`C/__init__.py` 的导出，`C/iris_adapter.py` 的运行时入口，以及本 TODO 涉及的配置项。不要遍历与任务无关的媒体和工具代码。
- 操作：逐项记录“模块/符号、实际调用者、实际写入的数据、读取者、开关、保留/合并/删除候选、理由”。把简表写在本卡下面，避免再生成一份大架构报告。
- 必须区分：生产控制逻辑、旁路观察、历史重放、兼容入口、测试辅助。记录类名不能代替查到调用者。
- 删除条件：用途被现有代码覆盖或没有支持的消费者；同时检查 `__init__` 导出、配置引用、反射调用、插件 Hook 和历史格式。只有代码搜索无命中尚不够证明公开 API 可移除。
- 合并条件：输入、输出、副作用、异常、历史编码都一致。名称相似但保护不同存储边界的校验不算重复。
- 不需要建抽象层来承载这份清单；一条删除候选确认后直接删代码、更新调用及相关测试。
- 完成条件：给出至少一个经过证实的删除/合并批次，或明确本批没有可安全删除项；不以删除行数作为验收指标。
- 当前已确认：旧 `_default_scope` 和 `scope_factory` 已删除；旧 promoter 仍是兼容入口，不能算清理完毕。

### T01 — 验证身份解析，不让昵称决定一个人是谁

- [x] 状态：完成（本地合同与 Iris 事件入口）；实际运行/重启持久化留给 T02。对应备忘录 §3–§5、§34。
- 读取：`C/identity.py` 的 `EntityRegistry` / `IdentityResolver`；`C/contracts.py` 对应实体合同；`tests/cognitive/test_identity_and_perspective.py`；实际事件到 resolver 的调用。
- 步骤：先重用现有测试样例；追踪平台、UID、昵称怎样进入 resolver；复现下表；仅补失败场景的最小修复。

| 输入 | 必须观察到的结果 |
|---|---|
| 同一平台/UID，昵称 A 改成 B | canonical entity 不变 |
| 同昵称，两个 UID | 不按昵称自动合并 |
| 两个平台碰巧有同一数字 UID | 没有明确关联时不跨平台合并 |
| 别名已明确登记 | 可解析，保留登记来源 |
| 别名同时指向两人 | 未解析/歧义，不任选一个 |
| 多人对话里的“他”没有目标 | 未解析，不使用最近发言者猜测 |
| bot 平台身份 | 绑定已有 SELF，不生成第二个人格 |

- 完成条件：从事件入口验证到解析结果，原调用方式仍能工作。通过便停止，不新增 LLM 共指系统。
- 测试组：G1。修复若涉及持久化，继续 T02 的重启验收。

执行记录（2026-09-07）：

```text
具体缺口：注册两个不同实体时，若平台名仅大小写/空白不同但 UID 相同，旧代码接受冲突数据，之后按注册顺序解析为第一个实体。
实际改动：identity.py 在 EntityRegistry 注册边界规范化 platform/UID，并拒绝同一规范化 platform+UID 属于两个实体的冲突；现有 UID 优先解析接口不变。
调用链：IrisPreAdapter.preprocess_event() → IdentityResolver.resolve_actor() → EntityRegistry.resolve_mention() → resolve_platform_id()。同昵称的 actor 与 @ 用户通过各自 UID 保持不同实体。
验收：同 UID 改昵称稳定；同昵称不同 UID 不合并；qq:10001 与 onebot:10001 不合并；确认别名可解析；两个确认别名冲突时未解析；“他”无依据时未解析；bot UID 仍绑定既有 SELF。
验证：G1 聚焦测试 17 passed；compileall、ruff 与 git diff --check 通过。
未验证：注册表仍为进程内状态，重启与持久化不属于本卡，交由 T02。
下一张卡：T02。
```

### T02 — 验证 SELF 视角、来源和身份重启

- [ ] 状态：部分完成；视角投影与来源标签已通过本地调用链验证，身份持久化待明确 owner。对应备忘录 §6–§7、§27、§29、§35。
- 读取：`C/perspective.py`、`C/iris_adapter.py`；追踪实际 Iris 检索结果怎样形成最终上下文。优先测试现有 `PerspectiveResolver` 和 adapter，避免创建另一份记忆模型。
- 样例一：actor=SELF 的一段历史经历，运行时表达为“我的经历”或面对模型的“你的经历”，不能把 SELF 描述成陌生第三者。
- 样例二：另一用户说“我去观测了”，保留说话人/来源，不能改成小天文亲自观测。
- 样例三：群内共同知识与普通天文事实，保留相应来源类别，不因为出现“小天文”三个字而转成自传。
- 样例四：旧记忆缺少可靠主体，保留不确定性；不以大范围字符串替换修改姓名和代词。
- 重启步骤：查明实体/别名现在从哪里加载；比较同一已确认实体重启前后 ID、别名来源和 SELF 绑定。若缺少持久化能力，记录缺失字段及现有可复用存储，先确定保存方式；不靠对话日志重建权威身份。
- 完成条件：实际注入路径的输出与原始记录前后对比通过；测试验证原始记录未变；重启能力用证据标记通过或明确待决策。
- 测试组：G1；有存储修改时增加实际重开存储测试。

执行记录（2026-09-07）：

```text
实际调用链：message_hook 为新 L1 写入 cognitive_runtime 元数据 → l1_buffer 聚合一致 subject 到 L2 → llm_request_hook 检索 L2 后调用 IrisPostAdapter.format_l2_context() 注入最终请求。
实际改动：L2 上下文现在按 RuntimeMemoryView.perspective 显式显示 [你的经历]、[他人经历]、[共同经历]、[来源未确认] 等结构化来源标签；不替换原始句子，也不写回 L1/L2/L3。
验收：SELF 记忆显示为你的经历；他人主体不变成 SELF；group 主体显示共同经历；缺少可靠主体的旧记录显示来源未确认；MemoryEntry 原始 content 未变。
重启证据：EntityRegistry/CognitiveRuntime 每个进程重新创建；平台 UID 可确定性重建同一 person:<platform>:<uid>，默认 SELF 可重建；运行时添加的 confirmed alias 及其 evidence/source/revocation 状态会丢失。
现有存储：Config.data_dir 与 hidden_config.json 已存在，但 hidden_config 是宽松的用户配置字典，不适合作为可审计 IdentityClaim 权威历史；现有 cognitive JSONL 分别属于 P2 事实/语义 authority，不能混入实体身份。
待决策：Identity 是否拥有 data_dir/cognitive 下独立的 append-only identity claim 日志，还是只保留显式配置的静态 SELF/别名。需同时冻结记录格式、来源/evidence、撤销、冲突和重放/损坏的 fail-closed 行为，才能实现持久化。
验证：身份/adapter/P0.7 聚焦测试 29 passed；compileall 与 git diff --check 通过。iris_adapter.py 存在 12 项既有 Ruff debt（导入排序、前置类型注解、宽泛观测异常等），本次未扩大到这些无关重构；本次新增代码的 F 规则检查通过。
下一张卡：T03；T02 持久化部分等待上述决策。
```

### T03 — 查清唯一人格和重复上下文

- [ ] 状态：部分完成；最终请求来源和无正文日志已验证，`persona_evolution` 的核心 Persona 自动发布处于待决策边界。对应备忘录 §2、§8–§10、§30。
- 读取：`I/iris_memory/core/persona.py`、实际请求构造与人格注入调用；按调用再读 `I/iris_memory/persona_evolution/component.py`、`service.py`、`publisher.py`。
- 注意：仓库已有 persona_evolution 代码，但目录存在不能证明它启用、也不能证明它修改核心 Persona。必须查实际开关、发布目标和调用者。
- 步骤：用脱敏测试输入抓取最终请求的段落来源/类型/次数；列出 Persona、自己的经历、用户画像、关系、情绪各自的写入点；查出重复后在最早重复产生的位置消除。
- 不记录线上原始提示词、私聊正文或模型响应到调试文件；测试用固定虚构文本即可。
- 反例：同一句人格定义不应从 Host 和记忆层各注入一次；用户画像不能被当成 bot 人格；没有关系经历不能显示“我们已经很熟”。
- 遇到自动发布修改核心 Persona 的实际路径：报告与备忘录的冲突，给出具体可停用/改目标方案，等待选择后修改，不能无声改变用户已有配置。
- 完成条件：来源表和最终请求测试能证明每类信息由明确入口注入；测试覆盖空记忆和不可用记忆时普通聊天仍工作。
- 测试：关联请求 Hook、`tests/core/test_persona.py`；改到 persona_evolution 再运行该目录相关测试，避免顺手修全部历史 lint。

执行记录（2026-09-07）：

| 信息 | 写入/解析 owner | 最终 Provider 请求位置 | 直接消费者 |
|---|---|---|---|
| 稳定 Persona | AstrBot `req.system_prompt`；`core/persona.py` 只解析当前 `persona_id` 作隔离键 | Iris 不修改 `system_prompt` | AstrBot Provider 与 learning 的兼容性复审 |
| 本轮对话 / 自己经历 | `message_hook.py` 写 L1；Cognitive pre/post adapter 只为 Iris 记忆增加主体和视角元数据 | `<iris:l1_context>`；检索记忆为 `<iris:l2_memory>`，其中 SELF 显示为“你的经历” | Provider；原始 L1/L2 不改写 |
| 用户/群画像 | `ProfileStorage`、名称更新与 profile 分析 | `<iris:profile>`，仅在画像有实际字段时出现 | Provider；画像字段不是 bot 人格 |
| 关系 / 情绪 | 当前为 UserProfile 的 `bot_relationship`、`favorability`、`emotional_baseline`；由 profile 路径写入 | 同一个 `<iris:profile>` 段；仅输出解释性字段 | Provider；没有独立关系/情绪 prompt 入口 |
| 图谱事实 | L3 图谱检索 | `<iris:l3_kg>` | Provider |
| 群聊表达学习 | Learning 的已批准暗语、表达模式、few-shot | `<iris:learning>` | Provider；不是 Persona 定义 |

最终请求证据：`preprocess_llm_request()` 并发收集 L1、profile、L2、learning，并在 L2 后收集 L3；`_inject_to_extra_user_content_parts()` 将非空来源各包成一次同名 `<iris:...>` 标签并追加一个临时 `TextPart`。它不写 `req.system_prompt`、`req.contexts` 或 `req.prompt`。因此未发现“同一 Persona 从 Host 和 Iris 再注入一次”的已证实重复；L1/L2/L3/profile/learning 的存储语义与检索条件不同，不能仅因都提供上下文而合并或删除。

已删除的纯转发：运行日志以前会无条件复制 `user_message`、所有合并注入正文、L2 查询/改写词和 L3 关键词；可选的最终上下文 debug 输出也会复制 Persona、上下文和临时注入正文。现在两者仅保留每段是否注入、字符数、预算、计数、稳定状态和耗时；不再保存这些原文。固定虚构文本测试确认脱敏后仍可观察注入指标。

发现的冻结冲突 / 待决策：`persona_evolution.enable` 默认是 `false`，故默认不注册组件；但一旦显式开启，`handle_user_message()` 会把每条入站消息交给该组件采样，阈值扫描可运行 active Job。Job 的默认 `approval_mode` 是 `auto`，`PersonaEvolutionService` 在该模式调用 `PersonaPublisher.publish()`，后者调用 AstrBot `PersonaManager.update_persona(persona_id, system_prompt=...)`。这与备忘录“核心 Persona 不自动修改”的边界冲突。当前工作区没有可信的运行时配置快照，不能宣称线上已启用或未启用。

需要用户冻结的选择后才能继续该子项：

1. 完全停用并移除 `persona_evolution` 及其历史数据入口；
2. 保留历史候选/人工编辑界面，但强制 `manual`，删除自动触发发布；
3. 暂时保留现状，并明确接受它可以自动覆盖 AstrBot 核心 Persona。

在选择前不改动该组件、已有 Persona 或用户配置。验证：请求 Hook/Persona 聚焦测试 48 passed；persona_evolution service/publisher 聚焦测试 28 passed；compileall、`git diff --check` 通过。完整 Ruff 对这两个历史文件报 46 项既有风格问题，本次未顺手清理；新修改以 F 规则单独检查。

决策（2026-09-07）：维护者选择方案 3——保留 `persona_evolution` 当前实现、现有数据入口和自动发布语义。本 TODO 后续卡不把它作为清理目标；任何未来要改变其开关、发布目标或自动发布行为的工作，必须另起明确任务并重新验收。

### T04 — 明确关系/情绪的最小 owner 和字段

- [x] 状态：完成现状盘点与最小收敛提案；不迁移、不删除、不冻结字段语义。T05 只能在维护者选择本卡的待决策项后开始。对应备忘录 §9–§15。
- 搜索实际 `affinity`、`affection`、`familiarity`、情绪 baseline/current 字段与写入点；从插件配置核实启用情况，不能假设某个旧插件正在生产运行。
- 填表：字段、含义、范围、默认值、证据来源、更新者、读取者、持久化位置、是否只是 prior。
- 需要具体决定：长期关系由哪个现有组件负责；首版保留哪些维度；缺乏证据的默认值怎样表示；与现有情绪插件怎样交接。
- 建议提交的最小方案：优先复用已有有效字段和存储，区分“未知/先验/有证据关系”；维度越少越好。建议不等于已冻结。
- 完成条件：维护者能直接选择具体字段/owner；没有第二套冲突状态被新建。未决定的字段不得由模型拍板。

执行记录（2026-09-07）：

实际运行时没有可审计的插件启用配置快照，因此下面的“默认”来自插件 schema/代码默认值，不能被表述为线上已经启用。仓库含有 `astrbot_plugin_affection` 和 group-chat mood 工具目录，只能证明代码存在，不能证明生产实例加载它们。`xiaotianwen_orchestrator/p2/affection.py` 仅为有界、内存中的观测账本和 provider 选择合同，未由运行时主入口持久化或注入；它不是关系/情绪 owner。

| 现有字段/状态 | 实际含义、范围、默认 | 证据来源与更新者 | 读取者 | 持久化位置 | 是否只是 prior / 当前结论 |
|---|---|---|---|---|---|
| `UserProfile.bot_relationship` | 用户对 bot 的称呼或关系设定；`str`，默认空；LONG tier | `ProfileAnalyzer` 从对话作长期 LLM 分析，提示词要求“明确线索”；`UserProfileManager.update_long_term_from_analysis()` 写入；Profile Web 更新可直接写 | `llm_request_hook._format_profiles_for_injection()` 作为“称呼”；Profile Web | AstrBot KV：`user_profile:<persona>:<group>:<user>`，由 `ProfileStorage` 保存；随 persona/group 隔离配置变化可见范围 | 画像 prior，不是逐条可审计关系事实；空值表示未知 |
| `UserProfile.favorability` | Iris 的“用户对 AI 好感度”；`float`，夹紧 `[0,100]`，代码默认 `0.0`；MID tier，界面映射陌生/认识/熟悉/友好/亲密 | Profile LLM 返回 `favorability_delta`，按 `[-max_delta,+max_delta]`（默认 20）累加；仅当 `profile.favorability_enable` 为真；Profile Web 也可直接写 | 请求 Hook 会在值 `>0` 时把数值及等级注入 `<iris:profile>`；Profile Web 显示/编辑 | 同一 Iris `UserProfile` KV | 历史解释 prior，非 Evidence。`0.0` 同时被用作初始值和“陌生”端点，现有字段无法机械区分“未知”与“有证据的零值” |
| `UserProfile.emotional_baseline` | 用户的中期情感基线；`str`，默认空；分析提示建议稳定/敏感/乐观/低落/焦虑，但模型本身未用 enum 强制 | Profile LLM MID/LONG 分析写入，受 `FieldMeta` 置信度覆盖逻辑控制；Profile Web 可直接写 | 请求 Hook 作为“情感”画像文本；Profile Web | 同一 Iris `UserProfile` KV | 用户画像 prior，不是 bot 的当前情绪；空值表示未知 |
| `astrbot_plugin_affection` 的 `affection`、`current_libido_other`、`current_aggression_other` | 独立插件的 bot→user 动态数值：好感 `[0,100]` 默认 50；两个对他当前值 `[0,50]`，并有同范围 baseline | 插件的 `on_waiting_llm_request` 创建后台 LLM 分析并更新；衰减任务把 current 拉回 baseline；也有管理命令写入 | 该插件的 `on_llm_request` 把当前数值和标签作为临时请求上下文；自身状态命令 | 插件自己的 `StarTools.get_data_dir()` 下、按 bot 分目录的 `user_data.json`；与 Iris KV 无共享 | 若该插件实际启用，它是独立的动态 affect owner；不是 Iris `favorability` 的副本，禁止自动互写/迁移 |
| `astrbot_plugin_affection` 的 `current_libido_self`、`current_aggression_self` | bot 自身动态数值，各 `[0,50]`，默认等于 baseline | 同一插件后台分析和衰减任务 | 同一插件临时请求注入/状态命令 | 该插件按 bot 分目录的 `self_data.json` | 若插件启用，仅属于该插件的 bot-self affect；Iris 没有等价字段 |
| group-chat `MoodTracker` | 会话/群聊临时 mood 与强度缓存 | group-chat-plus 内部工具更新、超时清理 | group-chat-plus 自己的表达/上下文路径 | 进程内缓存（不是 Iris ProfileStorage） | 不构成跨模块长期关系 owner；启用情况未证实 |

字段元数据的边界：Iris 的 `FieldMeta` 只有 `confidence`、`last_updated`、`update_count`、最近 `source`，可说明字段曾由 `llm` 更新，却不保存具体 source event、原文、因果依据或可撤销关系证据。因此它不足以把 `favorability` 升格为“有证据关系”。Profile 默认 `enable=true`、`enable_auto_injection=true`、`favorability_enable=true`；部署可实际覆盖它们，当前工作区没有运行时配置证据。

最小收敛建议（尚未冻结，T05 前必须选择）：

1. 不创建新的 relationship/affect 数据库或第二组字段。Iris `ProfileStorage` 继续是 `bot_relationship`、`favorability`、`emotional_baseline` 的唯一现有存储 owner；外部 affection 插件若实际启用，继续独占其现有 JSON，不与 Iris 自动同步。
2. 首版把 `bot_relationship` 限定为“用户明确给出的称呼/关系描述”这一条可选画像 prior；把 `emotional_baseline` 明确为“用户特征”，不当作 bot 情绪。两者为空即未知。
3. `favorability` 在没有可追溯证据模型前只能保留为 legacy prior，不能作为关系事实、奖励、人格改写或学习信号；T05 应先决定是停止其自动 LLM 更新与数值请求注入、还是明确接受该 legacy 语义。无论选择哪一项，`0.0` 且 `field_meta.update_count==0` 在新读取者中都应按未知处理，不能当作已证实“陌生”。
4. 对外部 affection 插件必须二选一：**A** 在实际部署配置中明确保留并承认它是唯一的 bot current-affect owner；**B** 明确停用其插件/注入，保留历史 JSON 只读且不迁移。未核实加载状态前，不得让 Iris 或编排器猜测它是否活跃。

决策（2026-09-07）：`favorability = 保留 legacy prior`；`astrbot_plugin_affection = 保留为唯一 bot current-affect owner`。不在 Iris 与 affection 插件之间迁移或同步历史数据；实际部署是否加载外部插件仍须由运行时插件配置单独核实。

### T05 — 按已定方案收敛关系/情绪实现

- [x] 状态：完成选定边界的最小收敛；保留两个现有持久化 owner，移除 Iris 请求上下文对 `favorability` 的数值/当前情绪暗示。对应备忘录 §11–§15。
- 一个批次只收敛一个重复状态。先把读取者改到明确 owner，再停止重复写入，最后清理废弃适配；保留旧数据的可恢复读取方式。
- 短期情绪只修改自己的状态；发现关系信号可以交给关系 owner，不直接跨模块写入。
- 衰减使用可注入时间测试：时间前进后接近 baseline，不能因为重启意外强化；没有新证据时不把先验变成真实关系。
- 用户可见验收：熟悉程度影响表达边界，输出不主动报告数值；没有证据时不假装共同经历。
- 完成条件：一个字段只有一个写入 owner，重启前后结果可解释；历史数据无批量破坏；相关状态与请求测试通过。
- 如果 T04 尚未决策，保持本卡待执行，继续 T06/T08。

执行记录（2026-09-07）：

冻结 owner：`astrbot_plugin_affection` 是唯一 bot current-affect owner；它继续独占自己的 `user_data.json`/`self_data.json`、后台更新、衰减和临时情绪请求段。Iris 不读取、写入、迁移或同步这些 JSON。Iris `UserProfile.favorability` 保留为其既有 KV 中的 legacy interaction prior，仍可由现有 Profile 管理器/人工 Profile 编辑更新，但不是 current affect、关系事实、奖励、Persona 输入或学习信号。

实际收敛：`_format_profiles_for_injection()` 不再投影 `好感度: 65(友好)` 一类原始数值；有值时仅投影等级，并明确标记为“历史互动倾向（legacy prior，非当前 bot 情绪）”。`emotional_baseline` 同时明确为用户画像的情绪倾向，而不是 bot current affect。零值仍不投影，因此不会因默认 `0.0` 把未知用户说成“陌生”。没有改变字段名、范围、KV key、模型更新、Profile Web 编辑、affection JSON、衰减、后台任务或插件加载配置。

验收：新增请求投影测试覆盖有历史 prior 时不出现原始分数、用户 baseline 不被投射为 bot current affect、未设置的默认 `0.0` 不产生关系事实；Profile 原有 favorability 更新/范围/开关测试保留。`tests/core/test_llm_request_hook.py` 与 Profile 的 user/analyzer/models 聚焦组共 109 passed；新增/修改文件的 F 规则检查通过；JSON schema 以 UTF-8 BOM 兼容读取通过；`compileall -q iris_memory` 与 `git diff --check` 通过。实际部署是否加载 affection 插件仍为 `live=未验证`，本卡不修改部署。

### T06 — 找出真正决定回复的入口

- [x] 状态：完成源码级调用链核实；线上插件集合、配置覆写和各 Provider 的工具循环次数仍需由运行日志单独核实。对应备忘录 §18–§23。
- 读取：`C/trigger.py`、`C/situation.py`、`C/behavior.py`、`C/iris_adapter.py`、`I/main.py`；以及实际 AstrBot H0 的 `WakingCheckStage → ProcessStage → InternalAgentSubStage`。Hook 顺序以 H0 阶段和 `call_event_hook()` 的顺序为准，不以装饰器 `priority` 的正负推断。插件之间的相对顺序仍由当次激活 handler 列表决定，不能由本地静态源码宣称为线上事实。
- 对私聊、@、精确回复、普通群聊分别画一条简短调用链：收到事件 → 触发判断 → 参与决策 → Host 生成 → 发送。注明 shadow/guard/active，以配置和调用为准。
- 同时列出冷却、连发限制、话题判断等重复检查，注明每次是否实际执行及影响结果。
- Situation 只保留决策真的使用的字段；无人消费的昂贵状态构造可以是删除候选，不能删除历史快照合同中仍需解码的字段。
- 完成条件：能回答“这次为什么回/没回、谁决定、调用几次模型”；没有新增模型调用或改变线上开关。
- 测试组：G2。检查真实 Hook 顺序，不能凭 priority 正负猜测执行先后。

执行记录（2026-09-07）：

先固定共同的真实框架顺序。H0 的 `WakingCheckStage` 先处理 wake prefix、@ 本 bot、`Reply.sender_id == self_id`、私聊规则和实际启用插件的过滤器；随后 `ProcessStage` 顺序执行已激活的 Adapter handler，**只有** `event.is_at_or_wake_command` 为真且没有发送/停止时才进入 Host `AgentRequestSubStage`。Host 构造好 `ProviderRequest` 后，Iris 的 `on_llm_request()` 内部顺序固定为：P0.5 cognitive → 旧 `iris_reply` 决策 → Iris 记忆预处理/注入 → Host 请求。P0 的 trace/事实观察发生在这个链内；`on_llm_response`、`after_message_sent`、`after_message_send_result` 只观察/归档结果，当前不重新决定本次 Host 是否发送。

| 入站类别 | 收到事件 → 触发判断 | 参与决策 / 实际 owner | Host 生成 → 发送 | 本次框架级模型调用 |
|---|---|---|---|---|
| 私聊 | H0 按 `friend_message_needs_wake_prefix`（或 webchat 例外）决定 wake；Iris `on_message` 是群聊 handler，不走旧主动触发 | `on_llm_request` 总会运行 P0 proposal。`RuntimeMode` 源码默认 `SHADOW`，因此 proposal 不改变 Host；若实际配置为 `GUARD`，仅 Guard exit 会 `stop_event()`。旧 `_handle_reply_decision()` 因没有 group/_triggering 不参与 | 未被 Guard/其他 Host gate 停止时进入 AstrBot Host Agent，再由 RespondStage 发送 | P0：0；Host：1 次请求起点。Agent 工具循环可产生额外 Provider 调用，不能把它静态写死为 1 |
| @ 本 bot（群） | H0 的 `At(self)` 置 wake；Iris 群聊 handler 只标记 `iris_mode=passive`，不建立 `_triggering` | P0 同上；旧主动“是否插话”决策不参与。若 passive 条件、provider 与滑窗都存在，Host 回复后 `_passive_watch_eval()` 还会调用一次只用于写关注锚点的旧 DecisionCore，不决定已发送的回复 | Host 正常生成/发送；post-response watch 不会撤回或改变这次 Host 文本 | P0：0；Host：1 个请求起点；满足 passive watch 条件时另有 1 次后置 DecisionCore 调用 |
| 精确回复本 bot | H0 仅以 `Reply.sender_id == self_id` 唤醒；P2r.0 精确回复事实用于历史身份/归档，不是本次 Host 决策 owner | 群聊时与 @ 的 `passive` 路径相同；私聊时与私聊路径相同。P0 的“reply to SELF”只产生 Shadow/Guard proposal，不替代 H0 唤醒 | 未被 Guard/其他 Host gate 停止时 Host 生成后发送 | P0：0；Host：1 个请求起点；仅群聊且 passive watch 条件满足时再有 1 次后置 DecisionCore |
| 普通群消息 | H0 可以因 Iris 的群聊 handler filter 激活该 handler，但该事实本身**不会**置 `is_at_or_wake_command`。只有旧 `on_message()` 在 `reply_config.enabled`、Gatekeeper、质量、忙碌/聚合、SignalGate 和 `can_detect()` 均通过后，才把事件标成 wake 并写 `_triggering` | 真正决定“本次是否让 Host 回复”的 owner 是旧 `_handle_reply_decision()`：它调用 `DecisionCore.decide()`；错误、parse fail、passive 冲突、cooldown、drift 或 `should_speak=false` 都 `stop_event()`。只有 `should_speak=true` 才允许 Host 继续。P0 默认 Shadow 仅记录 proposal；Guard 是唯一可额外阻断者 | 未触发/早期 gate 拒绝：无 Host；DecisionCore 拒绝：无 Host；DecisionCore 同意：注入 speak hint 后 Host 生成/RespondStage 发送 | 早期未触发：0；进入 DecisionCore 后拒绝：1 次 direct decision；同意：1 次 direct decision + 1 个 Host 请求起点（Host 工具循环另计） |

这里的“1 个 Host 请求起点”不是模型 token 或 Agent 内部多步调用总数；Host 使用工具/多轮 runner 时可再次调用 Provider。另有配置绑定的 inbound semantic evaluator，它为语义事实捕获服务、并不拥有是否回复的决定权；没有可信线上配置/日志，本卡不把它计入任一路径的确定调用数。

**重复门控和实际影响。** 普通群的 `Gatekeeper.should_process()` 已检查私聊、mute 和 group whitelist；随后 `SignalGate.evaluate_message()` 再查 enabled/cooldown/mute，`StateManager.should_trigger_sampling()` 又重查 cooldown/mute，之后 `can_detect()` 再做最小触发间隔。进入 Host 后，P0 `ParticipationController` 再读取 legacy cooldown、skip、连续回复惩罚、topic drift；但 `SHADOW` 下它对结果没有控制力，实际 `GUARD` 才会 stop。最后旧 `DecisionCore` 以模型返回的 cooldown/drift/speak 作最终 active 决定。也就是说，前四类本地 gate 对普通群实际决定是否到达 DecisionCore；P0 participation 在默认 Shadow 是重复计算/可观测信息；DecisionCore 是当前 active 的最终 owner。@/精确回复群聊不进入插话 DecisionCore，却可能在发送后进入一次不影响本轮文本的 watch DecisionCore。跟进路径还有 `follow_up_aggregate_window` 的真实 `asyncio.sleep()`；这属于旧主动回复，而不是 P2x.1 的被动 trace。

**Situation 去留结论。** 同一 Host `on_llm_request` 当前会执行 `SituationBuilder.observe()` 三次：`_handle_cognitive_behavior()` 的显式 observe 一次、`CognitiveRuntime.run_behavior()` 一次、`CognitiveBehaviorRuntime.run()` 再一次。后两次命中事件缓存，但仍是无效重复入口，是 T07 的首个删除候选。`build_full()` 只在 P0 trigger 为 YES 时构造；其 `runtime_memory_view/committed_affect/committed_relationship/behavioral_prior/persona_read_only` 当前均为空或不影响真实 Host prompt，然而 `Situation`/trace/历史 snapshot 合同仍可能需要解码，故本卡不删除字段。先以实际调用者、历史 fixture 和 trace 读取者证明无消费者后，才可删构造或字段。

**验证与缺口。** G2/P0、旧 signals/decision/state、message hook 与 unified dispatch 聚焦组 `163 passed`；它们证明 Shadow/Guard、旧门控和 DecisionCore 的组件行为。尚没有一条以真实 H0 pipeline 注册顺序同时覆盖“私聊、@、精确回复、普通群”并断言 Host 是否进入的集成测试；T07 若移动任何 owner，必须先补这条测试，读取运行时实际 `activated_handlers` 顺序，而不是依据 priority。线上 `reply_config`、P0 mode、plugin set、provider/tool 步数为 `live=未验证`，本卡没有新增模型调用、改变开关或修改发送行为。

### T07 — 删除重复行为职责，保持成功路径

- [x] 状态：完成一项可回滚的重复观察删减；真实 H0 Hook 四类入口集成测试作为后续保护项保留，旧主动回复的 active owner 未切换。依赖 T06 的调用链证据。
- 先处理无人使用的包装/重复计算；实际控制回复的重复 owner 切换需要写清保留哪一方及原行为差异。
- 每批覆盖：明确 @、私聊、普通群聊无触发、冷却命中、工具异常；同一个事件不能被重复生成或重复发送。
- 对 WAIT/SILENCE 验证不会启动无必要的主模型调用。对 REPLY 验证原 Host 工具、图片和发送路径仍可用。
- 不把当前 P2x.3 未提交候选自动当成可替换全部行为的生产能力。
- 完成条件：实际减少一项重复职责；同输入预期结果保持或差异得到明确批准；相关行为/Hook 回归通过。

执行记录（2026-09-07）：

本批只处理 T06 证实的 `SituationBuilder.observe()` 重复入口。之前同一 Host `on_llm_request` 会由 `main._handle_cognitive_behavior()`、`CognitiveRuntime.run_behavior()`、`CognitiveBehaviorRuntime.run()` 依次观察同一 experience 三次；现在唯一调用点是 `CognitiveBehaviorRuntime.run()`，它把同一份 `SituationLite` 放进返回的 `BehaviorTrace`，adapter 只读取该结果，不再二次观察，消息 Hook 也不提前观察。事件缓存仍由 `SituationBuilder` 自己维护，未改变 scope、速度、self-action、topic 或 episode hint 的值。

实际改动：

| 文件 | 改动 | 保留的边界 |
|---|---|---|
| `I/iris_memory/cognitive/behavior.py` | 四个退出分支和成功分支都在同一处携带本次 `SituationLite` | 不改 `TriggerController`、`ParticipationController`、`IntentPlanner`、`GroundingGuard` 规则 |
| `I/iris_memory/cognitive/iris_adapter.py` | 删除 `run_behavior()` 的预观察，读取 `BehaviorTrace.situation_lite` | `CognitiveRuntime` 仍只产出 proposal/trace；`RuntimeMode.SHADOW` 默认和 Guard 边界不变 |
| `I/main.py` | 删除 `_handle_cognitive_behavior()` 的额外预观察 | 不改 `on_message()`、`_handle_reply_decision()`、Host 请求/发送和旧状态写入 |
| `I/tests/cognitive/test_behavior_pipeline.py` | 永久断言一次 `run_behavior()` 只调用一次 observe 且返回同一 lite | 不添加模型、网络或生产开关 |

行为 owner 决策：旧 `DecisionCore` 仍是普通群主动回复的唯一 active 决定点；它的 direct decision、cooldown、drift、`should_speak` 和 `stop_event()` 语义未移除。P0 `ParticipationController` 仍是 Shadow/Guard proposal 层，不能把本次重复计算删减误报成行为接管。私聊、@、精确回复仍由 H0 wake + Host 主链处理；普通群无触发仍不会进入 Host。因而本批没有第二个生成器、没有第二次发送，也没有改变旧路径的模型调用数量（只移除了不产生模型调用的 Situation 观察）。

验收：新增一次观察计数测试；行为/Shadow/Guard、旧 signals/decision/state、消息 Hook 与统一派发聚焦组 `164 passed`；完整 `tests/cognitive` `420 passed`；`tests/web` `85 passed`；`compileall -q` 与 `git diff --check` 通过。`ruff` 对涉及文件仍报告工作区原有的导入排序、旧类型注解、宽泛异常等问题（本批新增功能行未引入新的运行时 lint 规则）；这些历史债务不在本卡顺手重构。

后续保护项：若要继续删除任何门控或切换 owner，先用真实 H0 pipeline 覆盖私聊、@、精确回复、普通群无触发、冷却命中、工具异常，并以 activated handler 实际序列而不是 priority 号验收；这不是本批的线上行为切换。

### T08 — 让现有 Review 可见可解释

- [x] 已完成。对应备忘录 §16–§17、§26、§32。
- 后端入口：`I/iris_memory/web/services/observatory_service.py` 的 `persisted_review()`、`episode_detail()`、`preview_review()`；路由 `I/iris_memory/web/routes/observatory.py`。
- 前端入口：`I/iris_memory/web/frontend/src/api/observatory.ts`，从引用定位实际页面，不预设组件文件名。
- 先开一条测试持久化 Run：显示时间、Episode、状态、Finding 文本、引用、没有证据的原因；已有显示直接验收。
- 对零结果区分：没有 Run、Run 无 Finding、Finding 不可 promotion、存储不可用。不要把所有情况写成“0”或“未启用”。
- Preview 必须明确标识预览，继续使用请求内存存储；浏览真实 Review 不触发 finalization、重新分类或生产写入。
- 完成条件：人能从一条记录理解“发生什么、系统认为怎样、依据在哪”；阅读前后存储记录数/内容不变。
- 测试组：G4。真实 Dashboard 验收单独记录，不用虚构生产数据补足样例。

执行记录（2026-09-07）：

```text
实际核对：Observatory 路由通过 get_cognitive_runtime() 取得当前 runtime 的 EpisodeStore、observatory_review_store 与 P2r0 archive；详情、列表和摘要没有创建第二个 production ReviewStore，也没有把 Preview 的请求内存 InMemoryReviewStore 当作真实历史来源。preview_review() 仍逐请求创建 InMemoryReviewStore，浏览详情只读，不触发 finalization、重新分类或任何生产写入。
实际改动：observatory_service.py 为持久化 Review 增加 detached 可解释投影：逐条给出 Run 时间、Episode、状态、Finding 文本、Finding 创建时间、结构化 evidence refs、Finding 数量/Evidence 数量，并给出 NO_RUN、NO_FINDINGS、FINDINGS_NOT_PROMOTABLE、PROMOTION_DISABLED、REVIEW_STORE_UNAVAILABLE 等明确原因；CognitiveObservatoryView.vue 展开显示这些字段，并修正 ReviewStore 不可用时的提示，避免把 Unavailable 当成 0。新增 Web 回归测试覆盖一条持久化 Finding、零 Evidence 原因、无 Run/无 Finding 区分、runtime-owned ReviewStore 复用及前后存储内容不变。
验收：G4 Web 测试 87 项通过；前端 Vitest 9 项通过；vue-tsc --noEmit 通过。未执行真实 Dashboard 人工验收，也未生成或写入生产样例数据；构建产物未在本卡重新生成，后续部署需按现有前端发布流程构建。
补充检查：全局 Ruff 对两个已修改 Python 文件报告 10 项存量导入排序、旧测试未使用变量和宽泛异常问题；这些问题在本卡之前已存在，未为 T08 扩大范围修复。
```

### T09 — 清理复盘遗留设计

- [x] 依赖：T00，涉及 UI 时参考 T08。对应备忘录 §16、§24–§27。
- 从 `review_service.py` 开始，一次清理一类：无人使用参数、重复包装、过时注释、旧的公开兼容入口。
- 旧 `promote_finding_to_evidence()`：先核对所有导入/导出与旧测试预期，决定删除或保留最小 fail-closed 兼容形式；不能同时保留两个实际生产 promoter。
- `promotion_infrastructure.py`、`reply_link_authority.py`、`reply_link_archive.py` 的存储校验按所保护的边界判断价值；若协议不同，不能为减少行数强行共用编码。
- 相同快照重复构造/哈希若要消除，必须证明 Run 使用的事实与归档字节仍一致；用原有历史样例验证，不生成新的“标准答案”替代旧答案。
- 完成条件：调用者、异常行为、历史读取与重试仍正确；检查旧记录重放、错 lineage 拒绝、同输入幂等。
- 测试组：G3；修改编码/存储时加 `test_p2a2_promotion_infrastructure.py` 与 `test_p2r0_reply_link_authority.py`。

执行记录（2026-09-07，第一批公开入口清理）：

```text
生产调用证据：promote_finding_to_evidence() 在生产源码没有调用者；真正的生产 promotion owner 是 explicit_correction_rule.py::ExplicitCorrectionProductionPromoterV1，由 main.py 的 P2 authority 组合层创建并交给 completion coordinator。
实际清理：移除 iris_memory.cognitive 包级 promote_finding_to_evidence 导出，避免旧 Review helper 被误认为当前生产 promoter；review_service.py 的模块级函数保留为最小 fail-closed 兼容入口，仍只返回 None，原有直接导入测试保留。
兼容与边界：没有删除历史 ReviewRun/ReviewEvidence 编码，没有改变 P2a/P2r0 存储校验，没有把旧 helper 接回生产，也没有新增 promoter、store 或 authority。
验证：新增包级公开入口回归；Review/promotion/P2r0/Episode 聚焦组和回复偏好/认知聚焦组继续通过。T09 其余快照字节、历史重放和全部删除候选仍需单独验收，因此本卡暂不整体勾选。
未验证：真实 completion coordinator 的线上调用、真实平台/Provider、生产配置和线上历史数据。
```

执行记录（2026-09-07，第二批快照重放与完成幂等）：

```text
状态：完成。保留各协议的独立编码与存储校验；没有找到可安全删除的重复快照、历史重放协议或第二个生产 promoter。
实际修复：ProductionReviewCompletionCoordinator.completion_satisfied() 现在接受与 complete_episode() 相同的可选 fact_envelopes，并按同一完整 P1d 快照计算 Run ID/hash；带事实的已完成 Run 可以被准确识别，省略或更换事实不会误认成已完成，也不会产生新持久化记录。EpisodeLifecycleOwner 的现有两参数回调和空事实生产路径保持兼容。
历史与 lineage：复用了既有 P1/P2a/P2r0 fixture，确认旧记录可重放；错误 Episode/Run、事实捕获绑定、Finding/Host lineage、外部伪造 P2 authority 和非规范历史均 fail-closed；已存在的 archive、Run、Evidence 重复提交继续只保留一份权威结果。
公开入口：旧 review_service.promote_finding_to_evidence() 仍只是模块级 fail-closed 兼容入口，包级导出已移除；实际生产 promoter 仍只有 ExplicitCorrectionProductionPromoterV1。
验证：新增带事实快照的 completion_satisfied 回归；P2r0 archive wiring 15 passed；T09 聚焦组（Review、P2a promotion infrastructure、P2r0 authority/archive、P2r1 explicit correction、Episode shadow）159 passed；changed production/test files 的 Ruff F 检查和 compileall 通过。
未验证：真实平台入站/Host 回执、线上 completion coordinator 的真实调用、真实生产历史数据与 Provider 输出；这些不由本卡的本地历史 fixture 验收替代。
边界：未修改生产配置、生产数据、Persona/Affect/Relationship 或其他后续学习边界；未提交、推送或部署。
```

### T10 — 设计一个基于明确要求的回复风格适应试验

- [x] 设计已落库；原始设计记录曾明确“本卡只形成可执行设计与验收样例”，本轮已收到连续 T10–T15 实施授权，按冻结边界完成最小闭环。依赖 T08 的 Review 可读性；T09 未完成不阻塞本卡。
- 对应备忘录 §24–§26、§30–§32。原设计阶段的四项待确认保留为历史含义；本轮施工选项已明确为：**先结论按需展开、限定单个私聊、维护者人工确认、批准后 7 天且不自动续期**。

#### T10.1 事实门槛

首个候选只讨论一个表达参数：在一个已确认用户的一个私聊中，默认先给直接结论，详细说明按需展开。当前事实能支持的结论如下：

| 输入 | 能证明的事实 | 能否形成长期调整候选 |
|---|---|---|
| “你这里说错了” | 用户纠正了某条输出 | 否；只保留纠正历史，不推导回答长度、工具使用或偏好 |
| “不是吧”“你确定？” | 语义不充分，可能是质疑、确认或玩笑 | 否 |
| “这次简短点” | 本次请求需要简短 | 否；只作为本轮明确指令 |
| “以后在这个私聊里先给结论，细节等我问” | 第一人称、持续性、范围明确的表达要求 | 可以提出候选；仍需可信身份、同一会话来源和人工确认 |
| “大家都喜欢短回答” | 对他人的概括 | 否 |
| 第三方转述“他希望你简短一点” | 非目标用户的转述 | 否 |

精确纠正 ReviewEvidence 仍只能证明“用户纠正了该输出”；它不能变成“回答太长”“应少说话”“应调用工具”或任何奖励/质量/偏好判断。若没有可信的持续要求记录，本卡停在候选设计，不用纠正次数、情绪、favorability 或 Finding 文本补足证据。

#### T10.2 唯一参数与实际效果

只允许一个参数 `response_expansion`，两个取值：

- `DEFAULT`：沿用当前回复方式；
- `CONCLUSION_FIRST`：先给直接结论；补充说明按当前问题需要提供，用户要求详细时完整展开。

它是表达顺序偏好，不是字符/token 上限。不得截断回答，不得删除必要条件、错误提示、工具结果或任务步骤；不得影响是否回复、是否调用工具、发送时机、记忆检索数量、行为权限、情绪、关系或 Persona。

生效样例：用户问“今晚适合观星吗？”时先回答是否适合，再简短说明依据；用户随后说“这次请详细解释计算过程”，本轮明确要求覆盖保存的表达偏好并给出完整过程。

#### T10.3 适用范围与身份

第一轮只支持已确认身份的用户、提出要求的同一私聊。范围匹配必须使用现有可信平台/会话字段，当前源码入口为：

- 平台：`I/iris_memory/platform/factory.py::_get_platform_type()` / `event.get_platform_name()`；
- 用户：`I/iris_memory/platform/base.py::PlatformAdapter.get_user_id()`；
- 私聊会话：`I/iris_memory/platform/base.py::PlatformAdapter.get_session_id()`（群聊返回群 ID，私聊返回 `private:{user_id}`）；
- bot 账号：优先使用现有事件 `event.get_self_id()`，缺失或为空时 fail-closed；
- 私聊判定：现有适配器 `is_group_message(event)` 必须为 False。

以上字段不足以形成精确身份时沿用默认行为，不用别名、最近发言者、同名用户、文本相似度或最近一条记录猜测适用对象。绝不扩散到同一用户所在群、其他用户私聊、其他 bot 账号或其他平台。

#### T10.4 保存 owner 与注入位置

实际源码核对结果（并已作为 T11 的施工入口）：

1. 唯一持久化 owner 是 `I/iris_memory/profile/storage.py::ProfileStorage` 使用的 AstrBot `KVStorage`；它已有 `get_kv_data/put_kv_data/delete_kv_data` 和锁能力。T11 在同一 KV 存储上增加了**专用、带版本的 `response_style_preference:v1` 命名空间**，而不是把记录塞进 `UserProfile.communication_style`、情绪、关系评分、核心 Persona 或普通事实知识。原因是现有画像字段可被画像分析/手工更新，缺少来源、批准、有效期和撤销的完整约束。
2. 最终请求的唯一读取/注入 owner 是 `I/iris_memory/core/llm_request_hook.py::preprocess_llm_request()`，经 `_collect_response_preference()` 进入 `_inject_to_extra_user_content_parts()` 的临时 `TextPart`（`mark_as_temp()`）。这里只读取已批准、未过期且 scope 完全匹配的记录，并追加一个受控的 `response_style_preference` section；读取失败直接不注入，不修改 `system_prompt`、`contexts` 或原始消息。

T10 不新增数据库、通用学习 manager、EvidenceStore、审批平台或后台任务。保存记录只需：scope（platform/account/user/conversation）、参数和值、来源事件可信引用、批准时间、7 天到期时间、批准状态、撤销时间/来源。来源 Review/Evidence 仅在已有可信引用时记录，不为凑数量强行生成新的 ReviewEvidence。

#### T10.5 候选、批准与恢复规则

- 候选必须来自明确的第一人称持续要求；本卡不把纠正、Acknowledgement、情绪或 favorability 转换为候选。
- 第一轮采用人工确认入口：维护者确认“用户确实提出了该范围内要求”，不替用户猜偏好。未批准的候选永不注入、永不影响后续请求。
- 批准后有效期建议为 7 天，**不自动续期**；该数值在 T11 前由用户确认。到期、撤销、读取失败或 scope 不匹配时恢复当时的默认表达方式。
- 重复处理同一来源事件：幂等，不增加记录、不延长有效期。
- 用户本次明确要求优先于已保存偏好；“恢复默认”“不用总这么简短”等明确撤销只撤销对应 scope/参数。
- 同一 scope 出现明确相反的持续要求：旧值不得继续自动套用，暂停适应并交人工确认；不采用“最近一条胜出”或“次数更多胜出”。
- 不改写原始消息、Review、Evidence 或 Iris；不向任何 Persona/Affect/Relationship/BehavioralPrior/Learning 链路写入。

#### T10.6 T11 验收表

| 场景 | 预期 |
|---|---|
| 只有精确纠正 Evidence | 不产生风格偏好 |
| “这次简短点” | 不保存长期偏好 |
| 明确持续要求但尚未批准 | 不影响后续请求 |
| 已批准、未过期、同一用户同一私聊 | 最终请求包含一次受控的 `response_style_preference` 注入 |
| 同一来源重复处理 | 记录不增加、期限不延长 |
| 本次要求详细解释 | 当前请求优先，正常展开 |
| 换用户、换群、换账号、换平台 | 不生效 |
| 明确撤销或到期 | 恢复当前默认配置 |
| 来源缺失、身份不确定、记录损坏 | 不生效，fail-closed |
| 重启 | 批准状态、期限、撤销结果保持一致 |
| 浏览 Observatory | 不批准、不续期、不生成行为状态 |
| 检查 Persona/Affect/Relationship | 内容不因该试验改变 |

本地验收先检查最终请求的实际注入文本、注入次数和完整 scope；真实回复是否更符合要求另做人工观察，不能用“模型刚好说得短”替代作用链验收。若当前没有真实样例，只使用本地测试样例，生产状态保持未激活，不制造线上消息或补写历史。

#### T10.7 本卡交付与下一步

本卡留下：唯一参数及作用、事实能力与缺口、一个保存 owner、一个请求注入位置、来源/scope/去重/冲突/到期/撤销规则和验收表。以下四项是原设计阶段的开工门槛；本轮用户提示词已明确授权并选择它们，因此已进入 T11：

1. 采用 `CONCLUSION_FIRST`（先结论、按需展开）；
2. 只限定一个已确认用户的一处私聊；
3. 采用人工确认后才生效；
4. 批准后 7 天有效且不自动续期。

执行记录（2026-09-07）：

```text
状态：完成（设计收敛；本轮已按授权进入实现）
具体缺口：原设计阶段没有带来源/批准/有效期/撤销约束的专用回复风格偏好记录；ProfileStorage 的 UserProfile 字段仍不承担该 authority，本轮已在同一 KVStorage 上完成最小专用命名空间扩展。
实际改动：核对并记录 ProfileStorage、现有 `conversation_key_from_event()` 身份/会话字段、`preprocess_llm_request` 与 `_inject_to_extra_user_content_parts` 的真实入口；实现延后到 T11，未改变 T01–T09 的职责边界。
删除/合并：不新增通用学习框架、审批平台、EvidenceStore、后台任务或新的行为 owner。
验证：设计入口、固定值、scope 约束和最终请求位置已由本地实现与回归覆盖；真实用户样例、人工批准记录和线上请求注入仍未验证。
未验证：没有生产样例；本地批准 fixture 不代表线上状态。
下一张卡：T11；本轮已连续完成，不在卡间等待再次确认。
```

### T11 — 实现一个有范围、可撤销的适应闭环

- [x] 依赖：T10 决策确认与明确实施授权已由本轮提示词提供；不是仅因 TODO 写下就自动开工。
- 优先扩展已有配置/存储/行为读取点，一次只支持一个批准的参数。不给所有事件增加学习 Agent。
- 候选保存：来源引用、scope、创建时间、有效期、批准状态、撤销记录。具体字段以确认合同为准，不在这里新建通用 schema。
- 验收顺序：候选生成但不生效 → 人工批准 → 只在目标 scope 生效 → 重复处理不强化 → 过期/撤销恢复 → 重启保留正确状态。
- 反例：另一群/另一用户不受影响；证据撤销时不继续生效；未知或冲突输入不发布；Persona 不被修改。
- 完成条件：可演示一项实际行为改变以及恢复过程，有关联证据；本地测试和线上验证分别报告。

执行记录（2026-09-07）：

```text
owner：ProfileStorage；KV key=response_style_preference:v1；严格 schema=response-style-preference.v1。
scope：只接受现有 conversation_key_from_event() 解析出的 PRIVATE，并同时绑定 platform_id/account_id/user_id/conversation_id；缺失身份、群聊、缺失消息 ID 均 fail-closed。
来源：候选由当前真实事件的 message_id 生成 rspref:<sha256>，调用者不能提交任意 source ID 或历史正文；维护者必须人工对照入站记录后批准。
状态：PENDING → APPROVED（7 天、不可自动续期）；REVOKED、过期、冲突 SUSPENDED 或读取失败均停止注入；同源重放保持幂等。
注入：preprocess_llm_request() → _collect_response_preference() → _inject_to_extra_user_content_parts()，只写临时 TextPart，不写 system_prompt/contexts/communication_style/Persona/Affect/Relationship。
恢复：撤销/到期后使用当时默认表达；本轮“详细/完整展开”匹配只做单轮覆盖，优先于保存偏好。
验证：tests/profile/test_response_preferences.py 覆盖候选、批准、scope、来源、冲突、撤销、到期、重启、损坏 KV、写失败、最终 ProviderRequest 和命令 handler。
未验证：真实生产用户样例、真实 Provider 输出满意度、线上部署。
```

复核修复记录（2026-09-07）：

```text
修复一：请求 Hook 只识别由偏好 formatter 生成的完整独立块；普通记忆、画像或其他上下文即使讨论 `<iris:response_style_preference>` 字面量，也不会被整段删除。
修复二：同一 PRIVATE scope、同一参数出现相反候选时，候选写入与旧 APPROVED 值暂停在同一 ProfileStorage 锁内完成；新候选仍保持 PENDING，须人工批准，批准前不自动启用任何新值。
修复三：严格 schema 解码拒绝 APPROVED 与 revoked/suspended 生命周期字段并存的损坏记录；SUSPENDED、REVOKED、PENDING、SUPERSEDED 的互斥字段也按状态校验，读取失败继续恢复默认。
虚构反例：标签字面量误删、相反候选待审核期间旧值继续生效、带撤销字段的 APPROVED 记录继续注入，均已分别回归覆盖。
验证：回复偏好、请求 Hook、身份/adapter/behavior、D02 feedback 聚焦组 119 passed；Review、promotion infrastructure、P2r0 reply authority、Episode shadow 聚焦组 122 passed；compileall 通过；git diff --check 通过（仅 LF/CRLF 提示）。
未验证：真实 AstrBot 装饰器/Provider、真实 KV 并发与故障、真实 Review/archive/episode 完整接线、生产配置与线上用户效果。
```

### T12 — 基于使用结果做第二轮删减

- [x] 依赖：本轮已有本地实现结果；清理只限本次触及链，未扩展为 Iris/编排层重构。
- 回看 T00 清单：已经无人使用的旧 wrapper、重复状态写入、废弃配置入口、重复展示删掉；仍用于历史重放的兼容代码保留最小形式。
- 删除配置字段前定位迁移/默认读取/旧配置行为；删除公开入口前处理调用者，不静默接受被忽略的参数。
- 更新 README 和本 TODO 的入口表，让后续模型只看到真实当前路径。阶段报告留在历史目录，不能作为当前开关事实。
- 完成条件：所有删除有原因与替代路径/无消费者证据，关联回归通过，用户能更快找到主要功能。

执行记录（2026-09-07）：

```text
无需删除：本次新增链没有发现可安全删除的旧 wrapper、配置字段或历史读取协议；现有 UserProfile.communication_style 仍有消费者，保持兼容。
已做的小范围清理：移除本次触及的 ProfileStorage 无用 response-preference 导入；统一唯一 owner、唯一读取/注入点和命令入口文档，避免出现第二套写入权威。
无消费者证据：response_style_preference:v1 只有 ProfileStorage 读写；response_preference section 只有 llm_request_hook 的最终注入路径；Observatory 未接入写操作。
验证：response-preference、llm hook、profile storage、cognitive/web 相关回归通过；未删除其他未提交开发成果。
```

执行记录补充（2026-09-07，D02/L09 增量复核）：

```text
状态：T12 保持完成；本次复核没有发现可安全删除的 wrapper、配置字段、公开入口或历史兼容代码。
新增链核对：D02/L09 的 occurred_at、30 天窗口、2 条独立证据、eligible/insufficient reason 和 out_of_window_feedback_refs 均由 response_preference_feedback.py 的聚合器及其虚构测试使用，没有悬空实现。
唯一 owner：response_style_preference:v1 仍只由 ProfileStorage 持久化；最终注入仍只有 llm_request_hook；聚合器保持 review-only，不另写 KV。
兼容性结论：UserProfile.communication_style 仍被 user_profile.py、models.py、tools/get_profile.py 使用，不能删除；旧历史读取与 P2r0/replay 兼容路径继续保留。
验证：一次性最小宿主桩下 D02/L09 聚焦测试与现有回复偏好测试合计 35 passed；新增模块和测试 ruff 通过；compileall 通过；git diff --check 通过（仅已有 LF/CRLF 提示）。本次 T12 增量为文档与清理审计记录，没有删除代码。
未验证：真实生产运行时、真实 Review/archive/episode 接线、真实 Provider 和线上用户效果仍未验证。
```

### T13 — 提供实际可操作的最小管理入口

- [x] 复用已有 `iris_mem` 管理命令链注册 `preference` handler；不新增审批平台、Dashboard 或通用学习 Agent。
- [x] 维护者可 `pending/status/approve/revoke`；`iris_mem` 入口保留 AstrBot `ADMIN` 权限装饰器，用户侧仅能在自己的当前私聊 `request/status/revoke`，不能批准或改他人 scope。
- [x] 帮助和返回文案明确说明：候选待人工核实、只限一处私聊、批准 7 天、不自动续期、可恢复默认；候选来源 ID 必须人工对照真实入站事件。
- [x] Observatory 继续只读，浏览/刷新不批准、不延期、不写偏好。

执行记录（2026-09-07）：

```text
注册链：main.py::_register_command_handlers() → ResponsePreferenceCommandHandler → CommandParser/execute_command。
本地命令演示：tests/profile/test_response_preferences.py::test_admin_command_parser_and_handler_use_only_system_candidate_id。
来源核验：pending/status 只展示系统生成的 scope/source 引用；伪造 rspref ID 被拒绝；没有真实来源时不批准。
权限边界：批准/管理员撤销位于现有 ADMIN iris_mem 入口；用户撤销只按当前事件 scope 匹配 PENDING/APPROVED 记录。
```

### T14 — 端到端与失败回归

- [x] 用本地 fixture 走到最终 `ProviderRequest.extra_user_content_parts`，验证未批准零注入、批准后同 scope 恰好一个受控 block、本轮详细要求优先、撤销/到期/冲突/损坏/写失败恢复默认。
- [x] 验证同源重复不新增/不延期，重启后状态保持；更换用户、bot 账号、平台实例、群聊或缺失身份时零注入；候选来源不接受调用者自填。
- [x] 保持纠正、含糊质疑、第三方转述、情绪和 `favorability` 不进入候选创建路径；没有自然语言分类器或自动批准。
- [x] 真实 Provider、线上消息、线上数据库和生产部署未执行；模型输出是否“更符合”不以随机短回答替代链路验收。

执行记录（2026-09-07）：

```text
本地 fixture 只构造脱敏事件与内存 KV；通过后仍不代表线上生效。
最终请求前：无 response_style_preference marker；最终请求后：批准且 scope 匹配时只存在一个 marker，撤销/详细覆盖后 marker 消失。
```

第三批增量记录（2026-09-07）：

```
L09 → L11：新增 ResponseLengthFeedbackReviewObserverV1.consolidate_eligible() 和纯 consolidator 适配器；eligible 的 response_length=SHORT aggregate 通过既有 ProfileStorage 写成 PENDING，使用确定性 l09:<sha256> 来源引用，仍需管理员 approve，未新增存储 owner、ReviewEvidence 或自动任务。
管理入口：新增管理员 iris_mem preference consolidate_length；重复聚合不新增候选，未达门槛、已有有效同值、scope 不匹配和写失败均不自动发布。
L10/L12/L13：ResponsePreferenceRecord/KV/schema、最终请求单 marker、当前详细要求覆盖、撤销/过期/重启语义沿用并完成回归；固定时钟演示补充 L11 aggregate→PENDING→approve 路径。
验证：本机 AstrBot 3.12 venv，一次性 tiktoken 内存降级桩下第三批聚焦组 137 passed、1 skipped、3 warnings；compileall、Ruff F、git diff --check 通过。
未验证：真实消息、线上 L09 完整调用者链、生产批准状态、全平台和 Provider 人工满意度。
```

### T15 — 交付能用版本并留下小型优化清单

- [x] README 已加入用户/维护者命令、来源核实、批准、查看、撤销、默认恢复、7 天期限、最终请求脱敏前后示例和本地 fixture 演示路径。
- [x] Todo 已记录真实 owner、读取/注入点、状态机、权限边界、验证结果和未验证生产边界；未声称真实偏好已批准或线上已激活。
- [x] 未来只保留以下小型优化，不引入奖励模型、通用学习状态机或新行为 owner：
  1. 在不放宽 fail-closed 的前提下补充明确要求的语言/平台覆盖测试；
  2. 增加维护者批量查看与来源核验的可读性，但继续沿用现有权限链；
  3. 采集脱敏的人工观察结果，评估表达顺序是否真正有帮助，不把短文本当作自动奖励；
  4. 根据真实使用反馈再决定是否需要更细的表达参数，默认不扩张 scope。

交付边界（2026-09-07）：代码完成；本地验收完成；真实样例批准未发生；H0 候选镜像与 Iris 运行时代码已在生产 `astrbot` 容器完成切换并通过启动/导入检查；线上真实 Host→inbound→archive→L06 样例仍未发生，其他平台未验收。

### 第四批：L14–L16 Episode 自动完成与复盘（2026-09-07）

- [x] L14：沿用 Episode 的 15 分钟 inactivity + 15 分钟 grace 和 durable finalization boundary；补充在途发送/工具 fixture，确认超时只推进状态，不伪造成功 Outcome。已有正常结束、迟到活动/回执、当前新消息和重启 fixture 继续有效。
- [x] L15：复用现有 Production Review Completion、P2/P2r0 archive 与 completion_satisfied；重复完成复用同一 immutable snapshot，失败后保持 FINALIZED 并重试，迟到事实不重写历史。
- [x] L16：生产组合接入已有 TaskScheduler 的单一 `episode_lifecycle_scan` 任务；增加幂等查询/单任务注销、每轮 Episode 上限与轮转扫描。禁用或停止时注销该任务，不创建第二个 lifecycle loop。
- 验证：第四批聚焦组 `181 passed, 1 skipped, 1 warning`；compileall、Ruff F、`git diff --check` 和 schema 解析通过。没有修改生产配置/数据，没有提交、推送或部署。
- 未验证：真实平台入站 scope/source、线上 Episode→Outcome→Review→archive→L06 调用者链、真实撤销/冲突、KV 重启并发故障、Provider 遵循和当前生产加载状态。

### 第五批：L17–L20 工具调用和回复时机（2026-09-07）

- [x] L17 shadow：复用已注册的 `SearchMemoryTool` 和请求 Hook 的明确历史回忆识别，只在当前请求有明确回忆信号且认知路径已有可行动请求时展示 `search_memory` 预览；通过 `ShadowStrategyProposal` 给出原决策/建议决策/依据/scope/权限效果，强制不可应用、不可执行。普通问题和“上次答案错了”不会形成全局工具偏好，建议不能授权发送、付费或删除。
- [x] L19 shadow：复用 `CognitiveBehaviorRuntime`、`TriggerController`、`ParticipationController`；按当前 `SituationLite.scope_id` 区分私聊和群聊，只展示普通群聊降低无邀请插话候选，保留私聊、@、精确回复、普通群聊以及 `SILENCE`/`WAIT` 的原决策。`main._handle_cognitive_behavior()` 只挂载内存 event extra，不改变 Host 回复/发送。
- [x] L18：D05 已冻结工具策略的具体激活、权限、明确不联网、必要操作优先级和撤销读取规则；已接入现有 ProfileStorage 与最终请求 Hook。
- [x] L20：D05 已冻结群范围、优先级、等待期限、激活/取消/超时规则；已接入现有 StateManager、TriggerController、SignalGate 和 ProactiveEngine，不创建第二条回复链。
- 变更：`iris_memory/cognitive/contracts.py` 增加不可执行的 `ShadowStrategyProposal`；`iris_memory/cognitive/behavior.py` 增加工具/回复时机纯 shadow 预览；`main.py` 在既有认知入站 Hook 记录预览；`tests/cognitive/test_shadow_runtime.py` 增加虚构 fixture。
- 验证：第五批聚焦（认知 shadow、Guard、统一派发）`18 passed`；认知合同/行为/适配器、请求 Hook、统一派发和回复偏好回归 `96 passed, 1 warning`；插件目录 `compileall`、变更文件 Ruff F、仓库级 `git diff --check` 通过。测试没有调用真实工具、Provider、平台发送或生产存储。
- 未验证：真实全平台入站 scope、线上工具权限和 Provider 行为、真实发送/等待取消超时、KV 并发/重启/故障、Review/Episode/Outcome/archive→L06 的线上完整接线、生产加载状态。工作树原有其他脏改动保持原样，没有提交、推送或部署。

### 第五批 D05 冻结后继续记录（2026-09-07）

- **D05 已冻结。** 工具策略限定为同一可信 PRIVATE scope 内、经管理员批准且 7 天有效的 `tool_memory_retrieval=ON`；只有当前消息明确回忆历史时才向最终 Provider 请求添加临时只读提示。当前明确“不联网/不要调用工具/不要检索”优先；不授予新工具权限、不改变回复时机、不发送、不付费、不删除、不修改 Persona/Affect/Relationship。参与策略限定为现有 StateManager 按 `group_id` 持有的 `no_uninvited_group_interjection`，默认关闭，管理员 `/iris_reply interjection on|off` 控制，复用现有 `state:<group_id>` KV。
- **L18 已完成。** `request_memory` 走现有 ProfileStorage response preference KV 和候选状态机；请求 Hook 读取批准/撤销/过期/冲突后的单一 active 记录，并在明确历史回忆请求时通过临时 `tool_preference` 段提示已有 `SearchMemoryTool`/L2 路径。未批准、跨 scope、引用/转发、撤销、过期、损坏和当前不联网要求均不产生提示。
- **L20 已完成。** 普通群无邀请 `chime_in` 和 timer `initiate` 在既有消费者前被抑制；私聊、明确 @/唤醒、回复 SELF、锚点 follow-up、现有 `WAIT`/`SILENCE` 保持原语义；管理员强制 `initiate` 保留。开关关闭恢复原行为，不新建等待任务、回复链或发送路径。
- **本地验证。** response preference/Hook `34 passed, 1 warning`；StateManager、ProactiveEngine、行为 `78 passed, 1 warning`；合同、shadow、Guard、统一派发 `24 passed, 1 warning`；插件目录 compileall、变更文件系统 Ruff F 和仓库级 `git diff --check` 通过。所有输入均为虚构数据，没有写生产配置/数据。
- **未验证。** 真实全平台入站 scope/source、真实 Provider 遵循、真实工具权限/调用、线上 KV 重启并发故障、真实撤销/冲突权威状态、生产 Review/Episode/Outcome/archive→L06 完整链、生产加载状态和人工满意度仍未验证；没有提交、推送或部署。

### 第五批 D05 review 修复（2026-09-08）

- 修复 L20 在途取消：非强制 timer 主动任务在唯一直接发送边界再次检查群级 `no_uninvited_group_interjection`。管理员在决策或生成期间开启策略时，旧任务不发送；管理员 `force=True` 仍是明确例外。
- 修复 L18 误激活：工具偏好提示使用仅匹配本人/本私聊过往内容的严格模式，不再把普通“历史”“之前”等 L2 查询改写词当作当前明确请求；带 quote/forward/reply 组件的当前请求不读取该提示。
- 修复管理员误报：`/iris_reply interjection on|off` 会识别本群 manifest 或状态 KV 写失败，并说明内存状态未确认持久化、重启后可能恢复旧值。
- 验证：虚构运行中开关、普通历史措辞、转发输入和 KV 写失败 fixture 已加入；回复偏好、请求 Hook、主动安全和群状态 `131 passed, 1 warning`。真实平台、Provider、KV 重启并发和生产加载仍未验证；未提交、推送或部署。

### 第六批 L21 / D06 关系 owner 盘点（2026-09-08）

- [x] L21：已以当前源码复验并冻结 D06。当前没有证据型长期关系事实的存储或写入者；未知保持未知，不从互动次数、负面反馈或模型推断信任/亲密。
- Iris `UserProfile.bot_relationship` 是称呼/关系描述的画像 prior；`favorability` 是 legacy interaction prior，不能作为 trust、奖励、Persona 输入、current-affect 或关系事实；`emotional_baseline` 是用户画像，不是 bot 情绪。三者均由既有 Iris `ProfileStorage` / `UserProfileManager` 负责，存于 `user_profile:<persona>:<group>:<user>`。
- `astrbot_plugin_affection` 若实际加载，独占 bot current-affect、后台更新、衰减、请求注入及其按 bot 隔离的 `user_data.json` / `self_data.json`。Iris 不读写、迁移或同步这些 JSON；仓库存在不表示生产已经加载。
- 此为 L21 的历史盘点记录；其后的 L22 已按单独冻结的来源、范围、有效期、去重、撤销和失败恢复完成，详见下一节，未把盘点本身解释为关系自动学习授权。
- 验证：既有虚构 Profile 模型、更新者和最终请求投影回归 `91 passed, 1 warning`；未新增关系字段、存储、模型调用、生产配置或数据操作。真实插件加载、Provider 注入顺序、KV 重启并发故障和线上关系表达仍未验证；未提交、推送或部署。

### 第六批 L22–L25 推荐保守设置（2026-09-08）

- [x] L22：复用 Iris `ProfileStorage` 的受控偏好 KV 实现唯一新关系状态 `relationship_familiarity=FAMILIAR`。只有当前用户在完整 PRIVATE scope 中说出固定直接表达“以后这里可以按熟人相处”才会生成待审候选；管理员批准后精确 scope 有效 7 天，不自动续期，用户可撤销，过期恢复未知。它不表示 trust、亲密或权限，且不投影为工具、发送、Persona 或 affect 行为；互动次数、Review、负面反馈、转发/引用和推断均不能写入。
- [x] L23：复验 `astrbot_plugin_affection` 独占 current-affect、`user_data.json` / `self_data.json`、一次请求注入、后台更新与衰减。Iris 不读写、迁移或同步其数据，未新增情绪输入，负面反馈不改关系。
- [x] L24：`persona_evolution_approval_mode` 默认改为 `manual`；任何学习运行即使是历史 `auto` Job 也只保存 candidate 并更新游标/冷却，不能调用 `PersonaManager`。管理员 `approve_revision` 仍是唯一核心发布操作，保留既有复核、冲突、失败恢复和回滚。
- [x] L25：取消运行时性格推断链：分析 prompt 不再要求 `personality_tags`，L1 MID/LONG/combined 不再写入，旧标签不再作为输入或请求提示投影。`太长了` 只表示当次反馈；“不是吧”、自称内向和情绪表达不成为持久偏好或人格事实。
- 验证：虚构事件覆盖关系候选的批准前后、重放、跨 scope、重启、撤销与过期，以及模糊输入拒绝；核心 Persona auto run 不调用 `PersonaManager`；L1 MID/LONG/combined 不写性格标签且请求画像不投影它。`tests/profile/test_response_preferences.py tests/profile/test_analyzer.py tests/core/test_llm_request_hook.py tests/persona_evolution/test_config.py tests/persona_evolution/test_service.py tests/l1_buffer/test_buffer.py` 为 `179 passed, 1 warning`，`compileall iris_memory main.py` 通过，Iris 源码检索未发现 affection JSON 或字段访问。未验证真实平台 adapter scope/message-id、生产 affection 加载与 hook 顺序、真实 Provider、KV 跨进程/重启/故障及生产配置；未提交、推送、部署或修改生产数据。

### 第七批 L26–L29 与项目交付边界（2026-09-08）

- [x] L26：已有 `ResponsePreferenceRecord` / PRIVATE scope / 生命周期 / KV 读回 / 锁已被回复顺序、长度、工具提示和熟悉度复用；它们仍保持各自证据与消费者边界。本批不建立通用学习 manager、规则 VM、第二份存储或奖励分数。
- [x] L27 本地预检：复验旧 `legacy_migration` 的检测零写入、复制备份、幂等短路和备份失败中止；确认它是 v2 兼容迁移，不具备 Iris 历史修复所需的逐条证据、前置版本和变更清单。插件的 `LEGACY_MIGRATION_ENABLED` 默认改为 `False`，正常启动不会自动写历史。
- [ ] L27 真实 dry-run / L28 小批回写：**BLOCKED**。D10 没有真实目标记录 ID、字段前后值、精确来源、备份位置和明确写入授权。没有读取真实历史数据、没有生成伪造清单、没有启动回写；旧迁移器不作为绕过该门槛的替代品。
- [x] L27/L28 本地执行边界：`ProfileStorage` 新增未接入运行时的单条撤销 dry-run、哈希条件写入和恢复入口。范围固定为 `response_style_preference:v1`；dry-run 要求 candidate ID、PRIVATE scope、source、活动 APPROVED 状态和 schema；执行只能改为 REVOKED，先备份、后读回，冲突零写入，恢复要求 after hash 完全一致。未增加通用迁移器、命令、Hook 或生产配置。
- [x] L29 本地关闭验证：ProfileStorage 不可用时，已有受控偏好不再影响新请求，新候选也不能写入且既有记录不被删除；隐式历史迁移默认关闭。Persona 演化、学习和语义评估的敏感用户可见路径仍保持默认关闭或 shadow。
- 项目状态已统一：L01–L25 均为代码与虚构 fixture 的本地验收；L26 无需额外重构；L27–L28 受 D10 阻塞；L29 的真实平台、单 scope 灰度和生产开启未执行。提交、推送、部署和任何生产数据操作均未执行。
- 验证：`tests/legacy_migration tests/profile/test_response_preferences.py tests/profile/test_storage.py tests/core/test_llm_request_hook.py tests/cognitive/test_shadow_runtime.py` 为 `177 passed, 1 skipped, 1 warning`。其中跳过项来自缺少可选 ChromaDB 的旧 L2 迁移测试；未把该结果当作真实平台或生产验收。

## 测试使用说明

以下命令从 `plugins/upstream/astrbot_plugin_iris_memory` 目录执行。先确认项目现有测试环境可用，不自动安装/升级依赖。

Windows 已使用的环境：

```powershell
$xtwPython = 'C:\Users\longz\Documents\学业相关\天文社\小天文设计素材\bot\.test-venv\Scripts\python.exe'
```

G1：身份与主体视角。

```powershell
& $xtwPython -m pytest -q tests/cognitive/test_identity_and_perspective.py tests/cognitive/test_iris_adapter.py
```

G2：参与/行为及已有运行边界。

```powershell
& $xtwPython -m pytest -q tests/cognitive/test_behavior_pipeline.py tests/cognitive/test_shadow_runtime.py tests/cognitive/test_guard_error_path.py
```

G3：Review、完成归档与精确纠正。

```powershell
& $xtwPython -m pytest -q tests/cognitive/test_review_implementation.py tests/cognitive/test_p2r0_archive_wiring.py tests/cognitive/test_p2r1_explicit_correction_rule.py
```

G4：Observatory。

```powershell
& $xtwPython -m pytest -q tests/web/test_cognitive_observatory.py
```

修改真实 Hook 时另外找到该 Hook 的现有测试；G2 不能代替所有消息入口验证。修改前端时读取 frontend/package.json 的真实 scripts，执行关联前端测试，不凭空编造命令。

每批代码改动运行 `git diff --check` 和变更 Python 文件的语法/适用 lint 检查。仅文档修改检查链接、命令和 diff 即可。跨多个认知模块时再运行 `tests/cognitive`，涉及 Web 时再增加 `tests/web`。

存储改动必须包含真正关闭/重开后的重放；失败注入必须验证未发布错误状态。不可把不相关 checksum 错误当成目标边界已经被验证。

## 决策与进度记录模板

每完成一张卡，直接在该卡中追加以下内容，不另建一套阶段报告：

```text
状态：完成 / 部分完成 / 待决策
具体缺口：一两句话，必须能复现
实际改动：文件和用途；若已有功能通过验收则写“无需改动”
删除/合并：符号、调用依据、替代者或无消费者证据
验证：命令与结果；本地/实际运行分开
未验证：只写真实缺口
下一张卡：编号；待决策则写具体问题
```

交给执行模型的短指令示例：

> 执行项目 Todo.md 的 T01。先核实当前工作区和该卡指定调用链，只修能复现的身份解析缺口。使用现有对象和存储，按卡内输入输出验收。完成后更新本卡并停止，不扩展到关系、学习或部署。

## 备忘录覆盖与明确暂缓项

| 备忘录目标 | 本轮路线 | 完成含义 |
|---|---|---|
| Entity / Alias / SELF / Perspective | T01–T02 | 真实检索与身份链正确，含重启边界 |
| 唯一 Persona / Relationship / Affect | T03–T05 | 来源清楚、状态有 owner、避免重复人格和关系 |
| Situation / Trigger / Decision / Silence | T06–T07 | 真正控制行为的路径清楚且职责收敛 |
| Episode / Outcome / Review | T08–T09 | 复盘可见，证据与历史可信，旧设计可删 |
| BehavioralPrior / 受控学习 | T10–T11 | 决策后实现一个可解释可撤销试验 |
| 结构演化、图/层次、多维长期巩固 | 暂缓 | 等实际检索/适应需求证明必要性，再选最小扩展 |

这张表是覆盖路线，不是“所有功能已经实现”的声明。首个实用版本不要求备忘录里所有研究方向同时落地。

## 2026-09-08 R01–R12 执行状态

详细执行卡与授权清单见 `docs/memory-evolution/luna_learning_todo.md` 的“2026-09-08 R01–R12 复验与收口”。本轮没有读写真实历史、生产配置或生产数据，也没有提交、推送、部署。

| 卡 | 状态 | 本轮结果 |
|---|---|---|
| R01 | 本地完成 | L28 单条撤销/恢复改为 CAS 必需、备份 hash 绑定、提交后不误报失败。 |
| R02 | 完成并上线 | AstrBot 核心提供限定 CAS，覆盖 SharedPreferences FIFO/缓存、SQLite BEGIN IMMEDIATE 事务和提交后读回；仅允许 `response_style_preference:v1`。生产 CAS 镜像已加载，未执行真实偏好写。 |
| R03 | 本地完成 | Persona 测试改为显式批准，保留 L24 禁止自动发布。 |
| R04 | 代码与测试完成 | 无正文 durable observation、重启重放、损坏/占锁 fail-closed、管理员显式撤销/冲突入口已接线；68 项组合测试通过。真实用户反馈触发的端到端失效仍需自然运行观察。 |
| R05 | 本地完成 | capture/archive/Review/P2r0 组合回归通过，未做真实平台发送。 |
| R06 | 本地完成 | `profile.enable` 生命周期和 Hook fail-closed 复验通过。 |
| R07 | 本地完成 | Identity 单一 owner、校验和持久化、UID-first、人工 alias 确认/精确撤销和冲突 fail-closed 已接通；待生产重启验证。 |
| R08 | 本地完成 | Situation 已接版本化 owner 快照并冻结为只读映射；缺失/过期/错误为空，Persona 无安全 owner 时仍为空。 |
| R09 | 本地完成 | FAMILIAR 已进入既有受控表达 Hook，禁止虚构关系。 |
| R10 | 本地完成 | 已批准 private-scope 回复偏好投影为最小 BehavioralPrior；本轮明确要求覆盖，permission effect 为 none。 |
| R11 | 本地完成 | affection owner 发布 60 秒脱敏 Affect 快照，Iris 只读校验投影，不接触 affection 存储。 |
| R12 | 待授权 | 已形成最小隔离演练、历史单条回写、灰度和部署前置清单。 |

本轮关键验证：回复偏好维护 `43 passed, 1 warning`；Persona revision `25 passed, 1 warning`；请求 Hook/表达偏好 `84 passed, 1 warning`；P2r0/Review/反馈组合 `85 passed, 1 skipped, 1 warning`；identity/Situation/Shadow `46 passed, 1 warning`。真实 KV、平台、Provider 与生产加载状态仍未验证。


## 2026-09-08 备忘录整理与 GitHub 收口

最新覆盖矩阵与剩余工作见 [记忆演化交付页](docs/memory-evolution/README.md)。R07/R08/R10/R11 已由维护者明确解冻并完成本地接线；按此前要求只做语法和差异检查，未运行 pytest，尚待生产重启和真实事件验证。实际 KV 无 CAS 的历史状态由已准备的 AstrBot CAS 后端补丁处理；L28 真实历史写仍需精确目标授权。旧 R12 待授权记录由后续明确上线和 GitHub 同步授权覆盖，但不包含历史写入。

2026-09-08T04:36Z：R07/R08/R10/R11 已部署至 `azure-xtw-01`。完整 Iris v3.0.4 与 affection v1.2 均成功加载，Iris 异步初始化完成，HTTP 200；Identity v1 信封已创建并收紧为 `0600`。首次定向同步暴露旧生产基线不完整，已通过完整插件备份后同版本覆盖修复。未运行 pytest 或真实消息验收，未执行 L28 历史写。

### P2b Shadow Candidate V1（2026-09-08）

- [x] 新增冻结的 `p2b-shadow-candidate.v1` 契约和 checksummed append-only journal；支持重启重放、幂等创建、跨进程非阻塞文件锁、批准/拒绝/撤销/冲突/过期状态机，损坏或不确定写入时 fail-closed。
- [x] 生产 composition 仅把满足既有 D02 门槛、完整 private UID scope 且能映射到至少两个不同 Episode 的 `response_length=SHORT` 精确反馈聚合投影为 PENDING shadow candidate。
- [x] `auto_approve=false`、`auto_publish=false`、`permission_effect=NONE`；候选批准只更新 P2b journal，不写 ProfileStorage，不改变请求、工具权限、Participation、Persona、Affect 或 Relationship。
- [x] 管理员入口复用 `iris_mem preference`：`p2b_status`、`p2b_evaluate`、`p2b_approve`、`p2b_reject`、`p2b_revoke`。观察台只显示模式、白名单、匿名状态计数和最近评估时间。
- [ ] P2b candidate 到现有 `response_style_preference:v1` 的显式发布动作尚未开放；在定义逐参数映射与二次授权前，APPROVED shadow candidate 仍不会影响回复。
- [ ] 通用 ReviewEvidence 映射继续关闭：当前 `ReviewEvidence.scope` 不含完整 platform/account/user/conversation 权威范围，不能安全泛化为用户偏好。


### R04 管理入口补齐

复用 ADMIN iris_mem preference 新增 feedback_status / feedback_revoke / feedback_conflict，按绑定精确链、scope 和 UTC 时间的稳定观察 ID 操作。修复失效记录重放绑定及清锁失败误报；保留人工巩固和批准。仅语法/静态检查，未跑测试、未部署；Host 自动失效事件和 CAS 仍未实现，冻结项不变。


### R04 生产接线

2026-09-08T01:45:04Z 定向五文件补丁已部署；capture/archive/Iris 异步初始化完成，HTTP 200。详情见 [交付页](docs/memory-evolution/README.md) 最新节。未修改配置或历史维护，未跑测试或恢复演练。CAS 和冻结事项继续保留。


## R02 后端 CAS 开发补充

已在 AstrBot 源码中实现 BaseDatabase 可选接口、SQLite BEGIN IMMEDIATE 条件事务、SharedPreferences FIFO CAS 和 PluginKVStoreMixin 接口。限定 response_style_preference:v1；禁止预写缓存、缺记录不创建、冲突返回 False、成功在 commit 后返回。独立连接竞争、队列顺序、缓存读回及故障用例已补，按既有要求未执行。生产尚未安装，历史维护仍关闭。可应用源码补丁、基线哈希和限制见 [CAS 开发说明](deploy/astrbot/patches/response-preference-cas.md)。

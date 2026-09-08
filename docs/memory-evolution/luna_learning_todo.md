# 小天文长期适应：交给 GPT-5.6-Luna 的小任务清单

日期：2026-09-07。用途：后续开发任务书；本文件不表示功能已经实现，也不自动解除已有架构限制。

目标：让小天文能从有明确来源的日常反馈中形成可解释、可撤销的长期偏好，逐步影响表达、工具选择和参与策略，并分别由现有状态 owner 处理情绪与关系。

## 先读与当前基础

- [当前项目 TODO](../../Todo.md)：优先读开头规则、T03–T05、T10–T15、测试说明。该文件后面的具体验收记录比前面的概览更细，不得仅据未勾选概览认定代码不存在。
- [原始备忘录](xiaotianwen_memory_evolution_memo_v2.md)。
- [架构草案](xiaotianwen_cognitive_runtime_architecture_draft_v0.1.md)：用于定位职责；遇到后来冻结的合同，以现行具体合同为准，冲突必须列出。

本次已核对文档与入口文件。没有重新执行代码测试，也没有读取生产配置。当前 TODO 记录：T10–T15 已完成明确持续要求→人工批准→单一私聊→7 天回复风格适应的本地闭环；未完成真实样例批准、部署和生产激活。Luna 从验收复用开始。

仓库根为 `bot/public/xiaotianwen`。下文 I=`plugins/upstream/astrbot_plugin_iris_memory`，C=`I/iris_memory/cognitive`。文件名均相对该仓库；新增符号是建议，不能把建议名称当作已经存在。

## 给 Luna 的固定执行规则

1. 一轮只做一张卡；一张卡超过一个独立行为改动时先拆子卡。读实际调用者、配置和测试，已有实现通过验收就复用。
2. 先检查 Git 状态和适用 AGENTS.md，保留现有改动。只修改本卡代码、必要测试及进度；不自行 commit、push、部署、改真实配置或回写历史数据。
3. 不新增第二套 Persona、情绪、关系、发送、存储或调度 owner。新增模块前说明现有入口为什么不够。
4. 来源身份使用可信平台、bot 账号、用户和会话字段；不能以昵称、时间最近、文本相似度或模型猜测补足来源。
5. 原始消息、执行事实、ReviewEvidence 与后续解释分开。Review 的“发生纠正”不等于“模型错误”，更不等于“用户喜欢简短”。
6. 当前请求的明确要求优先于已保存偏好；已保存偏好不能越过工具权限、系统规则或当前任务必要步骤。
7. 新能力默认关闭，先实现离线或 shadow 验收。shadow 只计算拟议效果，不影响发送、工具、情绪、关系或 Persona。
8. 未冻结的规则填入决策卡；只暂停依赖该规则的卡，继续独立任务。不能自行把建议阈值、有效期或发布方式当作用户决定。
9. 完成卡必须给出真实调用链验收；只有辅助函数测试时标“部分完成”。用虚构 fixture，不复制真实消息正文、凭证或私人画像进测试及日志。

## 决策卡：实现前把规则写清楚

这些是建议选项，不是新的冻结合同。Luna 可以盘点、写 fixture、做无生产影响的预览；依赖决策的发布代码等相应记录明确后再接通。

| ID | 必须确定的事项 | 建议起点 | 影响卡 |
|---|---|---|---|
| D01 | 学习依据与发布方式 | 第一版仅接受本人明确表达的持续要求；自然语言自动提候选，继续人工批准。下一版才考虑用户直接确认后自动生效 | L04–L08 |
| D02 | 重复日常纠正能否升级长期候选 | 本轮冻结：同一可信用户同一 PRIVATE scope 内，30 天内 2 条独立精确回复链达到 review-only 候选门槛；重复不计数，仍需人工批准，不直接变长期事实 | L06、L09 |
| D03 | 新参数、范围、期限、冲突 | 首先沿用现有单私聊和 7 天规则；“先给结论”与“简短”分开建模。新参数不自动继承授权 | L05–L12 |
| D04 | Episode 结束条件 | 使用生命周期事实；若采用空闲超时，必须明确超时值、在途执行、迟到事件和重启语义 | L14–L16 |
| D05 | 工具及回复策略的写入者、读取者和控制边界 | **已冻结（2026-09-07）**：工具侧只做已批准私聊历史检索提示；参与侧只做管理员控制的群级无邀请插话抑制；默认关闭，不新增权限或发送链 | L17–L20 |
| D06 | 关系模型 owner 与允许字段 | **已冻结（2026-09-08）**：`ProfileStorage` 复用现有受控偏好 KV，唯一新关系状态为 `relationship_familiarity=FAMILIAR`；仅固定直接私聊表达产生候选，管理员批准后精确 scope 有效 7 天，可撤销/过期，不代表 trust、亲密或权限 | L21–L22 |
| D07 | 情绪适应的输入和更新规则 | **已冻结（2026-09-08）**：`astrbot_plugin_affection` 独占 current-affect、其 JSON、后台更新、衰减和一次请求注入；Iris 不提交新情绪输入，也不读写、迁移或同步其数据 | L23 |
| D08 | Persona 自动变化是否变更旧合同 | **已冻结（2026-09-08）**：核心 Persona 默认人工审批；学习运行只能生成候选，不能调用 `PersonaManager` 更新核心。自动修改核心须另行修订合同 | L24 |
| D09 | 用户性格与模糊表达 | **已冻结（2026-09-08）**：不从消息、情绪或反馈推断性格；不投影/分析/写入运行时 `personality_tags`。模糊文本保持未知，明确可核实偏好继续走现有候选流程 | L25 |
| D10 | 历史回写范围及数据操作 | **BLOCKED（2026-09-08）**：没有获授权读取的目标记录、精确字段变更、前置版本或写入清单；不能以旧聊天、日志、相似文本或模型推测替代。历史写入保持关闭，先 dry-run 和小批验证 | L27–L28 |

每项填写：`状态=待定/已冻结；选项；参数；适用范围；授权来源；日期`。原有冻结事项只引用，不重新要求批准。

### D02 执行记录（2026-09-07）

```text
状态：D02 已冻结（2026-09-07；用户授权由本轮执行者选择保守参数）；已实现 L09 的 review-only 门槛判断，但没有把重复纠正发布为长期偏好。
本轮目标：沿用现有 Review/回复链、ProfileStorage 和人工批准入口，冻结并验证一个最小门槛；不新增学习数据库、ReviewEvidence 写入者、后台任务或请求 Hook。
```

当前已经有的安全能力：

- L06 的一条证据只能来自可信私聊中的精确“这段太长”表达，并且必须同时存在同一条 `InboundReplyReferenceFactV1`、状态为 `EXACT` 的 `ExactHostReplyLinkV1` 和对应 Host 输出事实。缺任一权威连接就停止，不回退到最近输出；“你说错了”、模糊质疑、第三方转述、引用或转发不进入这条长度反馈路径。
- L09 的去重身份是 `(source_event_id, inbound_reply_fact_id, exact_reply_link_id, host_output_fact_id)`。同一精确链重复回放只计一次；同一 scope 的 `REVOKED` 或 `CONFLICTED` 状态压过同一链的 `ACTIVE` 重放；不同私聊 scope 分组，不跨用户、会话、bot 账号或平台实例合并。
- L09 仍只生成内存中的 review-only aggregate；达到门槛时标记 `eligible=true`，但不能写 `response_style_preference:v1`，不能生成已批准记录，也不能影响下一次请求。

D02 已冻结的最小合同：

1. **证据单元。** 一条证据必须是一个唯一的精确回复链，包含当前用户的可信来源事件、被回复的入站事实、精确回复关联和 Host 输出事实；不得用消息数量、相邻消息、文本相似度、纠正次数或模型判断替代任一链路。
2. **独立性。** 同一精确链永远只算一次。只有同时满足不同的来源事件和不同的 Host 输出事实，才算两条独立观察；同一 Host 输出上的多次反馈不能通过重复投递增加数量。第一版不要求跨不同 Episode，避免为 D02 新增 Episode 解释规则；观察仍必须属于同一 PRIVATE scope。
3. **时间窗口。** 门槛窗口为 30 个 24 小时周期，边界包含 `now - 30 days` 和 `now`。每条聚合输入必须携带带时区的权威反馈事件时间；缺失、无时区、窗口外或未来时间均不计入。不得从链 ID、文件顺序、当前处理时间或消息正文补造时间。
4. **最低数量。** 门槛为 2 条独立活动观察；必须同时有至少 2 个 distinct source event 和至少 2 个 distinct Host output。达到门槛只表示可进入人工 review，不表示已经批准或生效。
5. **最低 scope。** 沿用当前可信 `ResponsePreferenceScope` 的单一 PRIVATE scope，完整绑定 `platform_id/account_id/user_id/conversation_id`。不允许把同一用户的其他私聊、群聊、其他 bot 或其他平台合并进来；缺失身份直接无 aggregate。
6. **撤销和冲突。** 重新评估时，`REVOKED` 和 `CONFLICTED` 证据从有效计数中移除，不能由旧任务恢复。冲突不采用“最新胜出”或“次数更多胜出”；同一精确链出现不一致的权威时间也按冲突处理。冲突解除前不能重新计入。
7. **发布和批准。** 聚合器只产生 review-only 结果；达到门槛后仍需由后续 Consolidator 创建现有 `PENDING` 候选，再沿用既有管理员批准命令。聚合器不能直接写已批准偏好，不能自动批准，不能绕过系统生成的候选 ID。生效参数仅限现有 `response_length=SHORT`，期限和撤销继续引用 D03 的受控回复偏好合同。

D02 已解决的规则缺口：

- 独立证据定义：同一四元组去重，并要求 source event 与 Host output 各自不同；
- 最低数量：2 条独立活动观察；
- 时间窗口：30 天，必须使用带时区的权威反馈事件时间；
- 最低范围：同一可信 PRIVATE scope；
- 撤销/冲突：失效证据移出计数，不允许旧状态恢复，时间不一致按冲突；
- 发布边界：只到 review-only 门槛，候选创建、人工批准和 7 天生效仍由后续已有链路承担。

D02 之后仍待后续卡处理的接线问题：

- L09 的 `ResponseLengthFeedbackAggregationInputV1.occurred_at` 现在由入站观察适配器严格读取平台原始 `time/timestamp`，并在现有 Review/archive 提交后接入 exact reply-link 聚合；真实平台字段和线上生命周期仍需单独验收。
- 当前聚合结果尚未转成 ProfileStorage 的 `PENDING` 候选；这属于 L11 Consolidator，不在 D02 中提前实现。
- 真实所有平台的回复链、线上 KV 和实际 Provider 仍未验收；本轮只使用脱敏虚构 fixture。

本轮结果：冻结 D02 并在现有 L09 review-only 模块中实现门槛判断；新增虚构时间窗口、独立性、scope、撤销/冲突和不一致时间回放测试。没有新增存储 owner、生产配置、KV 写入、部署、提交或推送。

### D05 执行记录（2026-09-07）

```text
状态：D05 已冻结；授权来源为维护者本轮“按照建议冻结 Dn，然后继续”。本记录把原先仅有的 shadow 边界收窄为两个可独立验收的最小策略；不解冻 Persona、Affect、Relationship、通用学习或自动修改核心 Persona。
```

**A. 工具策略：`tool_memory_retrieval=ON`**

- 聚合单位是一条当前用户通过现有 `/iris_preference request_memory` 明确提交的候选；普通纠正、Review 文本、Episode、Outcome、情绪、关系和模糊表达不能创建该候选。
- 作用范围沿用 `ResponsePreferenceScope` 的完整 PRIVATE 四元组：`platform_id + account_id + user_id + conversation_id`。没有完整可信 scope、消息 ID 或直接消息链时拒绝；引用/转发内容不能成为来源。不同用户、会话、bot 账号或平台实例绝不合并。
- 候选沿用 `ProfileStorage` 的唯一 `response_style_preference:v1` KV、系统生成的 `rspref:` ID、`PENDING → APPROVED/REVOKED/SUSPENDED/SUPERSEDED` 状态、现有管理员批准/撤销命令和 7×24 小时批准期限；不自动批准、不自动续期，冲突与损坏继续 fail-closed。
- 唯一读取者是最终 Provider 请求 Hook。仅当当前请求含有确定的历史回忆表达（例如“我以前说过什么”），且该 scope 有一个有效的 `APPROVED` 值时，才追加已有 `SearchMemoryTool`/L2 记忆链的只读提示。提示只影响已存在的请求上下文，不直接调用工具。
- 本轮明确写出“不联网”“不要调用工具”“不要检索”等固定要求时，当前要求覆盖历史提示；没有明确表达时不从语气、成本、简短回答或一次纠正推断工具偏好。必要操作不因该提示被跳过。
- 该值不授予新工具权限，不允许网络调用、发送消息、付费、删除数据、修改 Persona/Affect/Relationship 或改变回复时机；无权调用的工具仍由原有 Host/Provider 权限链决定。撤销、过期、跨 scope 或读取失败均恢复没有工具提示的原决策。

**B. 参与策略：`no_uninvited_group_interjection`**

- 唯一写入者是现有群主动回复 `StateManager`；唯一控制入口是已有管理员 `/iris_reply interjection on|off`，没有自然语言学习入口。状态按单个 `group_id` 保存在现有 Iris KV 的 `state:<group_id>` 组状态中，默认 `off`；不写 ProfileStorage，不把私聊偏好推广到群。
- `on` 只禁止普通群消息触发的无邀请 `chime_in` 采样和冷场 `initiate`；`off` 恢复原有门控。已有 cooldown、`WAIT`、`SILENCE`、backoff、锚点 follow-up 和其持久化/重试语义仍由原 owner 处理。
- 级别顺序固定为：当前私聊请求和明确 @/唤醒或回复 SELF 仍可进入原路径；群策略只在普通群级无邀请激活前生效；关闭后不读取或保留新的行为影响。管理员 `initiate` 的 `force=True` 是明确的维护者直接命令，仍可执行。
- 该策略不创建等待任务、不发送消息、不复制主动回复链；因此没有新增“撤销后旧等待任务误发”路径。已有等待/取消/超时行为保持原实现，策略检查在非强制主动发起和普通群激活前完成。

冻结后的验收输入与预期：工具候选批准前不提示、批准后仅同一私聊的明确历史回忆提示、其他 scope 不提示、撤销/过期不提示、当前明确不联网覆盖；参与策略默认关闭时保持原结果，开启时普通群无邀请静默，follow-up/@/唤醒/私聊保持原结果，管理员强制发起保持原结果。后续 L18/L20 只能实现上述参数，不能扩展为通用策略学习。

## 第一批：复用已有回复偏好，补齐可运行基础

### L01 — 验收现有闭环，不重建

- [x] 入口：`I/iris_memory/profile/response_preferences.py`、`profile/storage.py`、`commands/response_preference_handler.py`、`core/llm_request_hook.py`。
- 做什么：查找现有测试和命令，运行明确要求、候选、批准、注入、撤销、过期、冲突测试；记录默认开关和实际注册入口。
- 验收：同一虚构私聊批准后最终 Provider 请求只有一个偏好段；批准前、其他用户、其他会话、其他 bot、撤销后和过期后没有该段。本轮要求详细时正常展开。
- 交付：可复现的本地命令、真实测试结果和缺口列表；不宣称线上启用。

执行记录（2026-09-07）：

```text
状态：本地逻辑验收完成；真实 AstrBot 宿主验收未完成。
具体缺口：当前 .test-venv 没有 pytest；系统 Python 有 pytest 但未安装 astrbot 包，因此标准测试命令无法直接收集。未安装或升级依赖，改用一次性内存宿主桩，仅提供本组测试所需的 AstrBotConfig/TextPart 接口。
实际读取入口与调用者：ProfileStorage 持有唯一 KV owner；response_preferences.py 负责严格值、scope、来源、状态和格式化；main.py::_register_command_handlers() 注册 ResponsePreferenceCommandHandler；main.py 的 iris_preference request/status/revoke 负责用户当前私聊操作；core/llm_request_hook.py::_collect_response_preference() 在最终请求边界读取，_replace_response_preference_part() 保证受控段单份。
实际改动：无需改动源码；只更新本卡执行记录。
验收结果：虚构内存 KV 与虚构私聊事件下，候选默认 PENDING 且不注入；人工批准后同一 scope 注入一个 response_style_preference；其他用户、bot 账号、平台实例、群聊和缺失身份不注入；冲突值暂停旧值；撤销和严格 7 天到期恢复默认；重启读取保持状态；损坏 KV/写失败不报告成功且不注入；同源重复不新增、不延期；本轮“这次请详细解释计算过程”覆盖已保存偏好；管理员命令只接受系统生成的 rspref ID。
测试命令与结果：`@'...一次性 AstrBot 宿主桩...'@ | python -` 调用 `pytest.main(['-q', 'plugins/upstream/astrbot_plugin_iris_memory/tests/profile/test_response_preferences.py'])`，8 passed in 5.98s；直接执行 `.test-venv/Scripts/python.exe -m pytest ...` 因 `No module named pytest` 失败；系统 `python -m pytest ...` 因 `ModuleNotFoundError: No module named 'astrbot'` 失败；相关文件 compileall 通过；L01 新增源码与回归测试的 `ruff check` 通过；`git diff --check` 通过。
用户可见效果：profile 可用且通过现有命令创建并经维护者批准后，偏好只在绑定的一处私聊、批准后 7 天内影响表达顺序；用户本轮明确要求详细时不注入该偏好；撤销后恢复默认表达。
未验证：真实 AstrBot 装饰器分发、profile 生产配置、真实 Provider 请求与输出效果、真实 KV 重启、线上消息/数据库、部署和生产激活。
下一张可执行卡：L02；本轮不进入 L02 或自然语言学习。
```

### L02 — 补齐重启、并发和幂等

- [x] 依赖 L01。入口同上，优先复用存储锁与现有版本字段。
- 做什么：针对缺口补同一事件重复投递、重复批准、批准与撤销并发、存储失败和重开存储测试。
- 验收：同一来源不增加证据数量、不续期；撤销后不能被旧任务恢复；写入失败不会在内存显示已发布；重启后状态和到期时间一致。

执行记录（2026-09-07）：

```text
状态：本地逻辑验收完成；真实 AstrBot 宿主验收未完成。
具体缺口：L01 已覆盖同源重复请求、首次写入失败、批准后重启和到期恢复；原测试没有单独锁定重复批准、并发批准、批准/撤销并发以及批准写入失败后的重开状态。
实际读取入口与调用者：继续使用 ProfileStorage 的 response-preference 专用 KV 和 _response_preference_lock；request_response_preference() 负责同源去重，approve_response_preference() 负责单次批准/冲突处理，revoke_response_preference() 负责撤销，get_response_preference_for_event() 只返回一个有效批准记录。
实际改动：仅在 `I/tests/profile/test_response_preferences.py` 增加 4 个虚构回归测试；未修改生产源码、存储协议、命令入口或请求 Hook。
验收结果：重复批准返回 already_processed 且保持第一次 expires_at；并发批准只有一个 approved 结果，最终仅一条 APPROVED 记录；批准与撤销并发后最终固定为 REVOKED，查询不再返回 active 偏好；批准持久化失败返回 write_failed，重开 ProfileStorage 后仍为 PENDING，之后不会被错误显示为已发布。
测试命令与结果：使用与 L01 相同的一次性内存 AstrBot 宿主桩运行 `plugins/upstream/astrbot_plugin_iris_memory/tests/profile/test_response_preferences.py`，12 passed in 0.97s；相关文件 compileall 通过；L01 新增源码与本卡回归测试的 `ruff check` 通过；`git diff --check` 通过。
幂等/并发结论：同一 ProfileStorage 实例的专用 asyncio 锁串行化读改写；重复批准不会延长生命周期；撤销排在批准前或后都不会留下可用偏好；写入失败不会由本地返回值伪装成成功。
未验证：跨多个 ProfileStorage 实例共享同一 KV 的进程内并发、真实 AstrBot KV 后端故障语义、真实 AstrBot 装饰器与 Provider、生产配置、线上数据和部署仍未验证。L01 记录的 `.test-venv` 缺少 pytest、系统 Python 缺少 astrbot 的环境缺口仍存在。
下一张可执行卡：L03；本轮不进入自然语言学习、BehavioralPrior、Persona、Affect 或 Relationship。
```

### L03 — 固定一套反馈反例 fixture

- [x] 不依赖新发布策略。优先加入现有测试 fixture。
- 输入：“以后这个私聊先给结论”“这次简短点”“太长了”“你说错了”“不是吧”“他喜欢简短”“不要记住这个偏好”，以及同名不同 UID、引用和转发文本。
- 做什么：给每条标注可信身份、事件引用、表达对象、持续性、scope、是否允许形成候选以及拒绝原因。
- 验收：当前明确持续要求可进入既有流程；本次指令只影响本次；第三方、模糊语句及普通纠正不自动成为长期偏好。

执行记录（2026-09-07）：

```text
状态：fixture 与现有回复偏好边界验收完成；自然语言自动提取仍未实现，按 L03 约束留给 L04。
具体缺口：原测试覆盖了已批准状态机，但没有固定日常反馈、第三方表述、模糊质疑、撤销表达、同名不同 UID 以及引用/转发内容的统一判定数据。
实际改动：仅在 `I/tests/profile/test_response_preferences.py` 增加 `FEEDBACK_FIXTURES` 和 2 个测试；没有新增生产解析器、学习 manager、EvidenceStore 或新的行为 owner。
fixture 内容：共 10 个虚构案例。每条包含原始表达、内容来源、可信 UID、展示名、平台/bot/用户/会话字段、事件 ID、表达对象、持续性/持久化语义、是否允许候选、现有命令值和拒绝原因。覆盖明确持续要求、一次性简短要求、未精确关联的“太长了”、普通事实纠正、模糊“不是吧”、第三方偏好、撤销意图、同名不同 UID 两例以及引用/转发第三方内容。
验收结果：明确的第一人称持续要求以及两个同名但 UID 不同的直接案例，可通过现有 `CONCLUSION_FIRST` 显式请求入口创建 PENDING 候选；一次性要求、普通纠正、模糊表达、第三方陈述、撤销表达和引用/转发内容均被固定为不可自动形成候选，并保留具体拒绝原因。两个同名用户解析为不同的可信 private scope。
测试命令与结果：使用一次性内存 AstrBot 宿主桩运行 `plugins/upstream/astrbot_plugin_iris_memory/tests/profile/test_response_preferences.py`，23 passed in 0.79s；相关文件 compileall 通过；L01/L02 源码与 L03 回归测试的 `ruff check` 通过；`git diff --check` 通过。
边界结论：本卡只冻结事实分类 fixture 和既有显式入口映射；不会因为 fixture 存在就自动把“太长了”、纠正、模糊表达、第三方内容或转发内容转成长期偏好。自然语言入口仍需 L04 决定并实现可信来源校验。
未验证：真实 AstrBot 宿主分发、真实平台对引用/转发消息的结构字段、真实 Provider、线上 KV/生产配置、部署和生产激活。
下一张可执行卡：L04；本轮不进入 L04，也不解冻 BehavioralPrior、Persona、Affect 或 Relationship。
```

## 第二批：从日常自然语言提出偏好候选

### L04 — 接入明确要求的自然语言入口

- [x] 依赖 L01、L03、D01。先搜索消息 Hook 是否已处理自然语言，缺什么补什么。
- 做什么：把可信直接消息中的明确持续表达要求送进现有候选流程；保留命令入口。不能把网页、工具结果、转发和引用内容当成当前用户指令。
- 验收：“以后这里先给结论”仅产生一个待批准候选；未知身份拒绝；重复投递幂等；不自动影响下一次请求。

执行记录（2026-09-07）：

状态：已完成；在现有 `on_all_message` Hook 接入 `ProfileStorage.request_explicit_response_preference()`，只识别固定完整句式“以后这里先给结论”和“以后这个私聊先给结论”。候选仍使用现有 `response_style_preference:v1`、当前可信消息 ID 和当前私聊 scope，状态只会是 PENDING 或重复来源返回，不会自动批准或改变下一次请求。
边界：`scope_from_event()` 继续拒绝群聊、缺平台实例/bot账号/用户身份的事件；消息链带有 Reply/Quote/Forward/Node 标记或链结构异常时拒绝；没有添加网页、工具结果、转发文本或模糊表达解析。
测试：虚构直接消息创建一个 PENDING；同一消息重复投递返回 duplicate；同名不同 UID 保持不同 scope；群聊、未知身份、引用/转发均无记录；批准前 Hook 读取不到偏好。与 L05/L08 合并运行的定向测试共 68 passed。
未验证：真实 AstrBot Hook 调度、真实平台引用/转发组件字段及线上 KV；未修改生产配置、未部署。

### L05 — 增加一个“回答简短”的独立参数

- [x] 依赖 D03、L04。一次只增加一个参数；沿用现有存储、状态和注入方式。
- 做什么：定义简短为默认减少非必要展开；不设置机械截断，不把 CONCLUSION_FIRST 当成简短的同义词。
- 验收：“先给结论但完整展开”与“简短回答”能分别表示；必要依据、执行结果和错误信息保留；用户当次要求详细时覆盖偏好。

执行记录（2026-09-07）：

状态：已完成；在同一专用 KV 和既有状态机中增加独立 `response_length=SHORT` 参数，并保留 `response_expansion=CONCLUSION_FIRST`。两者分别生成 candidate ID、分别批准、分别按同一 7 天期限管理；同一个 scope 可以同时生效，互不互相冲突。新增 `iris_preference request_length SHORT|DEFAULT` 用户入口，维护者仍用现有 `iris_mem preference approve <candidate_id>` 审批。
表达规则：SHORT 只注入“减少非必要展开，不机械截断；保留必要依据、执行结果和错误信息”；没有字符数或 token 截断器，也没有把先给结论解释成简短。Hook 仍在本轮明确要求详细/完整时跳过整个表达偏好块。
测试：虚构数据验证两个参数可同时 PENDING/批准、candidate ID 不同、冲突只在同参数内处理、Hook 只注入一个合并后的受控块，并包含必要信息保留与当前详细要求覆盖；定向测试通过。
未验证：真实命令装饰器对新增 positional 参数的宿主解析、真实 Provider 对表达提示的最终遵循；未修改生产配置、未部署。

### L06 — 精确关联风格纠正与被纠正输出

- [x] 依赖 L03、D02。入口：`C/reply_link_*`、`explicit_correction_rule.py` 及其实际调用者。
- 做什么：复用可信回复关联。单独保存“用户明确评价该回答太长”这一有来源的解释候选，不更改旧 ReviewEvidence 含义。
- 验收：精确回复“这段太长”可归因到该输出；“你说错了”不能得出长度评价；没有可信关联时记原因并停止归因，不能关联到最近输出。

执行记录（2026-09-07）：

状态：已完成本卡允许的 review-only 部分；新增纯 `ResponseLengthFeedbackEvaluationV1`，输入只接受精确“这段太长”，并要求现有 `InboundReplyReferenceFactV1` 与 `ExactHostReplyLinkV1` 为同一条权威链。输出只包含来源事件、inbound fact、exact link 和 Host fact ID 的解释候选，不写 `ReviewEvidence`、不写回复偏好 KV、不升级长期值。
边界：`你说错了` 返回非长度反馈；缺 inbound fact、缺 exact link、link 非 EXACT 或 inbound 不匹配均返回固定原因并停止，不回退到最近 Host 输出。没有新增模型推断，也没有修改既有 explicit-correction ReviewEvidence 规则。
测试：虚构 Host/inbound/archive 链可得到一个 `RESPONSE_LENGTH_TOO_LONG` 候选；缺 link 与非 exact link 均无候选；事实纠正保持未知。定向测试通过。
未验证：真实运行时是否已经在所有平台提交可重放的精确 archive、真实回复内容与 Review 输入的衔接；本卡未把解释候选接入长期聚合或发布。

### L07 — 给可选语义提取加严格边界

- [x] 依赖 D01、D03；只有规则不足且确实需要模型提取时实施，已有解析器够用则标记无需新增。
- 做什么：固定输出 schema、参数白名单、证据原文位置、持续性与作用范围；输出只作为待校验候选，不把模型置信度当事实。
- 验收：模型超时、非法 JSON、未知参数、伪造引用、输入内“忽略规则”均不产生可发布候选；确定性身份与来源校验不可由模型绕过。

执行记录（2026-09-07）：

状态：无需新增模型语义提取。L04 的完整持续要求和 L06 的精确长度反馈均已有确定性规则；接入模型只会扩大边界并引入未冻结的 schema/证据位置/持续性规则。本轮没有调用模型、没有信任模型置信度、没有开放未知参数或自然语言泛化入口。
保留的严格边界：参数和取值由闭名单校验；scope/source 由平台事件和消息 ID确定；引用/转发链直接拒绝；当前详细要求由确定性 Hook 规则覆盖；所有真正的生效仍须人工批准。
测试：覆盖非法参数、损坏存储、缺身份/缺消息 ID、引用/转发、模糊纠正以及确定性候选路径；定向测试通过。
未验证：若以后需要处理当前闭名单之外的表达，仍需先冻结新 schema、证据引用和安全策略；本轮不解冻通用学习框架。

### L08 — 在现有界面中审阅与解释

- [x] 依赖 L04。入口：现有偏好命令及 `I/iris_memory/web`。
- 做什么：展示待批准/生效/冲突/过期/撤销、适用范围、来源引用、期限和拒绝原因；已有信息直接复用。一次提交只扩展命令或页面之一。
- 验收：维护者能看清“学到了什么、为什么、在哪里生效”；普通用户不能批准他人的候选；读取页面不修改状态；日志不复制原始私聊正文。

执行记录（2026-09-07）：

状态：已选择并扩展现有管理命令，不新增 Web 页面。`iris_mem preference pending/status` 继续读取同一专用 KV，并显示 candidate ID、PENDING/APPROVED/SUSPENDED/SUPERSEDED/EXPIRED/REVOKED、参数和值、platform/account/user/conversation scope、来源 kind+事件 ID、expires_at 和固定 reason；撤销者、冲突原因、过期原因均不复制私聊正文。
权限与读写：批准/按 candidate ID 撤销仍只在现有 ADMIN `iris_mem` 路由；普通用户入口只有当前私聊的 request/status/revoke，不能批准别人的候选。status/pending 的读取不会写状态；当前状态命令测试用 KV 快照证明读取前后不变。
测试：维护者可从 status 看出“学到了什么、为什么、在哪里和多久生效”；伪造 candidate ID 被拒绝；同名不同 UID scope 不合并；撤销/过期/冲突的恢复默认路径已通过定向测试。
未验证：真实 AstrBot 权限中间件和线上管理端渲染；本轮未改 Web、生产配置或部署。

## 第三批：把反馈巩固成长期行为偏好

### L09 — 聚合独立的明确反馈

- [x] 依赖 L06、D02。优先复用可追溯记录，避免新建证据库。
- 做什么：按精确 scope、参数和值聚合；独立性由不同可信来源事件及被评价输出等已冻结规则判断，重放不算新反馈。
- 验收：同一纠正回放十次仍算一次；不同用户和会话不合并；证据撤销或冲突后重新评估，不能继续显示满足门槛。

执行记录（2026-09-07）：

```text
状态：部分完成；D02 BLOCKED。已完成不依赖门槛决定的只读聚合预览，未把聚合结果发布为长期偏好。
依赖与边界：D02 的独立证据数量、时间窗口和最低作用范围仍只有建议起点，当前没有冻结授权；因此本记录不把任何数量解释为满足门槛，也不进入 L10/L11 的 BehavioralPrior 或 Consolidator 发布。
实际读取入口：复用 L06 `response_preference_feedback.py` 产生的 `ResponseLengthFeedbackCandidateV1`，scope 必须由现有 `profile.response_preferences.ResponsePreferenceScope` 提供；没有从正文、最近消息、昵称或模型推断 scope。
实际改动：在同一 L06 review-only 模块增加内存 `ResponseLengthFeedbackAggregationInputV1` 与 `aggregate_response_length_feedback()`；不新增 KV、ReviewEvidence、后台任务、命令或请求 Hook。
输入 → 预期 → 实测：同一精确链回放 10 次 → 计 1 条；不同用户/私聊 → 分成不同 aggregate；同一链出现 REVOKED 或 CONFLICTED → ACTIVE 重放被压过并从有效计数移除；无效 scope/输入 → fail-closed；所有聚合固定 `eligible=false`、`reason=d02_threshold_not_frozen`。新增 3 个 L09 fixture 测试覆盖这些结果。
测试：L06/L09 反馈测试 5 passed；与已有 profile 偏好和最终请求 Hook 回归合计 71 passed in 1.28s；相关 compileall、定向 ruff 和 `git diff --check` 通过。
用户可见效果：当前没有新增行为变化；聚合结果只可供离线审阅，不能写入 `response_style_preference:v1`，不能影响下一次请求。
未验证：真实 Review/回复归档在所有平台上的运行时接线、线上 KV、真实宿主 Hook、真实 Provider 输出和任何生产状态仍未验证。
BLOCKED 的具体规则缺口：请先冻结 D02 的独立证据定义、最少数量、时间窗口、scope 下限、撤销/冲突重算语义及人工批准入口，才能验收 L09 的门槛并继续 L10/L11；本轮不自行决定。
下一张可执行卡：D02 冻结后继续 L09；L10–L13 暂不解冻。
```

执行记录补充（2026-09-07，D02 冻结后）：

```text
状态：L09 仍为部分完成；本轮完成 review-only 门槛判断，但真实运行时调用者尚未接入权威时间，因此不把辅助函数测试标成完整运行时验收。聚合结果达到门槛时只标记 eligible=true，不创建候选、不批准、不影响请求。
冻结规则：同一可信用户同一 PRIVATE scope；30 天包含边界；至少 2 条独立活动观察；每条观察必须有不同 source_event_id 和不同 host_output_fact_id；同一精确链回放只计一次。
时间与失效：AggregationInput 必须携带带时区的权威 occurred_at；缺失、无时区、未来或超过 30 天的观察不计入；REVOKED、CONFLICTED 以及同一链时间不一致的重放均从有效集合移除。
实际改动：复用 `cognitive/response_preference_feedback.py`，增加固定门槛常量、时间窗口过滤、独立性计数、窗口外引用和不一致时间冲突处理；没有新增 KV、ReviewEvidence、候选写入、命令或请求 Hook。
验收：虚构 fixture 覆盖 2 条满足门槛、重复回放、不同 scope、同 source、同 Host、窗口外、未来时间、撤销/冲突、缺失/无时区时间和不一致重放时间；聚焦测试 7 passed，compileall、ruff 和 `git diff --check` 通过。
用户可见效果：没有新增行为变化；eligible aggregate 仍是 review-only，不会写入 `response_style_preference:v1`，也不会让 Hook 注入表达偏好。
未验证：真实调用者尚未把权威 occurred_at 接入 L09；真实 Review/archive/episode 生命周期、线上 KV、真实平台和 Provider 仍未验证。
下一张可执行卡：先补 L09 的真实权威时间和 Review/archive/episode 调用接线；完成后再评估 L10。本轮不自动进入 L10/L11，不解冻 Persona、Affect 或 Relationship。
```

执行记录补充（2026-09-07，L09 运行时接线完成）：

```text
状态：完成本地实现与验收；L09 仍保持 review-only。D02 的冻结规则已实际用于入站反馈聚合，达到门槛只返回 eligible aggregate，不创建 PENDING、不会批准、不会写 response_style_preference:v1，也不会影响最终请求 Hook。
实际接线：复用 P2r0CaptureService 的既有入站捕获点，在 inbound fact 成功提交后观察精确“这段太长”反馈；复用 P2r0HistoricalArchiveService 的既有 Review/archive 提交点，在 archive 成功提交或幂等重放后解析 exact reply link。Episode 的事实筛选和 P2r0 的唯一存储仍由原 owner 负责，没有新增 EvidenceStore、KV 或后台 scheduler。
权威时间：L09 只读取 event.message_obj.raw_message 的 time/timestamp 数字，并按既有适配器的秒级平台时间解释；缺失、非数字、无效或不可信的值直接丢弃，不使用通用 pre-adapter 的 datetime.now 回退。scope 由现有 scope_from_event() 解析，必须是完整 PRIVATE scope，并与 inbound fact 的 platform/account/conversation 身份完全相同。
重放与隔离：内存观察输入按四段 exact chain 去重；同一链重复 archive 通知不增加输入；不同 PRIVATE scope 由已有 scope 对象分组；同一 chain 的不同权威时间保留给聚合器标记 CONFLICTED。D02 的不同 source_event_id、不同 host_output_fact_id、30 天包含边界、过期/未来/撤销/冲突重算继续由纯聚合器执行。
新增验收：新增 capture Hook 复用、Review/archive 提交通知、平台原始时间缺失 fail-closed 三类测试；使用本机 AstrBot 3.12 虚拟环境并对缺失的可选 tiktoken 提供一次性降级桩，L06/L09、P2r0 archive 和 reply capture 聚焦组为 63 passed、1 skipped；既有 production composition 用例单独 1 passed；原有 Profile/最终请求 Hook 回归为 71 passed。新增/修改文件 compileall、Ruff F 规则和 git diff --check 通过。
用户可见效果：没有新增行为变化。L09 结果只存在于当前进程的内存 review observer；不会自动形成长期回复偏好，不会改 Persona、Affect、Relationship、BehavioralPrior 或请求/发送策略。
未验证：真实 AstrBot 入站 Hook 在所有平台的 raw time、private scope 和 source event 完整性；真实 Review/Outcome/Episode lifecycle 的线上归档重放；真实撤销/冲突权威来源；线上 KV 重启、并发、故障语义；真实 Provider 提示遵循；生产插件/配置加载。此前列出的真实运行时验证项仍需真实实例或隔离镜像单独完成。
下一张可执行卡：L10；进入前仍需按依赖单独授权。本轮不解冻 L11/L12/L13，也不进入 Persona、Affect 或 Relationship。
```

### L10 — 实现最小 BehavioralPrior 表示

- [x] 依赖 D02、D03、L09。先查是否已有合适结构；复用现有存储 owner，不另建学习数据库。
- 做什么：仅支持已冻结的表达参数。最少包含版本、scope、参数/值、证据引用、状态、批准方式、有效期和撤销信息；与现有偏好记录建立一个权威关系，不双写两个真相。
- 验收：能解释当前值及来源；缺字段、未知版本和损坏记录不生效；旧偏好数据仍可读取；不把原始纠正变成客观错误标签。

### L11 — 接入最小 Consolidator

- [x] 依赖 L10。Consolidator 指已有运行时中的巩固职责，不预设必须新增同名服务。
- 做什么：读取符合条件的证据，产出或更新候选；按冻结规则批准后才发布。Reviewer 不直接写行为参数。
- 验收：不够门槛时无发布；满足门槛但未批准时不生效；重复执行不重复发布；发布失败、并发撤销和旧版本任务不能覆盖新状态。

### L12 — 接上表达消费者与回滚

- [x] 依赖 L11。入口：已有最终请求 Hook。
- 做什么：让 Hook 从唯一有效来源读取表达参数；同参数只注入一次。新增总开关和必要的参数开关时复用现有配置体系。
- 验收：开关关闭、scope 不匹配、证据失效、冲突或过期均恢复默认；当前显式要求优先；关闭功能无需删除历史记录即可停止影响。

### L13 — 做一次完整本地对照演示

- [x] 依赖 L12。使用虚构会话和固定时钟。
- 做什么：演示初始回答→明确反馈→候选→批准→下一轮请求变化→本次详细要求覆盖→撤销恢复→重启验证。
- 验收：自动检查的是结构化状态与最终请求；实际回答是否更合意单独人工观察，不能把字数下降当成功指标。报告区分代码完成、本地运行和真实平台验收。

### 2026-09-07 真实运行时核验补充

本节只补充 L01–L09 已有闭环的运行证据和修复候选，不改变本轮已冻结的 D02，也不把 L10–L13 标记为已解冻。

- **AstrBot 入站与 Host 回执。** 切换前生产实例为 AstrBot 4.27.5，唯一启用的平台实例为 `xiaotianwen`（`aiocqhttp`）。旧镜像没有 `astrbot.core.platform.send_receipt` 和 `filter.after_message_send_result`，所以 Iris 的 H0 类型边界只能静默 fail-closed。2026-09-07 切换候选后，容器内实际导入 `PlatformSendReceiptV1`、`HostSendResultV1` 和 `register_after_message_send_result` 均成功；`aiocqhttp(xiaotianwen)` 也有启动日志。当前 P2r0 文件只读重放结果为 `0` 条 Host fact、`877` 条 inbound fact、`430` 条 archive、`1307` 条 committed transaction；本次验收没有发送真实 QQ 消息，因此没有新增 Host fact，不能把这个零值解释成 H0 回执失败。
- **H0 修复与生产切换。** 已把现有 `feat/h0-host-send-receipts` 无冲突移植到生产同版本 v4.27.5，候选提交为 `ca3cc5e0`；它对实际配置的 aiocqhttp 发送返回完整 `platform_id/account_id/conversation_id/platform_message_id`，其他未适配平台明确返回 receipt unavailable，不伪造 scope。固定镜像 `xiaotianwen/astrbot:h0-v4.27.5-ca3cc5e0`（image ID `sha256:7ad4fa8ec55ccc69ed6d158626434eeceb3726ea6c7cda37aebd15d08c990206`）已经运行在生产 `astrbot` 容器，状态为 `running`，退出码为 `0`；部署只切换了 `ASTRBOT_IMAGE`，没有重启 SnowLuma、没有提交或推送。
- **Review / Episode / Outcome / archive / L06。** 切换前生产重放得到 429 Episodes、425 finalized、456 Outcomes、425 Review runs、425 archives；因旧镜像缺 Host 事实，历史 archive 不能导出 L06 精确链。候选启动后 Iris、Episode/Outcome observer 和 P2r0 store 均成功加载，代码级完整虚构链与真实 H0 DTO 已通过；L06 仍是 review-only 纯评估器，没有发布偏好。生命周期扫描的迟到 Host/dispatch 回调现已在 FINALIZED Episode 上忽略并保持不可变，未修改 Review 或 archive owner。真实 Host→inbound→archive→L06 链仍需一条实际平台消息才能确认。
- **真实 KV。** 回复偏好继续只使用 AstrBot `SharedPreferences` 的 `preferences` 表和唯一 `(scope, scope_id, key)`。在生产实际 SQLite 的隔离 key 上已验证 PENDING 不注入、批准后注入一次、跨 scope 隔离、冲突挂起旧值、SHORT 与 expansion 独立、8 天后过期、撤销恢复默认，以及三个独立 Python 进程跨重启读取一致。额外发现两个 `ProfileStorage` 包装器并发读改写同一个 JSON 值时会丢一条候选；现改为同一事件循环内进程共享锁，隔离实测两条候选均提交。真实 DB 写失败没有在生产库上破坏性注入；故障路径以 AstrBot awaited commit 和注入式写失败测试验收，写失败返回 `write_failed` 且不发布。
- **真实 Provider。** 使用生产已有 `chatgpt_codex_source/gpt-5.6-luna`、临时会话和真实 `TextPart` 调用一次，Provider 明确识别 SHORT 提示为“默认减少非必要展开、不机械截断、保留必要依据/结果/错误，当前明确详细要求时完整展开”。这证明提示已到达并被该次真实 Provider 理解；不能外推为所有模型、所有回答都会遵循。候选重启后的生产日志显示 gpt-5.6-luna 已加载，但后续实际请求出现 Codex transport 配额/速率限制；配置的默认 `deepseek-responses/deepseek-v4-flash` 及 vision 变体因缺少凭据未实例化，相关既有总结/复审任务因此失败。本卡没有修改 Provider 配置、凭据或配额。
- **生产加载状态。** Iris 的 9 个组件均有成功初始化日志；`aiocqhttp(xiaotianwen)`、WebUI、Episode/Outcome observer、60 秒 lifecycle owner 和 gpt-5.6-luna semantic evaluator 均有启动证据；`profile.enable=true`、自动 profile 注入开启。无清单 Iris 运行时代码包已解包到生产插件目录，包 SHA-256 为 `8bd07ca29105bf88ba3ce4b7dce2ea312ca078f3d769d912977afe32d6dfe315`。启动过程中触发了现有 `astrbot_plugin_debounce` 缺依赖自动恢复，最终容器保持运行；这不是本卡新增配置。生产已有 `persona_evolution.enable=true`，本轮没有把它当作回复偏好的一部分，也没有修改该配置。
- **切换与回滚证据。** 预先尝试的整目录只读快照因远端仅剩约 2.3 GB 而失败，约 2.4 GB 的部分压缩文件已清理，未作为成功备份使用。随后建立并校验定向回滚点 `/home/developer/xiaotianwen/backups/pre-h0-focused-20260907-112900`，包含旧 Iris 插件、`data_v4.db` 及 WAL/SHM、`compose.env` 和旧镜像摘要，总计约 7.9 MB；其中 `iris-plugin-before.tar.gz` SHA-256 为 `ea838a82527149e1a8542811f468f22049fc46ed35fa009e08bdab115c3985d0`，`astrobot-db-before.tar.gz` SHA-256 为 `6ccb0016c1d64036232ca9c672f8edcd268808ac6aee58e4bf19b8d4dbecd5b6`。
- **测试。** v4.27.5 H0 回执组 Linux `33 passed`；真实 H0 镜像下 Iris 的 reply capture、P2r0 archive、L06/L09 纯评估、Episode、回复偏好与最终请求 Hook 聚焦组 `128 passed`。另一次本机同组也是 `128 passed`。隔离镜像完整 Iris 套件为 `1978 passed, 1 skipped, 3 failed`：失败是既有 schema BOM 两项和 legacy migration 默认值一项，与本轮回复偏好/H0 改动无调用关系，因此没有顺手改 Persona 或 migration 边界。H0 测试仍有 pytest 退出阶段的 aiosqlite worker warning，不影响断言，但尚未作为运行时缺陷关闭。
- **仍未完成。** 本次没有发送真实 QQ 消息，所以线上尚未产生可归属于本次部署的 Host fact 和 L06 精确链；没有配置的 Telegram、微信、飞书等平台不能宣称已验收。真实撤销与冲突状态、线上 KV 重启/并发/故障语义、所有实际 Provider 的提示遵循、真实回复满意度仍未完成验证；生产整目录快照也受磁盘空间限制未完成，当前只有定向回滚点。D02 门槛已经在本轮冻结并完成本地 review-only 验收，但真实时间来源和 Review/archive/episode 调用者尚未接入，L10–L13 仍未执行。

### 2026-09-07 L10–L13 尝试结果（受控回复偏好子集）

本次尝试只沿用已经冻结的单一回复表达参数、单私聊 scope、人工批准、7 天期限和现有最终请求 Hook；不把 D02 的建议阈值当作决定，不新增通用 BehavioralPrior 数据库、Consolidator、Persona、Affect 或 Relationship owner。

- **L10：部分完成，通用项仍 BLOCKED。** 现有 ResponsePreferenceRecord 加上 response_style_preference:v1 KV envelope 已具备受控表达先验所需的版本、scope、参数/值、可信来源、状态、批准人/时间、有效期和撤销信息；严格解码会拒绝未知版本、缺字段、未知参数、损坏记录和多条活动值。它与 ProfileStorage 是一条权威关系，Hook 只读取批准后的投影，没有双写另一个 BehavioralPrior 真相。当前没有冻结通用先验的 confidence/decay、ReviewEvidence 聚合或更多行为参数，因此不能把这一窄表示宣称为架构草案中的通用 BehavioralPrior。
- **L11：BLOCKED。** 当前显式要求入口可以创建 PENDING 候选，人工批准可以发布一个已冻结表达值，但它没有把 ReviewEvidence 或 L09 聚合预览转换为长期候选。要实现真正的 Consolidator，必须先冻结 D02 的独立证据定义、最少数量、时间窗口、scope 下限、撤销/冲突重算和人工批准入口；本次没有自行补充这些规则，也没有把 Reviewer 变成行为参数写入者。
- **L12：受控子集已完成。** preprocess_llm_request() 从唯一的 ProfileStorage 读取当前 scope 的有效批准记录，_replace_response_preference_part() 去重后最多注入一个 response_style_preference 临时段；scope 不匹配、读取失败、冲突、撤销、过期和未批准均恢复默认，当前明确“详细/完整”要求优先。没有新增总开关；既有 profile.enable 和参数白名单继续承担启停边界，关闭或不可用时不删除历史记录。
- **L13：受控子集本地演示完成，真实平台仍未验收。** 新增固定时钟组合测试 test_l13_complete_local_demo_with_fixed_clock()，按初始默认 → 明确持续要求 → PENDING → 批准前不注入 → 批准后下一轮单段注入 → 当前详细要求覆盖 → 撤销恢复 → 重开 KV 保持 REVOKED 的顺序验收结构化状态和最终请求。使用候选 H0 镜像、生产 Iris 代码只读挂载和虚构内存 KV 执行，结果 28 passed；没有生成回答、写入生产数据库或发送真实消息。完整 L10–L13 仍因 L11/D02 依赖保持未完成。
- **本次改动与检查。** 这是 D02 冻结后的后续记录；新增门槛测试和本执行记录，没有新增运行时 owner、存储协议、生产配置或部署。相关 Iris 目录 compileall、聚焦 ruff 和 `git diff --check` 已通过；候选容器测试产生的只读验证目录已清理。后续若继续，应按依赖进入 L10，再由 L11 处理候选桥接；本轮不自动解冻。

### 2026-09-07 L10–L13 第三批收口记录（受控回复偏好子集）

本批按用户要求连续完成 L10–L13 的已冻结回复表达子集。通用 BehavioralPrior、自动学习、Persona、Affect、Relationship、是否回复/何时回复、工具策略和后台 scheduler 仍保持未启用；本批没有修改生产配置、生产数据、提交、推送或部署。

- **L10：本地验收完成（受控子集）。** 沿用 `ResponsePreferenceRecord`、`response-style-preference.v1` 和现有 `ProfileStorage` 的唯一 `response_style_preference:v1` KV。新增的聚合来源只保存确定性 `l09:<sha256>` 引用，不复制原始私聊文本；记录仍具备版本、完整 PRIVATE scope、参数/值、来源、PENDING/APPROVED/REVOKED/SUSPENDED/SUPERSEDED 状态、人工批准、7 天期限和撤销字段。旧显式候选格式继续严格读取，未知来源/损坏数据 fail-closed。
- **L11：本地验收完成（最小显式 Consolidator）。** `ResponseLengthFeedbackReviewObserverV1.consolidate_eligible()` 读取已有 L09 review-only aggregate，只把满足已冻结 D02 门槛的 `response_length=SHORT` aggregate 交给同一个 `ProfileStorage` owner；通过新增的管理员 `iris_mem preference consolidate_length` 显式触发。它不自动批准、不调用最终请求 Hook、不建立第二个 Evidence/学习数据库；未达门槛、scope 不匹配、重复 aggregate、已有有效同值或持久化失败分别保持无发布/幂等/失败关闭语义。批准仍只能走既有 `approve`。
- **L12：复用既有 Hook，回归通过。** `preprocess_llm_request()` 仍只读取唯一 ProfileStorage 的有效批准投影，并通过已有临时 `TextPart` 最多注入一个 marker；未批准、scope 不匹配、撤销、过期、冲突、损坏和存储故障恢复默认；当前“详细/完整”要求覆盖保存的表达偏好，历史记录无需删除即可停止影响。
- **L13：固定时钟本地对照完成。** 既有 `test_l13_complete_local_demo_with_fixed_clock()` 验收默认 → 明确持续要求 → PENDING → 批准前不注入 → 批准后下一轮单段注入 → 当前详细要求覆盖 → 撤销恢复 → 重开 KV 保持 REVOKED；新增 L11 测试补充 eligible aggregate → PENDING、重复重放和批准后的 `SHORT` 读取，并验证管理员命令调用巩固器。自动检查结构化状态和最终请求，不把随机回答长度当作成功指标。
- **测试结果。** 使用本机 AstrBot 3.12 venv；在包含 `main.py` 生产组合导入的聚焦组中，以一次性内存 `tiktoken` 降级桩运行 `137 passed, 1 skipped, 3 warnings`（Profile response preferences、L06/L09 feedback、P2r0 archive、reply capture、最终请求 Hook）。同组不使用桩时唯一失败是该 venv 缺失可选 `tiktoken` 导致生产组合导入失败；不涉及本批断言。变更文件 `compileall`、Ruff F 规则和 `git diff --check` 通过。
- **未验证。** 仍未在真实平台发送消息或批准线上候选，因此真实 AstrBot 全平台 scope/source completeness、线上 Review/Episode/Outcome/archive → L09 的完整调用者链、真实撤销/冲突权威状态、线上 KV 重启并发故障、所有真实 Provider 的长期遵循、生产插件/配置加载和人工回复满意度均未由本批证明。当前只声明代码完成和本地运行完成。

### 2026-09-07 D12 编号识别记录

- 更早记录已搜索本任务文件、当前 Todo 记录、架构草案、相关源码和测试引用；当时项目只定义 D01–D10，没有 `D12`/`d12` 决策卡，也没有可直接验收的 D12 实现。
- 该记录只用于阻止当时的编号误判；本轮没有新增未经定义的 D12，也没有把 D02 或 D03 改名为 D12。D02 的门槛已在本轮按用户要求单独冻结，具体规则以本文件前面的 D02 执行记录为准。
- 当前能安全继续的最近边界已从“冻结 D02”变为“按依赖评估 L10”；现有受控回复偏好子集的存储、Hook、命令、撤销和过期闭环继续保持原状，L10/L11 仍需单独执行。
- 本记录本轮只做历史状态修正；没有额外行为代码、生产配置、运行时数据写入、部署、提交或推送。

## 第四批：自动完成 Episode 和复盘

### L14 — 固定 Episode 结束样例

- [x] 依赖 D04。入口：`C/episode_lifecycle.py`、`episode_store.py`、completion coordinator 的实际定义。
- 做什么：先写冻结规则对应 fixture：正常结束、长时间无消息、仍有工具运行、同用户新消息、迟到平台回执、跨重启。
- 验收：未完成发送/工具不会误标成功；结束不代表用户满意；超时只能证明规则触发，不能生成成功 Outcome。

### L15 — 幂等 finalization 与恢复

- [x] 依赖 L14。复用已有完成及归档链。
- 做什么：实现最小可恢复完成步骤，查验现有持久化标记再决定是否补充；失败后从可验证状态恢复。
- 验收：重复完成只产生一份有效结果；在各持久化边界中断并重启后不丢失、不重复 promotion；迟到事件按已冻结规则处理，不偷偷重写历史事实。

### L16 — 接入现有 scheduler

- [x] 依赖 L15、D04。先查真实启动/停止生命周期和已有调度机制，不开第二套后台循环。
- 做什么：按冻结条件查找可完成 Episode 并调用同一 finalization 入口；配置启停、扫描量上限、失败重试和任务取消。
- 验收：启停不重复注册；重启能继续；同时扫描不重复完成；到期任务只处理对应 Episode；调度关闭后不再触发完成。

### 2026-09-07 L14–L16 第四批收口记录

本批只处理 Episode 生命周期完成、已有 completion/archive 恢复和共享 scheduler 接线；没有解冻工具策略、回复时机、Persona、Affect、Relationship 或通用学习边界，没有修改生产配置/数据，没有提交、推送或部署。

- **L14 已完成。** 保留现有 `EpisodeLifecycleOwnerV1` 的 15 分钟 inactivity + 15 分钟 soft-close grace 规则以及 `AppendOnlyEpisodeStore` 的事实状态机。新增虚构夹具覆盖带 `send:pending`/`tool:running` 未完成引用的 Episode：到期只进入 `FINALIZED`，完成入口收到空的 durable Outcome 集，不凭超时生成成功 Outcome。既有夹具继续覆盖近期 Episode 不结束、同用户迟到活动延长 grace、正常工具/Host/dispatch walkthrough、同用户新消息/当前 Episode、迟到回执或 Outcome 不回写已完成历史、重启后 OPEN→INTERRUPTED 和状态恢复。
- **L15 已完成且无需重写 completion/archive。** 现有 completion coordinator 先按 immutable ReviewRun snapshot hash 复用 ReviewRun，再按同一 run 复用 P2/P2r0 archive；`completion_satisfied()` 只在 Review、archive 和已启用 promotion 的 durable 条件全部满足时返回 true。既有测试验证失败后保持 FINALIZED 并重试、重复完成只保留一个 ReviewRun/archive、重启保留 finalization boundary 和精确 Outcome 集、迟到事件/Outcome 位于 durable cutoff 后被排除。
- **L16 已完成。** `IrisMemoryPlugin` 在 `initialize_components()` 完成后把单轮 `owner.run_scheduled_scan` 注册到已有 `TaskScheduler`，任务名为 `episode_lifecycle_scan`，间隔复用 60 秒；不再在生产组合中调用 owner 自建 asyncio loop。新增 `TaskScheduler.is_task_registered()` 和 `unregister_task()`，支持幂等重启检查、只注销该任务、保留 scheduler 其他任务；Episode owner 增加 `max_episodes_per_scan`（schema 默认 100）并以轮转游标继续扫描，避免有界扫描固定处理前缀。scheduler 自带异常隔离负责下一周期重试；禁用配置或插件停止时注销任务，生产完成入口不再触发。
- **具体变更。** `iris_memory/cognitive/episode_lifecycle.py` 增加单次扫描上限、轮转和 scheduler 单轮调用；`iris_memory/tasks/scheduler.py` 增加任务查询/注销；`main.py` 调整初始化顺序、共享 scheduler 注册和停止清理；`_conf_schema.json` 只增加 `episode_lifecycle.max_episodes_per_scan` 的 schema，不写入生产配置。新增/补充 lifecycle、runtime composition、scheduler fixture。
- **测试。** 在 Windows `bot/.test-venv` 的 Python 3.12 环境运行第四批聚焦组：`test_episode_store.py`、`test_episode_shadow_integration.py`、`test_episode_runtime_integration.py`、`test_episode_lifecycle.py`、`test_p2r0_archive_wiring.py`、`test_reply_link_capture.py`、`test_review_implementation.py`、`test_scheduler.py`，结果 `181 passed, 1 skipped, 1 warning`。本批相关文件 `compileall`、系统 Ruff F 规则和 `git diff --check` 通过；schema 以 `utf-8-sig` 解析通过。
- **未验证。** 仍未在真实 AstrBot 入站/发送平台运行这条 owner→scheduler→completion/archive 链；全平台 scope/source 完整性、真实撤销/冲突权威状态、线上 KV 重启/并发/故障、实际 Provider 行为、生产实例当前是否加载这份工作树和线上人工满意度仍不能由本批本地测试证明。生产配置保持原样且自动 finalization 默认关闭，除非部署方已有明确配置。

## 第五批：工具调用和回复时机

### L17 — 工具偏好只做 shadow

- [x] 依赖 D05、L10。入口：实际工具选择消费者及 `C/behavior.py` 的调用链。
- 做什么：选择一个具体允许项，例如在已经可以自主查资料的请求里优先检索。先展示“原决策/建议决策/依据”。
- 验收：不会执行新工具；“上次答案错了”不自动变成“所有问题都查工具”；偏好不能授权发送消息、付费或删除数据。

### L18 — 工具策略接入实际消费者

- [x] 依赖 L17，且 D05 已明确该项激活规则。
- 做什么：只接一个经过许可的策略，沿用现有工具调用链；本卡不改变回复时机。
- 验收：明确要求不联网时不受历史检索偏好影响；无权调用的工具始终不能调用；用户要求执行必要操作时不能因省工具偏好省略；撤销后恢复原决策。

### L19 — 回复/等待偏好只做 shadow

- [x] 依赖 D05、L10。入口：`C/trigger.py`、`behavior.py`、插件真实入站链。
- 做什么：先挑一项，例如普通群聊降低无邀请插话倾向；明确个人偏好与群级策略的适用主体和管理权限，不能把私聊偏好自动推广全群。
- 验收：私聊、@、精确回复、普通群聊各有固定样例；本阶段真实回复和发送完全不变；保留 SILENCE/WAIT 的已有语义。

### L20 — 接入一个参与策略

- [x] 依赖 L19，且该策略的群范围、优先级、等待期限及激活规则已冻结。
- 做什么：由唯一参与决策 owner 读取参数；需要等待时使用现有机制，明确用户新消息到来、取消和超时处理。
- 验收：不开第二条回复链、不重复发送；明确直接请求按冻结优先级处理；旧等待任务不会在撤销/取消后发出过时回复；关闭开关恢复原行为。

### 2026-09-07 第五批 L17–L20 收口记录

本批只做 D05 允许的 shadow 盘点和预览，不把建议中的工具或参与偏好接入实际执行。没有新增工具、回复、发送、等待、存储或学习 owner；没有读取 L10 的回复长度记录来推导工具或参与策略，没有修改生产配置/数据，没有提交、推送或部署。

- **L17 已完成（本地真实组合的 shadow 链）。** 复用 `main.py::_register_llm_tools()` 已有的 `SearchMemoryTool`，以及请求 Hook 中已有的 `_has_memory_retrieval_intent()`、`_collect_l2_memory()`/`MemoryRetriever`。`CognitiveBehaviorRuntime.shadow_tool_preference()` 只接受当前请求 Hook 的明确回忆信号和本轮已有的可行动认知请求，返回不可执行的 `ShadowStrategyProposal`，列出原决策、建议决策、候选 `search_memory`、scope、依据和权限效果；它强制 `applied=False`、`executed=False`，不调用工具、不写偏好。普通问题没有当前回忆信号时原决策保持不变；“上次答案错了”没有可行动请求时不形成工具建议，也不会扩散为所有问题检索；建议明确不能授权发送消息、付费或删除数据。
- **L19 已完成（本地真实组合的 shadow 链）。** 复用现有 `TriggerController` 和 `ParticipationController`。`shadow_reply_timing_preference()` 以同一 `SituationLite.scope_id` 标出 `private_scope_only` 或 `group_scope_only`，只对普通群聊展示 `reduce_uninvited_group_interjection` 候选；私聊、@、回复 SELF 的触发结果保持原值，群级候选不读取或推广私聊偏好，已有 `SILENCE`/`WAIT` 也保持原值。`main._handle_cognitive_behavior()` 仅把两个预览对象放进 `iris_cognitive_strategy_shadow` event extra，既有 Host 回复和发送链不变。
- **L18 保持 BLOCKED。** D05 仍只有“先 shadow、只调整已允许行为”的宽边界，没有冻结具体工具策略的激活条件、工具权限/可用性判断、明确“不联网”优先级、撤销读取和必要操作优先级；因此没有把 `search_memory` 预览接进实际工具消费者，也没有假装已完成批准/撤销后的策略切换。
- **L20 保持 BLOCKED。** 没有冻结参与策略的群范围、优先级、等待期限、激活/取消/超时规则，也没有授权把 shadow 候选接入现有回复 owner；因此没有新建等待任务、回复链或发送路径，不会产生旧等待任务误发的新增风险。
- **本地验证。** 新增虚构 fixture 覆盖显式历史回忆、普通问题、纠正表达、私聊、@、精确回复、普通群聊、`WAIT` 和 `SILENCE`；验证 scope 不跨用、预览不可执行/不可应用。额外验证现有主 Hook 组合会挂载预览但不停止 Host：`test_shadow_runtime.py`、`test_guard_error_path.py`、`test_unified_dispatch.py` 共 `18 passed`；认知合同/行为/适配器、请求 Hook、统一派发和回复偏好回归共 `96 passed, 1 warning`；插件目录 `compileall`、变更 Python 文件 Ruff F、仓库级 `git diff --check` 通过。
- **未验证。** 仍未在真实 AstrBot 平台事件上证明各平台入站能提交完整 scope，未验证线上工具权限、真实 Provider 工具调用、真实发送/等待取消与超时、真实 KV 并发/重启/故障、Review/Episode/Outcome/archive→L06 的线上完整链，以及生产实例是否加载这份工作树。L18/L20 需先补 D05 冻结卡后再继续。

### 2026-09-07 D05 冻结后 L18/L20 接入记录

本轮依据上一节已冻结的 D05 继续实现 L18/L20。新增能力仍是默认关闭、受现有 owner 控制的窄策略，没有引入工具权限、发送权限、等待任务、第二条回复链、通用学习状态或生产配置。

- **L18 已完成（本地最终请求消费者）。** `ProfileStorage.request_memory_retrieval_preference()` 沿用现有私聊 scope、可信消息 ID、引用/转发 fail-closed、同一 KV、系统候选 ID、人工批准、7 天有效期、撤销、冲突和持久化读回校验。`llm_request_hook._collect_tool_preference()` 只在当前请求明确回忆历史且该 scope 有一个有效 `tool_memory_retrieval=ON` 时生成临时 `tool_preference` 段；它引用已经注册的 `SearchMemoryTool`/L2 只读路径，但不直接调用工具或改变权限。当前明确“不联网/不要调用工具/不要检索”时跳过该段；撤销、过期、其他 scope、未批准和损坏读取均不产生提示。原有 response style marker 和普通 L2 检索保持独立。
- **L20 已完成（本地现有参与/主动回复消费者）。** `StateManager` 增加默认关闭且按 `group_id` 持久化的 `no_uninvited_group_interjection`；已有管理员 `/iris_reply interjection on|off` 是唯一写入口。`main.on_message()` 在普通群无邀请 `chime_in` 激活前抑制；`ProactiveEngine` 在非强制 timer initiate 前抑制；`TriggerController` 读取同一只读投影并保留私聊、明确 @/回复 SELF、锚点 follow-up 以及既有 `WAIT`/`SILENCE` 语义。管理员 `initiate` 的明确 `force=True` 仍可走原路径。关闭开关恢复原行为，不产生新等待任务或发送链。
- **具体边界验收。** 虚构私聊候选覆盖 PENDING 不生效、批准后生效、同一 scope 注入、跨用户隔离、撤销、批准时间回溯后的过期和本轮“不联网”覆盖；虚构群状态覆盖默认 off、持久化重开、普通无邀请抑制、follow-up/明确 @/私聊保持、非强制主动发起不调用 Provider/不发送，以及 `TriggerSnapshot` 的原决策保留。所有策略提示和组状态都不复制私密正文。
- **本地测试。** 回复偏好与最终请求 Hook `34 passed, 1 warning`；主动状态/主动发起/认知行为 `78 passed, 1 warning`（中途发现测试夹具遗漏白名单和 `TriggerSnapshot` 导入，已修正后通过）；合同、shadow、Guard、统一派发 `24 passed, 1 warning`。插件目录 compileall、变更文件系统 `ruff --select F` 和仓库级 `git diff --check` 均通过。
- **未验证。** 仍未用真实 AstrBot 平台发送消息验证全平台 scope/source，未验证真实 Provider 是否遵循提示、真实工具调用权限、线上 KV 重启/并发/故障、真实撤销/冲突权威状态、现有 Review/Episode/Outcome/archive→L06 在生产中的完整接线、生产实例是否加载当前工作树以及人工满意度。没有提交、推送、部署或修改生产配置/数据。

### 2026-09-08 D05 review 修复记录

- **在途参与取消。** 非强制 timer `initiate` 除入口判定外，在唯一 `send_message` 边界再次读取同一 StateManager 群策略；决策或发言生成期间管理员开启 `interjection on` 时，旧任务返回“该群已禁止无邀请插话”且不发送。`force=True` 的管理员明确发起保持原例外。
- **工具提示激活收窄。** L18 临时提示不再复用宽泛 L2 查询改写关键词。它只接受直接询问本人/本私聊过往内容的固定模式；“历史唯物主义”“提交之前”等普通历史或时间用语不激活。当前请求含 quote/forward/reply 组件也不读取该偏好提示。
- **持久化结果如实报告。** StateManager 的既有 `save_dirty()` 继续保留失败重试语义，并返回失败 KV key。`/iris_reply interjection on|off` 在本群 manifest 或 `state:<group_id>` 写失败时报告“持久化失败；重启后可能恢复旧状态”，不再把仅内存状态称为已完成保存。
- **本地验证。** 虚构 fixture 覆盖上述在途切换、无关关键词、转发输入和 KV 写失败；回复偏好、请求 Hook、主动安全和群状态回归共 `131 passed, 1 warning`。没有真实平台发送、KV 故障注入或生产配置变更。

## 第六批：关系、情绪、Persona 与性格

### L21 — 确认关系唯一 owner

- [x] 已盘点并冻结 D06。读当前 TODO 的 T04–T05 与现有关系调用链。
- 做什么：列出现有字段、读写者、来源和持久化，明确哪些是 legacy prior，哪些是真正关系状态；在本卡补齐 D06，不迁移数据。
- 验收：每个拟使用字段都有一个写入 owner；`favorability` 不被当作奖励、信任事实或情绪信号；没有 owner 的字段不进入生产。

### 2026-09-08 L21 / D06 执行记录

```text
状态：L21 本地验收完成；D06 已冻结为现有字段分类和 owner 边界，未授权 L22 的任何关系变化公式。
授权来源：维护者“按照做第六批的任务”；沿用当前 TODO 的 T04/T05 已记录 owner 决定并以当前源码复验。
```

| 字段或状态 | 当前 owner / 写入者 | 范围与持久化 | 允许的当前含义 | 冻结限制 |
|---|---|---|---|---|
| `UserProfile.bot_relationship` | Iris `UserProfileManager` 经 `ProfileStorage`；既有分析更新和人工 Profile 编辑 | `user_profile:<persona>:<group>:<user>`，实际 persona/group 隔离由现有配置决定 | 用户对 bot 的称呼或关系描述这一画像 prior；空字符串为未知 | 不是逐条可审计的关系事实；L21 不新增读取者、自动升级、权限效果或关系推断 |
| `UserProfile.favorability` | 同一 Iris Profile owner；既有 Profile 分析 delta 和人工编辑 | 同一 Iris user-profile KV，`0.0` 为历史兼容默认 | legacy interaction prior | 不是 trust、亲密、奖励、current-affect、Persona 输入或学习信号；默认零且无来源元数据时按未知处理，不得作为“陌生”事实 |
| `UserProfile.emotional_baseline` | 同一 Iris Profile owner；既有分析更新和人工编辑 | 同一 Iris user-profile KV，空字符串为未知 | 用户画像的情绪倾向 | 不是 bot current-affect，不是关系状态，不向 affection 写入或同步 |
| affection 的 `affection`、`current_libido_other`、`current_aggression_other` 与 self fields | `astrbot_plugin_affection` 自己的 storage、后台潜意识更新、衰减和管理命令 | `StarTools.get_data_dir()` 下按 bot 分目录的 `user_data.json` / `self_data.json` | 若该插件实际加载，为 bot current-affect | Iris 不读、写、迁移或同步；仓库存在不代表生产已加载 |

**D06 最小合同。** 第一版不存在可由 Review、消息次数、负面反馈或模型推断写入的“关系事实”。缺乏明确字段值时保持未知；不凭频繁互动推出信任、亲密或权限。现有 `bot_relationship`、`favorability`、`emotional_baseline` 和 affection 状态只按上表解释，不能相互升级或自动转换。L22 若要增加一个有依据的关系变化，必须先另行冻结该维度的来源、范围、数值/状态、限幅、去重、撤销和重启失败语义。

**本地验收。** 当前 `UserProfile` 模型、Profile 更新者、Profile KV 和最终请求投影均与该分类一致；Iris 源码没有调用 affection 的 JSON storage，affection 源码自己负责请求注入、后台更新和衰减。使用既有虚构 fixture 运行 `tests/profile/test_models.py tests/profile/test_user_profile.py tests/core/test_llm_request_hook.py`，结果为 `91 passed, 1 warning`。本卡没有新增关系字段、存储、写入者、模型调用、生产配置或数据操作。

**未验证。** 没有生产插件配置快照，无法确认 affection 是否在线上加载；真实 Profile 分析输出、KV 并发/重启/故障、实际 Provider 注入顺序和用户对关系表达的感受仍未验证。

### L22 — 只实现一种有依据的关系变化

- [x] 依赖 L21、D06。例如可核实互动产生的熟悉度变化；具体维度和公式必须先冻结。
- 做什么：由关系 owner 接受带来源的输入、校验并更新；Review 只能提供符合合同的证据。加入限幅、去重及撤销/纠正路径。
- 验收：互动频繁不会自动变成信任或亲密；新用户保持未知；重放、证据撤销、重启和更新失败得到确定结果；不能影响权限。

### L23 — 经 affection owner 处理情绪输入

- [x] 依赖 D07。现有冻结边界：`astrbot_plugin_affection` 独占 current-affect 及其存储、更新和衰减。
- 做什么：先验收其已有情绪变化是否满足目标；如需新输入，沿用该插件允许的接口。缺接口则先定义最小适配合同。
- 验收：Iris 不直接读写/迁移/同步其 JSON；负面反馈不自动惩罚用户关系；状态只注入一次；没有可信输入时沿用原情绪行为。

### L24 — Persona 演化的受控路线

- [x] 依赖 D08。入口：`I/iris_memory/persona_evolution/`，尤其 component、service、publisher。
- 做什么：先确认现有发布目标和 auto 路径。保持核心不变的选项只调整已允许表达参数；若明确要求自动改核心，先单独修订合同，再拆成“生成提案/版本快照/校验/发布/回滚”五张子卡。
- 验收：在未解除旧限制前任何学习输入不能调用 PersonaManager 更新核心；批准新合同后还需验证身份、不变项、并发版本、失败恢复和回滚，不能只测生成了新提示词。
- 注意：表达偏好生效不等于完成了“自动修改核心 Persona”。交付必须分别标注。

### L25 — 用户性格与模糊表达的边界

- [x] 依赖 D09。先补拒绝推断测试，不实现通用性格分类器。
- 做什么：“太长了”可保留这次的明确长度反馈；“不是吧”保持未知；“我是内向的人”只能作为有来源的自述，不能当作模型独立验证的人格事实。
- 验收：不从简短发言推导内向、不从情绪推导稳定性格、不从一次不满推导永久偏好。澄清得到的明确答案作为新来源进入既有流程，未获回答不等于同意。
- 若最终目标确实包含自动性格归纳或模糊推断：另立合同变更卡，明确推测标签、适用范围、用户查看/纠正/删除及允许消费者；本清单不把被禁止能力偷偷改成默认启用。

### 2026-09-08 L22–L25 / D06–D09 执行记录

```text
状态：本地实现与验收完成；使用维护者授权的推荐保守设置。
授权来源：维护者“完成l22-l25 dn使用推荐设置”及“继续完成l22-l25”。
```

- **L22 / D06。** 复用 `ProfileStorage` 的已有 source-bound、精确 PRIVATE scope、人工审批、撤销、读回确认和进程锁闭环。唯一新状态是 `relationship_familiarity=FAMILIAR`：仅当前用户完整私聊事件的固定直接表达“以后这里可以按熟人相处”可产生待审候选；批准后有效 7 天、不自动续期，撤销或过期恢复未知。它没有请求投影或任何权限、工具、发送、Persona、affect 消费者；互动次数、Review、负面反馈、转发/引用和模型推断均不能写入。
- **L23 / D07。** 当前 Iris 源码没有读取 `astrbot_plugin_affection`、`user_data.json` 或 `self_data.json`。affection 自己拥有按 bot 分目录存储、`on_llm_request(priority=10)` 的一次情绪注入、`on_waiting_llm_request(priority=10)` 的后台更新和衰减。Iris 没有新增情绪输入，也没有让负面反馈改变关系状态；没有可信外部输入时维持现有 affection 行为。
- **L24 / D08。** 默认 `persona_evolution_approval_mode` 改为 `manual`，且 service 对既有 auto Job 也只存 `candidate`、推进语料游标与冷却，不再从学习运行调用 publisher。唯一可能写核心 Persona 的路径是既有管理员 `approve_revision`，它仍保留重新校验、hash 冲突、发布失败和回滚机制。表达偏好不等同于核心 Persona 自动修改。
- **L25 / D09。** Profile 分析 prompt 不再要求 `personality_tags`，旧标签不再回送分析、不再由 L1 的 MID/LONG/combined 派发写入，也不投影到请求。`太长了` 仍只可作为当次反馈；`不是吧`、自称内向或情绪表达均不建立持久候选或性格事实。旧存储数据未迁移或删除。
- **本地验证。** 虚构事件覆盖 L22 的待审、批准、重放、跨 scope、重启、撤销、过期和模糊输入拒绝；还覆盖 L24 的 auto 触发不会调用 `PersonaManager`、候选后冷却，以及 L25 的 MID/LONG/combined 写入与请求投影拒绝。运行 `tests/profile/test_response_preferences.py tests/profile/test_analyzer.py tests/core/test_llm_request_hook.py tests/persona_evolution/test_config.py tests/persona_evolution/test_service.py tests/l1_buffer/test_buffer.py`：`179 passed, 1 warning`；`compileall iris_memory main.py` 通过。Iris 源码检索未发现 affection JSON 或字段访问。
- **未验证。** 未在真实 AstrBot 平台重放事件或验证所有 adapter 的 scope/message-id 完整性；未验证线上 affection 插件是否加载、与 Iris 的实际 hook 顺序、Provider 是否遵循表达文本、KV 跨进程并发/重启/故障和生产配置。未提交、推送、部署，也未修改生产数据。

## 第七批：复用、历史处理和上线

### L26 — 在多个真实参数工作后再提取共同代码

- [x] 已验收，不新增通用学习框架。依赖至少两个已经端到端验收的参数。
- 做什么：只合并确实重复的 scope 校验、有效期、状态读取和幂等操作，保留各领域不同的证据与发布规则。
- 验收：固定历史样例读写兼容、既有测试通过、行为不变；不为了“通用学习框架”引入规则 VM、第二个 manager 或通用奖励分数。
- 完成含义：得到可复用的小基础设施；不声称任意行为均可自动学习。

### L27 — 历史 Iris 修复 dry-run

- [x] 已完成本地受控 dry-run 实现和虚构数据验收：只读取 `response_style_preference:v1`，要求精确 `candidate_id`、PRIVATE scope、source、活动状态和 schema 校验，输出单条与完整 payload 的 SHA-256，dry-run 零写入。
- [ ] **真实执行 BLOCKED：缺 D10 的目标记录、字段、前置版本和可读授权。** 依赖 D10 确定可读范围；写入尚不授权时只预览。
- 做什么：针对一个可复现缺陷生成变更清单，含真实记录 ID、修改前后字段、依据和跳过原因；输出不得额外复制不必要的私人正文。
- 验收：零写入；缺精确来源的记录跳过；不以 LLM 补造事实；重复运行清单稳定；不能借历史修复批量把旧聊天重新解释为长期偏好。

### L28 — 小批回写与可恢复执行

- [x] 已完成本地条件撤销和恢复实现及虚构数据验收：仅允许一个预检仍有效的 `APPROVED → REVOKED`；哈希、scope、source 或状态变化即零写入；写入前创建不可重用备份目录，写后读回校验，并可在 after hash 一致时从 before 快照恢复。
- [ ] **真实执行 BLOCKED：没有 L27 的逐条 dry-run 清单，也没有 D10 写入授权。** 依赖 L27，且具体变更清单与 D10 写入授权已明确。
- 做什么：先备份并实际验证可恢复，再用最小批准批次验证迁移；记录检查点和每条前置版本，数据变化后跳过冲突，不能覆盖新写入。
- 验收：中断续跑无重复写入；失败可恢复；计数与逐条结果一致；小批验收后才扩到批准范围。大规模历史修复是单独数据操作，不随源码部署自动执行。

### L29 — 本地运行、灰度与关闭验证

- [x] 本地完整验收完成；灰度和发布仍需单独部署授权。分成三个独立子卡：本地完整验收；经部署授权后单一测试范围灰度；经扩大范围授权后发布。
- 做什么：只启用已验收且规则已冻结的参数，记录配置版本、可解释原因、拒绝/冲突/过期计数和必要性能指标。
- 验收：真实入站→持久化→下次请求/决策消费者闭环可观察；总开关关闭立即停止新的适应影响；旧候选不因上线自动批准；错误时可以恢复配置和已验证代码版本。
- 交付：明确哪些已写代码、通过本地测试、真实平台验证、生产开启。未运行的检查写“未验证”。

### 2026-09-08 第七批 / D10 执行记录

```text
状态：L26 已验收；L27、L28 BLOCKED；L29 本地验收完成，灰度/生产未验证。
授权来源：维护者“完成第七批l26-l29并整理整个项目”。
```

- **L26。** 已有 `ResponsePreferenceRecord`、精确 `ResponsePreferenceScope`、来源、生命周期、KV 读回、撤销与锁已由回复顺序、回复长度、历史检索提示和 L22 熟悉度复用。它们的证据和消费者仍分别受各卡合同限制；没有为“通用学习”再抽象 manager、规则 VM、第二份存储或分数系统。
- **L27 / D10。** 现有 `legacy_migration` 是 v2 架构兼容迁移，不是有证据的 Iris 历史修复工具：它没有本卡所需的逐条目标记录、修改前后字段和 source evidence。为避免它绕开 D10，插件启动不再隐式执行该迁移。已在虚构数据中复验现有检测器的零写入路径，以及旧迁移器的复制备份、幂等短路、单项故障隔离和备份失败中止；没有读取任何真实历史消息、KV、数据库或配置。没有实际目标记录，所以不能生成符合 L27 要求的真实变更清单。
- **L28。** 没有把旧迁移器重新接到启动或部署，也没有以测试样例冒充小批生产回写。L28 需要先收到 L27 输出的逐条清单、每条前置版本、具体备份位置和明确写入授权；在这些条件满足前保持 BLOCKED，不能声称已具备中断续跑、逐条冲突跳过或恢复证明。
- **L29。** 本地默认关闭了隐式历史迁移；现有 `profile.enable` 不可用时，ProfileStorage、受控偏好读取与请求提示均 fail-closed，已保存记录不删除但不再影响新请求，新的候选也不能写入。Persona 演化、学习模块和语义评估等敏感路径的用户可见默认开关仍是关闭或 shadow。灰度、真实入站重放、真实关闭切换、Provider、KV 多进程与生产配置均未执行。
- **本地验证。** `tests/legacy_migration tests/profile/test_response_preferences.py tests/profile/test_storage.py tests/core/test_llm_request_hook.py tests/cognitive/test_shadow_runtime.py`：`177 passed, 1 skipped, 1 warning`。覆盖旧迁移启动默认关闭、检测器零数据、备份/失败中止/幂等、批准偏好关闭后不再影响请求，以及 shadow 不改变 Host 行为。
- **整个项目整理。** 当前交付边界已集中在项目 TODO 与本清单：L01–L25 为源码和虚构 fixture 的本地验收；L26 无需重构；L27–L28 受 D10 阻塞；L29 仅本地；所有真实平台、灰度、生产开启、历史回写、提交、推送和部署均为未执行状态。

### 2026-09-08 D10/L28 条件执行实现记录

- **已实现但未接入运行时。** `ProfileStorage` 增加局限于 `response_style_preference:v1` 的历史撤销 dry-run、条件执行和恢复入口；它们不是通用迁移框架，不注册为聊天命令，不由请求 Hook、启动或 scheduler 调用。dry-run 需要现存 record 的精确 candidate ID、PRIVATE scope 和 source；只有状态为活动 `APPROVED` 才返回计划，并以 record/payload canonical SHA-256 作为前置版本。
- **最小写入。** 条件执行要求非空授权 ID、绝对且未使用的备份目录，以及执行瞬间仍完全匹配的哈希、scope、source 和活动状态。唯一允许字段变动为 `APPROVED → REVOKED`、`revoked_by`、`revoked_at`；冲突、缺记录、失效或错误均不写入。备份保存 before payload 和私有 manifest；写后严格读回；恢复只在 current payload 仍等于该次 after hash 时写回 before，否则 `skipped_conflict`。
- **本地验证。** 虚构 KV 覆盖 dry-run 零写入、source/scope 不匹配零写入、条件撤销、备份落盘、读回、实际恢复，以及 dry-run 后记录改变时的冲突跳过。没有读取真实记录，也没有生成真实 D10 清单或调用该入口。

## 推荐执行顺序

第一段交付 L01–L08：自然语言明确要求可以成为可审阅候选，避免重复实现旧闭环。

第二段交付 L09–L13：有来源的反馈能成为可撤销行为偏好，真正完成一个最小学习闭环。

第三段按依赖并行规划：L14–L16 做 Episode 自动结束；L17–L20 扩展工具和参与策略；L21–L25 处理关系、情绪以及合同变更。L26–L29 在需要时实施。自动学习并不要求先修复全部旧历史。

## 每张卡的进度模板

```text
卡号：
状态：未开始 / 进行中 / 部分完成 / 本地验收完成 / BLOCKED
本轮唯一目标：
依赖决策与实际授权来源：
实际读取入口与调用者：
修改文件与用途：
输入 → 预期 → 实测：
测试命令与结果：
未验证：
BLOCKED 的具体规则缺口：
下一张可执行卡：
```

## 可以直接发给 Luna 的指令

> 请执行 `bot/projects/xiaotianwen_memory_evolution_memo/luna_learning_todo.md` 的 L01。先读该文件的执行规则、项目当前 Todo.md 相关记录和适用 AGENTS.md，检查 Git 状态。只验收和补齐已有回复偏好闭环，复用现有代码、存储、命令和请求 Hook。使用虚构数据测试批准前后、跨 scope 隔离、撤销、过期和当前明确要求覆盖。已有实现通过验收就记录无需改动，不重复建设。不要自行解冻后续学习、Persona、情绪或关系边界，不修改生产配置，不提交、推送或部署。完成后更新本卡进度，报告具体效果、测试结果和未验证项，然后停止。

下一轮把 L01 换为下一张依赖满足的卡。不要一次要求执行整份文件。

## 2026-09-08 R01–R12 复验与收口

本轮按 R01 至 R12 顺序复核已有实现，只修复可以用虚构数据稳定复现的缺口。没有读取或写入真实历史记录，没有修改生产配置，也没有提交、推送或部署。R07、R08、R10、R11 涉及此前明确冻结的长期身份、关系、行为先验或 Affect 边界；本轮没有自动解冻。

### R01 — L28 条件回写与恢复可靠性

状态：本地验收完成。

具体缺口：KV 已成功撤销后若写 `after.sha256` 失败，旧代码会误报 `write_failed`；恢复没有验证 before payload 和 manifest 的哈希绑定。

实际改动：`iris_memory/profile/storage.py` 的维护执行要求后端 `compare_and_swap_kv_data`。manifest 绑定 exact scope/source、目标 record、before/after payload hash；提交后读回或末尾标记失败返回 `committed_unverified` 并保留后置 hash/备份目录。恢复验证 manifest、before hash、current after hash 后也走条件写。没有接入命令、Hook、scheduler 或生产配置。

验证：`tests/profile/test_response_preferences.py`：`43 passed, 1 warning`。覆盖撤销/恢复、CAS 冲突、损坏备份和“提交成功、末尾标记失败”。

未验证：AstrBot 实际 KV 尚未提供原子 CAS，真实维护执行会安全返回 `conditional_write_unavailable`。

下一张卡：R02。

### R02 — 真实维护写入边界

状态：部分完成。

实际改动：无需新增不安全适配器。当前 `Star` KV 协议只有 get/put/delete；用进程锁冒充跨进程事务会有覆盖风险，因此缺 CAS 时零写入退出。

验证：R01 虚构 CAS 冲突和缺能力 fail-closed 路径通过。

未验证：需确认 AstrBot 后端是否有事务/CAS，或由后端提供仅限单条维护的原子 API。

下一张卡：R03。

### R03 — Persona 发布测试前提

状态：本地验收完成。

具体缺口：revision 测试仍假定 manual `run_job` 自动发布，和 L24“只产生 candidate、显式 approve 才发布”冲突。

实际改动：`tests/persona_evolution/test_revision_ops.py` 的版本、冲突、导出夹具在每个候选后调用既有 `approve_revision()`；没有恢复自动 Persona 发布。

验证：`tests/persona_evolution/test_revision_ops.py`：`25 passed, 1 warning`；此前 7 个失败消失。

未验证：真实 PersonaManager/Provider 的人工批准体验。

下一张卡：R04。

### R04 — 反馈证据重放与失效

状态：部分完成，保持契约冻结。

具体缺口：观察器已用 exact inbound/reply-link/Host 链去重，聚合也能处理 revoked/conflicted 输入；但原始明确反馈命中、可信 scope 和权威时间只在进程内，P2r0 archive 不保存这些派生观察字段，重启后不能猜回。

实际改动：无需改动。现有 capture→archive 真实接线保留，不能伪造持久化重放。

验证：`tests/cognitive/test_p2r0_archive_wiring.py tests/cognitive/test_reply_link_capture.py tests/cognitive/test_response_preference_feedback.py tests/cognitive/test_p2r1_explicit_correction_rule.py`：`85 passed, 1 skipped, 1 warning`。

未验证：需要批准一个不存正文、只存 exact chain ID/private scope/权威 UTC 时间/`ACTIVE|REVOKED|CONFLICTED` 的 append-only feedback observation 契约，才可实现跨重启 replay 与失效。

下一张卡：R05。

### R05 — 隔离 AstrBot 组合链

状态：本地验收完成，无需改动。

实际读取入口与调用者：`main.py` 将同一 `ResponseLengthFeedbackReviewObserverV1` 交给 P2r0 capture 和 archive service；capture 先落事实再观察，archive 持久化后通知观察器，completion coordinator 复用同一 Review/P2/P2r0 owner。

验证：R04 的 85 项组合回归。

未验证：没有真实 AstrBot 平台事件，不能证明所有 adapter 的 scope/source 可重放，也不能证明 Provider 遵循表达提示。

下一张卡：R06。

### R06 — 开关与生命周期

状态：本地验收完成，无需改动。

实际读取入口与调用者：`ProfileStorage.initialize()` 用 `profile.enable` 设置可用性，`shutdown()` 复位；请求 Hook 在组件不可用、读取失败、无记录、撤销或本轮明确详细要求时均不注入，关闭不会删除记录。

验证：`tests/profile/test_storage.py tests/profile/test_storage_persona.py tests/profile/test_response_preferences.py tests/core/test_llm_request_hook.py` 的相关本轮回归通过（偏好/Hook 组 `84 passed, 1 warning`）。

未验证：没有改真实配置或重启生产插件。

下一张卡：R07。

### R07 — 身份持久化

状态：保持冻结，无需改动。

具体缺口：`EntityRegistry` 只拥有进程内的确认身份/alias；没有持久化 schema、人工确认写入口、冲突裁决、撤销语义或真实记录授权。保持 UID-first 和缺失 identity fail-closed，不将姓名或模糊文本固化。

验证：`tests/cognitive/test_identity_and_perspective.py` 已包含在本轮 `46 passed, 1 warning` 组合回归。

下一张卡：R08。

### R08 — Situation 只读投影

状态：保持冻结，无需改动。

实际读取入口与调用者：`SituationFull` 继续为 affect、relationship、behavioral prior、Persona 输出空只读映射；不从 legacy `favorability`、情绪文本或交互次数推断填值。

验证：`tests/cognitive/test_p07_repairs.py tests/cognitive/test_shadow_runtime.py` 已包含在本轮 46 项组合回归。

未验证：各 owner 的版本化只读 API 与失效语义尚未定义。

下一张卡：R09。

### R09 — 熟悉度表达消费者

状态：本地验收完成。

具体缺口：L22 可保存、批准、撤销、过期 `relationship_familiarity=FAMILIAR`，但 formatter 忽略该参数，用户看不到效果。

实际改动：`format_response_preferences()` 在既有单一受控块中渲染熟悉日常语气，并禁止假定共同经历或声称亲属、恋爱等未明确关系；`llm_request_hook.py` 的受控块清理规则同步扩展，重复预处理仍仅保留一个 block。不改变工具、是否回复、时机、权限、Affect 或 Persona。

验证：`tests/profile/test_response_preferences.py tests/core/test_llm_request_hook.py`：`84 passed, 1 warning`；覆盖批准后、跨 scope、撤销、过期、详细要求覆盖和重复 Hook。

未验证：真实 Provider 语气遵循和线上体验。

下一张卡：R10。

### R10 — 最小长期行为策略消费者

状态：保持冻结，无需改动。

已有 L18 的只读检索提示和 L20 群级无邀请插话开关各有独立 owner；没有把回复长度、熟悉度、纠正或 Review 转为通用 `BehavioralPrior`，也没有扩张到“是否/何时回复”的学习。

下一张卡：R11。

### R11 — Affect 派生视图

状态：保持冻结，无需改动。

`astrbot_plugin_affection` 继续独占 current-affect；Iris 不读写、迁移或同步其 JSON，也不会让负面反馈改情绪或关系。需要 Affect owner 的版本化、脱敏、只读 API 后才可讨论投影；生产加载状态未知。

下一张卡：R12。

### R12 — 灰度、打包与最终授权

状态：本地准备完成，真实动作待统一授权。

验证：本轮关键组分别为 R01 `43 passed`、R03 `25 passed`、R05 `85 passed, 1 skipped`、R06/R09 `84 passed`、身份/Situation `46 passed`（均有 1 个已有 warning）。

未验证：真实 KV/平台/Provider/生产加载、真实历史回写和灰度未执行。

### 最后统一授权清单（推荐值）

1. **R02：** 只读确认 AstrBot KV 是否支持事务/CAS；若否，在非生产实例增加仅限 `response_style_preference:v1` 单条撤销/恢复的后端原子 API，不能用 get/put 替代。
2. **R04：** 在现有 P2r0 append-only owner 下增加 `response_length_feedback_observation:v1`，只存四段 exact chain ID、完整 private scope、权威 UTC 时间、`ACTIVE|REVOKED|CONFLICTED`、schema/version；不存正文、不自动建偏好或发布行为。先做虚构重启 replay/失效测试。
3. **R05/R06：** 用虚构账号和消息在隔离 AstrBot 实例演练 inbound→capture→archive→review→consolidate；不连接生产账号、不发真实群、不写生产 KV。
4. **R07/R08/R10/R11：** 推荐继续冻结。若要解冻，必须分别先批准唯一 owner、字段/schema、来源、scope、人工写入/撤销、过期、冲突、重启和只读消费者定义，不合并为通用学习框架。
5. **L28/D10：** 先提供允许读取范围、目标记录 ID、每条字段前后值与精确证据、前置版本、备份位置和恢复验证。推荐首批仅 `response_style_preference:v1` 的 1 条 `APPROVED→REVOKED`，备份目录为插件扫描目录外的 `/home/developer/xiaotianwen/backups/iris-l28/<authorization-id>/`；R02 原子能力完成后才可写。
6. **R12：** 先确认生产实例插件路径与配置快照，再在一个明确 private scope 灰度观察撤销、过期、Hook 注入和 Provider 输出；保留回滚。提交、推送、部署另行执行。


## 2026-09-08 GitHub 收口补充（覆盖旧状态概览）

授权：维护者先批准 R01–R12 推荐范围，随后要求跳过测试轮次、直接上线回复偏好；本轮明确要求对照备忘录补齐缺口、整理文件并同步 GitHub。R07/R08/R10/R11 继续冻结，真实历史回写仍未获授权。

- R04：补齐观察持久化源码与 runtime observer 接线。沿用同一个 observer，新增无正文的 `response_length_feedback_observation:v1` append-only JSONL；记录可信来源事件/入站事实 ID、PRIVATE scope、权威 UTC 时间及状态。恢复后必须重新与权威 P2r0 archive 建立完整精确链，不能由日志猜回原文。显式失效 API 要求现存完整链，撤销/冲突不会被 ACTIVE 重放覆盖。人工 consolidate 仍只创建 PENDING，不自动批准。
- R04 故障边界：逐条 SHA-256、fsync、跨进程排他锁目录；损坏尾部、未知字段、并发占锁或写入故障关闭该 observer 的巩固能力，不静默改用内存成功。崩溃残留锁须停用相关实例后由维护者检查恢复，不能自动抢锁。没有声称跨主机或网络文件系统事务语义。
- R02：只读核验实际 AstrBot `PluginKVStoreMixin`，仅有 get/put/delete，无 CAS。L28 继续 `conditional_write_unavailable` 零写入；不以插件锁冒充权威后端原子写。新增后端 API 仍是单独的 AstrBot 核心工作，不在插件中绕过 Host 缓存直写数据库。
- L27：授权范围内只读 inventory 已完成，目标 namespace 有 1 条 APPROVED 记录。未输出真实用户 scope、candidate ID 或正文到公共仓库，未生成授权写入清单。
- L29/R12：生产已部署五文件的回复偏好补丁并重启，Iris 同步加载及异步初始化成功，WebUI HTTP 200；本轮 R04 持久化及其他 GitHub 源码不等于全部已部署。五文件 manifest 见本目录 production-release-20260908.json。
- 验证：按维护者要求不运行 pytest 或真实消息演练；新增重启、损坏日志和占锁场景测试代码供后续运行，本轮只做 Python 语法、静态检查与 Git diff 检查。源码补齐不标记为测试通过。

当前导航和完整覆盖矩阵以本目录 README.md 为准。旧逐日记录作为历史保留，不再将旧 BLOCKED 或旧测试计数当作当前状态。


### R04 管理入口补齐

复用 ADMIN iris_mem preference 新增 feedback_status / feedback_revoke / feedback_conflict，按绑定精确链、scope 和 UTC 时间的稳定观察 ID 操作。修复失效记录重放绑定及清锁失败误报；保留人工巩固和批准。仅语法/静态检查，未跑测试、未部署；Host 自动失效事件和 CAS 仍未实现，冻结项不变。

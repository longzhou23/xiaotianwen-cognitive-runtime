# 记忆演化：当前交付与剩余工作

更新时间：2026-09-08。本目录是备忘录与执行卡的权威位置。原 `bot/projects/xiaotianwen_memory_evolution_memo` 保留跳转入口，避免多份文档继续漂移。

## 阅读顺序

1. 本页：当前状态、缺口及下一步。
2. [执行卡与冻结决定](luna_learning_todo.md)：L01–L29、D01–D10、R01–R12 的历史和最新补充。
3. [原始备忘录](xiaotianwen_memory_evolution_memo_v2.md)：产品目标，不等同于交付声明。
4. [架构草案](xiaotianwen_cognitive_runtime_architecture_draft_v0.1.md)：设计背景，后续冻结决定优先。
5. [项目 Todo](../../Todo.md)：全仓库进度。

## 对照原始备忘录

| 章节/目标 | 已有交付 | 剩余边界与可执行下一步 |
|---|---|---|
| 0–1、8、33、34、36：认知运行架构 | Iris/Host/Orchestrator 分工、规范对象、capture/archive/Review 组合入口 | 真实平台链不能用本地 fixture 代替；后续按平台做完整 scope 接入记录 |
| 2、6：唯一 Persona / SELF | AstrBot Persona 单一权威；身份 SELF 解析；Persona 候选后显式批准 | 不自动发布 Persona；生产本轮带入了禁止 auto Job 自动发布的代码 |
| 3–5、7：Entity、alias、共指与主体视角 | UID 优先、歧义 fail-closed、SELF/OTHER/UNKNOWN 投影 | R07 冻结：长期身份 registry 的 owner/schema/撤销裁决尚未批准；不得以昵称补造 |
| 9–15：状态、关系、情绪、多时间尺度 | 明确私聊 FAMILIAR 候选、7天人工批准；affection 独占 Affect | R11 继续冻结情绪同步；不新增信任、亲密度或隐式关系推断 |
| 16、24、25、30、31：BehavioralPrior / 长期学习 | 受控回复偏好记录、明确纠正门槛、人工巩固、scope/期限/撤销 | R04 本轮补齐 durable observation 源码；通用 BehavioralPrior、自动发布时间和奖励学习仍冻结 |
| 17、32：Episode/Outcome/Review | 生命周期、完成协调、精确链事实、复盘职责已有实现 | 真实 Host/平台完整链仍未演练；不能以回复数量当奖励，也不补造历史证据 |
| 18：Situation | 保留只读空投影 | R08 冻结；需先批准可读取状态字段和有效期，不从 legacy 字段推断长期状态 |
| 19–23：Silence/Trigger/Decision/Execution | 现有 Host 路径；管理员群级插话抑制；工具提示按批准 scope 消费 | 全部平台真实行为未验证；不启用通用“是否/何时回复”学习 |
| 26–29：Reinterpretation、Canonical/Derived、结构演化 | 原始事实与派生解释分离；已有 L1–L3 检索路径 | 大规模重解释、图拓扑自演化和历史重写未实现；需要独立设计和数据清单，不能作为上线顺带迁移 |
| 35：关键体验验证 | 既有本地反例/闭环测试代码，新增 R04 故障场景代码 | 本轮按用户要求不跑测试；真实 Provider 遵循和用户满意度未验证 |
| 37–41：研究问题与长期方向 | 已有冻结边界和分批执行卡 | 保留研究项，不将“有接口”写成“备忘录全部完成” |

## 本轮新增的持久化闭环

`AstrBot inbound → 既有 capture 验证直接反馈/scope/权威时间 → 同一 observer 的无正文观察日志 → 既有 P2r0 archive 精确 join → D02 review-only 聚合 → 管理员 consolidate → ProfileStorage PENDING → 显式 approve → 请求 Hook`。

日志位于插件数据目录 `cognitive/response_length_feedback_observation.v1.jsonl`，不在源码目录。只保存 schema、exact source/inbound ID、scope、UTC 时间和生命周期；失效记录另外携带完整四元组。不会保存消息正文或生成另一套 ReviewEvidence。每次巩固前重新加载日志并用 archive 重建精确链。缺 archive 的 pending 记录不能独立影响偏好。

`invalidate_observation(item, state)` 是现有 owner 的显式 API，只接受已经存在的精确观察，状态仅 REVOKED/CONFLICTED。管理员现可通过既有 `iris_mem preference` 路由显式查看、撤销或标记冲突；没有模型写入者。Host 平台自动撤销事件的接入仍需由真实事件来源提供，不能用“疑似冲突”文本调用它。已批准偏好的撤销仍使用既有管理员命令，不由观察日志直接改写。

损坏或不完整日志不会自动截断/删除；占锁、读写错误会停止巩固。维护时先停止所有共享该日志的实例，备份日志及残留 `.lock` 目录，再判断已完整且校验通过的记录边界；没有恢复核验前不要恢复巩固。该恢复流程本轮未演练。

## 实际生产与 GitHub 的区别

2026-09-08 09:20（UTC+8）已部署一个五文件补丁：`main.py` 的明确熟悉度候选与禁用启动迁移、请求 Hook 的单一受控块替换、回复偏好表示、ProfileStorage 维护保护、Persona 手动发布限制。生产已有 profile 开关，未修改配置、未批准旧候选、未历史回写。

Iris 异步初始化完成，容器运行且 WebUI HTTP 200。FAISS 的 AVX2 变体缺失后成功加载普通版本，并非 Iris 启动失败。相关源码 SHA-256 见 [生产补丁清单](production-release-20260908.json)。服务器的定向备份与 rollback.sh 已生成，但没有执行回退演练。

本次 GitHub 同步保存完整的备忘录相关工作树（包括此前未提交的实现），不代表生产已加载这些全部改动。尤其本轮 R04 日志接线尚未部署、未测试。后续标准部署可能覆盖此前五文件运行时补丁，部署时应以具体 commit 和 release manifest 对照。

## 仍需处理的工作

- R02 / L28：真实后端无 CAS。由 AstrBot 核心提供同时覆盖缓存、事务与读回的限定原子 API，再连接已有 `compare_and_swap_kv_data`；在此之前维护入口零写入。不要在插件内绕过 Host 直写 SQLite。
- R04：源码接线已补齐，新增重启/损坏/占锁测试未运行；跨重启完整组合链和显式失效来源仍未在真实运行中验证。
- L27：真实只读 inventory 已完成，范围内有一条 APPROVED；目标细节不进入公共 GitHub。没有字段前后值、证据/前置 hash/备份计划和单条授权时不执行 L28。
- L29：仅五文件生产补丁已通过启动检查；全源码版本部署及真实消息行为另记，不混用旧结果。
- R07/R08/R10/R11：继续冻结。解冻必须逐项明确 owner、字段、来源、scope、冲突、撤销和消费者合同。
- 结构自演化与历史重解释：保持独立后续设计，不引入通用学习框架或自动历史迁移。

## 验证口径

本轮没有运行 pytest、真实消息发送、Provider 样例或恢复演练。仅执行 Python 语法检查、适用静态检查、文档链接检查和 Git diff 检查。历史卡中的测试数字仅属于其记录日期，不能算作本轮新增代码的验证。

本轮构建结果：71 个相关 Python 文件语法检查通过；新增 R04 文件、main.py 和反馈测试文件 Ruff F 检查通过；`npm run build:check` 的 Vue 类型检查及 Vite 生产构建通过，已同步打包页面。构建有大于 600 kB 的现有图表 vendor chunk 提示，不影响构建完成。新增和历史测试均未在本轮运行。


## R04 管理闭环补充

管理员沿用 `iris_mem` 的 ADMIN 权限入口：

- `iris_mem preference feedback_status`：列出已完成精确 archive 的观察 ID、scope、UTC 时间和状态，不显示正文。
- `iris_mem preference feedback_revoke <observation_id>`：把指定观察标为 REVOKED。
- `iris_mem preference feedback_conflict <observation_id>`：把指定观察标为 CONFLICTED。
- `iris_mem preference consolidate_length`：沿用 D02 门槛，失效观察不再参与新巩固；只生成 PENDING。

观察 ID 同时绑定完整四元组、scope 与权威时间，状态变化不会改变 ID。操作前刷新日志和 archive，写入后读回实际状态；CONFLICTED 不会被后来的 REVOKED 降级。已批准偏好是独立的权威记录，仍须通过原 `revoke <candidate_id>` 显式撤销。命令不会自动批准、改 Persona 或改生产配置。

本轮同时修复日志重放未校验失效记录与原始 scope/时间一致的问题，以及释放日志锁失败仍可能回报写入成功的问题。缺 archive、日志故障或读回异常均不回报成功。新管理命令尚未部署，按既有要求未跑测试套件。该补充完成可操作的管理员闭环源码，不代表所有冻结研究目标完成。

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
| 3–5、7：Entity、alias、共指与主体视角 | UID 优先、歧义 fail-closed、SELF/OTHER/UNKNOWN 投影 | R07 已解冻：Identity 单一 owner 持久化；alias 仅人工确认并可按 claim ID 撤销，不以昵称自动补造 |
| 9–15：状态、关系、情绪、多时间尺度 | 明确私聊 FAMILIAR 候选、7天人工批准；affection 独占 Affect | R11 已解冻为 60 秒脱敏只读快照；不新增信任、亲密度或隐式关系推断 |
| 16、24、25、30、31：BehavioralPrior / 长期学习 | 受控回复偏好记录、明确纠正门槛、人工巩固、scope/期限/撤销 | R10 已将人工批准偏好投影为最小 prior；自动发布时间、奖励学习和权限扩张仍关闭 |
| 17、32：Episode/Outcome/Review | 生命周期、完成协调、精确链事实、复盘职责已有实现 | 真实 Host/平台完整链仍未演练；不能以回复数量当奖励，也不补造历史证据 |
| 18：Situation | Trigger YES 后冻结 owner 提供的版本化只读投影 | R08 已解冻；缺失、过期、scope 不符均为空，不从 legacy 字段推断长期状态 |
| 19–23：Silence/Trigger/Decision/Execution | 现有 Host 路径；管理员群级插话抑制；工具提示按批准 scope 消费 | 全部平台真实行为未验证；不启用通用“是否/何时回复”学习 |
| 26–29：Reinterpretation、Canonical/Derived、结构演化 | 原始事实与派生解释分离；已有 L1–L3 检索路径 | 大规模重解释、图拓扑自演化和历史重写未实现；需要独立设计和数据清单，不能作为上线顺带迁移 |
| 35：关键体验验证 | R04 重启、损坏、占锁、精确链和 archive 组合测试已运行 | 68 passed；真实 Provider 遵循和用户满意度仍需真实消息观察 |
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

- R02 / L28：AstrBot 核心限定 CAS 已测试并部署，覆盖缓存、FIFO、SQLite 事务、竞争和读回；Iris 继续只调用 Host 的 `compare_and_swap_kv_data`，不直写 SQLite。CAS 可用不等于 L28 获得数据写入授权。
- R04：源码接线和重启/损坏/占锁测试已完成，68 项组合测试通过；生产重启后 capture/archive 与异步初始化正常。真实用户反馈触发的完整组合链和显式失效动作仍需自然运行观察。
- L27：真实只读 inventory 已完成，范围内有一条 APPROVED；目标细节不进入公共 GitHub。没有字段前后值、证据/前置 hash/备份计划和单条授权时不执行 L28。
- L29：旧五文件启动结果作为历史保留；全源码 Iris v3.0.4、affection v1.2 和 CAS2 AstrBot 镜像已有各自部署记录。真实消息行为仍单列为未验证，不用 HTTP 200 代替。
- R07/R08/R10/R11：维护者已明确解冻，按 Identity/ProfileStorage/affection 既有 owner 分别接线；没有合并为通用学习框架。
- 结构自演化与历史重解释：已形成[独立后续设计](structural-evolution-and-history-reinterpretation.md)，不接入通用学习框架或自动历史迁移。

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


## 2026-09-08 R04 生产接线交付

维护者“完成剩余部分”后，沿用此前回复偏好部署授权，将 R04 的 observer、capture/archive 回调、管理员反馈状态/撤销/冲突命令作为五文件定向补丁部署。未把整个工作树或其他插件覆盖到生产。main.py 仅替换 capture/archive 初始化方法并接入 observer 引用，其他运行逻辑保留生产版本。

生产启动时间 2026-09-08T01:45:04Z。启动日志确认 P2r0 factual capture enabled、historical archive wiring enabled、Iris 异步初始化完成；WebUI HTTP 200。补丁逐文件 before/after SHA-256 见 [R04 生产清单](production-r04-release-20260908.json)。服务器已创建 iris-r04-20260908T014503Z 定向代码备份、配置快照及 rollback.sh，未执行回退演练。

R04 现在从“源码接线、未部署”推进到“生产代码已加载”。新反馈可沿 capture/archive 进入无正文日志与人工管理路径；没有将旧 archive 推断成历史反馈。运行过程中新增合法观察可能正常写入自身日志，但没有执行历史维护、修改配置或自动批准。按用户要求未运行测试套件、真实消息样例或主动故障演练，因此管理员命令实测、跨重启精确链重放、并发恢复和 Provider 效果仍未验证。

本节覆盖前文“R04 尚未部署”的历史状态。R02/CAS、真实历史单条授权、Host 自动撤销事件及 R07/R08/R10/R11 的冻结边界不因部署改变。

## 2026-09-08 R07/R08/R10/R11 解冻与生产接线

维护者明确要求解冻并完成四卡。公共实现以 `0a1fedc` 提交，身份文件权限收紧以 `c56204b` 补充；生产完整 Iris 插件同步到同一源码基线，affection owner 的脱敏快照实现同步到私有实例仓库 `1f7e555`。

生产路径为 `/home/developer/xiaotianwen/runtime/astrobot/data/plugins/`。首次仅覆盖新增文件时发现生产 Iris 仍是旧的五文件热补丁基线，出现 `ShadowStrategyProposal` 导入失败；随后在插件扫描目录外完整备份并从公共仓库同一提交覆盖整套 Iris 源码。最终 AstrBot HTTP 200，affection v1.2 与 Iris v3.0.4 均加载，Iris 异步初始化完成；Identity 信封存在 schema 与 checksum，权限为 `0600`。

备份：`/home/developer/xiaotianwen/backups/r07-r11-20260908T042805Z/` 保存最初定向文件，`/home/developer/xiaotianwen/backups/iris-full-before-20260908T042941Z/` 保存完整 Iris 目录，均带 SHA256SUMS。恢复时停容器、校验归档、解包回原插件目录、启动容器并复核插件加载与 HTTP 200。

本轮遵循维护者此前决定，没有运行 pytest 或真实消息验收。已验证源码编译、插件加载、身份持久化文件创建、权限和服务健康；尚未证明真实 Provider 对 BehavioralPrior 的表达遵循、每个平台的真实 scope、管理 API 实际操作、alias 冲突/撤销重启和 Affect 快照在真实 Trigger YES 请求中的可见性。


## R02 后端 CAS 开发补充

已在 AstrBot 源码中实现 BaseDatabase 可选接口、SQLite BEGIN IMMEDIATE 条件事务、SharedPreferences FIFO CAS 和 PluginKVStoreMixin 接口。限定 response_style_preference:v1；禁止预写缓存、缺记录不创建、冲突返回 False、成功在 commit 后返回。独立连接竞争、队列顺序、缓存读回及故障用例已补，按既有要求未执行。生产尚未安装，历史维护仍关闭。可应用源码补丁、基线哈希和限制见 [CAS 开发说明](../../deploy/astrbot/patches/response-preference-cas.md)。

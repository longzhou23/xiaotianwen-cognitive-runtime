# Identity Registry 离线重建

`deploy/maintenance/identity_rebuild.py` 是 Identity owner 之外的维护工具。它只生成候选快照，不创建第二个 registry，也不读取消息正文。候选构造和校验复用 `iris_memory.cognitive.identity.EntityRegistry` 的实体、claim、schema 和 checksum 合同。

## 输入边界

`plan` 需要一个当前 `iris.identity-registry.v1` 信封，以及零个或多个明确授权的 `iris.identity-rebuild-source.v1` JSON 文件。每个 source 必须包含：

- `authorization.authorized=true`、`scope=identity-rebuild` 和非空 `authorization_ref`；
- 只有 `entity`、`self_binding`、`alias` 三种结构化记录；
- 每条记录都有 `record_ref` 和 `provenance`（来源类型、来源引用、固定依据类别、证据引用）；
- 新用户实体只能由显式 `platform + platform_id` 创建；新 agent 不能由 `entity` 创建；
- alias 只有 `CONFIRMED` 且来自 `identity_export` 或 `manual_confirmed_claim`、依据为 `manual_confirmed_alias` 时才会进入候选；`POSSIBLE` 和其他来源会进入 skipped；
- SELF 只接受 `self_binding`，其 `entity_id` 必须等于当前 registry 的 `agent:xiaotianwen`，并带明确平台 UID。

维护工具默认从本仓库的 Iris 源码导入 `EntityRegistry`；在服务器上从临时维护路径执行时，可以用 `IRIS_PLUGIN_ROOT` 指向已部署的 Iris 插件源码目录。这个环境变量只改变代码导入位置，不改变身份数据路径或写入门禁。

Episode/Event、AstrBot 会话元数据、P2r0 archive 和语义 authority 都只能由受信任的导出器先转换为上述无正文结构化 export。工具不会从昵称、群名片、代词、消息相似度、最近发言者或模型输出补造身份；P2r0 的 reply-link 事实也不会被当作 alias 证据。

## 规划和私有输出

```bash
python3 deploy/maintenance/identity_rebuild.py plan \
  --current /private/runtime/astrobot/data/plugin_data/astrbot_plugin_iris_memory/cognitive/identity_registry.v1.json \
  --source /private/exports/identity-authorized.v1.json \
  --output-dir /private/maintenance/identity-rebuild-YYYYMMDD-HHMMSS
```

输出目录自动设为 `0700`，candidate 与 manifest 为 `0600`。candidate 是私有的完整身份信封；manifest 只记录 hash、计数、冲突/skipped 类别和 hash 化 provenance 引用。命令 stdout 只输出路径、sha256 和计数。`apply_blocked=true` 的计划只能用于人工审阅，不能直接写入。

硬冲突包括当前信封校验失败、同一 platform+UID 属于不同实体、实体数据冲突、SELF 绑定冲突、确认 alias 多目标、未知实体 alias，以及缺少显式 SELF bot binding。确认 alias 冲突会保留两条证据并继续由 EntityRegistry fail-closed 返回 unresolved；它不会任选一个目标。

## 写入和恢复门禁

执行前先停止 AstrBot，或者由 Identity owner 和维护工具共同持有约定的 owner lock。写入命令还必须给出当前目标的精确 sha256 和字面量 `CONFIRM`：

```bash
python3 deploy/maintenance/identity_rebuild.py apply \
  --target /private/runtime/astrobot/data/plugin_data/astrbot_plugin_iris_memory/cognitive/identity_registry.v1.json \
  --candidate /private/maintenance/identity-rebuild-.../identity_registry.candidate.v1.json \
  --manifest /private/maintenance/identity-rebuild-.../identity_rebuild.manifest.v1.json \
  --expected-sha256 '<read-current-hash>' \
  --owner-lock /private/runtime/.deploy/identity-owner.lock \
  --confirm CONFIRM
```

`apply` 强制读取同一 manifest，并核对 candidate hash、before hash 和 `apply_blocked=false`；因此冲突/skipped 清单未解决时，即使提供 `CONFIRM` 也不能写入。工具在同目录创建 `identity_registry.v1.json.backup.<UTC-timestamp>`（`0600`），重新检查 precondition，写同目录临时文件并 fsync，执行原子 replace，再 fsync 目录、读回 hash，并重新交给 `EntityRegistry` 校验。候选校验、备份、锁或 precondition 失败时目标不变；替换后的读回失败会用备份原子恢复并再次校验。恢复也要求精确的当前 hash、owner lock 和 `CONFIRM`：

```bash
python3 deploy/maintenance/identity_rebuild.py restore \
  --target /private/runtime/astrobot/data/plugin_data/astrbot_plugin_iris_memory/cognitive/identity_registry.v1.json \
  --backup /private/runtime/.../identity_registry.v1.json.backup.<UTC-timestamp> \
  --expected-sha256 '<hash-of-current-broken-or-new-target>' \
  --owner-lock /private/runtime/.deploy/identity-owner.lock \
  --confirm CONFIRM
```

恢复后重启插件并重新读取 registry，比较 target hash、实体/claim 计数和 `available` 状态；这一步属于运维验收，不能由一次成功的 replace 代替。工具自身的虚构测试覆盖稳定 UID、跨平台隔离、重名隔离、SELF、确认/未确认 alias、冲突、损坏/版本不匹配、dry-run 零写、precondition 零写、锁竞争、备份恢复和重启重放。真实平台 source export、跨进程 owner lock 协议和线上重启仍需独立验收。

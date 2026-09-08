<template>
  <section class="observatory">
    <v-card class="hero mb-3" variant="flat">
      <v-card-text class="py-5">
        <div class="d-flex align-start flex-wrap ga-3">
          <div>
            <div class="text-h5 font-weight-bold">小天文 Cognitive Observatory</div>
            <div class="text-body-2 text-medium-emphasis">{{ phaseTitle }} · Production Cognitive Runtime</div>
          </div>
          <v-spacer />
          <v-chip :color="statusColor(summary?.lifecycle?.status)" variant="flat" prepend-icon="mdi-timeline-check-outline">Lifecycle · {{ statusLabel(summary?.lifecycle?.status) }}</v-chip>
          <v-chip :color="statusColor(summary?.review?.status)" variant="tonal" prepend-icon="mdi-file-search-outline">Review · {{ statusLabel(summary?.review?.status) }}</v-chip>
          <v-chip :color="statusColor(summary?.promotion?.status)" variant="tonal" prepend-icon="mdi-gate">Promotion · {{ statusLabel(summary?.promotion?.status) }}</v-chip>
          <v-chip color="success" variant="tonal" prepend-icon="mdi-account-heart-outline">受控长期适应 · ENABLED</v-chip>
          <v-chip :color="p2bHeaderColor" variant="tonal" prepend-icon="mdi-flask-outline">{{ p2bHeaderLabel }}</v-chip>
        </div>
        <v-alert :color="summary?.promotion?.enabled ? 'info' : 'amber-darken-2'" variant="tonal" density="compact" class="mt-4 mb-0">
          <template v-if="summary?.promotion?.enabled">
            Review 与 Evidence promotion 已启用；当前没有 Finding 满足唯一允许的 EXPLICIT_CORRECTION_OF_EXACT_HOST_OUTPUT_V1 规则。
            <strong>Evidence = {{ summary?.review_evidence ?? '—' }}，不代表 promotion 已关闭。</strong>
          </template>
          <template v-else>
            Review promotion 当前不可用或已关闭；观测台只展示已持久化事实，不会自行推断状态。
          </template>
        </v-alert>
      </v-card-text>
    </v-card>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-row class="mb-1">
      <v-col v-for="card in summaryCards" :key="card.label" cols="6" sm="4" md="2">
        <v-card variant="flat" class="metric pa-3"><div class="text-caption text-medium-emphasis">{{ card.label }}</div><div class="text-h5 font-weight-bold">{{ card.value }}</div></v-card>
      </v-col>
    </v-row>

    <v-card v-if="summary?.available" variant="flat" class="panel pa-3 mb-3 pipeline-summary">
      <div class="d-flex align-center flex-wrap ga-2">
        <span class="section-label mb-0">Runtime pipeline</span>
        <v-chip size="small" :color="statusColor(summary.lifecycle?.status)">Lifecycle · {{ statusLabel(summary.lifecycle?.status) }}</v-chip>
        <v-chip size="small" :color="statusColor(summary.review?.status)">Review · {{ statusLabel(summary.review?.status) }}</v-chip>
        <v-chip size="small" :color="statusColor(summary.promotion?.status)">Promotion · {{ statusLabel(summary.promotion?.status) }}</v-chip>
        <v-chip size="small" color="success">受控长期适应 · ENABLED</v-chip>
        <v-chip size="small" :color="p2bHeaderColor">{{ p2bHeaderLabel }}</v-chip>
      </div>
      <div class="text-caption text-medium-emphasis mt-2">
         <span v-if="summary.review_store === 'UNAVAILABLE'">ReviewStore 当前不可用，计数不会以 0 代替。</span>
         <span v-else-if="summary.review?.status === 'DISABLED'">Review 当前未启用；不会把未运行误报成 0。</span>
         <span v-else>Review Runs / Findings 来自当前 production ReviewStore。</span>
         <span v-if="summary.review?.status === 'ENABLED' && summary.review_store === 'AVAILABLE'">Review 状态：{{ reviewStatusSummary }}。</span>
        <span v-if="summary.semantic_evaluator">Semantic evaluator：{{ summary.semantic_evaluator }}。</span>
        <span v-if="summary.promotion?.enabled">允许规则：{{ summary.promotion?.rules?.join(', ') || '无' }}。</span>
        <span v-else>Promotion 未启用。</span>
      </div>
    </v-card>

    <v-card v-if="summary?.adaptive_runtime" variant="flat" class="panel pa-4 mb-3 adaptive-panel">
      <div class="d-flex align-center flex-wrap ga-2 mb-3">
        <div><div class="section-label mb-0">长期适应运行态</div><div class="text-caption text-medium-emphasis">只显示接线状态和匿名计数，不显示消息、用户、scope 或候选 ID。</div></div>
        <v-spacer />
        <v-chip :color="summary.adaptive_runtime.history_write?.status === 'LOCKED' ? 'amber-darken-2' : 'success'" size="small" prepend-icon="mdi-lock-outline">历史维护 · {{ summary.adaptive_runtime.history_write?.status }}</v-chip>
      </div>
      <v-row dense>
        <v-col v-for="item in adaptiveCards" :key="item.label" cols="12" sm="6" lg="4">
          <v-card variant="outlined" class="adaptive-card pa-3">
            <div class="d-flex align-center ga-2"><v-icon :icon="item.icon" :color="item.ready ? 'success' : 'grey'" /><strong>{{ item.label }}</strong><v-spacer /><v-chip size="x-small" :color="item.ready ? 'success' : 'grey'">{{ item.ready ? '已接通' : '不可用' }}</v-chip></div>
            <div class="text-body-2 mt-2">{{ item.value }}</div><div class="text-caption text-medium-emphasis mt-1">{{ item.detail }}</div>
          </v-card>
        </v-col>
      </v-row>
      <v-alert color="amber-darken-2" variant="tonal" density="compact" class="mt-3 mb-0">L28 历史数据写入仍锁定；仅在精确单条授权后开放。日常请求中的已批准偏好、关系熟悉度、BehavioralPrior 和 Affect 只读投影可继续生效。</v-alert>
    </v-card>

    <v-card variant="flat" class="panel pa-4 mb-3 p2b-shadow-panel">
      <div class="d-flex align-center flex-wrap ga-2 mb-3">
        <div>
          <div class="section-label mb-0">P2b 影子观察</div>
          <div class="text-caption text-medium-emphasis">候选只在影子层评估，未经人工批准不会进入回复偏好。</div>
        </div>
        <v-spacer />
        <v-chip size="small" color="info" prepend-icon="mdi-eye-outline">模式 · {{ p2bShadow?.mode || '等待摘要' }}</v-chip>
        <v-chip size="small" :color="p2bShadow?.auto_approve === false ? 'success' : 'amber-darken-2'">自动批准 · {{ p2bFlagLabel(p2bShadow?.auto_approve) }}</v-chip>
        <v-chip size="small" :color="p2bShadow?.auto_publish === false ? 'success' : 'amber-darken-2'">自动发布 · {{ p2bFlagLabel(p2bShadow?.auto_publish) }}</v-chip>
      </div>

      <v-alert v-if="!p2bShadow" color="grey" variant="tonal" density="compact" class="mb-0">
        当前摘要尚未提供 <code>summary.p2b_shadow</code>；观察台不会用旧的 P1 计数猜测 P2b 状态。
      </v-alert>
      <template v-else>
        <v-row dense>
          <v-col cols="12" md="4">
            <v-card variant="outlined" class="p2b-overview-card pa-3 fill-height">
              <div class="section-label">候选状态</div>
              <div class="d-flex flex-wrap ga-2">
                <v-chip v-for="item in p2bStatusCards" :key="item.status" size="small" :color="item.color" variant="tonal">{{ item.label }} · {{ item.count }}</v-chip>
              </div>
            </v-card>
          </v-col>
          <v-col cols="12" md="4">
            <v-card variant="outlined" class="p2b-overview-card pa-3 fill-height">
              <div class="section-label">最近评估</div>
              <div class="text-h6">{{ p2bEvaluationTime }}</div>
              <div class="text-caption text-medium-emphasis mt-1">只记录评估时间和状态统计，不展示候选详情。</div>
            </v-card>
          </v-col>
          <v-col cols="12" md="4">
            <v-card variant="outlined" class="p2b-overview-card pa-3 fill-height">
              <div class="section-label">权限影响</div>
              <div class="text-h6 text-success">{{ p2bPermissionEffect }}</div>
              <div class="text-caption text-medium-emphasis mt-1">影子评估不能改变是否回复、回复时间、工具权限或人格。</div>
            </v-card>
          </v-col>
        </v-row>
        <v-card variant="tonal" color="blue-grey-darken-1" class="mt-3 pa-3">
          <div class="section-label">允许评估参数</div>
          <div class="d-flex flex-wrap ga-2">
            <v-chip v-for="parameter in p2bParameters" :key="parameter" size="small" color="info" variant="outlined">{{ parameter }}</v-chip>
            <span v-if="!p2bParameters.length" class="text-body-2 text-medium-emphasis">暂无参数</span>
          </div>
        </v-card>
        <v-alert color="success" variant="tonal" density="compact" class="mt-3 mb-0">当前为 SHADOW：可以生成和统计候选，但自动批准与自动发布必须保持关闭。</v-alert>
      </template>
    </v-card>

    <v-card v-if="!summary?.available" variant="flat" class="pa-7 text-center mb-3">
      <v-icon icon="mdi-database-off-outline" size="44" color="medium-emphasis" />
      <div class="text-h6 mt-2">EpisodeStore 尚未接入运行时</div>
      <div class="text-body-2 text-medium-emphasis mt-1">这不是数据错误。可使用下方内存 Demo 演示已冻结的 P1 观察与 Review 语义。</div>
    </v-card>

    <v-row>
      <v-col cols="12" lg="4">
        <v-card variant="flat" class="panel fill-height">
          <v-card-title class="d-flex align-center text-subtitle-1"><v-icon icon="mdi-view-list-outline" class="mr-2" />Episodes<v-spacer /><v-btn icon="mdi-refresh" variant="text" size="small" @click="loadAll" /></v-card-title>
          <v-card-text class="pt-0">
            <v-text-field v-model="query" label="搜索 Episode / Root / Ref" density="compact" hide-details clearable prepend-inner-icon="mdi-magnify" class="mb-2" @keyup.enter="loadEpisodes" />
            <v-btn-toggle v-model="state" density="compact" variant="tonal" class="state-toggle mb-3" @update:model-value="loadEpisodes"><v-btn value="ALL">ALL</v-btn><v-btn value="OPEN">OPEN</v-btn><v-btn value="SOFT_CLOSED">SOFT</v-btn><v-btn value="FINALIZED">FINALIZED</v-btn><v-btn value="INTERRUPTED">INTERRUPTED</v-btn></v-btn-toggle>
            <v-list v-if="episodes.length" density="compact" class="episode-list">
              <v-list-item v-for="episode in episodes" :key="episode.episode_id" :active="selectedId === episode.episode_id" @click="selectEpisode(episode.episode_id)">
                <template #prepend><v-icon :color="stateColor(episode.state)" icon="mdi-circle" size="10" /></template>
                <v-list-item-title class="text-body-2 text-truncate">{{ episode.episode_id }}</v-list-item-title>
                <v-list-item-subtitle v-if="viewMode === 'simple'">{{ episode.human?.lifecycle_label || episode.state }} · {{ episode.human?.interaction_turns ?? 0 }} 轮互动 · {{ episode.human?.host_outputs ?? 0 }} 次回复 · {{ episode.human?.outcomes ?? episode.outcome_count }} 个结果</v-list-item-subtitle>
                <v-list-item-subtitle v-else>{{ episode.state }} · {{ episode.event_count }} events · {{ episode.outcome_count }} outcomes</v-list-item-subtitle>
              </v-list-item>
            </v-list>
            <div v-else class="text-center text-body-2 text-medium-emphasis py-6">{{ loading ? '正在读取…' : 'No data yet' }}</div>
          </v-card-text>
        </v-card>

        <v-card variant="flat" class="panel mt-3">
          <v-card-title class="text-subtitle-1"><v-icon icon="mdi-flask-outline" class="mr-2" />Demo Cases <v-chip size="x-small" class="ml-2" color="info">IN-MEMORY ONLY</v-chip></v-card-title>
          <v-list density="compact"><v-list-item v-for="item in demos" :key="item.id" @click="selectDemo(item.id)"><v-list-item-title>{{ item.title }}</v-list-item-title><v-list-item-subtitle>{{ item.summary }}</v-list-item-subtitle></v-list-item></v-list>
        </v-card>
      </v-col>

      <v-col cols="12" lg="8">
        <v-card variant="flat" class="panel min-detail">
          <v-card-text v-if="!detail" class="py-16 text-center text-medium-emphasis"><v-icon size="48" icon="mdi-eye-outline" /><div class="mt-2">选择一个 Episode 或 Demo Case 查看不可变历史。</div></v-card-text>
          <template v-else>
            <v-card-title class="d-flex flex-wrap align-center ga-2"><span class="text-subtitle-1">{{ viewMode === 'simple' ? '当前互动' : detail.episode.episode_id }}</span><v-chip size="small" :color="stateColor(detail.episode.state)">{{ viewMode === 'simple' ? detail.human?.lifecycle_label : detail.episode.state }}</v-chip><v-chip v-if="isDemo" size="small" color="info">DEMO DATA</v-chip><v-spacer /><v-btn-toggle v-model="viewMode" density="compact" mandatory variant="tonal"><v-btn value="simple">简单视图</v-btn><v-btn value="engineering">工程视图</v-btn></v-btn-toggle><v-btn v-if="viewMode === 'engineering'" color="primary" variant="tonal" size="small" prepend-icon="mdi-play-circle-outline" :disabled="isDemo || !detail.episode.finalized_at" @click="preview">Preview Review</v-btn></v-card-title>
            <v-card-subtitle v-if="viewMode === 'engineering'">Root: {{ detail.episode.root_event_id }} · Started {{ formatTime(detail.episode.opened_at) }} · Finalized {{ formatTime(detail.episode.finalized_at) }}</v-card-subtitle>
            <v-card-text>
              <v-alert v-if="isDemo" color="info" variant="tonal" density="compact" class="mb-3">DEMO DATA 仅在本次请求内存中构造；不会进入真实 EpisodeStore、ReviewStore、Iris 或未来行为。</v-alert>
              <template v-if="viewMode === 'simple'">
                <v-row>
                  <v-col cols="12" md="7"><v-card variant="outlined" class="pa-4 human-card"><div class="section-label">这段互动</div><div class="text-h6">{{ detail.human?.lifecycle_label }}</div><div class="text-body-2 text-medium-emphasis mt-1">小天文正在把同一段连续互动整理为可审计历史。</div><v-row class="mt-2" dense><v-col cols="6" sm="3"><div class="human-metric">{{ detail.human?.interaction_turns }}</div><div class="text-caption">互动轮次</div></v-col><v-col cols="6" sm="3"><div class="human-metric">{{ detail.human?.host_outputs }}</div><div class="text-caption">实际回复</div></v-col><v-col cols="6" sm="3"><div class="human-metric">{{ detail.human?.dispatches }}</div><div class="text-caption">成功发送</div></v-col><v-col cols="6" sm="3"><div class="human-metric">{{ detail.human?.outcomes }}</div><div class="text-caption">观察结果</div></v-col></v-row></v-card></v-col>
                  <v-col cols="12" md="5"><v-card variant="tonal" color="teal-darken-1" class="pa-4"><div class="section-label">长期适应</div><div class="text-h6">受控能力已接通</div><div class="text-body-2 mt-1">已批准的私聊偏好、关系熟悉度与 BehavioralPrior 可进入请求；Affect 仅采用 affection 提供的短期有效视图。通用 P2b 自动学习仍关闭。</div><v-chip size="small" class="mt-3" color="success">限定范围运行中</v-chip></v-card></v-col>
                </v-row>
                <v-row class="mt-1">
                  <v-col cols="12" md="6"><v-card variant="outlined" class="pa-4 human-card"><div class="section-label">认知判断</div><div v-if="detail.human?.no_intent" class="text-body-1">{{ detail.human.no_intent }} 次未形成明确主动发言意图</div><div v-else class="text-body-1">已记录 {{ detail.human?.cognitive_decisions || 0 }} 次认知判断</div><div class="text-caption text-medium-emphasis mt-2">这是只读的历史观察；它不拥有最终发送控制权，也不会改变未来行为。</div></v-card></v-col>
                  <v-col cols="12" md="6"><v-card variant="outlined" class="pa-4 human-card"><div class="section-label">实际 Host 行为</div><div class="text-body-1">仍生成 {{ detail.human?.host_outputs }} 次回复，并发送 {{ detail.human?.dispatches }} 次</div><div class="text-caption text-medium-emphasis mt-2">这表示实际发生了回复；不表示质量、用户偏好、奖励或长期学习结果。</div></v-card></v-col>
                </v-row>
                <v-row class="mt-1">
                  <v-col cols="12" md="6"><v-card variant="outlined" class="pa-4 human-card"><div class="section-label">认知复盘</div><div v-if="detail.review?.result_code === 'REVIEW_STORE_UNAVAILABLE'" class="text-body-1">ReviewStore：当前不可用</div><div v-else-if="detail.review?.result_code === 'NO_RUN'" class="text-body-1">尚未执行：没有持久化 ReviewRun</div><div v-else-if="detail.review?.result_code === 'NO_FINDINGS'" class="text-body-1">ReviewRun 已存在，但没有 Finding</div><div v-else-if="detail.review?.result_code === 'PROMOTION_DISABLED'" class="text-body-1">Finding 已记录；promotion 未启用，没有 Evidence</div><div v-else-if="detail.review?.result_code === 'FINDINGS_NOT_PROMOTABLE'" class="text-body-1">Finding 已记录，但当前不可 promotion</div><div v-else-if="detail.review?.run_count" class="text-body-1">完成，发现 {{ detail.review.finding_count }} 条可审计观察</div><div v-else class="text-body-1">尚未执行</div><div class="text-caption text-medium-emphasis mt-2">{{ detail.review?.result_reason || 'Review 状态暂无可用解释。' }} Evidence 为 {{ detail.review?.evidence_count ?? '—' }}。</div></v-card></v-col>
                  <v-col cols="12" md="6"><v-card variant="outlined" class="pa-4 human-card"><div class="section-label">Host 执行事实</div><div v-if="detail.human?.host_fact_integrity === 'COMPLETE'" class="text-body-1 text-success">✓ {{ detail.human.verified_host_facts }} / {{ detail.human.host_outputs }} 已验证</div><div v-else-if="detail.human?.host_fact_integrity === 'PARTIAL'" class="text-body-1 text-amber-darken-2">部分不可用：{{ detail.human.verified_host_facts }} / {{ detail.human.host_outputs }} 已验证</div><div v-else class="text-body-1">本段互动没有实际 Host 回复</div><div v-if="detail.human?.host_fact_integrity === 'PARTIAL'" class="text-caption text-medium-emphasis mt-2">Episode 历史仍存在；runtime-local execution registry 可能因重启或容量淘汰而不再保存旧执行记录。</div></v-card></v-col>
                </v-row>
                <v-card variant="outlined" class="pa-4 human-card mt-3"><div class="section-label">事实完整性</div><template v-if="detail.human?.snapshot_available"><div class="text-body-2 text-success">✓ Episode 历史内容已冻结</div><div class="text-body-2 text-success">✓ 内容参与完整性校验</div><div class="text-body-2 text-success">✓ Episode 归属校验已启用</div></template><div v-else class="text-body-2 text-amber-darken-2">历史快照当前不可验证；请在工程视图查看原始原因。</div></v-card>
                <v-expansion-panels class="mt-4"><v-expansion-panel title="这些是什么意思？"><v-expansion-panel-text><div class="terminology"><p><strong>一段连续互动</strong>：系统把连续相关的来往整理在一起。</p><p><strong>经历</strong>：小天文收到并处理的一次互动。</p><p><strong>结果</strong>：后续实际发生的事实，不评价好坏。</p><p><strong>认知复盘观察</strong>：Review 得出的可审计观察。</p><p><strong>长期证据</strong>：经过严格规则验证的历史事实；当前仍不会自动改变未来行为。</p><p><strong>历史快照</strong>：Review 使用的不可变历史记录。</p></div></v-expansion-panel-text></v-expansion-panel></v-expansion-panels>
              </template>
              <template v-else>
              <div class="pipeline mb-4"><span>Raw Event</span><v-icon icon="mdi-arrow-right" /><span>Canonical Experience</span><v-icon icon="mdi-arrow-right" /><span>Episode</span><v-icon icon="mdi-arrow-right" /><span>Behavior / Host</span><v-icon icon="mdi-arrow-right" /><span>Outcome</span><v-icon icon="mdi-arrow-right" /><span>ReviewFinding</span><v-icon icon="mdi-arrow-right" /><strong>Promotion · {{ statusLabel(summary?.promotion?.status) }}</strong></div>
              <v-row>
                <v-col cols="12" md="7"><div class="section-label">Immutable Timeline</div><v-timeline density="compact" side="end" truncate-line="both"><v-timeline-item v-for="event in detail.timeline" :key="event.kind + event.ref_id" size="x-small" :dot-color="event.late_feedback ? 'amber-darken-2' : 'primary'"><div class="text-caption text-medium-emphasis">{{ formatTime(event.at) }}</div><div class="text-body-2 font-weight-medium">{{ event.kind }}</div><div class="text-caption text-medium-emphasis word-break">{{ event.ref_id }}</div><v-chip v-if="event.late_feedback" size="x-small" color="amber-darken-2" variant="tonal">LATE FEEDBACK</v-chip></v-timeline-item></v-timeline></v-col>
                <v-col cols="12" md="5"><div class="section-label">Fact attachment</div><v-card v-for="item in detail.attachments" :key="item.ref_id" variant="outlined" class="mb-2 pa-2"><div class="d-flex align-center"><v-chip size="x-small" :color="attachmentColor(item.status)">{{ item.status }}</v-chip><span class="text-caption ml-2">{{ item.source_type }}</span></div><div class="text-caption word-break mt-1">{{ item.ref_id }}</div><div v-if="item.reason" class="text-caption text-medium-emphasis">{{ item.reason }}</div></v-card><div class="text-caption text-medium-emphasis">状态由后端实际 P1 snapshot validation 产生；前端不自行重算。</div></v-col>
              </v-row>

              <div class="section-label mt-3">Outcomes</div><v-card v-if="!detail.outcomes.length" variant="outlined" class="pa-3 text-body-2 text-medium-emphasis">No outcomes observed. Absence is not negative feedback.</v-card><v-card v-for="outcome in detail.outcomes" :key="outcome.observation_id" variant="outlined" class="mb-2 pa-3"><div class="d-flex align-center ga-2"><strong>{{ outcome.kind }}</strong><v-chip v-if="outcome.late_feedback" size="x-small" color="amber-darken-2">LATE FEEDBACK</v-chip></div><div class="text-caption word-break">{{ outcome.observation_id }} · target {{ outcome.target_episode_id }}</div><div class="text-caption text-medium-emphasis">observed {{ formatTime(outcome.observed_at) }} · explicitness {{ outcome.explicitness }} · confidence {{ outcome.confidence }}</div></v-card>

               <div class="section-label mt-4">Persisted Review</div><v-card variant="outlined" class="pa-3"><template v-if="detail.review.status === 'AVAILABLE'"><div class="text-body-2">{{ detail.review.run_count }} immutable ReviewRun(s) · {{ detail.review.finding_count }} Finding(s) · Evidence {{ detail.review.evidence_count }}.</div><div class="text-caption text-medium-emphasis mt-1">{{ detail.review.result_reason }}</div><v-card v-for="run in detail.review.runs" :key="run.review_run_id" variant="tonal" class="mt-2 pa-3"><div class="d-flex align-center flex-wrap ga-2"><strong>{{ run.status }}</strong><span class="text-caption">{{ formatTime(run.created_at) }}</span><span class="text-caption word-break">{{ run.review_run_id }}</span></div><div class="text-caption word-break mt-1">Episode: {{ run.episode_id }}</div><div v-if="run.findings.length" class="mt-2"><v-card v-for="finding in run.findings" :key="finding.finding_id" variant="outlined" class="mb-2 pa-2"><div class="text-caption">Finding · {{ finding.finding_type }} · {{ finding.dimension }} · {{ formatTime(finding.created_at) }}</div><div class="text-body-2 mt-1">{{ finding.claim }}</div><div class="text-caption text-medium-emphasis mt-1">引用：</div><div v-for="ref in finding.evidence_refs" :key="ref.source_type + ref.ref_id" class="text-caption word-break">{{ ref.source_type }} / {{ ref.evidence_kind }} · {{ ref.ref_id }}</div></v-card></div><div v-else class="text-caption text-medium-emphasis mt-2">该 Run 没有 Finding。</div><div v-if="run.no_evidence_reason" class="text-caption text-amber-darken-2 mt-1">{{ run.no_evidence_reason }}</div></v-card></template><div v-else class="text-body-2 text-medium-emphasis">{{ detail.review.result_reason || (detail.review.status === 'NOT_WIRED' ? 'ReviewStore 尚未接入。' : detail.review.status === 'UNAVAILABLE' ? 'ReviewStore：Unavailable。' : '该 Episode 尚无持久化 Review。') }}</div><div class="text-caption text-medium-emphasis mt-2">Archive：{{ detail.archive?.available ? detail.archive.count : 'Unavailable' }} 个 P2r0 历史归档。</div></v-card>

              <v-divider class="my-4" /><div class="section-label">Snapshot Integrity</div><v-row dense><v-col cols="12" md="7"><v-card variant="outlined" class="pa-3"><div class="text-caption text-medium-emphasis">Input Snapshot Hash</div><div class="text-body-2 word-break">{{ detail.snapshot.hash || detail.snapshot.reason || 'Unavailable' }}</div></v-card></v-col><v-col cols="12" md="5"><v-card variant="outlined" class="pa-3"><div>FACT_PAYLOAD_HASHED <strong>YES</strong></div><div>FACT_DEEP_SNAPSHOTTED <strong>YES</strong></div><div>EPISODE_ATTACHMENT <strong>ENFORCED</strong></div></v-card></v-col></v-row>

              <v-card variant="tonal" :color="summary?.promotion?.enabled ? 'info' : 'amber-darken-2'" class="promotion mt-4 pa-4"><div class="text-subtitle-2">ReviewEvidence Promotion</div><div class="d-flex align-center mt-2"><span>ReviewFinding</span><v-icon icon="mdi-arrow-right" class="mx-2" /><v-chip :color="summary?.promotion?.enabled ? 'info' : 'amber-darken-2'">Promotion · {{ statusLabel(summary?.promotion?.status) }}</v-chip><v-icon icon="mdi-arrow-right" class="mx-2" /><span>ReviewEvidence</span></div><div class="text-body-2 mt-2">Evidence produced: <strong>{{ summary?.review_evidence ?? '—' }}</strong>。{{ summary?.promotion?.enabled ? '当前只允许 EXPLICIT_CORRECTION_OF_EXACT_HOST_OUTPUT_V1；没有满足条件的 Finding 时计数为 0。' : 'Promotion 当前不可用，观测台不会自行推断历史 Evidence。' }}</div></v-card>

              <v-card v-if="previewResult" variant="outlined" class="mt-4 pa-3"><div class="d-flex align-center"><div class="section-label mb-0">Preview Review</div><v-chip class="ml-2" size="x-small" color="info">PREVIEW ONLY · NOT PERSISTED</v-chip></div><div class="text-body-2 mt-2">Eligibility: <strong>{{ previewResult.eligibility.decision }}</strong> · {{ previewResult.eligibility.reason }}</div><v-alert v-if="previewResult.unavailable_reason" density="compact" variant="tonal" type="info" class="mt-2">完整 execution record 未接入运行时；为避免伪造 Host facts，本次 Preview 被安全拒绝。</v-alert><template v-if="previewResult.run"><div class="text-caption word-break mt-2">{{ previewResult.run.review_run_id }} · {{ previewResult.run.status }} · {{ previewResult.run.input_snapshot_hash }}</div><v-card v-for="finding in previewResult.run.findings" :key="finding.finding_id" variant="tonal" class="mt-2 pa-3"><strong>{{ finding.finding_type }}</strong> · {{ finding.dimension }}<div class="mt-1">{{ finding.claim }}</div><div class="text-caption">confidence {{ finding.confidence }} · causal {{ finding.causal_attribution }}</div><v-alert v-if="finding.claim.includes('contradicted')" density="compact" variant="outlined" class="mt-2">这表示系统观察到用户显式反驳了该输出；不证明 Host 客观错误、Grounding 失败、应调用工具、长期偏好，且不会改变未来行为。</v-alert><v-alert v-if="finding.claim.includes('acknowledgement')" density="compact" variant="outlined" class="mt-2">这只表示 Host 输出之后出现显式 acknowledgement；不表示成功、奖励、偏好或正向质量。</v-alert></v-card></template></v-card>
              <v-expansion-panels class="mt-4"><v-expansion-panel title="Canonical facts / provenance · read-only"><v-expansion-panel-text><pre>{{ pretty(detail.snapshot.canonical_facts || { status: detail.snapshot.status || 'No complete execution fact carrier wired' }) }}</pre></v-expansion-panel-text></v-expansion-panel><v-expansion-panel title="Raw JSON · read-only"><v-expansion-panel-text><pre>{{ pretty(detail.raw) }}</pre></v-expansion-panel-text></v-expansion-panel></v-expansion-panels>
              </template>
            </v-card-text>
          </template>
        </v-card>
      </v-col>
    </v-row>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getObservatoryDemoCase, getObservatoryDemoCases, getObservatoryEpisode, getObservatoryEpisodes, getObservatorySummary, previewObservatoryReview } from '@/api/observatory'

const summary = ref<any>(null); const episodes = ref<any[]>([]); const demos = ref<any[]>([]); const detail = ref<any>(null); const previewResult = ref<any>(null)
const selectedId = ref(''); const query = ref(''); const state = ref('ALL'); const loading = ref(false); const error = ref(''); const isDemo = ref(false); const viewMode = ref<'simple' | 'engineering'>('simple')
const phaseTitle = computed(() => summary.value?.phase || 'Cognitive Observatory')
const p2bShadow = computed(() => summary.value?.p2b_shadow || null)
const p2bHeaderLabel = computed(() => p2bShadow.value ? `P2b 影子模式 · ${p2bShadow.value.mode || 'SHADOW'}` : 'P2b 影子摘要 · 未接通')
const p2bHeaderColor = computed(() => p2bShadow.value?.mode === 'SHADOW' ? 'info' : 'grey')
const p2bStatusCards = computed(() => {
  const counts = p2bShadow.value?.candidate_status_counts
  const labels: Record<string, { label: string; color: string }> = {
    PENDING: { label: '待批准', color: 'amber-darken-2' },
    APPROVED: { label: '已批准', color: 'success' },
    REJECTED: { label: '已拒绝', color: 'grey' },
    REVOKED: { label: '已撤销', color: 'deep-orange' },
    CONFLICTED: { label: '冲突', color: 'error' },
    EXPIRED: { label: '已过期', color: 'grey-darken-1' },
  }
  return Object.keys(labels).map(status => ({ status, count: typeof counts?.[status] === 'number' ? counts[status] : 0, ...labels[status] }))
})
const p2bParameters = computed(() => Array.isArray(p2bShadow.value?.allowed_parameters) ? p2bShadow.value.allowed_parameters : [])
const p2bEvaluationTime = computed(() => formatObservedAt(p2bShadow.value?.last_evaluation_at))
const p2bPermissionEffect = computed(() => String(p2bShadow.value?.permission_effect || 'NONE').toUpperCase())
const summaryCards = computed(() => [{ label: 'Episodes', value: summary.value?.episodes ?? '—' }, { label: 'Finalized', value: summary.value?.finalized_episodes ?? '—' }, { label: 'Outcomes', value: summary.value?.outcomes ?? '—' }, { label: 'Review Runs', value: summary.value?.review_runs ?? '—' }, { label: 'Findings', value: summary.value?.review_findings ?? '—' }, { label: 'Evidence', value: summary.value?.review_evidence ?? '—' }])
const adaptiveCards = computed(() => {
  const a = summary.value?.adaptive_runtime || {}
  return [
    { label: 'Host 原子写', icon: 'mdi-database-lock-outline', ready: !!a.host_cas?.available, value: a.host_cas?.available ? 'CAS + 事务 + 读回' : 'Host API 未提供', detail: '仅限 response_style_preference:v1' },
    { label: '反馈重放', icon: 'mdi-replay', ready: !!a.feedback_replay?.available, value: `${a.feedback_replay?.observations ?? 0} 条有效观察`, detail: 'append-only，跨重启恢复' },
    { label: '身份库', icon: 'mdi-account-key-outline', ready: !!a.identity?.available, value: `${a.identity?.entities ?? '—'} 实体 · ${a.identity?.claims ?? '—'} 声明`, detail: 'Identity / EntityRegistry 单一 owner' },
    { label: 'Situation 投影', icon: 'mdi-layers-triple-outline', ready: !!a.situation?.available, value: `${a.situation?.events ?? 0} 次请求投影`, detail: a.situation?.last_projection_at ? `最近 ${formatUnix(a.situation.last_projection_at)}` : '等待真实请求' },
    { label: 'BehavioralPrior', icon: 'mdi-tune-variant', ready: !!a.behavioral_prior?.available, value: `${a.behavioral_prior?.observed ?? 0} 次命中`, detail: '只读表达偏好；不改变工具或回复权限' },
    { label: 'Affect 视图', icon: 'mdi-heart-pulse', ready: !!a.affect?.available, value: `${a.affect?.observed ?? 0} 次有效投影`, detail: `affection owner · TTL ${a.affect?.ttl_seconds ?? 60}s` },
  ]
})
const reviewStatusSummary = computed(() => {
  const counts = summary.value?.review_status_counts
  if (!counts || typeof counts !== 'object') return 'Unavailable'
  const entries = Object.entries(counts as Record<string, number>)
  return entries.length ? entries.map(([status, count]) => `${status} ${count}`).join(' · ') : '暂无 ReviewRun'
})
const statusLabel = (value?: string) => value ? value.replace('DISABLED / FAIL-CLOSED', 'DISABLED') : 'UNAVAILABLE'
const statusColor = (value?: string) => value === 'ENABLED' ? 'success' : value === 'DISABLED' || value === 'DISABLED / FAIL-CLOSED' ? 'amber-darken-2' : 'grey'
const stateColor = (value: string) => value === 'FINALIZED' ? 'success' : value === 'OPEN' ? 'primary' : 'grey'
const attachmentColor = (value: string) => value === 'ATTACHED' ? 'success' : value === 'REJECTED' ? 'error' : 'grey'
const formatTime = (value?: string) => value ? value.replace('T', ' ').replace('+00:00', ' UTC') : '—'
const formatUnix = (value?: number) => value ? new Date(value * 1000).toLocaleString() : '—'
const formatObservedAt = (value?: string | number) => typeof value === 'number' ? formatUnix(value) : formatTime(value)
const p2bFlagLabel = (value?: boolean) => value === false ? '关闭' : value === true ? '开启' : '未提供'
const pretty = (value: unknown) => JSON.stringify(value, null, 2)
async function loadEpisodes() { loading.value = true; try { const result = await getObservatoryEpisodes({ state: state.value, query: query.value, limit: 50 }); episodes.value = result.episodes || [] } catch (e: any) { error.value = e.message || '读取 Episode 失败' } finally { loading.value = false } }
async function loadAll() { error.value = ''; await Promise.all([getObservatorySummary().then(v => summary.value = v), getObservatoryDemoCases().then(v => demos.value = v), loadEpisodes()]).catch((e: any) => error.value = e.message || '加载失败') }
async function selectEpisode(id: string) { selectedId.value = id; isDemo.value = false; previewResult.value = null; try { detail.value = await getObservatoryEpisode(id) } catch (e: any) { error.value = e.message || '读取详情失败' } }
async function selectDemo(id: string) { selectedId.value = ''; isDemo.value = true; previewResult.value = null; try { const result = await getObservatoryDemoCase(id); detail.value = result.detail; previewResult.value = result.preview } catch (e: any) { error.value = e.message || '读取 Demo 失败' } }
async function preview() { if (!selectedId.value) return; try { previewResult.value = await previewObservatoryReview(selectedId.value) } catch (e: any) { error.value = e.message || 'Preview 失败' } }
onMounted(loadAll)
</script>

<style scoped>
.hero { background: linear-gradient(120deg, rgba(21, 101, 192, .12), rgba(0, 137, 123, .08)); border: 1px solid rgba(var(--v-theme-primary), .13); }.metric,.panel { border: 1px solid rgba(var(--v-theme-on-surface), .08); }.adaptive-panel { background: linear-gradient(135deg, rgba(0, 137, 123, .06), rgba(124, 77, 255, .05)); }.adaptive-card { min-height: 116px; background: rgba(var(--v-theme-surface), .72); }.p2b-shadow-panel { background: linear-gradient(135deg, rgba(33, 150, 243, .08), rgba(0, 188, 212, .06)); }.p2b-overview-card { min-height: 126px; background: rgba(var(--v-theme-surface), .72); }.episode-list { max-height: 410px; overflow: auto; }.state-toggle { max-width: 100%; overflow-x: auto; }.min-detail { min-height: 650px; }.pipeline { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; font-size: .78rem; color: rgba(var(--v-theme-on-surface), .7); }.pipeline strong { color: rgb(var(--v-theme-warning)); }.section-label { font-size: .88rem; font-weight: 700; margin-bottom: 8px; }.human-card { min-height: 132px; }.human-metric { font-size: 1.45rem; font-weight: 700; }.terminology p { margin: 0 0 8px; }.word-break { word-break: break-all; } pre { max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: .76rem; background: rgba(var(--v-theme-on-surface), .05); padding: 10px; border-radius: 6px; } @media (max-width: 600px) { .pipeline { display: none; } }
</style>

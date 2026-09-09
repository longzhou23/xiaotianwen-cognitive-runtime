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
          <v-card variant="outlined" class="adaptive-card adaptive-card-clickable pa-3" role="button" tabindex="0" @click="openAdaptiveDetail(item.key)" @keyup.enter="openAdaptiveDetail(item.key)" @keyup.space.prevent="openAdaptiveDetail(item.key)">
            <div class="d-flex align-center ga-2"><v-icon :icon="item.icon" :color="item.ready ? 'success' : 'grey'" /><strong>{{ item.label }}</strong><v-spacer /><v-chip size="x-small" :color="item.ready ? 'success' : 'grey'">{{ item.ready ? '已接通' : '不可用' }}</v-chip></div>
            <div class="text-body-2 mt-2">{{ item.value }}</div><div class="text-caption text-medium-emphasis mt-1">{{ item.detail }}</div>
            <v-btn variant="text" size="small" class="px-0 mt-1" append-icon="mdi-arrow-right" @click.stop="openAdaptiveDetail(item.key)">查看详情</v-btn>
          </v-card>
        </v-col>
      </v-row>
      <v-alert color="amber-darken-2" variant="tonal" density="compact" class="mt-3 mb-0">L28 历史数据写入仍锁定；仅在精确单条授权后开放。日常请求中的已批准偏好、关系熟悉度、BehavioralPrior 和 Affect 只读投影可继续生效。</v-alert>
    </v-card>

    <v-dialog v-model="adaptiveDetailOpen" max-width="960">
      <v-card>
        <v-card-title class="d-flex align-center ga-2">
          <v-icon :icon="selectedAdaptiveCard?.icon || 'mdi-information-outline'" />
          <span>{{ selectedAdaptiveCard?.label || '运行态详情' }}</span>
          <v-spacer />
          <v-chip v-if="adaptiveDetail" size="small" :color="detailStatusColor(adaptiveDetail.status)">{{ detailStatusLabel(adaptiveDetail.status) }}</v-chip>
        </v-card-title>
        <v-card-text>
          <v-alert v-if="!adaptiveDetail" type="info" variant="tonal" density="compact">详情接口当前不可用；汇总卡不会把不可用误报成空数据。</v-alert>
          <template v-else>
            <div class="text-caption text-medium-emphasis mb-3">来源：{{ adaptiveDetail.owner || '当前 owner 未提供' }}。此面板仅显示脱敏元数据；范围标识、用户标识、消息正文、证据原文和存储 payload 已隐藏。</div>
            <v-alert v-if="!adaptiveDetail.available" :type="adaptiveDetail.status === 'CORRUPTED' ? 'error' : 'warning'" variant="tonal" density="compact" class="mb-3">{{ detailReason(adaptiveDetail.reason) }}</v-alert>

            <template v-if="adminRecordKey">
              <v-alert color="info" variant="tonal" density="compact" class="mb-3">工程详情：仅管理员可见。这里读取已持久化的审计记录，接口为只读；基础视图仍只显示汇总状态。</v-alert>
              <v-progress-linear v-if="recordLoading" indeterminate color="primary" class="mb-3" />
              <v-alert v-if="recordError" type="error" variant="tonal" density="compact" class="mb-3">{{ recordError }}</v-alert>

              <template v-if="!recordLoading && !recordError && selectedAdaptiveKey === 'identity'">
                <v-row dense>
                  <v-col cols="6" sm="3"><div class="detail-metric">{{ recordDetail?.entity_count ?? '—' }}</div><div class="text-caption">实体</div></v-col>
                  <v-col cols="6" sm="3"><div class="detail-metric">{{ recordDetail?.claim_count ?? '—' }}</div><div class="text-caption">身份声明</div></v-col>
                  <v-col cols="6" sm="3"><div class="detail-metric">{{ recordDetail?.status || '—' }}</div><div class="text-caption">记录状态</div></v-col>
                  <v-col cols="6" sm="3"><div class="detail-metric">{{ recordDetail?.pagination?.limit ?? '—' }}</div><div class="text-caption">每页上限</div></v-col>
                </v-row>
                <div class="section-label mt-4">实体（管理员工程详情）</div>
                <v-table v-if="recordDetail?.entities?.length" density="compact">
                  <thead><tr><th>entity id</th><th>type</th><th>platform_ids</th><th>aliases</th><th>SELF</th></tr></thead>
                  <tbody><tr v-for="entity in recordDetail.entities" :key="entity.id"><td class="word-break">{{ entity.id }}</td><td>{{ entity.type }}</td><td class="word-break">{{ pretty(entity.platform_ids) }}</td><td class="word-break">{{ entity.aliases?.join('、') || '—' }}</td><td><v-chip size="x-small" :color="entity.self ? 'success' : 'grey'">{{ entity.self ? 'SELF' : '否' }}</v-chip></td></tr></tbody>
                </v-table>
                <div v-else class="text-body-2 text-medium-emphasis">当前没有可显示的身份实体，或身份库不可用。</div>
                <div class="section-label mt-4">Identity claims</div>
                <v-table v-if="recordDetail?.claims?.length" density="compact">
                  <thead><tr><th>claim_id</th><th>mention</th><th>candidate_entity</th><th>evidence refs</th><th>source</th><th>status</th><th>confidence</th><th>created_at</th></tr></thead>
                  <tbody><tr v-for="claim in recordDetail.claims" :key="claim.claim_id"><td class="word-break">{{ claim.claim_id }}</td><td>{{ claim.mention }}</td><td class="word-break">{{ claim.candidate_entity }}</td><td class="word-break">{{ claim.evidence?.join('、') || '—' }}</td><td class="word-break">{{ claim.source }}</td><td>{{ claim.status }}</td><td>{{ claim.confidence ?? '—' }}</td><td>{{ formatObservedAt(claim.created_at) }}</td></tr></tbody>
                </v-table>
                <div v-else class="text-body-2 text-medium-emphasis">当前没有可显示的身份声明。</div>
                <div class="d-flex align-center justify-end mt-3"><span class="text-caption text-medium-emphasis mr-3">{{ paginationLabel(recordDetail?.pagination?.offset, recordDetail?.pagination?.limit, recordDetail?.pagination?.entities_total, recordDetail?.pagination?.claims_total) }}</span><v-btn size="small" variant="text" :disabled="adminPage === 0" @click="loadAdminIdentity(adminPage - 1)">上一页</v-btn><v-btn size="small" variant="tonal" :disabled="!hasNextIdentity" @click="loadAdminIdentity(adminPage + 1)">下一页</v-btn></div>
              </template>

              <template v-else-if="!recordLoading && !recordError && selectedAdaptiveKey === 'episodes'">
                <div class="text-caption text-medium-emphasis mb-3">Episode 内容只来自持久化 `topic_hint` 快照；不会从原始消息数据库补读。完整性状态由后端快照校验返回。</div>
                <v-table v-if="recordDetail?.episodes?.length" density="compact">
                  <thead><tr><th>episode_id</th><th>scope_id</th><th>state</th><th>opened / last</th><th>content snapshot</th><th>详情</th></tr></thead>
                  <tbody><tr v-for="episode in recordDetail.episodes" :key="episode.episode_id" class="record-row"><td class="word-break">{{ episode.episode_id }}</td><td class="word-break">{{ episode.scope_id }}</td><td>{{ episode.state }}</td><td>{{ formatObservedAt(episode.opened_at) }}<br>{{ formatObservedAt(episode.last_activity_at) }}</td><td class="word-break"><span v-if="episode.content_snapshot?.status === 'AVAILABLE'">{{ episode.content_snapshot.text }}</span><span v-else>{{ episode.content_snapshot?.status || 'EMPTY' }}</span><v-chip v-if="episode.content_snapshot?.truncated" size="x-small" color="amber-darken-2" class="ml-1">已截断</v-chip></td><td><v-btn size="x-small" variant="text" @click="loadAdminEpisode(episode.episode_id)">查看</v-btn></td></tr></tbody>
                </v-table>
                <div v-else class="text-body-2 text-medium-emphasis">当前没有可显示的 Episode，或 EpisodeStore 不可用。</div>
                <div class="d-flex align-center justify-end mt-3"><span class="text-caption text-medium-emphasis mr-3">{{ paginationLabel(recordDetail?.offset, recordDetail?.limit, recordDetail?.total) }}</span><v-btn size="small" variant="text" :disabled="adminPage === 0" @click="loadAdminEpisodes(adminPage - 1)">上一页</v-btn><v-btn size="small" variant="tonal" :disabled="!hasNextRecords(recordDetail)" @click="loadAdminEpisodes(adminPage + 1)">下一页</v-btn></div>
                <v-card v-if="selectedRecordDetail" variant="outlined" class="mt-4 pa-3"><div class="d-flex align-center"><div class="section-label mb-0">{{ selectedRecordDetail.episode?.episode_id }}</div><v-spacer /><v-chip size="small" color="info">只读详情</v-chip></div><div class="text-caption text-medium-emphasis">scope_id {{ selectedRecordDetail.episode?.scope_id }} · {{ selectedRecordDetail.episode?.state }}</div><div class="section-label mt-3">不可变内容快照</div><div class="record-content word-break">{{ selectedRecordDetail.episode?.content_snapshot?.text || '没有持久化内容快照' }}<v-chip v-if="selectedRecordDetail.episode?.content_snapshot?.truncated" size="x-small" color="amber-darken-2" class="ml-2">已截断</v-chip></div><div class="text-caption text-medium-emphasis mt-1">状态：{{ selectedRecordDetail.episode?.content_snapshot?.status || 'UNAVAILABLE' }}</div><div class="section-label mt-3">event refs</div><v-table density="compact"><thead><tr><th>ref_id</th><th>kind</th><th>source_event_id</th><th>trace_id</th><th>execution_record_id</th><th>observed_at</th></tr></thead><tbody><tr v-for="ref in selectedRecordDetail.episode?.event_refs || []" :key="ref.ref_id"><td class="word-break">{{ ref.ref_id }}</td><td>{{ ref.kind }}</td><td class="word-break">{{ ref.source_event_id || '—' }}</td><td class="word-break">{{ ref.trace_id || '—' }}</td><td class="word-break">{{ ref.execution_record_id || '—' }}</td><td>{{ formatObservedAt(ref.observed_at) }}</td></tr></tbody></v-table><div class="section-label mt-3">关联 Outcomes</div><div v-if="!selectedRecordDetail.outcomes?.length" class="text-body-2 text-medium-emphasis">没有关联 Outcome。</div><v-card v-for="outcome in selectedRecordDetail.outcomes || []" :key="outcome.observation_id" variant="tonal" class="mb-2 pa-2"><strong>{{ outcome.kind }}</strong> · {{ outcome.observation_id }}<div class="text-caption">{{ outcome.evidence?.join('、') || '无 evidence' }} · {{ formatObservedAt(outcome.observed_at) }}</div></v-card><div class="section-label mt-3">关联 Review</div><pre>{{ pretty(selectedRecordDetail.review || { status: 'UNAVAILABLE' }) }}</pre><div class="section-label mt-3">完整性</div><pre>{{ pretty(selectedRecordDetail.snapshot || { status: 'UNAVAILABLE' }) }}</pre></v-card>
              </template>

              <template v-else-if="!recordLoading && !recordError && selectedAdaptiveKey === 'outcomes'">
                <div class="text-caption text-medium-emphasis mb-3">Outcome 是观察记录，不代表奖励或质量判断；下表保留契约中的 evidence 与 provenance。</div>
                <v-table v-if="recordDetail?.outcomes?.length" density="compact">
                  <thead><tr><th>observation_id</th><th>target_episode_id</th><th>kind</th><th>observed_at</th><th>source_event_id</th><th>explicitness</th><th>evidence</th><th>详情</th></tr></thead>
                  <tbody><tr v-for="outcome in recordDetail.outcomes" :key="outcome.observation_id" class="record-row" @click="selectedOutcome = outcome"><td class="word-break">{{ outcome.observation_id }}</td><td class="word-break">{{ outcome.target_episode_id }}</td><td>{{ outcome.kind }}</td><td>{{ formatObservedAt(outcome.observed_at) }}</td><td class="word-break">{{ outcome.source_event_id || '—' }}</td><td>{{ outcome.explicitness }}</td><td class="word-break">{{ outcome.evidence?.join('、') || '—' }}</td><td><v-btn size="x-small" variant="text" @click.stop="selectedOutcome = outcome">查看</v-btn></td></tr></tbody>
                </v-table>
                <div v-else class="text-body-2 text-medium-emphasis">当前没有可显示的 Outcome，或 EpisodeStore 不可用。</div>
                <div class="d-flex align-center justify-end mt-3"><span class="text-caption text-medium-emphasis mr-3">{{ paginationLabel(recordDetail?.offset, recordDetail?.limit, recordDetail?.total) }}</span><v-btn size="small" variant="text" :disabled="adminPage === 0" @click="loadAdminOutcomes(adminPage - 1)">上一页</v-btn><v-btn size="small" variant="tonal" :disabled="!hasNextRecords(recordDetail)" @click="loadAdminOutcomes(adminPage + 1)">下一页</v-btn></div>
                <v-card v-if="selectedOutcome" variant="outlined" class="mt-4 pa-3"><div class="section-label">Outcome 观察详情</div><v-row dense><v-col cols="12" sm="6"><div class="text-caption">outcome_id</div><div class="word-break">{{ selectedOutcome.observation_id }}</div></v-col><v-col cols="12" sm="6"><div class="text-caption">target_episode_id</div><div class="word-break">{{ selectedOutcome.target_episode_id }}</div></v-col><v-col cols="12" sm="6"><div class="text-caption">provenance</div><div class="word-break">{{ selectedOutcome.provenance?.join('、') || '—' }}</div></v-col><v-col cols="12" sm="6"><div class="text-caption">confidence / producer</div><div>{{ selectedOutcome.confidence ?? '—' }} / {{ selectedOutcome.producer || '—' }}</div></v-col></v-row><div class="text-caption mt-2">evidence</div><div class="record-content word-break">{{ selectedOutcome.evidence?.join('、') || '—' }}</div></v-card>
              </template>
            </template>

             <template v-else-if="selectedAdaptiveKey === 'affect'">
              <v-row dense>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ formatObservedAt(adaptiveDetail.generated_at) }}</div><div class="text-caption">生成时间</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ formatObservedAt(adaptiveDetail.expires_at) }}</div><div class="text-caption">失效时间</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ adaptiveDetail.ttl_seconds ?? '—' }}s</div><div class="text-caption">快照 TTL</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ adaptiveDetail.metrics?.length || 0 }}</div><div class="text-caption">安全数值</div></v-col>
              </v-row>
              <v-table v-if="adaptiveDetail.metrics?.length" density="compact" class="mt-3"><thead><tr><th>脱敏字段</th><th>当前值</th><th>上限</th></tr></thead><tbody><tr v-for="metric in adaptiveDetail.metrics" :key="metric.name"><td>{{ metric.name }}</td><td>{{ metric.value }}</td><td>{{ metric.maximum }}</td></tr></tbody></v-table>
              <v-table v-if="Object.keys(adaptiveDetail.labels || {}).length" density="compact" class="mt-3"><thead><tr><th>状态标签</th><th>内容</th></tr></thead><tbody><tr v-for="(value, name) in adaptiveDetail.labels" :key="name"><td>{{ name }}</td><td>{{ value }}</td></tr></tbody></v-table>
              <div v-if="adaptiveDetail.status === 'EMPTY'" class="text-body-2 text-medium-emphasis mt-3">当前快照没有可显示的脱敏数值或标签。</div>
            </template>

            <template v-else-if="selectedAdaptiveKey === 'response_preferences'">
              <v-table v-if="adaptiveDetail.records?.length" density="compact"><thead><tr><th>参数</th><th>状态</th><th>请求时间</th><th>批准时间</th><th>失效时间</th><th>来源类型</th></tr></thead><tbody><tr v-for="record in adaptiveDetail.records" :key="record.parameter + record.requested_at + record.status"><td>{{ record.parameter }}</td><td>{{ record.status }}</td><td>{{ formatObservedAt(record.requested_at) }}</td><td>{{ formatObservedAt(record.approved_at) }}</td><td>{{ formatObservedAt(record.expires_at) }}</td><td>{{ record.source_kind }}</td></tr></tbody></v-table>
              <div v-else class="text-body-2 text-medium-emphasis">{{ detailReason(adaptiveDetail.reason) }}</div>
            </template>

            <template v-else-if="selectedAdaptiveKey === 'p2b_shadow'">
              <v-row dense>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ adaptiveDetail.mode || '—' }}</div><div class="text-caption">模式</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ adaptiveDetail.permission_effect || '—' }}</div><div class="text-caption">权限影响</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ formatObservedAt(adaptiveDetail.last_evaluation_at) }}</div><div class="text-caption">最近评估</div></v-col>
                <v-col cols="6" sm="3"><div class="detail-metric">{{ adaptiveDetail.allowed_parameters?.join('、') || '—' }}</div><div class="text-caption">允许参数</div></v-col>
              </v-row>
              <div class="section-label mt-4">候选状态统计</div>
              <v-table density="compact"><thead><tr><th>状态</th><th>数量</th></tr></thead><tbody><tr v-for="(count, status) in adaptiveDetail.candidate_status_counts" :key="status"><td>{{ status }}</td><td>{{ count }}</td></tr></tbody></v-table>
            </template>

            <template v-else>
              <v-table density="compact"><thead><tr><th>字段</th><th>值</th></tr></thead><tbody><tr v-for="row in adaptiveDetailRows" :key="row.label"><td>{{ row.label }}</td><td class="word-break">{{ row.value }}</td></tr></tbody></v-table>
            </template>
          </template>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn variant="text" @click="adaptiveDetailOpen = false">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>

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
import { getObservatoryAdminEpisode, getObservatoryAdminEpisodes, getObservatoryAdminIdentity, getObservatoryAdminOutcomes, getObservatoryDemoCase, getObservatoryDemoCases, getObservatoryEpisode, getObservatoryEpisodes, getObservatoryRuntimeDetail, getObservatorySummary, previewObservatoryReview } from '@/api/observatory'

const summary = ref<any>(null); const runtimeDetail = ref<any>(null); const episodes = ref<any[]>([]); const demos = ref<any[]>([]); const detail = ref<any>(null); const previewResult = ref<any>(null)
const selectedId = ref(''); const query = ref(''); const state = ref('ALL'); const loading = ref(false); const error = ref(''); const isDemo = ref(false); const viewMode = ref<'simple' | 'engineering'>('simple'); const selectedAdaptiveKey = ref(''); const adaptiveDetailOpen = ref(false)
const recordDetail = ref<any>(null); const selectedRecordDetail = ref<any>(null); const selectedOutcome = ref<any>(null); const recordLoading = ref(false); const recordError = ref(''); const adminPage = ref(0); const adminPageSize = 20
const phaseTitle = computed(() => summary.value?.phase || 'Cognitive Observatory')
const p2bShadow = computed(() => summary.value?.p2b_shadow || null)
const adaptiveDetail = computed(() => selectedAdaptiveKey.value ? runtimeDetail.value?.details?.[selectedAdaptiveKey.value] || null : null)
const selectedAdaptiveCard = computed(() => adaptiveCards.value.find(card => card.key === selectedAdaptiveKey.value) || null)
const adminRecordKey = computed(() => ['identity', 'episodes', 'outcomes'].includes(selectedAdaptiveKey.value))
const hasNextIdentity = computed(() => {
  const page = recordDetail.value?.pagination
  const total = Math.max(Number(page?.entities_total) || 0, Number(page?.claims_total) || 0)
  return (Number(page?.offset) || 0) + (Number(page?.limit) || adminPageSize) < total
})
const adaptiveDetailRows = computed(() => {
  const value = adaptiveDetail.value
  if (!value || typeof value !== 'object') return []
  const fields: Array<[string, string]> = [['status', '状态'], ['observed', '观察次数'], ['record_count', '记录数'], ['run_count', 'ReviewRun'], ['finding_count', 'Finding'], ['evidence_count', 'Evidence'], ['count', '总数'], ['finalized_count', '已完成'], ['outcome_count', 'Outcome'], ['mode', '模式'], ['permission_effect', '权限影响'], ['last_projection_at', '最近投影'], ['latest_observed_at', '最近观察'], ['reason', '说明']]
  return fields.filter(([key]) => value[key] !== undefined && value[key] !== null).map(([key, label]) => ({ label, value: key.endsWith('_at') ? formatObservedAt(value[key]) : key === 'reason' ? detailReason(value[key]) : String(value[key]) }))
})
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
  const d = runtimeDetail.value?.details || {}
  return [
    { key: 'host_cas', label: 'Host 原子写', icon: 'mdi-database-lock-outline', ready: !!a.host_cas?.available, value: a.host_cas?.available ? 'CAS + 事务 + 读回' : 'Host API 未提供', detail: '仅限 response_style_preference:v1' },
    { key: 'feedback_replay', label: '反馈重放', icon: 'mdi-replay', ready: !!a.feedback_replay?.available, value: `${a.feedback_replay?.observations ?? 0} 条有效观察`, detail: 'append-only，跨重启恢复' },
    { key: 'identity', label: '身份库', icon: 'mdi-account-key-outline', ready: !!a.identity?.available, value: `${a.identity?.entities ?? '—'} 实体 · ${a.identity?.claims ?? '—'} 声明`, detail: 'Identity / EntityRegistry 单一 owner' },
    { key: 'situation', label: 'Situation 投影', icon: 'mdi-layers-triple-outline', ready: !!a.situation?.available, value: `${a.situation?.events ?? 0} 次请求投影`, detail: a.situation?.last_projection_at ? `最近 ${formatUnix(a.situation.last_projection_at)}` : '等待真实请求' },
    { key: 'relationship', label: 'Relationship 投影', icon: 'mdi-account-heart-outline', ready: d.relationship?.available === true, value: `${d.relationship?.observed ?? a.relationship?.observed ?? 0} 次观察`, detail: '只读投影 · owner ProfileStorage' },
    { key: 'behavioral_prior', label: 'BehavioralPrior', icon: 'mdi-tune-variant', ready: !!a.behavioral_prior?.available, value: `${a.behavioral_prior?.observed ?? 0} 次命中`, detail: '只读表达偏好；不改变工具或回复权限' },
    { key: 'affect', label: 'Affect 视图', icon: 'mdi-heart-pulse', ready: !!a.affect?.available, value: `${a.affect?.observed ?? 0} 次有效投影`, detail: `affection owner · TTL ${a.affect?.ttl_seconds ?? 60}s` },
    { key: 'response_preferences', label: '回复偏好', icon: 'mdi-format-list-checks', ready: d.response_preferences?.available === true, value: `${d.response_preferences?.record_count ?? '—'} 条安全记录`, detail: '只显示参数、状态、来源类型和 TTL' },
    { key: 'p2b_shadow', label: 'P2b 影子候选', icon: 'mdi-flask-outline', ready: d.p2b_shadow?.available === true, value: d.p2b_shadow?.available ? '可查看状态统计' : '影子存储未接通', detail: '不展示候选 ID、scope、证据或值' },
    { key: 'review', label: 'Review', icon: 'mdi-file-search-outline', ready: d.review?.available === true, value: `${d.review?.run_count ?? '—'} Run · ${d.review?.finding_count ?? '—'} Finding`, detail: '只显示审计计数和状态' },
    { key: 'episodes', label: 'Episodes', icon: 'mdi-view-list-outline', ready: d.episodes?.available === true, value: `${d.episodes?.count ?? '—'} 段 · ${d.episodes?.finalized_count ?? '—'} 已完成`, detail: '详细内容仍需选择具体 Episode' },
    { key: 'outcomes', label: 'Outcomes', icon: 'mdi-flag-checkered', ready: d.outcomes?.available === true, value: `${d.outcomes?.count ?? '—'} 条观察`, detail: '只显示数量与 owner 状态' },
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
const detailStatusLabel = (value?: string) => ({ AVAILABLE: '可用', SUMMARY_ONLY: '仅有摘要', EMPTY: '为空', EXPIRED: '已过期', UNAVAILABLE: '不可用', CORRUPTED: '数据损坏' } as Record<string, string>)[value || ''] || value || '不可用'
const detailStatusColor = (value?: string) => value === 'AVAILABLE' ? 'success' : value === 'SUMMARY_ONLY' ? 'info' : value === 'CORRUPTED' ? 'error' : value === 'EXPIRED' ? 'amber-darken-2' : 'grey'
const detailReason = (value?: string) => ({
  sanitized_affect_snapshot_not_bound: 'Affect owner 尚未提供可验证的脱敏快照。',
  affect_snapshot_ttl_elapsed: '脱敏 Affect 快照已超过 TTL，当前不会继续展示旧数值。',
  identity_registry_empty: '当前没有可显示的身份声明。',
  response_preferences_not_bound: '偏好 owner 尚未提供可验证的安全详情。',
  feedback_replay_not_bound: '反馈重放 owner 尚未提供可验证的安全详情。',
  invalid_affect_metric: 'Affect 快照结构无法验证，已停止展示其内容。',
  invalid_affect_snapshot: 'Affect 快照结构无法验证，已停止展示其内容.',
} as Record<string, string>)[value || ''] || (value ? `状态原因：${value}` : '当前没有可用的安全详情。')
const formatStatusCount = (value?: Record<string, number>) => {
  if (!value || typeof value !== 'object') return '—'
  const entries = Object.entries(value).filter(([, count]) => typeof count === 'number')
  return entries.length ? entries.map(([status, count]) => `${status} ${count}`).join(' · ') : '—'
}
function openAdaptiveDetail(key: string) {
  selectedAdaptiveKey.value = key
  adaptiveDetailOpen.value = true
  recordError.value = ''
  recordDetail.value = null
  selectedRecordDetail.value = null
  selectedOutcome.value = null
  adminPage.value = 0
  if (key === 'identity') void loadAdminIdentity(0)
  if (key === 'episodes') void loadAdminEpisodes(0)
  if (key === 'outcomes') void loadAdminOutcomes(0)
}
async function loadAdminIdentity(page = 0) {
  recordLoading.value = true; recordError.value = ''; adminPage.value = page
  try { recordDetail.value = await getObservatoryAdminIdentity({ limit: adminPageSize, offset: page * adminPageSize }) } catch (e: any) { recordError.value = e.message || '读取管理员身份记录失败' } finally { recordLoading.value = false }
}
async function loadAdminEpisodes(page = 0) {
  recordLoading.value = true; recordError.value = ''; adminPage.value = page; selectedRecordDetail.value = null
  try { recordDetail.value = await getObservatoryAdminEpisodes({ state: state.value, query: query.value, limit: adminPageSize, offset: page * adminPageSize }) } catch (e: any) { recordError.value = e.message || '读取管理员 Episode 记录失败' } finally { recordLoading.value = false }
}
async function loadAdminEpisode(id: string) {
  recordLoading.value = true; recordError.value = ''; selectedRecordDetail.value = null
  try { selectedRecordDetail.value = await getObservatoryAdminEpisode(id) } catch (e: any) { recordError.value = e.message || '读取管理员 Episode 详情失败' } finally { recordLoading.value = false }
}
async function loadAdminOutcomes(page = 0) {
  recordLoading.value = true; recordError.value = ''; adminPage.value = page; selectedOutcome.value = null
  try { recordDetail.value = await getObservatoryAdminOutcomes({ limit: adminPageSize, offset: page * adminPageSize }) } catch (e: any) { recordError.value = e.message || '读取管理员 Outcome 记录失败' } finally { recordLoading.value = false }
}
const hasNextRecords = (value: any) => Number(value?.offset || 0) + Number(value?.limit || adminPageSize) < (Number(value?.total) || 0)
const paginationLabel = (offset?: number, limit?: number, ...totals: any[]) => {
  const total = Math.max(...totals.map(value => Number(value) || 0), 0)
  if (!total) return totals.some(value => value === 'Unavailable') ? '记录不可用' : '0 条记录'
  const start = (Number(offset) || 0) + 1
  const end = Math.min(start + (Number(limit) || adminPageSize) - 1, total)
  return `${start}-${end} / ${total}`
}
async function loadRuntimeDetail() {
  try { runtimeDetail.value = await getObservatoryRuntimeDetail() } catch { runtimeDetail.value = null }
}
async function loadEpisodes() { loading.value = true; try { const result = await getObservatoryEpisodes({ state: state.value, query: query.value, limit: 50 }); episodes.value = result.episodes || [] } catch (e: any) { error.value = e.message || '读取 Episode 失败' } finally { loading.value = false } }
async function loadAll() { error.value = ''; await Promise.all([getObservatorySummary().then(v => summary.value = v), getObservatoryDemoCases().then(v => demos.value = v), loadEpisodes(), loadRuntimeDetail()]).catch((e: any) => error.value = e.message || '加载失败') }
async function selectEpisode(id: string) { selectedId.value = id; isDemo.value = false; previewResult.value = null; try { detail.value = await getObservatoryEpisode(id) } catch (e: any) { error.value = e.message || '读取详情失败' } }
async function selectDemo(id: string) { selectedId.value = ''; isDemo.value = true; previewResult.value = null; try { const result = await getObservatoryDemoCase(id); detail.value = result.detail; previewResult.value = result.preview } catch (e: any) { error.value = e.message || '读取 Demo 失败' } }
async function preview() { if (!selectedId.value) return; try { previewResult.value = await previewObservatoryReview(selectedId.value) } catch (e: any) { error.value = e.message || 'Preview 失败' } }
onMounted(loadAll)
</script>

<style scoped>
.hero { background: linear-gradient(120deg, rgba(21, 101, 192, .12), rgba(0, 137, 123, .08)); border: 1px solid rgba(var(--v-theme-primary), .13); }.metric,.panel { border: 1px solid rgba(var(--v-theme-on-surface), .08); }.adaptive-panel { background: linear-gradient(135deg, rgba(0, 137, 123, .06), rgba(124, 77, 255, .05)); }.adaptive-card { min-height: 116px; background: rgba(var(--v-theme-surface), .72); }.adaptive-card-clickable { cursor: pointer; }.adaptive-card-clickable:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }.detail-metric { font-size: 1.18rem; font-weight: 700; overflow-wrap: anywhere; }.p2b-shadow-panel { background: linear-gradient(135deg, rgba(33, 150, 243, .08), rgba(0, 188, 212, .06)); }.p2b-overview-card { min-height: 126px; background: rgba(var(--v-theme-surface), .72); }.episode-list { max-height: 410px; overflow: auto; }.state-toggle { max-width: 100%; overflow-x: auto; }.min-detail { min-height: 650px; }.pipeline { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; font-size: .78rem; color: rgba(var(--v-theme-on-surface), .7); }.pipeline strong { color: rgb(var(--v-theme-warning)); }.section-label { font-size: .88rem; font-weight: 700; margin-bottom: 8px; }.human-card { min-height: 132px; }.human-metric { font-size: 1.45rem; font-weight: 700; }.terminology p { margin: 0 0 8px; }.word-break { word-break: break-all; } pre { max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-all; font-size: .76rem; background: rgba(var(--v-theme-on-surface), .05); padding: 10px; border-radius: 6px; } @media (max-width: 600px) { .pipeline { display: none; } }
</style>

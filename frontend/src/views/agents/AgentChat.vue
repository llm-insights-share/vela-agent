<template>
  <div style="height: calc(100vh - 140px); display: flex; gap: 0">
    <div class="session-sidebar">
      <div class="session-sidebar-header">
        <span class="session-sidebar-title">会话历史</span>
        <a-button size="small" type="primary" @click="createNewSession" :loading="creatingSession">
          <PlusOutlined />
        </a-button>
      </div>
      <div class="session-list" v-if="sessions.length > 0">
        <div
          v-for="s in sessions"
          :key="s.session_id"
          :class="['session-item', { active: s.session_id === sessionId }]"
          @click="switchSession(s)"
        >
          <div class="session-item-top">
            <span class="session-item-title" :title="s.title || '新对话'">{{ s.title || '新对话' }}</span>
            <a-tag :color="sessionStatusColor(s.status)" size="small">
              <LoadingOutlined v-if="s.status === 'RUNNING'" style="margin-right: 4px;" />
              {{ sessionStatusLabel(s.status) }}
            </a-tag>
          </div>
          <div class="session-item-meta">
            <span class="session-item-msg-count">{{ (s.messages || []).length }} 条消息</span>
            <span class="session-item-time">{{ formatTime(s.created_at) }}</span>
          </div>
        </div>
      </div>
      <div class="session-list-empty" v-else-if="!loadingSessions">
        <span style="color: #9e9590; font-size: 12px;">暂无会话</span>
      </div>
      <div class="session-list-empty" v-else>
        <a-spin size="small" />
      </div>
    </div>

    <div style="flex: 1; display: flex; flex-direction: column; min-width: 0;">
      <div class="chat-header">
        <a-button type="text" @click="$router.back()">
          <ArrowLeftOutlined /> 返回
        </a-button>
        <span class="chat-title">{{ agent.name }} - 对话测试</span>
        <div v-if="sessionId" class="session-id-wrap">
          <a-tag color="green">会话: {{ sessionId.substring(0, 8) }}...</a-tag>
          <a-tooltip title="复制完整会话 ID">
            <a-button
              type="text"
              size="small"
              class="session-id-copy"
              @click="copySessionId"
            >
              <CopyOutlined />
            </a-button>
          </a-tooltip>
        </div>
        <a-tag v-if="isRunning" color="orange">
          <LoadingOutlined style="margin-right: 4px;" />运行中
        </a-tag>
        <a-tag v-else-if="isHitlWait" color="gold">待审批</a-tag>
        <div class="chat-header-actions">
          <a-select
            v-if="agent.agent_type === 'SINGLE'"
            v-model:value="executionMode"
            size="small"
            style="width: 160px"
            :options="executionModeOptions"
          />
          <a-button size="small" @click="openDebugDrawer">调试</a-button>
        </div>
      </div>

    <div class="chat-messages" ref="msgContainer">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        :class="['chat-msg', msg.role === 'user' ? 'chat-msg-user' : 'chat-msg-assistant']"
      >
        <div class="chat-msg-role">
          <template v-if="msg.role === 'user'">你</template>
          <template v-else>
            {{ agent.name }}
            <a-tag v-if="msg.activeSkill" color="orange" style="margin-left: 6px; font-size: 10px;">
              {{ msg.activeSkill }}
            </a-tag>
            <a-tag v-if="msg.executionMode && msg.executionMode !== 'direct'" color="blue" style="margin-left: 4px; font-size: 10px;">
              {{ executionModeOptions.find(o => o.value === msg.executionMode)?.label || msg.executionMode }}
            </a-tag>
            <span v-if="msg.runMetrics" class="run-metrics-hint" style="margin-left: 6px; font-size: 10px; color: #888;">
              搜索 {{ msg.runMetrics.web_search_calls || 0 }} 次
              <template v-if="msg.runMetrics.tool_search_calls">
                · 工具检索 {{ msg.runMetrics.tool_search_calls }} 次
              </template>
              <template v-if="msg.runMetrics.loaded_tool_count">
                · 已加载 {{ msg.runMetrics.loaded_tool_count }} 工具
              </template>
              · {{ msg.runMetrics.elapsed_ms ? Math.round(msg.runMetrics.elapsed_ms / 1000) + 's' : '' }}
              <template v-if="msg.runMetrics.forced_synthesis"> · 强制合成</template>
            </span>
            <a-space v-if="msg.role === 'assistant' && msg.content" size="small" style="margin-left: 8px">
              <a-button type="text" size="small" @click="submitFeedback(i, 1)">👍</a-button>
              <a-button type="text" size="small" @click="submitFeedback(i, -1)">👎</a-button>
            </a-space>
          </template>
        </div>

        <LlmTurnCards
          v-if="msg.role === 'assistant' && msg._llmTurns?.length"
          :turns="msg._llmTurns"
          :code-executions="msg.codeExecutions"
          :default-expanded="!msg.content || currentSessionStatus === 'RUNNING' || currentSessionStatus === 'HITL_WAIT'"
        />

        <ExecutionStoryPanel
          v-else-if="msg.role === 'assistant' && msg._executionStory"
          :story="msg._executionStory"
          :default-expanded="msg._executionStory.status === 'running' || msg._executionStory.status === 'hitl_wait'"
        />

        <!-- Legacy flat timeline fallback when no structured story -->
        <div v-else-if="msg._thinkingSteps && msg._thinkingSteps.length" class="chat-thinking">
          <div class="chat-thinking-header" @click="msg.thinkingExpanded = !msg.thinkingExpanded">
            <CaretRightOutlined v-if="!msg.thinkingExpanded" style="font-size: 10px;" />
            <CaretDownOutlined v-else style="font-size: 10px;" />
            <span style="margin-left: 4px;">思考与执行过程</span>
            <span class="chat-thinking-summary">{{ thinkingSummary(msg._thinkingSteps) }}</span>
          </div>
          <div v-if="msg.thinkingExpanded" class="chat-thinking-body chat-thinking-timeline">
            <div
              v-for="(step, si) in msg._thinkingSteps"
              :key="si"
              :class="['think-step', `think-step-${step.type}`]"
            >
              <div class="think-step-rail" />
              <div class="think-step-body">
                <div class="think-step-head">
                  <a-tag :color="thinkingStepColor(step.type)" size="small">{{ thinkingStepLabel(step) }}</a-tag>
                  <a-button
                    v-if="step.type === 'tool' && !step.searchCard && step.text && step.text.length > 80"
                    type="link"
                    size="small"
                    class="think-step-toggle"
                    @click.stop="step.expanded = !step.expanded"
                  >{{ step.expanded ? '收起' : '展开' }}</a-button>
                </div>
                <div v-if="step.searchCard" class="search-result-card">
                  <div v-if="step.searchCard.answer" class="search-answer">
                    <div class="search-card-label">摘要答案</div>
                    <div class="search-answer-body">{{ step.searchCard.answer }}</div>
                  </div>
                  <div v-if="step.searchCard.results?.length" class="search-list">
                    <div class="search-card-label">搜索结果</div>
                    <div
                      v-for="(item, ri) in step.searchCard.results"
                      :key="ri"
                      class="search-item"
                    >
                      <div class="search-item-title">{{ ri + 1 }}. {{ item.title }}</div>
                      <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" class="search-item-link">{{ item.url }}</a>
                      <div v-if="item.snippet" class="search-item-snippet">{{ item.snippet }}</div>
                    </div>
                  </div>
                </div>
                <pre
                  v-else-if="step.type === 'tool'"
                  class="think-step-text"
                >{{ step.expanded || step.text.length <= 80 ? step.text : (step.text.slice(0, 80) + '…') }}</pre>
                <div v-else class="think-step-text">{{ step.text }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="chat-msg-content" v-if="msg.content || (msg.role === 'user' && msg.activeSkill)">
          <template v-if="msg.role === 'user' && msg.activeSkill">
            <span class="user-skill-prefix">/{{ msg.activeSkill }}&nbsp;&nbsp;</span><span class="user-msg-text">{{ msg.content }}</span>
          </template>
          <template v-else-if="msg.content">
            <div class="chat-markdown-body" v-html="renderMarkdown(msg.content)"></div>
          </template>
        </div>

        <div v-if="msg.attachments && msg.attachments.length" class="chat-attachments">
          <a-tag v-for="att in msg.attachments" :key="att.id" color="blue">
            <PaperClipOutlined /> {{ att.filename }}
          </a-tag>
        </div>
        <div v-if="msg.codeExecutions && msg.codeExecutions.length && !msg._llmTurns?.length" class="chat-code-execs">
          <CodeExecutionCard
            v-for="(cex, ci) in msg.codeExecutions"
            :key="ci"
            :exec="cex"
            :default-expanded="ci === msg.codeExecutions.length - 1"
          />
        </div>
        <div v-if="msg.files && msg.files.length > 0" class="chat-files">
          <a-alert
            v-if="msg.filesTruncated || hasTruncatedFiles(msg.files)"
            type="warning"
            show-icon
            style="margin-bottom: 8px;"
          >
            <template #message>文件可能不完整</template>
            <template #description>
              模型输出在生成文件时被截断，当前文件内容可能缺失尾部。请尝试简化请求、增加超时时间，或让 Agent 继续补全。
            </template>
          </a-alert>
          <div v-if="nonImageFiles(msg.files).length" class="chat-files-title">生成的文件：</div>
          <div v-if="imageFiles(msg.files).length" class="chat-image-grid">
            <img
              v-for="f in imageFiles(msg.files)"
              :key="f.url"
              :src="f.url"
              :alt="f.name"
              class="chat-image-thumb"
              loading="lazy"
              @click="previewFile(f)"
            />
          </div>
          <div
            v-for="f in nonImageFiles(msg.files)"
            :key="f.url"
            class="chat-file-item"
          >
            <span class="chat-file-link" @click="previewFile(f)">
              <FileOutlined />
              <span class="chat-file-name">{{ f.name }}</span>
              <span class="chat-file-size">({{ f.size_display }})</span>
              <a-tag v-if="f.truncated" color="warning" class="chat-file-truncated-tag">可能不完整</a-tag>
            </span>
          </div>
        </div>

        <div v-if="msg.executionTrace && msg.executionTrace.length" class="chat-trace">
          <div class="chat-thinking-header" @click="msg.traceExpanded = !msg.traceExpanded">
            <CaretRightOutlined v-if="!msg.traceExpanded" style="font-size: 10px;" />
            <CaretDownOutlined v-else style="font-size: 10px;" />
            <span style="margin-left: 4px;">工作流执行轨迹 ({{ msg.executionTrace.length }} 步)</span>
          </div>
          <div v-if="msg.traceExpanded" class="chat-trace-body">
            <div v-for="(step, si) in msg.executionTrace" :key="si" class="trace-step">
              <a-tag :color="step.status === 'success' ? 'green' : step.status === 'hitl_wait' ? 'orange' : 'red'" size="small">
                {{ step.node_type }}
              </a-tag>
              <span class="trace-label">{{ step.label || step.node_id }}</span>
              <span class="trace-duration" v-if="step.duration_ms">{{ step.duration_ms }}ms</span>
            </div>
          </div>
        </div>

        <div v-if="msg.pendingApprovalId && !msg.approvalStatus" class="chat-hitl-actions">
          <a-alert
            :message="msg.pendingOtp || msg.previewPayload?.flow_kind === 'otp_wait'
              ? (msg.previewPayload?.prompt || '请输入短信验证码')
              : (msg.pendingSkillParams || msg.previewPayload?.flow_kind === 'skill_params')
                ? (msg.previewPayload?.prompt || '请补充技能参数')
              : msg.pendingWorkflow ? '工作流 HITL 等待审批'
              : msg.pendingDelivery ? '多 Agent 交付物等待审批'
              : `工具 [${msg.pendingToolName}] 等待审批`"
            type="warning"
            show-icon
            style="margin-bottom: 8px;"
          />
          <div v-if="msg.previewPayload && (msg.previewPayload.som_image_b64 || msg.previewPayload.screenshot_b64)" class="hitl-som-preview">
            <div class="hitl-preview-meta">
              <a-tag v-if="msg.previewPayload.risk_tier" color="orange">{{ msg.previewPayload.risk_tier }}</a-tag>
              <span v-if="msg.previewPayload.action">动作: {{ msg.previewPayload.action }}</span>
              <span v-if="msg.previewPayload.target_label">目标: {{ msg.previewPayload.target_label }}</span>
            </div>
            <img
              :src="'data:image/png;base64,' + (msg.previewPayload.som_image_b64 || msg.previewPayload.screenshot_b64)"
              alt="SoM 预览"
              class="hitl-som-image"
            />
          </div>
          <div v-if="msg.pendingOtp || msg.previewPayload?.flow_kind === 'otp_wait'" class="hitl-otp-form">
            <a-input
              v-model:value="msg.otpCode"
              placeholder="请输入验证码"
              maxlength="12"
              style="width: 200px;"
              @pressEnter="submitOtpHitl(msg)"
            />
            <a-button type="primary" size="small" :loading="msg.approving" @click="submitOtpHitl(msg)">
              提交验证码
            </a-button>
            <a-button size="small" :loading="msg.approving" @click="rejectHitl(msg)">
              取消
            </a-button>
          </div>
          <div
            v-else-if="msg.pendingSkillParams || msg.previewPayload?.flow_kind === 'skill_params'"
            class="hitl-skill-params-form"
          >
            <div
              v-for="key in (msg.previewPayload?.missing_params || [])"
              :key="key"
              class="hitl-param-row"
            >
              <div class="hitl-param-label">
                {{ key }}
                <span v-if="msg.previewPayload?.param_schema?.properties?.[key]?.description" class="hitl-param-desc">
                  — {{ msg.previewPayload.param_schema.properties[key].description }}
                </span>
              </div>
              <a-input
                v-model:value="msg.skillParamValues[key]"
                :placeholder="`请输入 ${key}`"
                allow-clear
              />
            </div>
            <a-space style="margin-top: 8px;">
              <a-button type="primary" size="small" :loading="msg.approving" @click="submitSkillParamsHitl(msg)">
                提交参数并继续
              </a-button>
              <a-button size="small" :loading="msg.approving" @click="rejectHitl(msg)">
                取消
              </a-button>
            </a-space>
          </div>
          <a-space v-else>
            <a-button type="primary" size="small" :loading="msg.approving" @click="approveHitl(msg)">
              批准
            </a-button>
            <a-button danger size="small" :loading="msg.approving" @click="rejectHitl(msg)">
              拒绝
            </a-button>
          </a-space>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && msg.pendingWorkflow && msg.approvalFinalResult" class="chat-hitl-result">
          <a-alert message="工作流审批已通过 - 执行结果" type="success" show-icon style="margin-bottom: 8px;" />
          <div class="chat-msg-content" v-html="renderMarkdown(msg.approvalFinalResult)"></div>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && msg.pendingDelivery && msg.approvalFinalResult" class="chat-hitl-result">
          <a-alert message="审批已通过 - 交付物" type="success" show-icon style="margin-bottom: 8px;" />
          <div class="chat-msg-content" v-html="renderMarkdown(msg.approvalFinalResult)"></div>
        </div>

        <div v-if="msg.approvalStatus === 'approved' && !msg.pendingDelivery && !msg.pendingWorkflow" class="chat-hitl-result">
          <a-alert message="工具审批已通过，结果已注入对话上下文。请发送消息继续。" type="success" show-icon />
        </div>

        <div v-if="msg.approvalStatus === 'rejected'" class="chat-hitl-result">
          <a-alert :message="msg.pendingWorkflow ? '工作流审批已拒绝' : msg.pendingDelivery ? '交付物审批已拒绝' : '工具审批已拒绝，已通知 Agent。'" type="error" show-icon />
        </div>
      </div>

      <div v-if="showLiveProgress" class="chat-msg chat-msg-assistant">
        <div class="chat-msg-role">
          {{ agent.name }}
          <a-tag v-if="activeSkill" color="orange" style="margin-left: 6px; font-size: 10px;">
            {{ activeSkill }}
          </a-tag>
          <a-spin size="small" style="margin-left: 8px;" />
        </div>
        <LlmTurnCards
          :turns="liveLlmTurns.length ? liveLlmTurns : livePlaceholderTurns"
          :default-expanded="true"
        />
      </div>
    </div>

    <div class="chat-input-area">
      <div class="skill-bar" v-if="activeSkill">
        <a-tag color="orange" closable @close="clearSkill">
          <ThunderboltOutlined /> {{ activeSkill }}
        </a-tag>
      </div>
      <div class="attachment-bar" v-if="pendingAttachments.length">
        <a-tag
          v-for="att in pendingAttachments"
          :key="att.attachment_id || att.tempId"
          :closable="!att.uploading"
          color="blue"
          @close="removeAttachment(att)"
        >
          <LoadingOutlined v-if="att.uploading" style="margin-right: 4px;" />
          <PaperClipOutlined v-else style="margin-right: 4px;" />
          {{ att.filename }}
        </a-tag>
      </div>
      <div class="chat-input-row">
        <div class="chat-input-wrapper" ref="inputWrapper">
          <a-button
            class="attach-btn"
            type="text"
            :disabled="isSending || uploadingAttachment"
            @click="triggerUpload"
          >
            <PaperClipOutlined />
          </a-button>
          <input
            ref="fileInput"
            type="file"
            hidden
            multiple
            :accept="ACCEPT_TYPES"
            @change="onFilesSelected"
          />
          <a-textarea
            ref="inputRef"
            v-model:value="inputText"
            placeholder="输入消息... 输入 / 选择 Skill"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            @pressEnter="onEnter"
            @input="onInput"
            :disabled="isSending"
          />
          <a-button
            v-if="canAbort"
            type="primary"
            danger
            :loading="aborting"
            :disabled="aborting"
            @click="abortCurrentSession"
            class="send-btn"
          >
            <StopOutlined v-if="!aborting" />
          </a-button>
          <a-button
            v-else
            type="primary"
            :loading="isSending"
            :disabled="(!inputText.trim() && !readyAttachments.length) || isSending || hasUploadingAttachments"
            @click="sendMessage"
            class="send-btn"
          >
            <SendOutlined />
          </a-button>
        </div>
        <div class="chat-timeout-setting">
          <a-checkbox v-model:checked="skipHistory" :disabled="isSending" style="white-space: nowrap; font-size: 12px;">
            不引用历史
          </a-checkbox>
          <span class="timeout-label">超时</span>
          <a-input-number
            v-model:value="timeoutSeconds"
            :min="10"
            :max="600"
            :step="5"
            size="small"
            style="width: 80px"
          />
          <span class="timeout-unit">秒</span>
        </div>
      </div>

      <div class="skill-popover" v-if="showSkillMenu && filteredSkills.length > 0" ref="skillMenuRef">
        <div
          v-for="skill in filteredSkills"
          :key="skill.skill_pack_id"
          class="skill-item"
          :class="{ active: skillMenuIndex === filteredSkills.indexOf(skill) }"
          @click="selectSkill(skill)"
          @mouseenter="skillMenuIndex = filteredSkills.indexOf(skill)"
        >
          <div class="skill-item-name">
            <ThunderboltOutlined style="color: #c2410c; margin-right: 6px;" />
            {{ skill.name }}
          </div>
          <div class="skill-item-desc">{{ skill.description || skill.version }}</div>
        </div>
      </div>
    </div>

    <!-- 文件预览弹窗 -->
    <Teleport to="body">
      <div class="preview-overlay" v-if="previewVisible" @mousedown.self="closePreview">
        <div
          class="preview-modal"
          :style="{ width: previewWidth + 'px', height: previewHeight + 'px' }"
        >
          <div class="preview-header">
            <span class="preview-title">
              <FileOutlined style="margin-right: 6px;" />{{ previewFileName }}
              <a-tag v-if="previewFileTruncated" color="warning" style="margin-left: 8px; font-size: 11px;">可能不完整</a-tag>
            </span>
            <div class="preview-actions">
              <a-button size="small" type="text" :href="previewFileUrl" :download="previewFileName">
                <DownloadOutlined /> 下载
              </a-button>
              <a-button size="small" type="text" @click="closePreview">
                <CloseOutlined />
              </a-button>
            </div>
          </div>
          <div class="preview-body" ref="previewBodyRef">
            <a-alert
              v-if="previewFileTruncated"
              type="warning"
              show-icon
              message="此文件可能因模型输出截断而不完整"
              description="预览内容可能缺少尾部，建议重新生成或请求 Agent 补全文件。"
              style="margin: 12px 12px 0;"
            />
            <!-- HTML 预览 -->
            <iframe
              v-if="previewType === 'html'"
              :srcdoc="previewContent"
              class="preview-iframe"
              sandbox="allow-scripts allow-same-origin"
            />
            <!-- Markdown 预览 -->
            <div
              v-else-if="previewType === 'markdown'"
              class="preview-markdown"
              v-html="renderMarkdown(previewContent)"
            />
            <!-- 图片预览 -->
            <img
              v-else-if="previewType === 'image'"
              :src="previewFileUrl"
              class="preview-image"
              :alt="previewFileName"
            />
            <!-- CSV 表格预览 -->
            <div v-else-if="previewType === 'csv'" class="preview-csv">
              <table class="csv-table" v-if="csvData.length > 0">
                <thead>
                  <tr>
                    <th v-for="(h, hi) in csvData[0]" :key="hi">{{ h }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in csvData.slice(1)" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <!-- 文本/JSON/XML 预览 -->
            <pre v-else-if="previewType === 'text'" class="preview-text">{{ previewContent }}</pre>
            <!-- PDF 预览 -->
            <iframe
              v-else-if="previewType === 'pdf'"
              :src="previewFileUrl"
              class="preview-iframe"
            />
            <!-- Office 文件：提示下载 -->
            <div v-else-if="previewType === 'office'" class="preview-office">
              <FileOutlined style="font-size: 48px; color: #9e9590;" />
              <p style="margin-top: 16px; color: #5c5650;">此文件类型不支持在线预览</p>
              <a-button type="primary" :href="previewFileUrl" :download="previewFileName" style="margin-top: 12px;">
                <DownloadOutlined /> 下载文件
              </a-button>
            </div>
            <!-- 加载中 -->
            <div v-else-if="previewLoading" class="preview-loading">
              <a-spin size="large" />
              <p style="margin-top: 12px; color: #9e9590;">加载中...</p>
            </div>
          </div>
          <!-- 右下角拖拽调整大小 -->
          <div class="preview-resize-handle" @mousedown="startResize"></div>
        </div>
      </div>
    </Teleport>

    <a-drawer
      v-model:open="debugOpen"
      title="调试 · 模型交互"
      width="680"
      :destroy-on-close="false"
      @close="stopDebugPoll"
    >
      <div v-if="!sessionId" class="debug-empty">
        <a-empty description="请先创建或选择会话" />
      </div>
      <div v-else-if="loadingLlmCalls && llmCalls.length === 0" class="debug-loading">
        <a-spin tip="加载中..." />
      </div>
      <div v-else-if="llmCalls.length === 0" class="debug-empty">
        <a-empty description="暂无模型调用记录，发送消息后将在此显示" />
      </div>
      <div v-else class="debug-call-list">
        <a-card
          v-for="call in llmCalls"
          :key="call.call_id"
          size="small"
          class="debug-call-card"
        >
          <template #title>
            <div class="debug-call-title">
              <span>#{{ call.seq }}</span>
              <a-tag color="blue">{{ sourceLabel(call.source) }}</a-tag>
              <span class="debug-call-model">{{ call.model_name }}</span>
            </div>
          </template>
          <template #extra>
            <a-space size="small">
              <a-tag>{{ call.duration_ms }}ms</a-tag>
              <a-tag v-if="tokenTotal(call)" color="purple">{{ tokenTotal(call) }} tokens</a-tag>
            </a-space>
          </template>

          <div class="debug-section">
            <div
              class="debug-section-head"
              @click="toggleDebugSection(`${call.call_id}-input`)"
            >
              <CaretRightOutlined v-if="!isDebugSectionExpanded(`${call.call_id}-input`)" style="font-size: 10px;" />
              <CaretDownOutlined v-else style="font-size: 10px;" />
              <span class="debug-section-label">输入</span>
              <span v-if="!isDebugSectionExpanded(`${call.call_id}-input`)" class="debug-section-summary">
                · {{ inputSectionSummary(call) }}
              </span>
            </div>
            <template v-if="isDebugSectionExpanded(`${call.call_id}-input`)">
              <div v-if="systemMessages(call.input?.messages).length" class="debug-messages">
                <div
                  v-for="(msg, mi) in systemMessages(call.input?.messages)"
                  :key="'sys-' + mi"
                  :class="['debug-msg-block', 'debug-msg-system']"
                >
                  <div
                    class="debug-msg-block-head"
                    @click="toggleDebugMsgCard(`${call.call_id}-sys-${mi}`)"
                  >
                    <CaretRightOutlined v-if="!isDebugMsgExpanded(`${call.call_id}-sys-${mi}`)" style="font-size: 10px;" />
                    <CaretDownOutlined v-else style="font-size: 10px;" />
                    <span class="debug-msg-role">{{ roleLabel(msg.role) }}</span>
                    <span v-if="!isDebugMsgExpanded(`${call.call_id}-sys-${mi}`)" class="debug-msg-preview">{{ msgPreview(msg) }}</span>
                  </div>
                  <template v-if="isDebugMsgExpanded(`${call.call_id}-sys-${mi}`)">
                    <pre v-if="msg.content" class="debug-msg-content">{{ formatContent(msg.content) }}</pre>
                  </template>
                </div>
              </div>
              <div v-if="call.input?.tools?.length" class="debug-tools-block">
                <div class="debug-sub-label">Tools 定义（{{ call.input.tools.length }}）</div>
                <div class="debug-tool-cards">
                  <div
                    v-for="(tool, ti) in call.input.tools"
                    :key="ti"
                    class="debug-tool-card"
                  >
                    <div
                      class="debug-tool-card-head"
                      @click="toggleToolCard(`${call.call_id}-${ti}`)"
                    >
                      <CaretRightOutlined v-if="!isToolCardExpanded(`${call.call_id}-${ti}`)" style="font-size: 10px;" />
                      <CaretDownOutlined v-else style="font-size: 10px;" />
                      <span class="debug-tool-card-name">{{ toolFn(tool).name || 'unnamed' }}</span>
                      <a-tag size="small">{{ tool.type || 'function' }}</a-tag>
                    </div>
                    <template v-if="isToolCardExpanded(`${call.call_id}-${ti}`)">
                      <div v-if="toolFn(tool).description" class="debug-tool-card-desc">
                        {{ toolFn(tool).description }}
                      </div>
                      <div v-if="toolParamEntries(tool).length" class="debug-tool-params">
                        <div class="debug-sub-label">parameters</div>
                        <div
                          v-for="param in toolParamEntries(tool)"
                          :key="param.name"
                          class="debug-tool-param-row"
                        >
                          <code class="debug-tool-param-name">{{ param.name }}</code>
                          <a-tag size="small">{{ param.type }}</a-tag>
                          <a-tag v-if="param.required" color="orange" size="small">required</a-tag>
                          <span v-if="param.description" class="debug-tool-param-desc">{{ param.description }}</span>
                        </div>
                      </div>
                      <a-collapse v-else-if="toolFn(tool).parameters" ghost size="small">
                        <a-collapse-panel key="params" header="parameters (JSON)">
                          <pre class="json-block">{{ JSON.stringify(toolFn(tool).parameters, null, 2) }}</pre>
                        </a-collapse-panel>
                      </a-collapse>
                    </template>
                  </div>
                </div>
              </div>
              <div v-if="nonSystemMessages(call.input?.messages).length" class="debug-messages">
                <div
                  v-for="(msg, mi) in nonSystemMessages(call.input?.messages)"
                  :key="'msg-' + mi"
                  :class="['debug-msg-block', `debug-msg-${msg.role || 'unknown'}`]"
                >
                  <div
                    class="debug-msg-block-head"
                    @click="toggleDebugMsgCard(`${call.call_id}-msg-${mi}`)"
                  >
                    <CaretRightOutlined v-if="!isDebugMsgExpanded(`${call.call_id}-msg-${mi}`)" style="font-size: 10px;" />
                    <CaretDownOutlined v-else style="font-size: 10px;" />
                    <span class="debug-msg-role">{{ roleLabel(msg.role) }}</span>
                    <span v-if="!isDebugMsgExpanded(`${call.call_id}-msg-${mi}`)" class="debug-msg-preview">{{ msgPreview(msg) }}</span>
                  </div>
                  <template v-if="isDebugMsgExpanded(`${call.call_id}-msg-${mi}`)">
                    <pre v-if="msg.content" class="debug-msg-content">{{ formatContent(msg.content) }}</pre>
                    <div v-if="msg.tool_calls?.length" class="debug-tool-calls">
                      <div class="debug-sub-label">tool_calls</div>
                      <pre class="json-block">{{ JSON.stringify(msg.tool_calls, null, 2) }}</pre>
                    </div>
                    <div v-if="msg.role === 'tool'" class="debug-tool-meta">
                      <span v-if="msg.tool_call_id">tool_call_id: {{ msg.tool_call_id }}</span>
                      <span v-if="msg.name"> · name: {{ msg.name }}</span>
                    </div>
                  </template>
                </div>
              </div>
              <div class="debug-params">
                <a-tag>max_tokens: {{ call.input?.max_tokens ?? '—' }}</a-tag>
                <a-tag>temperature: {{ call.input?.temperature ?? '—' }}</a-tag>
              </div>
            </template>
          </div>

          <div class="debug-section">
            <div
              class="debug-section-head"
              @click="toggleDebugSection(`${call.call_id}-output`)"
            >
              <CaretRightOutlined v-if="!isDebugSectionExpanded(`${call.call_id}-output`)" style="font-size: 10px;" />
              <CaretDownOutlined v-else style="font-size: 10px;" />
              <span class="debug-section-label">输出</span>
              <span v-if="!isDebugSectionExpanded(`${call.call_id}-output`)" class="debug-section-summary">
                · {{ outputSectionSummary(call) }}
              </span>
            </div>
            <template v-if="isDebugSectionExpanded(`${call.call_id}-output`)">
              <a-alert
                v-if="call.output?.raw_error"
                type="error"
                show-icon
                :message="call.output.raw_error"
                style="margin-bottom: 8px;"
              />
              <div v-if="call.output?.reasoning_content" class="debug-reasoning">
                <div class="debug-sub-label">推理内容</div>
                <pre class="debug-msg-content">{{ formatContent(call.output.reasoning_content) }}</pre>
              </div>
              <pre v-if="call.output?.content" class="debug-msg-content">{{ formatContent(call.output.content) }}</pre>
              <div v-if="call.output?.tool_calls?.length" class="debug-tool-calls">
                <div class="debug-sub-label">tool_calls</div>
                <pre class="json-block">{{ JSON.stringify(call.output.tool_calls, null, 2) }}</pre>
              </div>
              <div v-if="call.output?.usage && Object.keys(call.output.usage).length" class="debug-usage">
                <a-tag v-for="(val, key) in call.output.usage" :key="key">{{ key }}: {{ val }}</a-tag>
              </div>
              <div
                v-if="!call.output?.raw_error && !call.output?.content && !call.output?.tool_calls?.length && !call.output?.reasoning_content"
                class="debug-empty-inline"
              >
                （无输出内容）
              </div>
            </template>
          </div>

          <div class="debug-call-time">
            <span v-if="formatCallTime(call.created_at)">{{ formatCallTime(call.created_at) }}</span>
            <span v-if="call.duration_ms != null"> · 执行耗时 {{ formatDuration(call.duration_ms) }}</span>
          </div>
        </a-card>
      </div>
    </a-drawer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowLeftOutlined, CaretRightOutlined, CaretDownOutlined,
  ThunderboltOutlined, SendOutlined, PlusOutlined, DownloadOutlined,
  FileOutlined, CloseOutlined, LoadingOutlined, StopOutlined, PaperClipOutlined,
  CopyOutlined,
} from '@ant-design/icons-vue'
import { agentApi, sessionApi, hitlApi, skillApi, inboxApi, monitorApi } from '../../api'
import { useAuthStore } from '../../stores/auth'
import { message } from 'ant-design-vue'
import { marked } from 'marked'
import hljs from 'highlight.js/lib/core'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import CodeExecutionCard from '../../components/CodeExecutionCard.vue'
import LlmTurnCards from '../../components/LlmTurnCards.vue'
import ExecutionStoryPanel from '../../components/ExecutionStoryPanel.vue'
import 'highlight.js/styles/github-dark.css'
import {
  watchBackgroundSession,
  setActiveViewing,
  unwatchBackgroundSession,
} from '../../composables/useBackgroundSessions'
import { formatRelativeTime, formatLocaleString } from '../../utils/datetime'
import { normalizeExecutionStory, synthesizeStoryFromSteps } from '../../utils/executionStory'
import { normalizeLlmTurns, turnsFromLlmCalls, turnsFromThinkingSteps, enrichTurnsWithCodeExecutions } from '../../utils/llmTurns'

hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)

marked.setOptions({
  breaks: true,
  gfm: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch (_) { /* ignore */ }
    }
    try {
      return hljs.highlightAuto(code).value
    } catch (_) {
      return code
    }
  },
})

const route = useRoute()
const auth = useAuthStore()
const agentId = route.params.id
const agent = reactive({})
const sessionId = ref('')
const messages = ref([])
const inputText = ref('')
const sending = ref(false)
const thinkingExpanded = ref(false)
const msgContainer = ref(null)
const inputRef = ref(null)
const inputWrapper = ref(null)
const skillMenuRef = ref(null)
const fileInput = ref(null)

const ACCEPT_TYPES = '.pdf,.docx,.doc,.txt,.md,.markdown,.xlsx,.xls,.png,.jpg,.jpeg,.webp,.gif'
const pendingAttachments = ref([])
const uploadingAttachment = ref(false)

const readyAttachments = computed(() =>
  pendingAttachments.value.filter(a => a.attachment_id && !a.uploading)
)
const hasUploadingAttachments = computed(() =>
  pendingAttachments.value.some(a => a.uploading)
)

const skills = ref([])
const activeSkill = ref(null)
const activeSkillId = ref(null)
const showSkillMenu = ref(false)
const skillMenuIndex = ref(0)
const slashQuery = ref('')
const timeoutSeconds = ref(180)
const executionMode = ref('auto')
const skipHistory = ref(false)
const creatingSession = ref(false)
const sessions = ref([])
const loadingSessions = ref(false)
const currentSessionStatus = ref('ACTIVE')
const aborting = ref(false)
let sessionPollTimer = null

const debugOpen = ref(false)
const llmCalls = ref([])
const loadingLlmCalls = ref(false)
let debugPollTimer = null

const sourceLabelMap = {
  react: 'ReAct',
  plan: 'Plan & Execute',
  direct: '直接对话',
  coordinator: 'Coordinator',
  workflow: '工作流',
  workflow_llm: '工作流 LLM',
  tool_assess: '工具质检',
  query_rewrite: 'Query 改写',
}

function sourceLabel(source) {
  return sourceLabelMap[source] || source || '未知'
}

function roleLabel(role) {
  const map = { system: 'System', user: 'User', assistant: 'Assistant', tool: 'Tool' }
  return map[role] || role || 'Unknown'
}

function systemMessages(messages) {
  return (messages || []).filter(m => m.role === 'system')
}

function nonSystemMessages(messages) {
  return (messages || []).filter(m => m.role !== 'system')
}

function toolFn(tool) {
  return tool?.function || tool || {}
}

function toolParamEntries(tool) {
  const params = toolFn(tool).parameters || {}
  const properties = params.properties
  if (!properties || typeof properties !== 'object') return []
  const required = new Set(params.required || [])
  return Object.entries(properties).map(([name, def]) => ({
    name,
    type: (def && def.type) || 'any',
    description: (def && def.description) || '',
    required: required.has(name),
  }))
}

const expandedToolCards = ref(new Set())
const expandedDebugSections = ref(new Set())
const expandedDebugMsgCards = ref(new Set())

function isToolCardExpanded(key) {
  return expandedToolCards.value.has(key)
}

function toggleToolCard(key) {
  const next = new Set(expandedToolCards.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedToolCards.value = next
}

function isDebugSectionExpanded(key) {
  return expandedDebugSections.value.has(key)
}

function toggleDebugSection(key) {
  const next = new Set(expandedDebugSections.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedDebugSections.value = next
}

function isDebugMsgExpanded(key) {
  return expandedDebugMsgCards.value.has(key)
}

function toggleDebugMsgCard(key) {
  const next = new Set(expandedDebugMsgCards.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedDebugMsgCards.value = next
}

function contentPreview(content, maxLen = 80) {
  const text = formatContent(content).replace(/\s+/g, ' ').trim()
  if (!text) return '（无内容）'
  return text.length > maxLen ? `${text.slice(0, maxLen)}…` : text
}

function msgPreview(msg) {
  if (msg?.content) return contentPreview(msg.content)
  if (msg?.tool_calls?.length) return `tool_calls (${msg.tool_calls.length})`
  if (msg?.role === 'tool' && msg.tool_call_id) return `tool_call_id: ${msg.tool_call_id}`
  return '（无内容）'
}

function inputSectionSummary(call) {
  const msgCount = (call.input?.messages || []).length
  const toolCount = (call.input?.tools || []).length
  const parts = [`${msgCount} 条消息`]
  if (toolCount) parts.push(`${toolCount} 个 Tools`)
  return parts.join(' · ')
}

function outputSectionSummary(call) {
  if (call.output?.raw_error) return '错误'
  const tokens = tokenTotal(call)
  if (tokens) return `${tokens} tokens`
  if (call.output?.tool_calls?.length) return '有 tool_calls'
  if (call.output?.content || call.output?.reasoning_content) return '有内容'
  return '无输出'
}

function formatDuration(ms) {
  if (ms == null) return ''
  const n = Number(ms)
  if (Number.isNaN(n)) return ''
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s (${n}ms)`
  return `${n}ms`
}

function formatContent(content) {
  if (content == null) return ''
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content.map(part => {
      if (typeof part === 'string') return part
      if (part?.type === 'text') return part.text || ''
      return JSON.stringify(part, null, 2)
    }).join('\n')
  }
  return JSON.stringify(content, null, 2)
}

function tokenTotal(call) {
  return call.output?.usage?.total_tokens || 0
}

function formatCallTime(iso) {
  return formatLocaleString(iso, '')
}

async function fetchLlmCalls() {
  if (!sessionId.value) {
    llmCalls.value = []
    return
  }
  loadingLlmCalls.value = true
  try {
    const res = await sessionApi.llmCalls(sessionId.value)
    llmCalls.value = res.items || []
  } catch (e) {
    console.error('加载 LLM 调用记录失败:', e)
  } finally {
    loadingLlmCalls.value = false
  }
}

function startDebugPollIfNeeded() {
  stopDebugPoll()
  if (debugOpen.value && isRunning.value) {
    debugPollTimer = setInterval(fetchLlmCalls, 2500)
  }
}

function stopDebugPoll() {
  if (debugPollTimer) {
    clearInterval(debugPollTimer)
    debugPollTimer = null
  }
}

async function openDebugDrawer() {
  debugOpen.value = true
  await fetchLlmCalls()
  startDebugPollIfNeeded()
}

const isRunning = computed(() => currentSessionStatus.value === 'RUNNING')
const isHitlWait = computed(() => currentSessionStatus.value === 'HITL_WAIT')
const canAbort = computed(() => isRunning.value || isHitlWait.value)
const isSending = computed(() => sending.value || isRunning.value)

const liveTurnsPreview = ref([])
const liveLlmTurns = computed(() => normalizeLlmTurns(liveTurnsPreview.value) || [])

/** Placeholder turn while waiting for first LLM call to flush */
const livePlaceholderTurns = computed(() => {
  const modeLabel = executionModeOptions.find(o => o.value === executionMode.value)?.label || executionMode.value
  return [{
    turn_id: 'live_pending',
    seq: 1,
    source: executionMode.value === 'direct' ? 'direct' : 'react',
    input: {
      messages: [{ role: 'user', content: (inputText.value || '').trim().slice(0, 200) || '…' }],
      summary: '等待模型响应…',
      has_system: true,
      tools_count: 0,
    },
    thinking: null,
    response: { content: `执行模式: ${modeLabel} · 正在调用大模型…`, tool_calls: null },
    tool_results: [],
  }]
})

const showLiveProgress = computed(() => {
  if (!isSending.value) return false
  const last = messages.value[messages.value.length - 1]
  // Final/in-progress assistant bubble already has turn cards
  if (last?.role === 'assistant' && last._llmTurns?.length) return false
  if (liveLlmTurns.value.length) return true
  if (
    last?.role === 'assistant'
    && !last.content
    && (last._executionStory || last._thinkingSteps?.length)
  ) {
    return false
  }
  return true
})

watch(debugOpen, (open) => {
  if (open) {
    startDebugPollIfNeeded()
  } else {
    stopDebugPoll()
  }
})

watch(isRunning, () => {
  if (debugOpen.value) {
    startDebugPollIfNeeded()
    if (!isRunning.value) {
      fetchLlmCalls()
    }
  }
})

async function submitFeedback(messageIndex, rating) {
  if (!sessionId.value) return
  try {
    await monitorApi.submitFeedback({
      session_id: sessionId.value,
      agent_id: agentId.value,
      message_index: messageIndex,
      rating,
    })
    message.success(rating > 0 ? '感谢反馈' : '已记录差评')
  } catch (e) {
    message.error(e.message || '反馈失败')
  }
}

async function abortCurrentSession() {
  if (!sessionId.value || !canAbort.value || aborting.value) return
  aborting.value = true
  try {
    const res = await sessionApi.abort(sessionId.value)
    message.success(res.message || '已请求中止')
    if (res.status) {
      currentSessionStatus.value = res.status
    }
    startSessionPollIfNeeded()
    await fetchSessions()
    const s = await sessionApi.get(sessionId.value)
    currentSessionStatus.value = s.status
    if (s.messages) {
      messages.value = mapSessionMessages(s.messages)
    }
  } catch (e) {
    message.error(e.message || '中止失败')
  } finally {
    aborting.value = false
  }
}

function sessionStatusLabel(status) {
  const map = {
    ACTIVE: '活跃',
    RUNNING: '运行中',
    HITL_WAIT: '待审批',
    ERROR: '错误',
    CLOSED: '已关闭',
    IDLE: '空闲',
  }
  return map[status] || status
}

function sessionStatusColor(status) {
  const map = {
    ACTIVE: 'green',
    RUNNING: 'orange',
    HITL_WAIT: 'gold',
    ERROR: 'red',
  }
  return map[status] || 'default'
}

function parseThinkingSteps(thinking) {
  if (!thinking || typeof thinking !== 'string') return []
  const lines = thinking.split('\n')
  const steps = []

  const looksLikeNewStep = (trimmed) => (
    /^工具\s*\[/.test(trimmed)
    || /^\[QueryRewrite\]/i.test(trimmed)
    || /^\[Memory\]/i.test(trimmed)
    || /^\[ReAct/i.test(trimmed)
    || /^\[Direct\]/i.test(trimmed)
    || /^\[Plan-and-Execute\]/i.test(trimmed)
    || /^\[规划\]/.test(trimmed)
    || /^思考:/.test(trimmed)
    || /^计划内容:/.test(trimmed)
    || /^\[TIMEOUT\]/.test(trimmed)
    || /^\[中止\]/.test(trimmed)
    || /^\[LLM/.test(trimmed)
    || /^\[文件\]/.test(trimmed)
    || /^\[代码执行\]/.test(trimmed)
    || /^\[UI技能\]/.test(trimmed)
    || /^调用\s+\d+\s*个工具/.test(trimmed)
    || /^执行步骤/.test(trimmed)
  )

  const classify = (line) => {
    const trimmed = line.trim()
    if (!trimmed) return null

    const toolMatch = trimmed.match(/^工具\s*\[([^\]]+)\]\s*(?:结果:|:)\s*(.*)$/)
    if (toolMatch) {
      const toolName = toolMatch[1]
      const stepType = (toolName === 'execute_code' || toolName === 'install_packages')
        ? 'code_exec'
        : 'tool'
      return {
        type: stepType,
        toolName,
        text: toolMatch[2] || '',
        expanded: false,
      }
    }

    if (/^\[QueryRewrite\]/i.test(trimmed) || /^原文:/.test(trimmed) || /^改写:/.test(trimmed)) {
      return { type: 'rewrite', text: trimmed, expanded: false }
    }
    if (/^\[Memory\]/i.test(trimmed)) {
      return { type: 'memory', text: trimmed, expanded: false }
    }
    if (/^\[ReAct/i.test(trimmed) || /^\[Direct\]/i.test(trimmed) || /^\[Plan-and-Execute\]/i.test(trimmed)) {
      return { type: 'phase', text: trimmed, expanded: false }
    }
    if (/^思考:/.test(trimmed) || /^\[规划\]/.test(trimmed) || /^计划内容:/.test(trimmed)) {
      return { type: 'thought', text: trimmed, expanded: false }
    }
    if (/^\[TIMEOUT\]/.test(trimmed) || /^\[中止\]/.test(trimmed)) {
      return { type: 'error', text: trimmed, expanded: false }
    }
    if (/^调用\s+\d+\s*个工具/.test(trimmed) || /^执行步骤/.test(trimmed)) {
      return { type: 'action', text: trimmed, expanded: false }
    }
    return { type: 'info', text: trimmed, expanded: false }
  }

  for (const raw of lines) {
    const trimmed = raw.trim()
    if (!trimmed) continue

    const indented = /^\s/.test(raw)
    if (
      steps.length
      && !looksLikeNewStep(trimmed)
      && (indented || steps[steps.length - 1].type === 'tool' || steps[steps.length - 1].type === 'rewrite')
    ) {
      steps[steps.length - 1].text = `${steps[steps.length - 1].text}\n${trimmed}`.trim()
      continue
    }

    const step = classify(raw)
    if (step) steps.push(step)
  }
  return steps
}

function thinkingSummary(thinkingOrSteps) {
  const steps = Array.isArray(thinkingOrSteps)
    ? thinkingOrSteps
    : parseThinkingSteps(thinkingOrSteps || '')
  if (!steps.length) return ''
  const toolCount = steps.filter(s => s.type === 'tool').length
  const parts = [`${steps.length} 步`]
  if (toolCount) parts.push(`调用 ${toolCount} 个工具`)
  return parts.join(' · ')
}

function thinkingStepColor(type) {
  const map = {
    rewrite: 'cyan',
    memory: 'purple',
    phase: 'blue',
    thought: 'default',
    tool: 'geekblue',
    code_exec: 'purple',
    action: 'orange',
    error: 'red',
    info: 'default',
  }
  return map[type] || 'default'
}

function thinkingStepLabel(step) {
  if (step.type === 'code_exec') return `代码 · ${step.toolName || 'execute_code'}`
  if (step.type === 'tool') return `工具 · ${step.toolName || 'unknown'}`
  const map = {
    rewrite: 'QueryRewrite',
    memory: 'Memory',
    phase: '阶段',
    thought: '思考',
    action: '动作',
    error: '异常',
    info: '日志',
  }
  return map[step.type] || '步骤'
}

/** 识别「摘要答案 / 搜索结果」结构，返回卡片数据；否则 null */
function parseSearchContent(content) {
  if (!content || typeof content !== 'string') return null
  const text = content.trim()
  if (!/(摘要答案|搜索结果)/.test(text)) return null
  // 避免把普通 Markdown 回复误判：需有明确区块标题
  const hasAnswerHeader = /(?:^|\n)##?\s*摘要答案\s*:?\s*(?:\n|$)/m.test(text)
    || /(?:^|\n)摘要答案\s*:?\s*(?:\n|$)/m.test(text)
  const hasResultsHeader = /(?:^|\n)##?\s*搜索结果\s*:?\s*(?:\n|$)/m.test(text)
    || /(?:^|\n)搜索结果\s*:?\s*(?:\n|$)/m.test(text)
  if (!hasAnswerHeader && !hasResultsHeader) return null

  let answer = ''
  const results = []

  const answerMatch = text.match(/(?:##?\s*)?摘要答案\s*:?\s*\n+([\s\S]*?)(?=(?:\n(?:##?\s*)?搜索结果\s*:?\s*(?:\n|$))|$)/)
  if (answerMatch) {
    answer = answerMatch[1].trim()
  }

  const resultsBlockMatch = text.match(/(?:##?\s*)?搜索结果\s*:?\s*\n+([\s\S]*)$/)
  const resultsBlock = resultsBlockMatch ? resultsBlockMatch[1].trim() : ''

  if (resultsBlock) {
    // Markdown: ### 1. title  / - 链接: / - 摘要:
    const mdItems = resultsBlock.split(/(?=###\s*\d+\.)/).filter(Boolean)
    if (mdItems.length && /###\s*\d+\./.test(resultsBlock)) {
      for (const block of mdItems) {
        const titleM = block.match(/###\s*\d+\.\s*(.+)/)
        const linkM = block.match(/链接\s*[:：]\s*(?:\[[^\]]*\]\()?(\S+?)\)?(?:\s|$)/m)
          || block.match(/https?:\/\/\S+/)
        const snipM = block.match(/(?:摘要|内容)\s*[:：]\s*([\s\S]*?)(?=\n\s*[-*]|\n###|$)/)
        results.push({
          title: (titleM?.[1] || '').trim(),
          url: (typeof linkM?.[1] === 'string' ? linkM[1] : linkM?.[0] || '').replace(/[)\].,]+$/, ''),
          snippet: (snipM?.[1] || '').trim(),
        })
      }
    } else {
      // Plain: 1. title\n   链接: url\n   内容: ...
      const plainItems = resultsBlock.split(/(?=^\d+\.\s)/m).filter(s => /^\d+\.\s/.test(s.trim()))
      for (const block of plainItems) {
        const titleM = block.match(/^\d+\.\s*(.+)$/m)
        const linkM = block.match(/链接\s*[:：]\s*(\S+)/)
        const snipM = block.match(/内容\s*[:：]\s*([\s\S]*?)(?=\n\s*\d+\.\s|$)/)
          || block.match(/摘要\s*[:：]\s*([\s\S]*?)(?=\n\s*\d+\.\s|$)/)
        results.push({
          title: (titleM?.[1] || '').trim(),
          url: (linkM?.[1] || '').trim(),
          snippet: (snipM?.[1] || '').trim(),
        })
      }
    }
  }

  if (!answer && !results.length) return null
  return { answer, results }
}

/** ReAct 中间轨迹：tool 消息、仅用于发起工具调用的 assistant 消息 */
function isIntermediateMessage(msg) {
  if (msg.role === 'tool') return true
  if (msg.role !== 'assistant') return false
  const toolCalls = msg.tool_calls || msg.toolCalls
  return (toolCalls && toolCalls.length > 0) || !(msg.content || '').trim()
}

/** 把中间消息按顺序转成思考步骤，tool_call_id 反查工具名 */
function intermediateToSteps(buffer) {
  const toolNameById = {}
  const steps = []
  for (const msg of buffer) {
    if (msg.role === 'assistant') {
      for (const tc of (msg.tool_calls || msg.toolCalls || [])) {
        if (tc?.id) toolNameById[tc.id] = tc.function?.name || tc.name || 'unknown'
      }
      const text = (msg.content || '').trim()
      if (text) steps.push({ type: 'thought', text, expanded: false })
    } else if (msg.role === 'tool') {
      steps.push({
        type: 'tool',
        toolName: toolNameById[msg.tool_call_id] || msg.name || 'unknown',
        text: (msg.content || '').trim(),
        expanded: false,
      })
    }
  }
  return steps
}

/** 后端 thinking 里的工具结果被截断到 200 字，用 tool 消息全文补齐 */
function mergeToolResults(thinkingSteps, intermediateSteps) {
  const fullByName = new Map()
  for (const step of intermediateSteps) {
    if (step.type !== 'tool') continue
    if (!fullByName.has(step.toolName)) fullByName.set(step.toolName, [])
    fullByName.get(step.toolName).push(step.text)
  }

  const usedByName = new Map()
  const merged = thinkingSteps.map(step => {
    if (step.type !== 'tool') return step
    const queue = fullByName.get(step.toolName)
    const used = usedByName.get(step.toolName) || 0
    if (!queue || used >= queue.length) return step
    usedByName.set(step.toolName, used + 1)
    const full = queue[used]
    return full.length > step.text.length ? { ...step, text: full } : step
  })

  for (const [name, queue] of fullByName) {
    for (let i = usedByName.get(name) || 0; i < queue.length; i++) {
      merged.push({ type: 'tool', toolName: name, text: queue[i], expanded: false })
    }
  }
  return merged
}

function attachSearchCards(steps) {
  return steps.map(step => (
    step.type === 'tool' ? { ...step, searchCard: parseSearchContent(step.text) } : step
  ))
}

function normalizeMessage(msg, intermediateSteps) {
  const thinking = msg.thinking || ''
  const baseSteps = parseThinkingSteps(thinking)
  const steps = baseSteps.length
    ? mergeToolResults(baseSteps, intermediateSteps)
    : intermediateSteps
  const enrichedSteps = attachSearchCards(steps)

  let llmTurns = normalizeLlmTurns(msg.llmTurns || msg.llm_turns)
  if (!llmTurns?.length) {
    llmTurns = turnsFromThinkingSteps(enrichedSteps)
  }
  const codeExecutions = msg.codeExecutions || msg.code_executions || []
  if (llmTurns?.length) {
    llmTurns = enrichTurnsWithCodeExecutions(llmTurns, codeExecutions)
  }

  let executionStory = normalizeExecutionStory(msg.executionStory || msg.execution_story)
  if (!executionStory && !llmTurns?.length && enrichedSteps.length) {
    const status = msg.pendingApprovalId || msg.pending_approval_id
      ? 'hitl_wait'
      : (msg.content ? 'done' : 'running')
    executionStory = synthesizeStoryFromSteps(enrichedSteps, {
      status,
      metrics: msg.runMetrics || msg.run_metrics || null,
    })
  }

  return {
    ...msg,
    thinking,
    thinkingExpanded: false,
    _thinkingSteps: enrichedSteps,
    _llmTurns: llmTurns,
    _executionStory: executionStory,
    traceExpanded: true,
    executionTrace: msg.executionTrace || msg.execution_trace || [],
    executionMode: msg.executionMode || msg.execution_mode || '',
    activeSkill: msg.activeSkill || msg.active_skill || null,
    runMetrics: msg.runMetrics || msg.run_metrics || null,
    files: msg.files || [],
    filesTruncated: msg.filesTruncated || msg.files_truncated || false,
    codeExecutions,
    pendingApprovalId: msg.pendingApprovalId || msg.pending_approval_id || null,
    pendingDelivery: msg.pendingDelivery || msg.pending_delivery || false,
    pendingWorkflow: msg.pendingWorkflow || msg.pending_workflow || false,
    pendingToolName: msg.pendingToolName || msg.pending_tool_name || '',
    previewPayload: msg.previewPayload || msg.preview_payload || null,
    pendingOtp: msg.pendingOtp || msg.pending_otp
      || (msg.previewPayload || msg.preview_payload || {})?.flow_kind === 'otp_wait',
    pendingSkillParams: msg.pendingSkillParams || msg.pending_skill_params
      || (msg.previewPayload || msg.preview_payload || {})?.flow_kind === 'skill_params',
    otpCode: msg.otpCode || '',
    skillParamValues: msg.skillParamValues || (() => {
      const missing = (msg.previewPayload || msg.preview_payload || {})?.missing_params || []
      const filled = (msg.previewPayload || msg.preview_payload || {})?.filled_params || {}
      const init = {}
      missing.forEach((k) => { init[k] = filled[k] || '' })
      return init
    })(),
    approvalStatus: msg.approvalStatus || null,
    approvalFinalResult: msg.approvalFinalResult || '',
  }
}

function mapSessionMessages(msgs) {
  const out = []
  let buffer = []

  const flushBuffer = () => {
    if (!buffer.length) return
    const steps = intermediateToSteps(buffer)
    // If the turn ends while the last assistant still has tool_calls, promote its
    // text (or a fallback) as the formal reply — otherwise UI shows only thinking.
    let formal = ''
    for (let i = buffer.length - 1; i >= 0; i--) {
      const m = buffer[i]
      if (m.role === 'assistant' && (m.content || '').trim()) {
        formal = (m.content || '').trim()
        break
      }
    }
    if (!formal && steps.length) {
      const toolSteps = steps.filter((s) => s.type === 'tool')
      const lastTool = toolSteps[toolSteps.length - 1]
      if (lastTool) {
        formal = `执行已结束。最后调用工具「${lastTool.toolName}」，请展开上方过程查看详情。`
      } else {
        formal = '执行已结束，请展开上方思考与执行过程查看详情。'
      }
    }
    buffer = []
    if (steps.length || formal) {
      out.push(normalizeMessage({ role: 'assistant', content: formal }, steps))
    }
  }

  for (const msg of (msgs || [])) {
    if (isIntermediateMessage(msg)) {
      buffer.push(msg)
      continue
    }
    if (msg.role === 'assistant') {
      out.push(normalizeMessage(msg, intermediateToSteps(buffer)))
      buffer = []
    } else {
      flushBuffer()
      out.push(normalizeMessage(msg, []))
    }
  }
  flushBuffer()

  return out
}

async function loadSessionById(id) {
  const s = await sessionApi.get(id)
  currentSessionStatus.value = s.status
  messages.value = mapSessionMessages(s.messages)
  enrichMessagesWithSessionLlmCalls(s)
  liveTurnsPreview.value = s.pending_context?.llm_turns || []
  await nextTick()
  scrollToBottom()
}

function enrichMessagesWithSessionLlmCalls(session) {
  if (!session?.llm_calls?.length) return
  const mapped = messages.value
  // Attach session llm_calls as turns to the last assistant without llmTurns
  const lastAssistant = [...mapped].reverse().find((m) => m.role === 'assistant')
  if (lastAssistant && !lastAssistant._llmTurns?.length) {
    lastAssistant._llmTurns = turnsFromLlmCalls(session.llm_calls)
  }
}

async function refreshCurrentSession() {
  if (!sessionId.value) return
  try {
    const s = await sessionApi.get(sessionId.value)
    const prevStatus = currentSessionStatus.value
    currentSessionStatus.value = s.status
    messages.value = mapSessionMessages(s.messages)
    enrichMessagesWithSessionLlmCalls(s)
    liveTurnsPreview.value = (s.status === 'RUNNING' || s.status === 'HITL_WAIT')
      ? (s.pending_context?.llm_turns || [])
      : []

    const idx = sessions.value.findIndex(x => x.session_id === s.session_id)
    if (idx >= 0) {
      sessions.value[idx] = s
    } else if ((s.messages || []).length > 0 || s.status === 'RUNNING') {
      sessions.value.unshift(s)
    }

    if (prevStatus === 'RUNNING' && s.status !== 'RUNNING') {
      try {
        await inboxApi.markSessionRead(sessionId.value)
      } catch (e) {
        console.error('[inbox] mark session read failed:', e)
      }
      unwatchBackgroundSession(sessionId.value)
      await fetchSessions()
      if (s.status === 'HITL_WAIT') {
        startSessionPollIfNeeded()
      } else {
        stopSessionPoll()
      }
    } else if (prevStatus === 'HITL_WAIT' && s.status === 'RUNNING') {
      watchBackgroundSession(sessionId.value, agentId, agent.name)
      startSessionPollIfNeeded()
    }
    await nextTick()
    scrollToBottom()
  } catch (e) {
    console.error('刷新会话失败:', e)
  }
}

function startSessionPollIfNeeded() {
  stopSessionPoll()
  // Also poll HITL_WAIT so inbox/other-tab approve can resume UI progress here.
  if (currentSessionStatus.value === 'RUNNING' || currentSessionStatus.value === 'HITL_WAIT') {
    sessionPollTimer = setInterval(refreshCurrentSession, 2500)
  }
}

function stopSessionPoll() {
  if (sessionPollTimer) {
    clearInterval(sessionPollTimer)
    sessionPollTimer = null
  }
}
const executionModeOptions = [
  { label: '自动选择模式', value: 'auto' },
  { label: 'ReAct 模式', value: 'react' },
  { label: 'Plan & Execute', value: 'plan_and_execute' },
  { label: '直接对话', value: 'direct' },
]

// 文件预览相关状态
const previewVisible = ref(false)
const previewFileName = ref('')
const previewFileUrl = ref('')
const previewFileTruncated = ref(false)
const previewType = ref('')
const previewContent = ref('')
const previewLoading = ref(false)
const csvData = ref([])
const previewWidth = ref(900)
const previewHeight = ref(600)
const previewBodyRef = ref(null)
let isResizing = false
let resizeStartX = 0
let resizeStartY = 0
let resizeStartW = 0
let resizeStartH = 0

const filteredSkills = computed(() => {
  if (!slashQuery.value) return skills.value
  const q = slashQuery.value.toLowerCase()
  return skills.value.filter(s =>
    s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q)
  )
})

onMounted(async () => {
  try {
    const a = await agentApi.get(agentId)
    Object.assign(agent, a)
    if (a.timeout_seconds) {
      timeoutSeconds.value = a.timeout_seconds
    }

    skills.value = (await skillApi.list({ page_size: 100 })).items || []

    const querySessionId = route.query.session_id
    if (querySessionId) {
      sessionId.value = querySessionId
      await loadSessionById(querySessionId)
    } else {
      const session = await sessionApi.create({
        agent_id: agentId,
        caller_type: 'web_playground',
        caller_id: auth.user?.user_id || '',
      })
      sessionId.value = session.session_id
      currentSessionStatus.value = session.status || 'ACTIVE'
    }

    setActiveViewing(sessionId.value, agentId)
    await fetchSessions()
    startSessionPollIfNeeded()
  } catch (e) {
    message.error(e.message)
  }
})

async function fetchSessions() {
  loadingSessions.value = true
  try {
    const res = await sessionApi.list({ agent_id: agentId, page_size: 50 })
    sessions.value = (res.items || []).filter(
      s => (s.messages || []).length > 0 || s.status === 'RUNNING'
    )
  } catch (e) {
    console.error('获取会话列表失败:', e)
  } finally {
    loadingSessions.value = false
  }
}

async function switchSession(s) {
  if (s.session_id === sessionId.value) return
  sessionId.value = s.session_id
  setActiveViewing(sessionId.value, agentId)
  activeSkill.value = null
  activeSkillId.value = null
  skipHistory.value = false
  pendingAttachments.value = []
  try {
    await loadSessionById(s.session_id)
    startSessionPollIfNeeded()
  } catch (e) {
    message.error(e.message)
  }
}

/** Backend stores UTC; naive ISO strings must be treated as UTC for local relative time. */
function formatTime(t) {
  return formatRelativeTime(t, '')
}

async function createNewSession() {
  try {
    creatingSession.value = true
    const session = await sessionApi.create({
      agent_id: agentId,
      caller_type: 'web_playground',
      caller_id: auth.user?.user_id || '',
    })
    sessionId.value = session.session_id
    messages.value = []
    currentSessionStatus.value = session.status || 'ACTIVE'
    setActiveViewing(sessionId.value, agentId)
    stopSessionPoll()
    activeSkill.value = null
    activeSkillId.value = null
    skipHistory.value = false
    pendingAttachments.value = []
    await fetchSessions()
    message.success('新会话已创建')
  } catch (e) {
    message.error(e.message)
  } finally {
    creatingSession.value = false
  }
}

function onInput(e) {
  const val = e.target?.value || inputText.value
  const cursorPos = e.target?.selectionStart || 0

  const beforeCursor = val.substring(0, cursorPos)
  const slashMatch = beforeCursor.match(/\/(\S*)$/)

  if (slashMatch) {
    slashQuery.value = slashMatch[1]
    showSkillMenu.value = true
    skillMenuIndex.value = 0
  } else {
    showSkillMenu.value = false
    slashQuery.value = ''
  }
}

function onEnter(e) {
  if (showSkillMenu.value) {
    e.preventDefault()
    if (filteredSkills.value.length > 0) {
      selectSkill(filteredSkills.value[skillMenuIndex.value])
    }
    return
  }
  if (!e.shiftKey) {
    e.preventDefault()
    if (canAbort.value) return
    sendMessage()
  }
}

function selectSkill(skill) {
  const val = inputText.value
  const cursorPos = inputRef.value?.$el?.querySelector('textarea')?.selectionStart || val.length
  const beforeCursor = val.substring(0, cursorPos)
  const afterCursor = val.substring(cursorPos)

  const slashIdx = beforeCursor.lastIndexOf('/')
  const newBefore = beforeCursor.substring(0, slashIdx)
  inputText.value = newBefore + afterCursor

  activeSkill.value = skill.name
  activeSkillId.value = skill.skill_pack_id
  showSkillMenu.value = false
  slashQuery.value = ''

  nextTick(() => {
    inputRef.value?.focus()
  })
}

function clearSkill() {
  activeSkill.value = null
  activeSkillId.value = null
}

// ---- 文件预览 ----

const TEXT_EXTENSIONS = new Set(['.txt', '.json', '.xml', '.drawio', '.dio', '.py', '.js', '.ts', '.css', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.sh', '.bat', '.log', '.env'])
const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp'])
const OFFICE_EXTENSIONS = new Set(['.docx', '.xlsx', '.pptx', '.doc', '.xls', '.ppt'])

function getPreviewType(filename) {
  const ext = filename.substring(filename.lastIndexOf('.')).toLowerCase()
  if (ext === '.html' || ext === '.htm') return 'html'
  if (ext === '.md' || ext === '.markdown') return 'markdown'
  if (ext === '.csv') return 'csv'
  if (ext === '.pdf') return 'pdf'
  if (IMAGE_EXTENSIONS.has(ext)) return 'image'
  if (OFFICE_EXTENSIONS.has(ext)) return 'office'
  if (TEXT_EXTENSIONS.has(ext)) return 'text'
  return 'text'
}

function hasTruncatedFiles(files) {
  return Array.isArray(files) && files.some(f => f.truncated)
}

function isImageFile(file) {
  if (!file?.name && !file?.url) return false
  const name = (file.name || file.url || '').toLowerCase()
  const dot = name.lastIndexOf('.')
  const ext = dot >= 0 ? name.slice(dot) : ''
  return IMAGE_EXTENSIONS.has(ext)
}

function imageFiles(files) {
  return (files || []).filter(isImageFile)
}

function nonImageFiles(files) {
  return (files || []).filter((f) => !isImageFile(f))
}

function wrapMarkdownImages(html) {
  if (!html || !/<img[\s>]/i.test(html)) return html

  // marked 常把「正文 + 多张图」放在同一个 <p> 内，需拆出图片区
  let out = html.replace(/<p>([\s\S]*?)<\/p>/gi, (match, inner) => {
    const imgs = inner.match(/<img[^>]*>/gi) || []
    if (!imgs.length) return match
    const textOnly = inner.replace(/<img[^>]*>/gi, '').trim()
    if (!textOnly) {
      return `<div class="chat-image-grid">${imgs.join('')}</div>`
    }
    return `<p>${textOnly}</p><div class="chat-image-grid">${imgs.join('')}</div>`
  })

  // 连续「仅含图片」的段落
  out = out.replace(
    /((?:<p>\s*<img[^>]*>\s*<\/p>\s*)+)/gi,
    (block) => {
      const imgs = block.match(/<img[^>]*>/gi) || []
      return `<div class="chat-image-grid">${imgs.join('')}</div>`
    },
  )

  out = out.replace(/<img(?![^>]*class=)/gi, '<img class="chat-inline-image"')

  return out
}

async function previewFile(file) {
  previewVisible.value = true
  previewFileName.value = file.name
  previewFileUrl.value = file.url
  previewFileTruncated.value = !!file.truncated
  previewContent.value = ''
  previewLoading.value = true
  csvData.value = []

  const type = getPreviewType(file.name)
  previewType.value = type

  if (type === 'text' || type === 'markdown' || type === 'html' || type === 'csv' || type === 'json') {
    try {
      const resp = await fetch(file.url)
      if (!resp.ok) throw new Error('加载失败')
      const text = await resp.text()
      previewContent.value = text

      if (type === 'csv') {
        parseCsv(text)
      }
    } catch (e) {
      previewContent.value = '加载文件内容失败: ' + e.message
    }
  }

  previewLoading.value = false
}

function parseCsv(text) {
  const lines = text.trim().split('\n')
  const result = []
  for (const line of lines) {
    const cols = []
    let current = ''
    let inQuotes = false
    for (const ch of line) {
      if (ch === '"') {
        inQuotes = !inQuotes
      } else if (ch === ',' && !inQuotes) {
        cols.push(current.trim())
        current = ''
      } else {
        current += ch
      }
    }
    cols.push(current.trim())
    result.push(cols)
  }
  csvData.value = result
}

function closePreview() {
  previewVisible.value = false
  previewFileName.value = ''
  previewFileUrl.value = ''
  previewFileTruncated.value = false
  previewType.value = ''
  previewContent.value = ''
  csvData.value = []
}

function startResize(e) {
  if (!e.target.classList.contains('preview-resize-handle')) return
  isResizing = true
  resizeStartX = e.clientX
  resizeStartY = e.clientY
  resizeStartW = previewWidth.value
  resizeStartH = previewHeight.value
  document.addEventListener('mousemove', onResize)
  document.addEventListener('mouseup', onResizeEnd)
  e.preventDefault()
}

function onResize(e) {
  if (!isResizing) return
  const dx = e.clientX - resizeStartX
  const dy = e.clientY - resizeStartY
  previewWidth.value = Math.max(400, resizeStartW + dx)
  previewHeight.value = Math.max(300, resizeStartH + dy)
}

function onResizeEnd() {
  isResizing = false
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', onResizeEnd)
}

onUnmounted(() => {
  stopSessionPoll()
  stopDebugPoll()
  setActiveViewing(null, null)
  document.removeEventListener('mousemove', onResize)
  document.removeEventListener('mouseup', onResizeEnd)
})

async function sendMessage() {
  const text = inputText.value.trim()
  const attachmentIds = readyAttachments.value.map(a => a.attachment_id)
  if ((!text && !attachmentIds.length) || isSending.value) return
  if (hasUploadingAttachments.value) {
    message.warning('附件上传中，请稍候')
    return
  }

  const skillPackId = activeSkillId.value
  const skillName = activeSkill.value
  const displayText = text || '请分析附件'
  const attachmentMeta = readyAttachments.value.map(a => ({
    id: a.attachment_id,
    filename: a.filename,
  }))

  inputText.value = ''
  pendingAttachments.value = []
  showSkillMenu.value = false
  activeSkill.value = null
  activeSkillId.value = null
  messages.value.push({
    role: 'user',
    content: displayText,
    activeSkill: skillName || undefined,
    attachments: attachmentMeta.length ? attachmentMeta : undefined,
  })
  sending.value = true
  thinkingExpanded.value = false
  liveTurnsPreview.value = []

  await nextTick()
  scrollToBottom()

  try {
    const payload = {
      message: text,
      attachment_ids: attachmentIds,
      timeout_seconds: timeoutSeconds.value,
      execution_mode: executionMode.value,
      skip_history: skipHistory.value,
    }
    if (skillPackId) {
      payload.skill_pack_id = skillPackId
    }

    await sessionApi.chatAsync(sessionId.value, payload)
    currentSessionStatus.value = 'RUNNING'
    watchBackgroundSession(sessionId.value, agentId, agent.name)
    startSessionPollIfNeeded()
    await fetchSessions()
  } catch (e) {
    message.error(e.message)
  } finally {
    sending.value = false
  }
}

function triggerUpload() {
  if (!sessionId.value) {
    message.warning('请先创建或选择会话')
    return
  }
  fileInput.value?.click()
}

async function onFilesSelected(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length || !sessionId.value) return

  uploadingAttachment.value = true
  try {
    for (const file of files) {
      if (readyAttachments.value.length >= 5) {
        message.warning('单条消息最多 5 个附件')
        break
      }

      const tempId = `pending_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      pendingAttachments.value.push({
        tempId,
        filename: file.name,
        uploading: true,
      })

      try {
        const formData = new FormData()
        formData.append('file', file, file.name)
        const res = await sessionApi.uploadAttachment(sessionId.value, formData)
        const idx = pendingAttachments.value.findIndex(a => a.tempId === tempId)
        if (idx >= 0) {
          pendingAttachments.value[idx] = {
            attachment_id: res.attachment_id,
            filename: res.filename,
            is_image: res.is_image,
            uploading: false,
          }
        }
      } catch (e) {
        pendingAttachments.value = pendingAttachments.value.filter(a => a.tempId !== tempId)
        message.error(`上传失败 ${file.name}: ${e.message}`)
      }
    }
  } finally {
    uploadingAttachment.value = false
  }
}

function removeAttachment(att) {
  pendingAttachments.value = pendingAttachments.value.filter(a => {
    if (att.tempId) return a.tempId !== att.tempId
    return a.attachment_id !== att.attachment_id
  })
  if (att.attachment_id && sessionId.value) {
    sessionApi.deleteAttachment(sessionId.value, att.attachment_id).catch(() => {})
  }
}

async function submitOtpHitl(msg) {
  const code = (msg.otpCode || '').trim()
  if (!code) {
    message.warning('请输入验证码')
    return
  }
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: 'current_user',
      comment: '',
      otp_code: code,
    })
    msg.approvalStatus = 'approved'
    message.success(res.message || '验证码已提交')
    await afterHitlApproved(msg, res)
  } catch (e) {
    message.error('提交失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function submitSkillParamsHitl(msg) {
  const missing = msg.previewPayload?.missing_params || []
  const values = { ...(msg.skillParamValues || {}) }
  const still = missing.filter((k) => !(String(values[k] || '').trim()))
  if (still.length) {
    message.warning(`请填写：${still.join(', ')}`)
    return
  }
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: 'current_user',
      comment: '',
      param_values: values,
    })
    msg.approvalStatus = 'approved'
    message.success(res.message || '参数已提交，技能继续执行')
    await afterHitlApproved(msg, res)
  } catch (e) {
    message.error('提交失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function afterHitlApproved(msg, res) {
  if (res?.tool_result) {
    msg.approvalFinalResult = typeof res.tool_result === 'string'
      ? res.tool_result
      : JSON.stringify(res.tool_result)
  }
  if (res?.pending_approval_id) {
    msg.pendingApprovalId = res.pending_approval_id
    msg.approvalStatus = null
    if (res.preview_payload) {
      msg.previewPayload = res.preview_payload
    }
    currentSessionStatus.value = 'HITL_WAIT'
  } else if (res?.session_status === 'RUNNING') {
    currentSessionStatus.value = 'RUNNING'
    watchBackgroundSession(sessionId.value, agentId, agent.name)
    startSessionPollIfNeeded()
  }
  await refreshCurrentSession()
  if (currentSessionStatus.value === 'RUNNING') {
    watchBackgroundSession(sessionId.value, agentId, agent.name)
    startSessionPollIfNeeded()
  }
}

async function approveHitl(msg) {
  msg.approving = true
  try {
    const res = await hitlApi.approve(sessionId.value, msg.pendingApprovalId, {
      approved: true,
      reviewer: 'current_user',
      comment: '',
    })
    msg.approvalStatus = 'approved'
    if (res.kind === 'delivery') {
      msg.approvalFinalResult = res.final_result || ''
    } else if (res.kind === 'workflow') {
      msg.approvalFinalResult = res.final_result || ''
      if (res.execution_trace?.length) {
        msg.executionTrace = res.execution_trace
      }
      if (res.pending_approval_id) {
        msg.pendingApprovalId = res.pending_approval_id
        msg.approvalStatus = null
        msg.pendingWorkflow = true
        msg.content = res.final_result || msg.content
      }
    } else {
      await afterHitlApproved(msg, res)
      message.success(res.message || '已批准')
      return
    }
    message.success(res.message || '已批准')
    await refreshCurrentSession()
  } catch (e) {
    message.error('审批失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

async function rejectHitl(msg) {
  msg.approving = true
  try {
    const res = await hitlApi.reject(sessionId.value, msg.pendingApprovalId, {
      approved: false,
      reviewer: 'current_user',
      comment: '用户拒绝',
    })
    msg.approvalStatus = 'rejected'
    message.success(res.message || '已拒绝')
  } catch (e) {
    message.error('审批失败: ' + e.message)
  } finally {
    msg.approving = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

function copySessionId() {
  if (!sessionId.value) return
  navigator.clipboard.writeText(sessionId.value).then(() => {
    message.success('会话 ID 已复制')
  }).catch(() => {
    message.error('复制失败')
  })
}

function renderMarkdown(text) {
  if (!text) return ''
  return wrapMarkdownImages(marked.parse(text))
}
</script>

<style scoped>
.session-sidebar {
  width: 220px;
  min-width: 220px;
  background: #faf8f5;
  border-right: 1px solid #ddd8ce;
  display: flex;
  flex-direction: column;
  border-radius: 8px 0 0 0;
  overflow: hidden;
}
.session-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid #ddd8ce;
  background: #fff;
}
.session-sidebar-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.session-list-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.session-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}
.session-item:hover {
  background: #f0ede6;
}
.session-item.active {
  background: #e8e4dc;
}
.session-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.session-item-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: #5c5650;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 8px;
}
.session-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.session-item-msg-count {
  font-size: 11px;
  color: #9e9590;
}
.session-item-time {
  font-size: 11px;
  color: #b5afa8;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fff;
  border-bottom: 1px solid #ddd8ce;
  border-radius: 8px 8px 0 0;
}
.chat-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 16px;
  font-weight: 600;
  color: #1a1714;
  flex: 1;
}
.session-id-wrap {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.session-id-copy {
  color: #52c41a;
  padding: 0 4px;
  height: 22px;
}
.session-id-copy:hover {
  color: #389e0d;
  background: rgba(82, 196, 26, 0.08);
}
.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #fff;
  border-left: 1px solid #ddd8ce;
  border-right: 1px solid #ddd8ce;
}
.chat-msg {
  margin-bottom: 16px;
  max-width: 80%;
}
.chat-msg-user {
  margin-left: auto;
}
.chat-msg-role {
  font-size: 11px;
  color: #9e9590;
  margin-bottom: 4px;
}
.chat-msg-user .chat-msg-role {
  text-align: right;
}
.chat-msg-content {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
}
.chat-msg-assistant .chat-msg-content {
  background: #f3f0e8;
  color: #1a1714;
}
.chat-msg-user .chat-msg-content {
  background: #1a1714;
  color: #fff;
}
.user-skill-prefix {
  color: #ef4444;
  font-weight: 600;
}
.user-msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-msg-content :deep(p) {
  margin: 0 0 8px 0;
}
.chat-msg-content :deep(p:last-child) {
  margin-bottom: 0;
}
.chat-msg-content :deep(a) {
  color: #1a6fb5;
  text-decoration: underline;
}
.chat-msg-content :deep(a:hover) {
  color: #0d4f85;
}
.chat-msg-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
}
.chat-msg-content :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.chat-msg-content :deep(pre code) {
  background: none;
  padding: 0;
}
.chat-msg-content :deep(ul), .chat-msg-content :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}
.chat-msg-content :deep(li) {
  margin-bottom: 4px;
}
.chat-msg-content :deep(h1), .chat-msg-content :deep(h2),
.chat-msg-content :deep(h3), .chat-msg-content :deep(h4) {
  margin: 12px 0 6px 0;
  font-weight: 600;
}
.chat-msg-content :deep(h1) { font-size: 18px; }
.chat-msg-content :deep(h2) { font-size: 16px; }
.chat-msg-content :deep(h3) { font-size: 14px; }
.chat-msg-content :deep(h4) { font-size: 13px; }
.chat-msg-content :deep(hr) {
  border: none;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
  margin: 12px 0;
}
.chat-msg-content :deep(blockquote) {
  border-left: 3px solid rgba(0, 0, 0, 0.15);
  padding-left: 10px;
  margin: 8px 0;
  color: rgba(0, 0, 0, 0.6);
}
.chat-msg-content :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}
.chat-msg-content :deep(th), .chat-msg-content :deep(td) {
  border: 1px solid rgba(0, 0, 0, 0.1);
  padding: 6px 10px;
  text-align: left;
}
.chat-msg-content :deep(th) {
  background: rgba(0, 0, 0, 0.04);
  font-weight: 600;
}

.chat-files {
  margin-top: 10px;
  padding: 10px 14px;
  background: #f8f6f2;
  border: 1px solid #e8e4dc;
  border-radius: 8px;
}
.chat-code-execs {
  margin-top: 10px;
}
.chat-files-title {
  font-size: 12px;
  color: #6b6560;
  margin-bottom: 6px;
  font-weight: 500;
}
.chat-files .chat-image-grid,
.chat-msg-content :deep(.chat-image-grid),
.chat-markdown-body :deep(.chat-image-grid) {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 8px;
}
.chat-image-thumb,
.chat-msg-content :deep(.chat-image-grid img),
.chat-markdown-body :deep(.chat-image-grid img) {
  width: 100%;
  height: auto;
  max-height: 220px;
  object-fit: contain;
  border-radius: 6px;
  border: 1px solid #e8e4dc;
  background: #fff;
  cursor: pointer;
  display: block;
}
.chat-markdown-body :deep(.chat-inline-image) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
}
.chat-hitl-actions {
  margin-top: 8px;
}
.hitl-som-preview {
  margin-bottom: 10px;
  border: 1px solid #ffd591;
  border-radius: 8px;
  padding: 8px;
  background: #fffbe6;
}
.hitl-preview-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  color: #595959;
}
.hitl-som-image {
  max-width: 100%;
  border-radius: 6px;
  border: 1px solid #f0f0f0;
}
.hitl-otp-form {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.hitl-skill-params-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hitl-param-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.hitl-param-label {
  font-size: 12px;
  color: #595959;
  font-weight: 500;
}
.hitl-param-desc {
  font-weight: 400;
  color: #8c8c8c;
}
.chat-hitl-result {
  margin-top: 10px;
}
.chat-file-item {
  margin-bottom: 4px;
}
.chat-file-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #2563eb;
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
  cursor: pointer;
}
.chat-file-link:hover {
  background: #e8e4dc;
  color: #1d4ed8;
}
.chat-file-name {
  font-weight: 500;
}
.chat-file-size {
  font-size: 11px;
  color: #9e9590;
}
.chat-file-truncated-tag {
  margin-left: 6px;
  font-size: 10px;
  line-height: 18px;
}

.chat-thinking {
  margin-bottom: 8px;
}
.chat-thinking-header {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #9e9590;
  cursor: pointer;
  padding: 4px 0;
  user-select: none;
}
.chat-thinking-header:hover {
  color: #1a1714;
}
.chat-thinking-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: #faf8f5;
  border: 1px solid #e8e4dc;
  border-radius: 6px;
  font-size: 12px;
  color: #5c5650;
  white-space: pre-wrap;
  max-height: 240px;
  overflow-y: auto;
  line-height: 1.6;
}
.chat-thinking-summary {
  margin-left: 8px;
  font-size: 11px;
  color: #b0a89f;
}
.chat-thinking-timeline {
  white-space: normal;
  max-height: 360px;
  padding: 10px 10px 10px 4px;
}
.think-step {
  display: flex;
  gap: 10px;
  position: relative;
  padding: 6px 0 10px;
}
.think-step:last-child {
  padding-bottom: 2px;
}
.think-step-rail {
  width: 3px;
  border-radius: 2px;
  background: #ddd8ce;
  flex-shrink: 0;
  align-self: stretch;
  min-height: 28px;
}
.think-step-rewrite .think-step-rail { background: #67e8f9; }
.think-step-memory .think-step-rail { background: #c4b5fd; }
.think-step-phase .think-step-rail { background: #93c5fd; }
.think-step-thought .think-step-rail { background: #d4d4d8; }
.think-step-tool .think-step-rail { background: #818cf8; }
.think-step-action .think-step-rail { background: #fdba74; }
.think-step-error .think-step-rail { background: #fca5a5; }
.think-step-body {
  flex: 1;
  min-width: 0;
}
.think-step-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.think-step-toggle {
  padding: 0;
  height: auto;
  font-size: 11px;
}
.think-step-text {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
  color: #5c5650;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fff;
  border: 1px solid #efeae2;
  border-radius: 4px;
  padding: 6px 8px;
}
.think-step-tool .think-step-text {
  background: #f8f7ff;
  border-color: #e0e7ff;
}
.chat-thinking.sending .chat-thinking-body {
  background: #fef9f0;
  border-color: #f5e6cc;
}

.search-result-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.search-card-label {
  font-size: 11px;
  font-weight: 600;
  color: #9e9590;
  letter-spacing: 0.02em;
  margin-bottom: 6px;
}
.search-answer {
  padding: 10px 12px;
  background: #f7faf7;
  border: 1px solid #dce8dc;
  border-radius: 6px;
}
.search-answer-body {
  font-size: 13px;
  line-height: 1.65;
  color: #1a1714;
  white-space: pre-wrap;
}
.search-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.search-item {
  padding: 10px 12px;
  background: #faf8f5;
  border: 1px solid #e8e4dc;
  border-radius: 6px;
}
.search-item-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a1714;
  margin-bottom: 4px;
  line-height: 1.4;
}
.search-item-link {
  display: block;
  font-size: 11px;
  color: #3b82f6;
  word-break: break-all;
  margin-bottom: 4px;
}
.search-item-snippet {
  font-size: 12px;
  color: #5c5650;
  line-height: 1.55;
  white-space: pre-wrap;
}

.chat-trace {
  margin: 6px 0;
  font-size: 12px;
}
.chat-trace-body {
  margin-top: 4px;
  padding: 8px 12px;
  background: #f0f5ff;
  border: 1px solid #adc6ff;
  border-radius: 6px;
}
.trace-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid #e8e4dc;
}
.trace-step:last-child { border-bottom: none; }
.trace-label { flex: 1; color: #333; }
.trace-duration { color: #999; font-size: 11px; }

.thinking-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.thinking-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #5c5650;
}
.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d9d0c5;
  flex-shrink: 0;
}
.step-dot.active {
  background: #c2410c;
  animation: pulse-dot 1.2s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.chat-input-area {
  position: relative;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #ddd8ce;
  border-top: none;
  border-radius: 0 0 8px 8px;
}
.skill-bar {
  margin-bottom: 8px;
}
.attachment-bar {
  margin-bottom: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chat-attachments {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.attach-btn {
  flex-shrink: 0;
  color: #9e9590;
  padding: 4px 8px;
  height: auto;
}
.attach-btn:hover {
  color: #c2410c;
}
.chat-input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex: 1;
}
.chat-input-wrapper :deep(.ant-input) {
  flex: 1;
}
.send-btn {
  flex-shrink: 0;
}
.chat-input-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}
.chat-timeout-setting {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding-bottom: 4px;
}
.timeout-label {
  font-size: 12px;
  color: #9e9590;
  white-space: nowrap;
}
.timeout-unit {
  font-size: 12px;
  color: #9e9590;
}

.skill-popover {
  position: absolute;
  bottom: 100%;
  left: 16px;
  right: 16px;
  margin-bottom: 4px;
  background: #fff;
  border: 1px solid #e8e4dc;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
}
.skill-item {
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f3f0e8;
}
.skill-item:last-child {
  border-bottom: none;
}
.skill-item.active {
  background: #fef9f0;
}
.skill-item:hover {
  background: #fef9f0;
}
.skill-item-name {
  font-size: 13px;
  font-weight: 500;
  color: #1a1714;
}
.skill-item-desc {
  font-size: 11px;
  color: #9e9590;
  margin-top: 2px;
  margin-left: 22px;
}

/* ---- 文件预览弹窗 ---- */
.preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.preview-modal {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  min-width: 400px;
  min-height: 300px;
}
.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid #e8e4dc;
  background: #faf8f5;
  flex-shrink: 0;
}
.preview-title {
  font-size: 13px;
  font-weight: 500;
  color: #1a1714;
  display: flex;
  align-items: center;
}
.preview-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.preview-body {
  flex: 1;
  overflow: auto;
  padding: 0;
}
.preview-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
.preview-markdown {
  padding: 20px 24px;
  font-size: 13px;
  line-height: 1.7;
  color: #1a1714;
}
.preview-markdown :deep(p) {
  margin: 0 0 10px 0;
}
.preview-markdown :deep(h1) { font-size: 20px; margin: 16px 0 8px; }
.preview-markdown :deep(h2) { font-size: 17px; margin: 14px 0 6px; }
.preview-markdown :deep(h3) { font-size: 15px; margin: 12px 0 6px; }
.preview-markdown :deep(code) {
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.preview-markdown :deep(pre) {
  background: rgba(0, 0, 0, 0.05);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
}
.preview-markdown :deep(pre code) {
  background: none;
  padding: 0;
}
.preview-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.preview-text {
  padding: 16px 20px;
  margin: 0;
  font-size: 12px;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1a1714;
  background: #faf8f5;
  min-height: 100%;
}
.preview-csv {
  padding: 0;
  overflow: auto;
}
.csv-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.csv-table th,
.csv-table td {
  border: 1px solid #e8e4dc;
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap;
}
.csv-table th {
  background: #f5f2ed;
  font-weight: 600;
  color: #1a1714;
  position: sticky;
  top: 0;
  z-index: 1;
}
.csv-table tr:hover td {
  background: #fef9f0;
}
.preview-office {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
}
.preview-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
}
.preview-resize-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 20px;
  height: 20px;
  cursor: nwse-resize;
  background: linear-gradient(135deg, transparent 50%, #d9d0c5 50%);
  border-radius: 0 0 12px 0;
}
.preview-resize-handle:hover {
  background: linear-gradient(135deg, transparent 50%, #b5afa8 50%);
}

.debug-empty,
.debug-loading {
  display: flex;
  justify-content: center;
  padding: 48px 0;
}
.debug-call-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.debug-call-card :deep(.ant-card-head) {
  min-height: 40px;
}
.debug-call-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.debug-call-model {
  color: #6b6560;
  font-size: 12px;
}
.debug-section {
  margin-bottom: 12px;
}
.debug-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  margin-bottom: 8px;
}
.debug-section-head:hover .debug-section-label {
  color: #1d4ed8;
}
.debug-section-label {
  font-weight: 600;
  font-size: 12px;
  color: #1a1714;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.debug-section-summary {
  font-size: 11px;
  color: #9e9590;
  font-weight: 400;
  text-transform: none;
  letter-spacing: normal;
}
.debug-msg-block-head {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  margin-bottom: 4px;
}
.debug-msg-block-head:hover .debug-msg-role {
  color: #1d4ed8;
}
.debug-msg-preview {
  flex: 1;
  min-width: 0;
  font-size: 11px;
  color: #9e9590;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.debug-sub-label {
  font-size: 11px;
  color: #9e9590;
  margin-bottom: 4px;
}
.debug-messages {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}
.debug-tools-block {
  margin-bottom: 12px;
}
.debug-tool-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.debug-tool-card {
  border-radius: 6px;
  padding: 8px 10px;
  border: 1px solid #d6e4ff;
  background: #f7faff;
}
.debug-tool-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.debug-tool-card-head:hover .debug-tool-card-name {
  color: #1d4ed8;
}
.debug-tool-card-name {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  color: #1a1714;
}
.debug-tool-card-desc {
  font-size: 12px;
  color: #6b6560;
  margin-bottom: 6px;
  line-height: 1.45;
}
.debug-tool-params {
  margin-top: 4px;
}
.debug-tool-param-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  padding: 4px 0;
  border-top: 1px solid #e8eef8;
  font-size: 12px;
}
.debug-tool-param-name {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #1d4ed8;
}
.debug-tool-param-desc {
  color: #9e9590;
  font-size: 11px;
}
.debug-msg-block {
  border-radius: 6px;
  padding: 8px 10px;
  border: 1px solid #e8e2d9;
}
.debug-msg-system { background: #f5f3ef; }
.debug-msg-user { background: #fef7ed; border-color: #f5d0a9; }
.debug-msg-assistant { background: #f0f7ff; border-color: #bfdbfe; }
.debug-msg-tool { background: #f0fdf4; border-color: #bbf7d0; }
.debug-msg-role {
  font-size: 10px;
  font-weight: 600;
  color: #9e9590;
  text-transform: uppercase;
  flex-shrink: 0;
}
.debug-msg-content {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}
.debug-tool-calls {
  margin-top: 6px;
}
.debug-tool-meta {
  font-size: 11px;
  color: #9e9590;
  margin-top: 4px;
}
.debug-params,
.debug-usage {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.debug-reasoning {
  margin-bottom: 8px;
}
.debug-call-time {
  font-size: 11px;
  color: #b5afa8;
  margin-top: 4px;
}
.debug-empty-inline {
  font-size: 12px;
  color: #b5afa8;
}
.json-block {
  margin: 0;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
  background: #faf8f5;
  padding: 8px;
  border-radius: 4px;
}
</style>
<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">系统配置</h2>
    </div>

    <a-card style="margin-bottom: 24px;">
      <template #title>工具配置</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.tools ? '展开' : '收起'"
          :aria-label="cardCollapsed.tools ? '展开' : '收起'"
          @click.stop="cardCollapsed.tools = !cardCollapsed.tools"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.tools" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.tools">
        <a-form :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }" style="margin-bottom: 8px;">
          <a-form-item label="Web Search 提供方">
            <a-radio-group v-model:value="webSearchProvider" @change="onWebSearchProviderChange">
              <a-radio-button value="tavily">Tavily</a-radio-button>
              <a-radio-button value="duckduckgo">DuckDuckGo</a-radio-button>
            </a-radio-group>
            <div class="field-hint">
              运行时只向 Agent 注入选定的搜索工具；保存后新对话生效。
            </div>
          </a-form-item>
        </a-form>
        <a-alert
          v-if="webSearchProvider === 'tavily' && !tavilyStatus.configured"
          type="warning"
          show-icon
          message="已选定 Tavily，但尚未配置 API Key；请填写下方 Key，不会自动切换到 DuckDuckGo。"
          style="margin-bottom: 12px;"
        />
        <a-collapse v-model:activeKey="activeKeys">
          <a-collapse-panel v-if="webSearchProvider === 'tavily'" key="tavily" header="Tavily Web Search">
            <template #extra>
              <a-tag v-if="tavilyStatus.configured" color="green">已配置</a-tag>
              <a-tag v-else color="orange">未配置</a-tag>
            </template>
            <a-form :model="tavilyForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
              <a-form-item label="API Key">
                <a-input-password
                  v-model:value="tavilyForm.api_key"
                  placeholder="输入 Tavily API Key"
                />
                <div class="field-hint">
                  在 <a href="https://tavily.com/" target="_blank">tavily.com</a> 注册获取 API Key。
                  配置后，Agent 可使用内置的 <code>tavily_web_search</code> 工具进行网络搜索。
                </div>
              </a-form-item>
              <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
                <a-button type="primary" :loading="tavilySaving" @click="saveTavily">保存</a-button>
                <a-button style="margin-left: 12px;" @click="testTavily" :loading="tavilyTesting">测试连接</a-button>
              </a-form-item>
            </a-form>
            <div v-if="tavilyTestResult" style="margin-top: 12px;">
              <a-alert
                :type="tavilyTestResult.success ? 'success' : 'error'"
                :message="tavilyTestResult.message"
                show-icon
              />
            </div>
          </a-collapse-panel>
          <a-collapse-panel v-else key="duckduckgo" header="DuckDuckGo Web Search">
            <template #extra>
              <a-tag v-if="ddgStatus.available" color="green">可用</a-tag>
              <a-tag v-else color="orange">未安装</a-tag>
            </template>
            <div class="field-hint" style="margin-bottom: 12px;">
              无需 API Key。依赖包 <code>duckduckgo-search</code>，Agent 将使用
              <code>duckduckgo_web_search</code>。
            </div>
            <a-alert
              v-if="!ddgStatus.available"
              type="warning"
              show-icon
              message="后端未检测到 duckduckgo-search，请执行 pip install duckduckgo-search"
            />
            <a-alert
              v-else
              type="success"
              show-icon
              message="DuckDuckGo 可用，当前对话将只暴露 duckduckgo_web_search"
            />
          </a-collapse-panel>
        </a-collapse>

        <a-divider style="margin: 20px 0 16px;" />

        <div class="field-hint" style="margin-bottom: 12px;">
          <strong>Tool Search（延迟加载）</strong>：开启 deferred 后，平台内置工具始终进入 LLM 可用列表；
          <code>tool_search</code> 只搜索并激活用户安装的 MCP/自定义工具。
        </div>
        <a-form :model="toolSearchForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
          <a-form-item label="启用 Tool Search">
            <a-switch v-model:checked="toolSearchForm.enabled" />
            <div class="field-hint">默认关闭；开启后可选择 eager（用户工具也全量注入）或 deferred（用户工具按需搜索）。</div>
          </a-form-item>
          <template v-if="toolSearchForm.enabled">
            <a-form-item label="加载模式">
              <a-radio-group v-model:value="toolSearchForm.mode">
                <a-radio-button value="eager">Eager（全量注入）</a-radio-button>
                <a-radio-button value="deferred">Deferred（用户工具延迟加载）</a-radio-button>
              </a-radio-group>
            </a-form-item>
            <a-form-item label="搜索后端">
              <a-radio-group v-model:value="toolSearchForm.search_backend">
                <a-radio-button value="bm25">BM25</a-radio-button>
                <a-radio-button value="keyword">关键词</a-radio-button>
              </a-radio-group>
            </a-form-item>
            <a-form-item label="最大命中数">
              <a-input-number v-model:value="toolSearchForm.max_results" :min="1" :max="20" style="width: 120px;" />
            </a-form-item>
            <a-form-item label="会话加载上限">
              <a-input-number v-model:value="toolSearchForm.max_loaded_per_session" :min="1" :max="50" style="width: 120px;" />
            </a-form-item>
            <a-form-item label="额外常驻用户工具">
              <a-select
                v-model:value="toolSearchForm.always_loaded"
                mode="tags"
                placeholder="输入用户/MCP 工具名，使其无需搜索即可用（可选）"
                style="width: 100%;"
              >
                <a-select-option v-for="opt in toolSearchCoreOptions" :key="opt" :value="opt">{{ opt }}</a-select-option>
              </a-select>
              <div class="field-hint">
                平台内置工具无需配置。当前 Web Search：<code>{{ toolSearchMeta.active_web_search || '—' }}</code>
              </div>
            </a-form-item>
          </template>
          <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
            <a-button type="primary" :loading="toolSearchSaving" @click="saveToolSearch">保存 Tool Search</a-button>
          </a-form-item>
        </a-form>

        <a-divider style="margin: 20px 0 16px;" />

        <div class="field-hint" style="margin-bottom: 12px;">
          <strong>可观测性（OpenInference / Phoenix）</strong>：开启后按 OpenInference 语义打点并双写本地 Monitor；
          填写 Phoenix OTLP 地址后可同步导出到 Phoenix UI（默认
          <code>http://127.0.0.1:6006</code>）。
        </div>
        <a-form :model="observabilityForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
          <a-form-item label="启用 OTEL">
            <a-switch v-model:checked="observabilityForm.otel_enabled" />
            <div class="field-hint">关闭后不再创建 OpenInference span（本地投影走 fallback）。</div>
          </a-form-item>
          <a-form-item label="Phoenix / OTLP">
            <a-input
              v-model:value="observabilityForm.otlp_endpoint"
              placeholder="http://127.0.0.1:6006"
              allow-clear
              :disabled="!observabilityForm.otel_enabled"
            />
            <div class="field-hint">
              填 Phoenix 根地址即可，后端会自动追加 <code>/v1/traces</code>。留空则仅本地 Monitor 双写。
            </div>
          </a-form-item>
          <a-form-item label="成功采样率">
            <a-input-number
              v-model:value="observabilityForm.success_sample_rate"
              :min="0"
              :max="1"
              :step="0.1"
              style="width: 120px;"
              :disabled="!observabilityForm.otel_enabled"
            />
            <div class="field-hint">成功 run 正文保留比例（0–1）；失败/护栏仍全量保留。</div>
          </a-form-item>
          <a-alert
            v-if="observabilityMeta.endpoint_from_env || observabilityMeta.sdk_disabled_by_env"
            type="info"
            show-icon
            style="margin-bottom: 12px;"
            :message="observabilityEnvHint"
          />
          <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
            <a-space>
              <a-button type="primary" :loading="observabilitySaving" @click="saveObservability">
                保存可观测性
              </a-button>
              <a-tag v-if="observabilityMeta.runtime_otel_enabled" color="green">运行中</a-tag>
              <a-tag v-else color="default">已关闭</a-tag>
              <a-tag v-if="observabilityMeta.effective_otlp_endpoint" color="blue">
                导出: {{ observabilityMeta.effective_otlp_endpoint }}
              </a-tag>
            </a-space>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>自优化（SelfOpt）</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.selfopt ? '展开' : '收起'"
          @click.stop="cardCollapsed.selfopt = !cardCollapsed.selfopt"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.selfopt" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.selfopt">
        <div class="field-hint" style="margin-bottom: 12px;">
          默认关闭。开启后须勾选目标 Agent；可指定反思模型（默认跟随各 Agent 绑定模型）。正式上线需人工确认。
        </div>
        <a-form :model="selfoptForm" :label-col="{ span: 4 }" :wrapper-col="{ span: 16 }">
          <a-form-item label="启用自优化">
            <a-switch v-model:checked="selfoptForm.enabled" />
          </a-form-item>
          <a-form-item label="允许在线 A/B">
            <a-switch v-model:checked="selfoptForm.ab_enabled" :disabled="!selfoptForm.enabled" />
          </a-form-item>
          <a-form-item label="定时反思 Job">
            <a-switch v-model:checked="selfoptForm.schedule_enabled" :disabled="!selfoptForm.enabled" />
            <div class="field-hint">开启后后台按小时轮询白名单内已发布 Agent（约每 20h 跑一次）。</div>
          </a-form-item>
          <a-form-item label="目标 Agent">
            <a-select
              v-model:value="selfoptForm.agent_ids"
              mode="multiple"
              allow-clear
              show-search
              placeholder="选择可参与自优化的 Agent（空=不针对任何 Agent）"
              :options="selfoptAgentOptions"
              :filter-option="filterSelfoptAgent"
              :disabled="!selfoptForm.enabled"
              style="width: 100%"
            />
            <div v-if="selfoptOptionsError" class="field-hint" style="color: #b5341c">{{ selfoptOptionsError }}</div>
          </a-form-item>
          <a-form-item label="反思供应商">
            <a-select
              v-model:value="selfoptReflectProviderId"
              allow-clear
              show-search
              placeholder="先选供应商（留空=跟随各 Agent）"
              :options="selfoptProviderOptions"
              :filter-option="filterSelfoptAgent"
              :disabled="!selfoptForm.enabled"
              style="width: 100%"
              @change="onSelfoptProviderChange"
            />
          </a-form-item>
          <a-form-item label="反思模型">
            <a-select
              v-model:value="selfoptForm.reflect_model_service_id"
              allow-clear
              show-search
              placeholder="跟随目标 Agent 绑定模型"
              :options="selfoptModelOptions"
              :filter-option="filterSelfoptAgent"
              :disabled="!selfoptForm.enabled || !selfoptReflectProviderId"
              style="width: 100%"
            />
            <div class="field-hint">先选供应商再选模型；两项都留空则使用被优化 Agent 自己的模型服务。</div>
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 4, span: 16 }">
            <a-button type="primary" :loading="selfoptSaving" @click="saveSelfopt">保存自优化配置</a-button>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>代码执行沙箱 (Code Interpreter)</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.codeExec ? '展开' : '收起'"
          @click.stop="cardCollapsed.codeExec = !cardCollapsed.codeExec"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.codeExec" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.codeExec">
        <div class="field-hint" style="margin-bottom: 16px;">
          控制 Agent 内置 <code>execute_code</code> 工具的加固沙箱：独立 venv、资源限制、产物捕获与跨调用变量状态。
        </div>
        <a-form :model="codeExecForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="启用">
            <a-switch v-model:checked="codeExecForm.enabled" />
          </a-form-item>
          <a-form-item label="超时 (秒)">
            <a-input-number v-model:value="codeExecForm.wall_timeout" :min="10" :max="600" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="CPU 限制 (秒)">
            <a-input-number v-model:value="codeExecForm.cpu_seconds" :min="5" :max="300" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="内存 (MB)">
            <a-input-number v-model:value="codeExecForm.memory_mb" :min="256" :max="8192" style="width: 160px;" />
            <div class="field-hint">macOS 上内存限制可能不生效</div>
          </a-form-item>
          <a-form-item label="允许网络">
            <a-switch v-model:checked="codeExecForm.allow_network" />
          </a-form-item>
          <a-form-item label="允许安装包">
            <a-switch v-model:checked="codeExecForm.allow_install" />
          </a-form-item>
          <a-form-item label="状态持久化">
            <a-switch v-model:checked="codeExecForm.state_persist" />
          </a-form-item>
          <a-form-item label="包白名单">
            <a-select
              v-model:value="codeExecForm.package_allowlist"
              mode="tags"
              style="width: 100%;"
              placeholder="pandas, numpy, matplotlib..."
            />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="codeExecSaving" @click="saveCodeExec">保存</a-button>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>知识库 · 上下文感知检索</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.contextual ? '展开' : '收起'"
          @click.stop="cardCollapsed.contextual = !cardCollapsed.contextual"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.contextual" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.contextual">
        <div class="field-hint" style="margin-bottom: 16px;">
          在向量化前为每个分块生成 LLM 上下文前缀（Anthropic Contextual Retrieval），提升检索召回质量。
          索引时使用「前缀 + 原文」，检索返回仍为原始分块。
        </div>
        <a-form :model="contextualForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="全局启用">
            <a-switch v-model:checked="contextualForm.enabled" />
          </a-form-item>
          <a-form-item label="前缀生成模型">
            <a-select
              v-model:value="contextualForm.model_service_id"
              allow-clear
              placeholder="默认使用第一个可用模型服务"
              :options="modelServiceOptions"
              style="width: 100%"
            />
          </a-form-item>
          <a-form-item label="并发数">
            <a-input-number v-model:value="contextualForm.max_concurrency" :min="1" :max="32" style="width: 160px;" />
          </a-form-item>
          <a-form-item label="单块超时 (秒)">
            <a-input-number v-model:value="contextualForm.chunk_timeout_seconds" :min="5" :max="120" style="width: 160px;" />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="contextualSaving" @click="saveContextual">保存</a-button>
          </a-form-item>
        </a-form>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>打开驭屏系统</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.screenpilot ? '展开' : '收起'"
          :aria-label="cardCollapsed.screenpilot ? '展开' : '收起'"
          @click.stop="cardCollapsed.screenpilot = !cardCollapsed.screenpilot"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.screenpilot" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.screenpilot">
        <div class="screenpilot-card">
          <div class="screenpilot-card-main">
            <div>
              <div class="field-hint" style="margin-bottom: 8px;">
                打开后自动注册 {{ screenpilot.tools.length || 10 }} 个 <code>cu_*</code> MCP 工具（导航 / 观测 / 动作 / 提取 / 技能重放 / 技能编译 / 技能搜索 / 任务执行 / OTP / Vision）。关闭则移除这些工具并解除 Agent 绑定。
                可在 <a href="/tools">工具管理</a> 中查看。
              </div>
              <div v-if="screenpilot.tools.length" class="sp-tools">
                <a-tag v-for="t in screenpilot.tools" :key="t.tool_id" color="blue">
                  {{ t.name }}
                </a-tag>
              </div>
              <div v-else class="field-hint">当前未注册驭屏 MCP 工具</div>
            </div>
            <a-switch
              :checked="screenpilot.enabled"
              :loading="screenpilotSaving"
              checked-children="已打开"
              un-checked-children="已关闭"
              @change="onScreenpilotToggle"
            />
          </div>
        </div>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>Letta 记忆服务</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.letta ? '展开' : '收起'"
          :aria-label="cardCollapsed.letta ? '展开' : '收起'"
          @click.stop="cardCollapsed.letta = !cardCollapsed.letta"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.letta" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.letta">
        <div class="field-hint" style="margin-bottom: 16px;">
          自托管 Letta 提供核心记忆（blocks）与归档记忆（语义检索）。LLM / Embedding 通过 vela 网关回连本系统的模型服务与知识库同款嵌入模型，无需外部 API Key。
        </div>
        <a-form :model="lettaForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 14 }">
          <a-form-item label="启用">
            <a-switch v-model:checked="lettaForm.enabled" />
          </a-form-item>
          <a-form-item label="服务地址">
            <a-input v-model:value="lettaForm.base_url" placeholder="http://127.0.0.1:8283" />
          </a-form-item>
          <a-form-item label="访问密码">
            <a-input-password v-model:value="lettaForm.password" placeholder="留空或保持掩码表示不修改" />
          </a-form-item>
          <a-form-item label="网关地址">
            <a-input v-model:value="lettaForm.gateway_base" placeholder="http://127.0.0.1:8000" />
          </a-form-item>
          <a-form-item label="网关密钥">
            <a-input-password v-model:value="lettaForm.gateway_token" placeholder="留空或保持掩码表示不修改" />
          </a-form-item>
          <a-form-item label="蒸馏模型服务">
            <a-select
              v-model:value="lettaForm.distill_model_service_id"
              allow-clear
              placeholder="默认使用各 Agent 自己的模型服务"
              :options="modelServiceOptions"
              style="width: 100%"
            />
            <div class="field-hint">须支持 function calling（如 DeepSeek-chat / qwen-max）</div>
          </a-form-item>
          <a-form-item label="Embedding">
            <a-input
              :value="`${lettaMeta.embedding_model} · ${lettaMeta.embedding_dim} 维`"
              disabled
            />
          </a-form-item>
          <a-form-item :wrapper-col="{ offset: 5, span: 14 }">
            <a-button type="primary" :loading="lettaSaving" @click="saveLetta">保存</a-button>
            <a-button style="margin-left: 12px;" :loading="lettaTesting" @click="testLetta">测试连接</a-button>
          </a-form-item>
        </a-form>
        <div v-if="lettaTestResult" style="margin-top: 12px;">
          <a-alert
            :type="lettaTestResult.success ? 'success' : 'error'"
            :message="lettaTestResult.message"
            show-icon
          />
        </div>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>记忆模块</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.memory ? '展开' : '收起'"
          :aria-label="cardCollapsed.memory ? '展开' : '收起'"
          @click.stop="cardCollapsed.memory = !cardCollapsed.memory"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.memory" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.memory">
        <div class="field-hint" style="margin-bottom: 16px;">
          为各 Agent 开关记忆闭环（自我记录 / 自我处理 / 自我检索）。开启后，对话过程会自动写入情景事件，会话关闭时蒸馏语义记忆，并在后续对话中自动召回。
        </div>
        <a-table
          :columns="memoryColumns"
          :data-source="memoryAgents"
          :loading="memoryLoading"
          row-key="agent_id"
          :pagination="false"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag>{{ record.status }}</a-tag>
            </template>
            <template v-else-if="column.key === 'memory_enabled'">
              <a-switch
                :checked="record.memory_enabled"
                @change="(checked) => onMemoryToggle(record, checked)"
              />
            </template>
          </template>
        </a-table>
        <div style="margin-top: 16px;">
          <a-button type="primary" :loading="memorySaving" @click="saveMemoryMounts">
            保存挂载配置
          </a-button>
          <a-button style="margin-left: 12px;" @click="fetchMemoryAgents">刷新</a-button>
        </div>
      </div>
    </a-card>

    <a-card style="margin-bottom: 24px;">
      <template #title>Query 改写引擎</template>
      <template #extra>
        <a-button
          type="text"
          size="small"
          :title="cardCollapsed.rewrite ? '展开' : '收起'"
          :aria-label="cardCollapsed.rewrite ? '展开' : '收起'"
          @click.stop="cardCollapsed.rewrite = !cardCollapsed.rewrite"
        >
          <template #icon>
            <UpOutlined v-if="!cardCollapsed.rewrite" />
            <DownOutlined v-else />
          </template>
        </a-button>
      </template>
      <div v-show="!cardCollapsed.rewrite">
        <div class="field-hint" style="margin-bottom: 16px;">
          为各 Agent 开关 Query 改写引擎。开启后，对话进入检索 / 工具前会自动判断是否需要改写，并按 T0 透传 / T1 规则 / T2 LLM 路由执行。
        </div>
        <a-table
          :columns="rewriteColumns"
          :data-source="rewriteAgents"
          :loading="rewriteLoading"
          row-key="agent_id"
          :pagination="false"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'status'">
              <a-tag>{{ record.status }}</a-tag>
            </template>
            <template v-else-if="column.key === 'query_rewrite_enabled'">
              <a-switch
                :checked="record.query_rewrite_enabled"
                @change="(checked) => onRewriteToggle(record, checked)"
              />
            </template>
          </template>
        </a-table>
        <div style="margin-top: 16px;">
          <a-button type="primary" :loading="rewriteSaving" @click="saveRewriteMounts">
            保存挂载配置
          </a-button>
          <a-button style="margin-left: 12px;" @click="fetchRewriteAgents">刷新</a-button>
        </div>
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { UpOutlined, DownOutlined } from '@ant-design/icons-vue'
import { configApi, serviceApi, memoryApi, agentApi, providerApi } from '../../api'
import { message } from 'ant-design-vue'

const cardCollapsed = reactive({
  tools: true,
  selfopt: true,
  codeExec: true,
  contextual: true,
  screenpilot: true,
  letta: true,
  memory: true,
  rewrite: true,
})

const webSearchProvider = ref('tavily')
const webSearchSaving = ref(false)
const toolSearchSaving = ref(false)
const toolSearchMeta = reactive({ active_web_search: '' })

const observabilityForm = reactive({
  otel_enabled: true,
  otlp_endpoint: '',
  success_sample_rate: 1.0,
})
const observabilityMeta = reactive({
  effective_otlp_endpoint: '',
  endpoint_from_env: false,
  sdk_disabled_by_env: false,
  runtime_otel_enabled: true,
})
const observabilitySaving = ref(false)
const selfoptForm = reactive({
  enabled: false,
  schedule_enabled: false,
  ab_enabled: true,
  reflect_model_service_id: undefined,
  agent_ids: [],
})
const selfoptSaving = ref(false)
const selfoptAgentOptions = ref([])
const selfoptProviderOptions = ref([])
const selfoptModelOptions = ref([])
const selfoptAllServices = ref([])
const selfoptReflectProviderId = ref(undefined)
const selfoptOptionsError = ref('')

function filterSelfoptAgent(input, option) {
  return (option?.label || '').toLowerCase().includes((input || '').toLowerCase())
}

function syncSelfoptModelOptions(providerId) {
  const pid = providerId || selfoptReflectProviderId.value
  if (!pid) {
    selfoptModelOptions.value = []
    return
  }
  selfoptModelOptions.value = (selfoptAllServices.value || [])
    .filter((s) => s.provider_id === pid)
    .map((s) => ({
      label: `${s.display_name || s.model_name} (${s.model_name})`,
      value: s.model_service_id,
    }))
}

function onSelfoptProviderChange(providerId) {
  selfoptForm.reflect_model_service_id = undefined
  syncSelfoptModelOptions(providerId)
}
const observabilityEnvHint = computed(() => {
  const parts = []
  if (observabilityMeta.sdk_disabled_by_env) {
    parts.push('环境变量 OTEL_SDK_DISABLED 已关闭 SDK，会覆盖下方开关。')
  }
  if (observabilityMeta.endpoint_from_env) {
    parts.push(
      `环境变量 OTEL_EXPORTER_OTLP_ENDPOINT 优先生效（当前有效: ${observabilityMeta.effective_otlp_endpoint || '—'}）。`
    )
  }
  return parts.join(' ')
})
const toolSearchCoreOptions = [
  'cu_search_skills',
  'ui_search_skills',
]
const toolSearchForm = reactive({
  enabled: false,
  mode: 'eager',
  search_backend: 'bm25',
  max_results: 5,
  max_loaded_per_session: 12,
  always_loaded: [],
})
const activeKeys = ref(['tavily'])
const tavilySaving = ref(false)
const tavilyTesting = ref(false)
const tavilyTestResult = ref(null)

const tavilyStatus = reactive({
  configured: false,
})
const ddgStatus = reactive({
  available: false,
})

const tavilyForm = reactive({
  api_key: '',
})

const codeExecForm = reactive({
  enabled: true,
  wall_timeout: 60,
  cpu_seconds: 30,
  memory_mb: 2048,
  allow_network: false,
  allow_install: true,
  state_persist: true,
  package_allowlist: ['pandas', 'numpy', 'matplotlib'],
})
const codeExecSaving = ref(false)

const contextualForm = reactive({
  enabled: false,
  model_service_id: undefined,
  max_concurrency: 12,
  chunk_timeout_seconds: 30,
})
const contextualSaving = ref(false)

const lettaForm = reactive({
  enabled: true,
  base_url: 'http://127.0.0.1:8283',
  password: '',
  gateway_base: 'http://127.0.0.1:8000',
  gateway_token: '',
  distill_model_service_id: undefined,
})
const lettaMeta = reactive({
  embedding_model: 'vela-embedding',
  embedding_dim: 1024,
})
const lettaSaving = ref(false)
const lettaTesting = ref(false)
const lettaTestResult = ref(null)
const modelServiceOptions = ref([])

const memoryAgents = ref([])
const memoryLoading = ref(false)
const memorySaving = ref(false)
const memoryColumns = [
  { title: 'Agent', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status', width: 120 },
  { title: '挂载记忆', key: 'memory_enabled', width: 120 },
]

const rewriteAgents = ref([])
const rewriteLoading = ref(false)
const rewriteSaving = ref(false)
const rewriteColumns = [
  { title: 'Agent', dataIndex: 'name' },
  { title: '状态', key: 'status', dataIndex: 'status', width: 120 },
  { title: '挂载改写', key: 'query_rewrite_enabled', width: 120 },
]

const screenpilotSaving = ref(false)
const screenpilot = reactive({
  enabled: false,
  tools: [],
})

async function fetchCodeExecConfig() {
  try {
    const cfg = await configApi.getCodeExec()
    codeExecForm.enabled = !!cfg.enabled
    codeExecForm.wall_timeout = cfg.wall_timeout ?? 60
    codeExecForm.cpu_seconds = cfg.cpu_seconds ?? 30
    codeExecForm.memory_mb = cfg.memory_mb ?? 2048
    codeExecForm.allow_network = !!cfg.allow_network
    codeExecForm.allow_install = cfg.allow_install !== false
    codeExecForm.state_persist = cfg.state_persist !== false
    codeExecForm.package_allowlist = cfg.package_allowlist || []
  } catch (e) {
    // ignore
  }
}

async function saveCodeExec() {
  codeExecSaving.value = true
  try {
    const res = await configApi.updateCodeExec({ ...codeExecForm })
    message.success(res.message || '代码执行沙箱配置已保存')
  } catch (e) {
    message.error(e.message)
  } finally {
    codeExecSaving.value = false
  }
}

async function fetchContextualConfig() {
  try {
    const cfg = await configApi.getContextualRetrieval()
    contextualForm.enabled = !!cfg.enabled
    contextualForm.model_service_id = cfg.model_service_id || undefined
    contextualForm.max_concurrency = cfg.max_concurrency ?? 12
    contextualForm.chunk_timeout_seconds = cfg.chunk_timeout_seconds ?? 30
  } catch (e) {
    // ignore
  }
}

async function saveContextual() {
  contextualSaving.value = true
  try {
    await configApi.updateContextualRetrieval({
      enabled: !!contextualForm.enabled,
      model_service_id: contextualForm.model_service_id || '',
      max_concurrency: contextualForm.max_concurrency,
      chunk_timeout_seconds: contextualForm.chunk_timeout_seconds,
    })
    message.success('上下文感知检索配置已保存')
    await fetchContextualConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    contextualSaving.value = false
  }
}

async function fetchScreenpilot() {
  try {
    const res = await configApi.getScreenpilot()
    screenpilot.enabled = !!res.enabled
    screenpilot.tools = res.tools || []
  } catch (e) {
    // ignore
  }
}

async function onScreenpilotToggle(checked) {
  screenpilotSaving.value = true
  try {
    const res = await configApi.updateScreenpilot({ enabled: !!checked })
    screenpilot.enabled = !!res.enabled
    screenpilot.tools = res.tools || []
    message.success(res.message || (checked ? '驭屏系统已打开' : '驭屏系统已关闭'))
  } catch (e) {
    message.error(e.message)
    await fetchScreenpilot()
  } finally {
    screenpilotSaving.value = false
  }
}

async function fetchConfig() {
  try {
    const res = await configApi.getWebSearch()
    webSearchProvider.value = res.provider === 'duckduckgo' ? 'duckduckgo' : 'tavily'
    tavilyStatus.configured = !!(res.tavily && res.tavily.configured)
    ddgStatus.available = !!(res.duckduckgo && res.duckduckgo.available)
    activeKeys.value = [webSearchProvider.value]
  } catch (e) {
    try {
      const status = await configApi.getTavilyStatus()
      tavilyStatus.configured = status.configured
    } catch (_) {
      // ignore
    }
  }
}

async function onWebSearchProviderChange() {
  const provider = webSearchProvider.value
  if (provider === 'tavily' && !tavilyStatus.configured) {
    message.warning('已选定 Tavily，请配置 API Key（不会自动切换到 DuckDuckGo）')
  }
  webSearchSaving.value = true
  try {
    await configApi.updateWebSearch({ provider })
    activeKeys.value = [provider]
    message.success(
      provider === 'duckduckgo'
        ? '已切换为 DuckDuckGo；当前对话将只暴露 duckduckgo_web_search'
        : '已切换为 Tavily；当前对话将只暴露 tavily_web_search'
    )
    await fetchConfig()
  } catch (e) {
    message.error(e.message)
    await fetchConfig()
  } finally {
    webSearchSaving.value = false
  }
}

async function saveTavily() {
  if (!tavilyForm.api_key) {
    message.warning('请输入 API Key')
    return
  }
  tavilySaving.value = true
  try {
    await configApi.updateTavily({ api_key: tavilyForm.api_key })
    message.success('Tavily 配置已保存')
    tavilyForm.api_key = ''
    await fetchConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    tavilySaving.value = false
  }
}

async function testTavily() {
  tavilyTesting.value = true
  tavilyTestResult.value = null
  try {
    const status = await configApi.getTavilyStatus()
    if (status.configured) {
      tavilyTestResult.value = { success: true, message: 'API Key 已配置，Tavily Web Search 工具可用' }
    } else {
      tavilyTestResult.value = { success: false, message: 'API Key 未配置，请先保存 API Key' }
    }
  } catch (e) {
    tavilyTestResult.value = { success: false, message: '检查失败: ' + e.message }
  } finally {
    tavilyTesting.value = false
  }
}

async function fetchMemoryAgents() {
  memoryLoading.value = true
  try {
    memoryAgents.value = await configApi.listMemoryAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    memoryLoading.value = false
  }
}

async function fetchLettaConfig() {
  try {
    const cfg = await configApi.getLetta()
    lettaForm.enabled = !!cfg.enabled
    lettaForm.base_url = cfg.base_url || ''
    lettaForm.password = cfg.password || ''
    lettaForm.gateway_base = cfg.gateway_base || ''
    lettaForm.gateway_token = cfg.gateway_token || ''
    lettaForm.distill_model_service_id = cfg.distill_model_service_id || undefined
    lettaMeta.embedding_model = cfg.embedding_model || 'vela-embedding'
    lettaMeta.embedding_dim = cfg.embedding_dim || 1024
  } catch (e) {
    // ignore
  }
}

async function fetchModelServices() {
  try {
    const res = await serviceApi.list({ page: 1, page_size: 100 })
    modelServiceOptions.value = (res.items || []).map((s) => ({
      label: `${s.display_name || s.model_name} (${s.model_name})`,
      value: s.model_service_id,
    }))
  } catch (e) {
    modelServiceOptions.value = []
  }
}

async function saveLetta() {
  lettaSaving.value = true
  try {
    const payload = {
      enabled: !!lettaForm.enabled,
      base_url: lettaForm.base_url,
      gateway_base: lettaForm.gateway_base,
      distill_model_service_id: lettaForm.distill_model_service_id || '',
    }
    if (lettaForm.password && !String(lettaForm.password).includes('*')) {
      payload.password = lettaForm.password
    }
    if (lettaForm.gateway_token && !String(lettaForm.gateway_token).includes('*')) {
      payload.gateway_token = lettaForm.gateway_token
    }
    const res = await configApi.updateLetta(payload)
    message.success(res.message || 'Letta 配置已保存')
    await fetchLettaConfig()
  } catch (e) {
    message.error(e.message)
  } finally {
    lettaSaving.value = false
  }
}

async function testLetta() {
  lettaTesting.value = true
  lettaTestResult.value = null
  try {
    const s = await memoryApi.lettaStatus()
    if (s.healthy) {
      lettaTestResult.value = {
        success: true,
        message: `连接成功 · embedding ${s.embedding_model} (${s.embedding_dim}维) · 映射 ${s.mapping_count || 0}`,
      }
    } else {
      lettaTestResult.value = {
        success: false,
        message: `不可用: ${s.error || 'unknown'}（请确认已启动 backend/letta/start_letta.sh）`,
      }
    }
  } catch (e) {
    lettaTestResult.value = { success: false, message: e.message }
  } finally {
    lettaTesting.value = false
  }
}

function onMemoryToggle(record, checked) {
  record.memory_enabled = checked
}

async function saveMemoryMounts() {
  memorySaving.value = true
  try {
    const items = memoryAgents.value.map((a) => ({
      agent_id: a.agent_id,
      memory_enabled: !!a.memory_enabled,
    }))
    const res = await configApi.updateMemoryAgents(items)
    message.success(res.message || '记忆模块挂载配置已保存')
    await fetchMemoryAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    memorySaving.value = false
  }
}

async function fetchRewriteAgents() {
  rewriteLoading.value = true
  try {
    rewriteAgents.value = await configApi.listQueryRewriteAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    rewriteLoading.value = false
  }
}

function onRewriteToggle(record, checked) {
  record.query_rewrite_enabled = checked
}

async function saveRewriteMounts() {
  rewriteSaving.value = true
  try {
    const items = rewriteAgents.value.map((a) => ({
      agent_id: a.agent_id,
      query_rewrite_enabled: !!a.query_rewrite_enabled,
    }))
    const res = await configApi.updateQueryRewriteAgents(items)
    message.success(res.message || 'Query改写引擎挂载配置已保存')
    await fetchRewriteAgents()
  } catch (e) {
    message.error(e.message)
  } finally {
    rewriteSaving.value = false
  }
}

async function fetchToolSearch() {
  try {
    const res = await configApi.getToolSearch()
    toolSearchForm.enabled = !!res.enabled
    toolSearchForm.mode = res.mode === 'deferred' ? 'deferred' : 'eager'
    toolSearchForm.search_backend = res.search_backend === 'keyword' ? 'keyword' : 'bm25'
    toolSearchForm.max_results = res.max_results || 5
    toolSearchForm.max_loaded_per_session = res.max_loaded_per_session || 12
    toolSearchForm.always_loaded = Array.isArray(res.always_loaded) ? [...res.always_loaded] : []
    toolSearchMeta.active_web_search = res.active_web_search || ''
  } catch (_) {
    // ignore
  }
}

async function saveToolSearch() {
  toolSearchSaving.value = true
  try {
    const res = await configApi.updateToolSearch({
      enabled: toolSearchForm.enabled,
      mode: toolSearchForm.mode,
      search_backend: toolSearchForm.search_backend,
      max_results: toolSearchForm.max_results,
      max_loaded_per_session: toolSearchForm.max_loaded_per_session,
      always_loaded: toolSearchForm.always_loaded,
    })
    message.success(res.message || 'Tool Search 配置已保存')
    await fetchToolSearch()
  } catch (e) {
    message.error(e.message)
  } finally {
    toolSearchSaving.value = false
  }
}

async function fetchObservability() {
  try {
    const res = await configApi.getObservability()
    observabilityForm.otel_enabled = res.otel_enabled !== false
    observabilityForm.otlp_endpoint = res.otlp_endpoint || ''
    observabilityForm.success_sample_rate =
      typeof res.success_sample_rate === 'number' ? res.success_sample_rate : 1.0
    observabilityMeta.effective_otlp_endpoint = res.effective_otlp_endpoint || ''
    observabilityMeta.endpoint_from_env = !!res.endpoint_from_env
    observabilityMeta.sdk_disabled_by_env = !!res.sdk_disabled_by_env
    observabilityMeta.runtime_otel_enabled = !!res.runtime_otel_enabled
  } catch (_) {
    // ignore
  }
}

async function saveObservability() {
  observabilitySaving.value = true
  try {
    const res = await configApi.updateObservability({
      otel_enabled: !!observabilityForm.otel_enabled,
      otlp_endpoint: (observabilityForm.otlp_endpoint || '').trim(),
      success_sample_rate: Number(observabilityForm.success_sample_rate ?? 1),
    })
    message.success(res.message || '可观测性配置已保存')
    await fetchObservability()
  } catch (e) {
    message.error(e.message)
  } finally {
    observabilitySaving.value = false
  }
}

async function fetchSelfopt() {
  try {
    const res = await configApi.getSelfopt()
    selfoptForm.enabled = !!res.enabled
    selfoptForm.schedule_enabled = !!res.schedule_enabled
    selfoptForm.ab_enabled = res.ab_enabled !== false
    selfoptForm.reflect_model_service_id = res.reflect_model_service_id || undefined
    selfoptForm.agent_ids = Array.isArray(res.agent_ids) ? [...res.agent_ids] : []
    // Resolve provider from saved model service after options loaded
    const msid = selfoptForm.reflect_model_service_id
    if (msid && selfoptAllServices.value.length) {
      const svc = selfoptAllServices.value.find((s) => s.model_service_id === msid)
      selfoptReflectProviderId.value = svc?.provider_id || undefined
      syncSelfoptModelOptions(selfoptReflectProviderId.value)
    } else if (!msid) {
      selfoptReflectProviderId.value = undefined
      selfoptModelOptions.value = []
    }
  } catch (e) {
    // ignore
  }
}

async function fetchSelfoptOptions() {
  selfoptOptionsError.value = ''
  try {
    const [agentsRes, providersRes, servicesRes] = await Promise.all([
      agentApi.list({ page: 1, page_size: 100 }),
      providerApi.list({ page: 1, page_size: 100 }),
      serviceApi.list({ page: 1, page_size: 100 }),
    ])
    selfoptAgentOptions.value = (agentsRes.items || []).map((a) => ({
      label: a.name,
      value: a.agent_id,
    }))
    selfoptProviderOptions.value = (providersRes.items || []).map((p) => ({
      label: p.display_name || p.provider_code,
      value: p.provider_id,
    }))
    selfoptAllServices.value = servicesRes.items || []
    // Prefill cascade from saved reflect_model_service_id
    const msid = selfoptForm.reflect_model_service_id
    if (msid) {
      const svc = selfoptAllServices.value.find((s) => s.model_service_id === msid)
      selfoptReflectProviderId.value = svc?.provider_id || undefined
    }
    syncSelfoptModelOptions(selfoptReflectProviderId.value)
    if (!selfoptAgentOptions.value.length) {
      selfoptOptionsError.value = '未获取到 Agent 列表，请确认已创建 Agent'
    }
  } catch (e) {
    selfoptAgentOptions.value = []
    selfoptProviderOptions.value = []
    selfoptAllServices.value = []
    selfoptModelOptions.value = []
    selfoptOptionsError.value = e.message || '加载 Agent/模型列表失败'
  }
}

async function saveSelfopt() {
  selfoptSaving.value = true
  try {
    const res = await configApi.updateSelfopt({
      enabled: !!selfoptForm.enabled,
      schedule_enabled: !!selfoptForm.schedule_enabled,
      ab_enabled: !!selfoptForm.ab_enabled,
      reflect_model_service_id: selfoptForm.reflect_model_service_id || '',
      agent_ids: selfoptForm.agent_ids || [],
    })
    message.success(res.message || '自优化配置已保存')
    await fetchSelfopt()
  } catch (e) {
    message.error(e.message)
  } finally {
    selfoptSaving.value = false
  }
}

onMounted(async () => {
  await fetchConfig()
  await fetchToolSearch()
  await fetchObservability()
  await fetchSelfopt()
  await fetchSelfoptOptions()
  await fetchCodeExecConfig()
  await fetchContextualConfig()
  await fetchScreenpilot()
  await fetchLettaConfig()
  await fetchModelServices()
  await fetchMemoryAgents()
  await fetchRewriteAgents()
})
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 700; color: #1a1714; margin: 0; }
.field-hint {
  font-size: 11px;
  color: #9e9590;
  margin-top: 4px;
  line-height: 1.5;
}
.field-hint code {
  font-size: 11px;
  background: #f3f0e8;
  padding: 1px 5px;
  border-radius: 3px;
  color: #5c5650;
}
.screenpilot-card-main {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}
.sp-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
</style>

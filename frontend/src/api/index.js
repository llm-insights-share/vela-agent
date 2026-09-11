import axios from 'axios'

const TOKEN_KEY = 'vela_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      clearToken()
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        const redirect = encodeURIComponent(window.location.pathname + window.location.search)
        window.location.href = `/login?redirect=${redirect}`
      }
    }
    if (err.code === 'ECONNABORTED' && err.message?.includes('timeout')) {
      return Promise.reject(new Error('请求超时，模型响应较慢，请重试或简化 Skill 内容'))
    }
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)))
  }
)

export default api

export const authApi = {
  login: (username, password) => {
    const body = new URLSearchParams()
    body.set('username', username)
    body.set('password', password)
    return api.post('/auth/login', body, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
  },
  register: (data) => api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
  updateProfile: (data) => api.patch('/auth/me/profile', data),
  updatePassword: (data) => api.patch('/auth/me/password', data),
  uploadAvatar: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/auth/me/avatar', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}

export const userApi = {
  list: () => api.get('/users'),
  create: (data) => api.post('/users', data),
  setActive: (id, is_active) => api.patch(`/users/${id}/active`, { is_active }),
  setRoles: (id, roles) => api.patch(`/users/${id}/roles`, { roles }),
  remove: (id) => api.delete(`/users/${id}`),
}

export const agentApi = {
  list: (params) => api.get('/agents', { params }),
  create: (data) => api.post('/agents', data),
  get: (id) => api.get(`/agents/${id}`),
  update: (id, data) => api.put(`/agents/${id}`, data),
  delete: (id) => api.delete(`/agents/${id}`),
  deprecate: (id) => api.post(`/agents/${id}/deprecate`),
  republish: (id) => api.post(`/agents/${id}/republish`),
  publish: (id, data) => api.post(`/agents/${id}/publish`, data),
  validate: (id) => api.post(`/agents/${id}/validate`),
  rollback: (id, versionId) => api.post(`/agents/${id}/rollback?version_id=${versionId}`),
  versions: (id) => api.get(`/agents/${id}/versions`),
  getSkills: (id) => api.get(`/agents/${id}/skills`),
  bindSkills: (id, skillPackIds) => api.put(`/agents/${id}/skills`, skillPackIds),
  getKnowledgeBases: (id) => api.get(`/agents/${id}/knowledge-bases`),
  bindKnowledgeBases: (id, kbIds) => api.put(`/agents/${id}/knowledge-bases`, kbIds),
  getTools: (id) => api.get(`/agents/${id}/tools`),
  bindTools: (id, toolIds) => api.put(`/agents/${id}/tools`, toolIds),
}

export const providerApi = {
  list: (params) => api.get('/providers', { params }),
  create: (data) => api.post('/providers', data),
  get: (id) => api.get(`/providers/${id}`),
  update: (id, data) => api.put(`/providers/${id}`, data),
  delete: (id) => api.delete(`/providers/${id}`),
  syncModels: (id) => api.post(`/providers/${id}/sync-models`),
}

export const serviceApi = {
  list: (params) => api.get('/model-services', { params }),
  create: (data) => api.post('/model-services', data),
  update: (id, data) => api.put(`/model-services/${id}`, data),
  delete: (id) => api.delete(`/model-services/${id}`),
  test: (id) => api.post(`/model-services/${id}/test`),
}

export const skillApi = {
  list: (params) => api.get('/skills', { params }),
  create: (data) => api.post('/skills', data),
  get: (id) => api.get(`/skills/${id}`),
  update: (id, data) => api.put(`/skills/${id}`, data),
  delete: (id) => api.delete(`/skills/${id}`),
  unpublish: (id) => api.post(`/skills/${id}/unpublish`),
  publish: (id) => api.post(`/skills/${id}/publish`),
  import: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/skills/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },
}

export const knowledgeApi = {
  list: (params) => api.get('/knowledge-bases', { params }),
  create: (data) => api.post('/knowledge-bases', data),
  get: (id) => api.get(`/knowledge-bases/${id}`),
  update: (id, data) => api.put(`/knowledge-bases/${id}`, data),
  delete: (id) => api.delete(`/knowledge-bases/${id}`),
  addDocuments: (id, data) => api.post(`/knowledge-bases/${id}/documents`, data),
  uploadFile: (id, formData) => api.post(`/knowledge-bases/${id}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  listFiles: (id) => api.get(`/knowledge-bases/${id}/files`),
  updateFileStatus: (id, docId, data) => api.patch(`/knowledge-bases/${id}/files/${docId}`, data),
  deleteFile: (id, docId) => api.delete(`/knowledge-bases/${id}/files/${docId}`),
  getFileContent: (id, docId, params) => api.get(`/knowledge-bases/${id}/files/${docId}/content`, {
    params,
    responseType: 'blob',
  }),
  listFileChunks: (id, docId) => api.get(`/knowledge-bases/${id}/files/${docId}/chunks`),
  search: (id, data) => api.post(`/knowledge-bases/${id}/search`, data),
  suggestSearchFilters: (id, data) => api.post(`/knowledge-bases/${id}/search/suggest-filters`, data),
  previewImport: (id, formData) => api.post(`/knowledge-bases/${id}/import/preview`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }),
  previewImportText: (id, data) => api.post(`/knowledge-bases/${id}/import/preview`, data, {
    timeout: 120000,
  }),
  confirmImport: (id, data) => api.post(`/knowledge-bases/${id}/import/confirm`, data, {
    timeout: 300000,
  }),
  cancelImport: (id, previewId) => api.delete(`/knowledge-bases/${id}/import/preview/${previewId}`),
  updateFileTags: (id, docId, data) => api.patch(`/knowledge-bases/${id}/files/${docId}/tags`, data),
  reindexContextual: (id) => api.post(`/knowledge-bases/${id}/reindex-contextual`, null, {
    timeout: 600000,
  }),
}

export const sessionApi = {
  list: (params) => api.get('/sessions', { params }),
  create: (data) => api.post('/sessions', data),
  get: (id) => api.get(`/sessions/${id}`),
  chat: (id, data) => {
    const reqTimeout = ((data.timeout_seconds || 120) + 10) * 1000
    return api.post(`/sessions/${id}/chat`, data, { timeout: reqTimeout })
  },
  chatAsync: (id, data) => api.post(`/sessions/${id}/chat/async`, data, { timeout: 10000 }),
  /**
   * Subscribe to session SSE events (thinking_delta, story_patch, status, done, error, hitl).
   * Uses fetch + ReadableStream so Authorization header works.
   * Returns an abort controller; call controller.abort() to disconnect.
   */
  events: (id, { onEvent, onError, signal } = {}) => {
    const token = getToken()
    const controller = new AbortController()
    if (signal) {
      if (signal.aborted) controller.abort()
      else signal.addEventListener('abort', () => controller.abort(), { once: true })
    }
    const url = `/api/v1/sessions/${encodeURIComponent(id)}/events`
    ;(async () => {
      try {
        const res = await fetch(url, {
          method: 'GET',
          headers: {
            Accept: 'text/event-stream',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        })
        if (!res.ok) {
          throw new Error(`SSE ${res.status}`)
        }
        const reader = res.body?.getReader()
        if (!reader) throw new Error('No SSE body')
        const decoder = new TextDecoder()
        let buffer = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split('\n\n')
          buffer = parts.pop() || ''
          for (const block of parts) {
            const dataLine = block
              .split('\n')
              .find((l) => l.startsWith('data:'))
            if (!dataLine) continue
            const raw = dataLine.slice(5).trim()
            if (!raw) continue
            try {
              const evt = JSON.parse(raw)
              onEvent?.(evt)
            } catch (e) {
              /* ignore malformed */
            }
          }
        }
      } catch (err) {
        if (err?.name === 'AbortError') return
        onError?.(err)
      }
    })()
    return controller
  },
  mutateMessages: (id, data) => api.post(`/sessions/${id}/messages/mutate`, data),
  uploadAttachment: (id, formData) => api.post(`/sessions/${id}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  }),
  listAttachments: (id) => api.get(`/sessions/${id}/attachments`),
  deleteAttachment: (id, attachmentId) => api.delete(`/sessions/${id}/attachments/${attachmentId}`),
  listRunning: (params) => api.get('/sessions', { params: { ...params, status: 'RUNNING' } }),
  abort: (id) => api.post(`/sessions/${id}/abort`, {}, { timeout: 15000 }),
  llmCalls: (id) => api.get(`/sessions/${id}/llm-calls`),
  close: (id) => api.post(`/sessions/${id}/close`),
  delete: (id) => api.delete(`/sessions/${id}`),
  getConnectors: (id) => api.get(`/sessions/${id}/connectors`),
  updateConnectors: (id, connectorIds) => api.put(`/sessions/${id}/connectors`, { connector_ids: connectorIds }),
}

export const connectorApi = {
  catalog: () => api.get('/connectors/catalog'),
  list: () => api.get('/connectors'),
  fromCatalog: (data) => api.post('/connectors/from-catalog', data),
  create: (data) => api.post('/connectors', data),
  get: (id) => api.get(`/connectors/${id}`),
  update: (id, data) => api.put(`/connectors/${id}`, data),
  delete: (id) => api.delete(`/connectors/${id}`),
  discover: (id) => api.post(`/connectors/${id}/discover`, {}, { timeout: 60000 }),
  sync: (id) => api.post(`/connectors/${id}/sync`, {}, { timeout: 90000 }),
  test: (id) => api.post(`/connectors/${id}/test`, {}, { timeout: 60000 }),
  testTool: (id, data) => api.post(`/connectors/${id}/test-tool`, data, { timeout: 60000 }),
  testToolLlm: (id, data) => api.post(`/connectors/${id}/test-tool-llm`, data, { timeout: 120000 }),
  disconnect: (id) => api.post(`/connectors/${id}/disconnect`),
  startOauth: (id, data) => api.post(`/connectors/${id}/oauth/start`, data || {}),
}

export const toolApi = {
  list: (params) => api.get('/tools', { params }),
  listBuiltin: () => api.get('/tools/builtin'),
  create: (data) => api.post('/tools', data),
  get: (id) => api.get(`/tools/${id}`),
  update: (id, data) => api.put(`/tools/${id}`, data),
  delete: (id) => api.delete(`/tools/${id}`),
  test: (id, data) => api.post(`/tools/${id}/test`, data),
  discoverMcp: (data) => api.post('/tools/mcp/discover', data, { timeout: 60000 }),
}

export const mcpServerApi = {
  list: () => api.get('/mcp/servers'),
  create: (data) => api.post('/mcp/servers', data),
  get: (id) => api.get(`/mcp/servers/${id}`),
  update: (id, data) => api.put(`/mcp/servers/${id}`, data),
  delete: (id) => api.delete(`/mcp/servers/${id}`),
  discover: (id) => api.post(`/mcp/servers/${id}/discover`, {}, { timeout: 60000 }),
  sync: (id) => api.post(`/mcp/servers/${id}/sync`, {}, { timeout: 60000 }),
  testTool: (id, data) => api.post(`/mcp/servers/${id}/test-tool`, data, { timeout: 60000 }),
  testToolLlm: (id, data) => api.post(`/mcp/servers/${id}/test-tool-llm`, data, { timeout: 120000 }),
  startOauth: (id, data) => api.post(`/mcp/servers/${id}/oauth/start`, data || {}),
}

export const configApi = {
  getToolConfig: () => api.get('/config/tools'),
  updateTavily: (data) => api.put('/config/tools/tavily', data),
  getTavilyStatus: () => api.get('/config/tools/tavily/status'),
  getWebSearch: () => api.get('/config/tools/web-search'),
  updateWebSearch: (data) => api.put('/config/tools/web-search', data),
  getToolSearch: () => api.get('/config/tools/tool-search'),
  updateToolSearch: (data) => api.put('/config/tools/tool-search', data),
  getScreenpilot: () => api.get('/config/screenpilot'),
  updateScreenpilot: (data) => api.put('/config/screenpilot', data),
  listMemoryAgents: () => api.get('/config/memory/agents'),
  updateMemoryAgents: (items) => api.put('/config/memory/agents', { items }),
  getLetta: () => api.get('/config/memory/letta'),
  updateLetta: (data) => api.put('/config/memory/letta', data),
  getCodeExec: () => api.get('/config/code-exec'),
  updateCodeExec: (data) => api.put('/config/code-exec', data),
  listQueryRewriteAgents: () => api.get('/config/query-rewrite/agents'),
  updateQueryRewriteAgents: (items) => api.put('/config/query-rewrite/agents', { items }),
  getContextualRetrieval: () => api.get('/config/knowledge/contextual-retrieval'),
  updateContextualRetrieval: (data) => api.put('/config/knowledge/contextual-retrieval', data),
  getObservability: () => api.get('/config/observability'),
  updateObservability: (data) => api.put('/config/observability', data),
  getSelfopt: () => api.get('/config/selfopt'),
  updateSelfopt: (data) => api.put('/config/selfopt', data),
}

export const selfoptApi = {
  status: () => api.get('/selfopt/status'),
  overview: (params) => api.get('/selfopt/overview', { params }),
  createJob: (data) => api.post('/selfopt/jobs', data, { timeout: 180000 }),
  listJobs: (params) => api.get('/selfopt/jobs', { params }),
  getJob: (id) => api.get(`/selfopt/jobs/${id}`),
  getJobDetail: (id) => api.get(`/selfopt/jobs/${id}/detail`),
  listProposals: (params) => api.get('/selfopt/proposals', { params }),
  getProposal: (id) => api.get(`/selfopt/proposals/${id}`),
  startAb: (id, data) => api.post(`/selfopt/proposals/${id}/start-ab`, data || {}),
  rejectProposal: (id, data) => api.post(`/selfopt/proposals/${id}/reject`, data || {}),
  listAb: (params) => api.get('/selfopt/ab', { params }),
  getAb: (id) => api.get(`/selfopt/ab/${id}`),
  abReport: (id) => api.get(`/selfopt/ab/${id}/report`),
  promote: (id, data) => api.post(`/selfopt/ab/${id}/promote`, data || {}),
  keepControl: (id, data) => api.post(`/selfopt/ab/${id}/keep-control`, data || {}),
  abort: (id, data) => api.post(`/selfopt/ab/${id}/abort`, data || {}),
  getAgentPolicy: (agentId) => api.get(`/selfopt/agents/${agentId}/policy`),
  updateAgentPolicy: (agentId, data) => api.put(`/selfopt/agents/${agentId}/policy`, data),
}

export const queryRewriteApi = {
  preview: (data) => api.post('/query-rewrite/preview', data),
}

export const memoryApi = {
  listScopes: () => api.get('/memory/scopes'),
  listBlocks: (params) => api.get('/memory/blocks', { params }),
  updateBlock: (label, data) => api.put(`/memory/blocks/${label}`, data),
  listPassages: (params) => api.get('/memory/passages', { params }),
  createPassage: (data) => api.post('/memory/passages', data),
  deletePassage: (id, params) => api.delete(`/memory/passages/${id}`, { params }),
  lettaStatus: () => api.get('/memory/letta/status'),
  listEpisodes: (params) => api.get('/memory/episodes', { params }),
  processSession: (sessionId) => api.post(`/memory/process/${sessionId}`),
}

export const compositionApi = {
  get: (agentId) => api.get(`/agents/${agentId}/composition`),
  addSubAgent: (agentId, data) => api.post(`/agents/${agentId}/composition/sub-agents`, data),
  removeSubAgent: (agentId, childId) => api.delete(`/agents/${agentId}/composition/sub-agents/${childId}`),
  updateCoordinator: (agentId, data) => api.put(`/agents/${agentId}/composition/coordinator`, data),
  listCandidates: (agentId) => api.get(`/agents/${agentId}/composition/candidates`),
}

export const workflowApi = {
  get: (agentId) => api.get(`/agents/${agentId}/workflow`),
  update: (agentId, data) => api.put(`/agents/${agentId}/workflow`, data),
  validate: (agentId) => api.post(`/agents/${agentId}/workflow/validate`),
  candidates: (agentId) => api.get(`/agents/${agentId}/workflow/candidates`),
  triggerCron: (agentId) => api.post(`/agents/${agentId}/workflow/cron/trigger`),
}

export const monitorApi = {
  summary: (params) => api.get('/monitor/summary', { params }),
  listRuns: (params) => api.get('/monitor/runs', { params }),
  listObservations: (params) => api.get('/monitor/observations', { params }),
  listSessions: (params) => api.get('/monitor/sessions', { params }),
  listUsers: (params) => api.get('/monitor/users', { params }),
  getRun: (id) => api.get(`/monitor/runs/${id}`),
  exportOtel: (id) => api.get(`/monitor/runs/${id}/export/otel`),
  listAlerts: (params) => api.get('/monitor/alerts', { params }),
  ackAlert: (id) => api.post(`/monitor/alerts/${id}/ack`),
  listAlertRules: () => api.get('/monitor/alert-rules'),
  createAlertRule: (data) => api.post('/monitor/alert-rules', data),
  updateAlertRule: (id, data) => api.patch(`/monitor/alert-rules/${id}`, data),
  deleteAlertRule: (id) => api.delete(`/monitor/alert-rules/${id}`),
  listSavedViews: () => api.get('/monitor/saved-views'),
  createSavedView: (data) => api.post('/monitor/saved-views', data),
  submitFeedback: (data) => api.post('/monitor/feedback', data),
  effectReport: (params) => api.get('/monitor/reports/effect', { params }),
}

export const evalApi = {
  listDatasets: (params) => api.get('/eval/datasets', { params }),
  getDataset: (id) => api.get(`/eval/datasets/${id}`),
  createDataset: (data) => api.post('/eval/datasets', data),
  updateDataset: (id, data) => api.patch(`/eval/datasets/${id}`, data),
  deleteDataset: (id) => api.delete(`/eval/datasets/${id}`),
  listCases: (id) => api.get(`/eval/datasets/${id}/cases`),
  createCase: (id, data) => api.post(`/eval/datasets/${id}/cases`, data),
  updateCase: (datasetId, caseId, data) => api.patch(`/eval/datasets/${datasetId}/cases/${caseId}`, data),
  deleteCase: (datasetId, caseId) => api.delete(`/eval/datasets/${datasetId}/cases/${caseId}`),
  importRun: (datasetId, runId) => api.post(`/eval/datasets/${datasetId}/import-run/${runId}`),
  importFeedback: (datasetId, data) => api.post(`/eval/datasets/${datasetId}/import-feedback`, data),
  listJobs: (params) => api.get('/eval/jobs', { params }),
  createJob: (data) => api.post('/eval/jobs', data),
  runJob: (id) => api.post(`/eval/jobs/${id}/run`),
  getJob: (id) => api.get(`/eval/jobs/${id}`),
  compareJobs: (params) => api.get('/eval/jobs/compare', { params }),
  listEvaluators: (params) => api.get('/eval/evaluators', { params }),
  createEvaluator: (data) => api.post('/eval/evaluators', data),
  updateEvaluator: (id, data) => api.patch(`/eval/evaluators/${id}`, data),
  deleteEvaluator: (id) => api.delete(`/eval/evaluators/${id}`),
  listJudgeEvaluators: () => api.get('/eval/judge-evaluators'),
  createJudgeEvaluator: (data) => api.post('/eval/judge-evaluators', data),
  updateJudgeEvaluator: (id, data) => api.patch(`/eval/judge-evaluators/${id}`, data),
  listAnnotationQueues: () => api.get('/eval/annotation-queues'),
  createAnnotationQueue: (data) => api.post('/eval/annotation-queues', data),
  listAnnotationItems: (queueId) => api.get(`/eval/annotation-queues/${queueId}/items`),
  addAnnotationItem: (queueId, data) => api.post(`/eval/annotation-queues/${queueId}/items`, data),
  updateAnnotationItem: (queueId, itemId, data) => api.patch(`/eval/annotation-queues/${queueId}/items/${itemId}`, data),
}

export const scheduleApi = {
  list: (params) => api.get('/schedules', { params }),
  create: (data) => api.post('/schedules', data),
  get: (id) => api.get(`/schedules/${id}`),
  update: (id, data) => api.put(`/schedules/${id}`, data),
  delete: (id) => api.delete(`/schedules/${id}`),
  enable: (id) => api.post(`/schedules/${id}/enable`),
  disable: (id) => api.post(`/schedules/${id}/disable`),
  trigger: (id) => api.post(`/schedules/${id}/trigger`),
  listRuns: (id, params) => api.get(`/schedules/${id}/runs`, { params }),
  previewCron: (data) => api.post('/schedules/preview-cron', data),
  listRecentRuns: (params) => api.get('/schedules/runs/recent', { params }),
}

export const inboxApi = {
  list: (params) => api.get('/inbox/messages', { params }),
  unreadCount: () => api.get('/inbox/unread-count'),
  markRead: (id) => api.post(`/inbox/messages/${id}/read`),
  markSessionRead: (sessionId) => api.post(`/inbox/sessions/${sessionId}/read`),
}

export const dataQueryApi = {
  listAgents: (params) => api.get('/dataquery-agents', { params }),
  createAgent: (data) => api.post('/dataquery-agents', data),
  getAgent: (id) => api.get(`/dataquery-agents/${id}`),
  updateAgent: (id, data) => api.put(`/dataquery-agents/${id}`, data),
  deleteAgent: (id) => api.delete(`/dataquery-agents/${id}`),
  getDatasources: (id) => api.get(`/dataquery-agents/${id}/datasources`),
  updateDatasources: (id, data) => api.put(`/dataquery-agents/${id}/datasources`, data),
  listDatasourceTables: (id, datasourceId) => api.get(`/dataquery-agents/${id}/datasources/${datasourceId}/tables`),
  testQuery: (id, data) => api.post(`/dataquery-agents/${id}/test-query`, data),
  listLogs: (id, params) => api.get(`/dataquery-agents/${id}/logs`, { params }),
  listQualityStats: (id, params) => api.get(`/dataquery-agents/${id}/quality-stats`, { params }),

  listDictionary: (id, params) => api.get(`/dataquery-agents/${id}/metadata/dictionary`, { params }),
  createDictionary: (id, data) => api.post(`/dataquery-agents/${id}/metadata/dictionary`, data),
  updateDictionary: (id, itemId, data) => api.put(`/dataquery-agents/${id}/metadata/dictionary/${itemId}`, data),
  deleteDictionary: (id, itemId) => api.delete(`/dataquery-agents/${id}/metadata/dictionary/${itemId}`),
  listSchemaTables: (id, params) => api.get(`/dataquery-agents/${id}/metadata/schema/tables`, { params }),
  listSchemaColumns: (id, tableName, params) => api.get(`/dataquery-agents/${id}/metadata/schema/tables/${encodeURIComponent(tableName)}/columns`, { params }),
  upsertTableDictionary: (id, data) => api.put(`/dataquery-agents/${id}/metadata/table-dictionary`, data),
  batchUpsertDictionary: (id, data) => api.put(`/dataquery-agents/${id}/metadata/dictionary/batch`, data),

  listCodeMappings: (id, params) => api.get(`/dataquery-agents/${id}/metadata/code-mappings`, { params }),
  createCodeMapping: (id, data) => api.post(`/dataquery-agents/${id}/metadata/code-mappings`, data),
  updateCodeMapping: (id, itemId, data) => api.put(`/dataquery-agents/${id}/metadata/code-mappings/${itemId}`, data),
  deleteCodeMapping: (id, itemId) => api.delete(`/dataquery-agents/${id}/metadata/code-mappings/${itemId}`),

  listExamples: (id, params) => api.get(`/dataquery-agents/${id}/knowledge/examples`, { params }),
  createExample: (id, data) => api.post(`/dataquery-agents/${id}/knowledge/examples`, data),
  updateExample: (id, itemId, data) => api.put(`/dataquery-agents/${id}/knowledge/examples/${itemId}`, data),
  deleteExample: (id, itemId) => api.delete(`/dataquery-agents/${id}/knowledge/examples/${itemId}`),

  listTerms: (id, params) => api.get(`/dataquery-agents/${id}/knowledge/terms`, { params }),
  createTerm: (id, data) => api.post(`/dataquery-agents/${id}/knowledge/terms`, data),
  updateTerm: (id, itemId, data) => api.put(`/dataquery-agents/${id}/knowledge/terms/${itemId}`, data),
  deleteTerm: (id, itemId) => api.delete(`/dataquery-agents/${id}/knowledge/terms/${itemId}`),

  listFeedback: (id, params) => api.get(`/dataquery-agents/${id}/knowledge/feedback`, { params }),
  createFeedback: (id, data) => api.post(`/dataquery-agents/${id}/knowledge/feedback`, data),
}

export const hitlApi = {
  list: (params) => api.get('/approvals', { params }),
  get: (approvalId) => api.get(`/approvals/${approvalId}`),
  getPending: (sessionId) => api.get(`/sessions/${sessionId}/pending-approvals`),
  approve: (sessionId, approvalId, data) => api.post(`/sessions/${sessionId}/approvals/${approvalId}/approve`, data),
  reject: (sessionId, approvalId, data) => api.post(`/sessions/${sessionId}/approvals/${approvalId}/reject`, data),
}

export const screenpilotApi = {
  status: () => api.get('/screenpilot/status'),
  listSystems: () => api.get('/screenpilot/systems'),
  createSystem: (data) => api.post('/screenpilot/systems', data),
  getSystem: (id) => api.get(`/screenpilot/systems/${id}`),
  updateSystem: (id, data) => api.put(`/screenpilot/systems/${id}`, data),
  deleteSystem: (id) => api.delete(`/screenpilot/systems/${id}`),
  cdpStatus: (url) => api.get('/screenpilot/cdp/status', { params: url ? { url } : {} }),
  createCredential: (data) => api.post('/screenpilot/credentials', data),
  listCredentials: (systemId) => api.get(`/screenpilot/systems/${systemId}/credentials`),
  updateCredential: (id, data) => api.put(`/screenpilot/credentials/${id}`, data),
  deleteCredential: (id) => api.delete(`/screenpilot/credentials/${id}`),
  auditLogs: (params) => api.get('/screenpilot/audit-logs', { params }),
  listSkills: (params) => api.get('/screenpilot/skills', { params }),
  getSkill: (id) => api.get(`/screenpilot/skills/${id}`),
  updateSkill: (id, data) => api.put(`/screenpilot/skills/${id}`, data),
  updateSkillStep: (skillId, stepId, data) =>
    api.put(`/screenpilot/skills/${skillId}/steps/${stepId}`, data),
  compileSkill: (data) => api.post('/screenpilot/skills/compile', data),
  searchSkills: (data) => api.post('/screenpilot/skills/search', data),
  replaySkill: (data) => api.post('/screenpilot/skills/replay', data),
  runSkill: (data) => api.post('/screenpilot/skills/run', data),
  navigateSession: (data) => api.post('/screenpilot/sessions/navigate', data),
  observeSession: (id) => api.post(`/screenpilot/sessions/${id}/observe`),
  actSession: (id, data) => api.post(`/screenpilot/sessions/${id}/act`, data),
  getTrajectory: (id) => api.get(`/screenpilot/sessions/${id}/trajectory`),
  replaceTrajectory: (id, data) => api.put(`/screenpilot/sessions/${id}/trajectory`, data),
  clearTrajectory: (id) => api.delete(`/screenpilot/sessions/${id}/trajectory`),
  closeSession: (id) => api.delete(`/screenpilot/sessions/${id}`),
  publishSkill: (id, data) => api.post(`/screenpilot/skills/${id}/publish`, data),
  unpublishSkill: (id) => api.post(`/screenpilot/skills/${id}/unpublish`),
  deleteSkill: (id) => api.delete(`/screenpilot/skills/${id}`),
  importSkill: (id, data) => api.post(`/screenpilot/skills/${id}/import`, data),
  reindexSkills: (scope) => api.post('/screenpilot/skills/reindex', null, { params: { scope } }),
  analyzeRisk: (params) => api.get('/screenpilot/risk/analyze', { params }),
  optimizeRisk: (data) => api.post('/screenpilot/risk/optimize', data),
  gatewayStatus: () => api.get('/screenpilot/gateway/status'),
  listApprovals: (params) => api.get('/screenpilot/approvals', { params }),
  getApproval: (id) => api.get(`/screenpilot/approvals/${id}`),
  approveApproval: (id, data) => api.post(`/screenpilot/approvals/${id}/approve`, data),
  rejectApproval: (id, data) => api.post(`/screenpilot/approvals/${id}/reject`, data),
}

export const codeExecApi = {
  listExecutions: (sessionId, params) =>
    api.get(`/code-exec/sessions/${sessionId}/executions`, { params }),
  getExecution: (executionId) => api.get(`/code-exec/executions/${executionId}`),
  run: (sessionId, data) => api.post(`/code-exec/sessions/${sessionId}/run`, data),
  resetState: (sessionId) => api.delete(`/code-exec/sessions/${sessionId}/state`),
}
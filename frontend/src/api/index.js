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
  search: (id, data) => api.post(`/knowledge-bases/${id}/search`, data),
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

export const configApi = {
  getToolConfig: () => api.get('/config/tools'),
  updateTavily: (data) => api.put('/config/tools/tavily', data),
  getTavilyStatus: () => api.get('/config/tools/tavily/status'),
  getScreenpilot: () => api.get('/config/screenpilot'),
  updateScreenpilot: (data) => api.put('/config/screenpilot', data),
  listMemoryAgents: () => api.get('/config/memory/agents'),
  updateMemoryAgents: (items) => api.put('/config/memory/agents', { items }),
  getLetta: () => api.get('/config/memory/letta'),
  updateLetta: (data) => api.put('/config/memory/letta', data),
  listQueryRewriteAgents: () => api.get('/config/query-rewrite/agents'),
  updateQueryRewriteAgents: (items) => api.put('/config/query-rewrite/agents', { items }),
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
  mcpTemplate: () => api.get('/screenpilot/mcp-template'),
  listSkills: (params) => api.get('/screenpilot/skills', { params }),
  getSkill: (id) => api.get(`/screenpilot/skills/${id}`),
  updateSkill: (id, data) => api.put(`/screenpilot/skills/${id}`, data),
  updateSkillStep: (skillId, stepId, data) =>
    api.put(`/screenpilot/skills/${skillId}/steps/${stepId}`, data),
  compileSkill: (data) => api.post('/screenpilot/skills/compile', data),
  searchSkills: (data) => api.post('/screenpilot/skills/search', data),
  replaySkill: (data) => api.post('/screenpilot/skills/replay', data),
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
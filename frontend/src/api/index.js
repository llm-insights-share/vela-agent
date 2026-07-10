import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.code === 'ECONNABORTED' && err.message?.includes('timeout')) {
      return Promise.reject(new Error('请求超时，模型响应较慢，请重试或简化 Skill 内容'))
    }
    const msg = err.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)))
  }
)

export default api

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
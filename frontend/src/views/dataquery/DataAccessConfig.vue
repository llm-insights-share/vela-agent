<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">数据访问</h2>
      <a-space>
        <a-button @click="openCreateAgent">新建 DataQueryAgent</a-button>
        <a-button @click="$router.push('/data-access/monitor')">监控视图</a-button>
        <a-button type="primary" :disabled="!currentAgentId" @click="saveDatasourceBindings">保存数据源绑定</a-button>
      </a-space>
    </div>

    <a-row :gutter="16">
      <a-col :span="7">
        <a-card title="DataQueryAgent 列表">
          <a-list :data-source="agents" size="small" bordered>
            <template #renderItem="{ item }">
              <a-list-item :class="{ active: item.dq_agent_id === currentAgentId }" @click="selectAgent(item)">
                <div style="width:100%">
                  <div><strong>{{ item.name }}</strong></div>
                  <div class="meta-line">{{ item.status }} · {{ item.model_service_id }}</div>
                </div>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </a-col>

      <a-col :span="17">
        <a-card v-if="currentAgent" :title="`配置：${currentAgent.name}`">
          <a-tabs v-model:activeKey="activeTab">
            <a-tab-pane key="basic" tab="基础配置">
              <a-form layout="vertical">
                <a-row :gutter="12">
                  <a-col :span="12"><a-form-item label="名称"><a-input v-model:value="currentAgent.name" /></a-form-item></a-col>
                  <a-col :span="12"><a-form-item label="状态"><a-select v-model:value="currentAgent.status"><a-select-option value="ACTIVE">ACTIVE</a-select-option><a-select-option value="INACTIVE">INACTIVE</a-select-option><a-select-option value="DEPRECATED">DEPRECATED</a-select-option></a-select></a-form-item></a-col>
                </a-row>
                <a-row :gutter="12">
                  <a-col :span="12"><a-form-item label="主模型服务 ID"><a-input v-model:value="currentAgent.model_service_id" /></a-form-item></a-col>
                  <a-col :span="6"><a-form-item label="Temperature"><a-input-number v-model:value="currentAgent.temperature" :min="0" :max="2" :step="0.1" style="width:100%" /></a-form-item></a-col>
                  <a-col :span="6"><a-form-item label="Max Tokens"><a-input-number v-model:value="currentAgent.max_tokens" :min="256" :max="32768" style="width:100%" /></a-form-item></a-col>
                </a-row>
                <a-row :gutter="12">
                  <a-col :span="8"><a-form-item label="默认 LIMIT"><a-input-number v-model:value="currentAgent.default_limit" :min="1" :max="5000" style="width:100%" /></a-form-item></a-col>
                  <a-col :span="8"><a-form-item label="超时(秒)"><a-input-number v-model:value="currentAgent.timeout_seconds" :min="5" :max="300" style="width:100%" /></a-form-item></a-col>
                  <a-col :span="8"><a-form-item label="严格模式"><a-switch v-model:checked="currentAgent.strict_mode" /></a-form-item></a-col>
                </a-row>
                <a-form-item label="说明">
                  <a-textarea v-model:value="currentAgent.description" :rows="3" />
                </a-form-item>
                <a-button type="primary" @click="saveCurrentAgent">保存基础配置</a-button>
              </a-form>
            </a-tab-pane>

            <a-tab-pane key="datasource" tab="数据源绑定">
              <a-space style="margin-bottom:12px">
                <a-button @click="addDatasource">新增数据源</a-button>
              </a-space>
              <a-table :data-source="datasourceBindings" :pagination="false" rowKey="row_key" size="small">
                <a-table-column title="数据源ID" key="datasource_id">
                  <template #default="{ record }"><a-input v-model:value="record.datasource_id" /></template>
                </a-table-column>
                <a-table-column title="类型" key="db_type" width="120">
                  <template #default="{ record }"><a-select v-model:value="record.db_type"><a-select-option value="sqlite">sqlite</a-select-option><a-select-option value="postgresql">postgresql</a-select-option><a-select-option value="mysql">mysql</a-select-option></a-select></template>
                </a-table-column>
                <a-table-column title="连接串" key="db_url">
                  <template #default="{ record }"><a-input v-model:value="record.db_url" placeholder="sqlite:///path/to.db" /></template>
                </a-table-column>
                <a-table-column title="表白名单(逗号)" key="table_whitelist">
                  <template #default="{ record }"><a-input :value="(record.table_whitelist||[]).join(',')" @change="onWhitelistChange(record, $event.target.value)" /></template>
                </a-table-column>
                <a-table-column title="操作" key="action" width="80">
                  <template #default="{ index }"><a-button danger size="small" @click="removeDatasource(index)">删</a-button></template>
                </a-table-column>
              </a-table>
              <div style="margin-top:12px">
                <a-alert type="info" show-icon message="nl2sql_query 按普通工具方式接入" description="在工具管理中创建/更新工具：name=nl2sql_query，tool_type=restful(或mcp/local_python)，并在 config 中设置 adapter=dataquery_agent 与 dq_agent_id。" />
              </div>
            </a-tab-pane>

            <a-tab-pane key="dictionary" tab="数据字典">
              <a-space style="margin-bottom:12px"><a-button @click="openDictionaryCreate">新增字典项</a-button></a-space>
              <a-table :data-source="dictionaryItems" rowKey="id" size="small" :pagination="{ pageSize: 20 }">
                <a-table-column title="表" dataIndex="table_name" />
                <a-table-column title="列" dataIndex="column_name" />
                <a-table-column title="业务名" dataIndex="business_name" />
                <a-table-column title="描述" dataIndex="description" ellipsis />
              </a-table>
            </a-tab-pane>

            <a-tab-pane key="mapping" tab="代码映射">
              <a-space style="margin-bottom:12px"><a-button @click="openMappingCreate">新增映射</a-button></a-space>
              <a-table :data-source="codeMappings" rowKey="id" size="small" :pagination="{ pageSize: 20 }">
                <a-table-column title="列" dataIndex="column_name" />
                <a-table-column title="代码" dataIndex="code_value" />
                <a-table-column title="名称" dataIndex="display_name" />
              </a-table>
            </a-tab-pane>

            <a-tab-pane key="examples" tab="样例与术语">
              <a-row :gutter="12">
                <a-col :span="12">
                  <a-card size="small" title="样例">
                    <a-space style="margin-bottom:8px"><a-button size="small" @click="openExampleCreate">新增样例</a-button></a-space>
                    <a-list size="small" bordered :data-source="examples">
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <div>
                            <div>{{ item.nl_question }}</div>
                            <div class="meta-line">{{ item.intent_tag }}</div>
                          </div>
                        </a-list-item>
                      </template>
                    </a-list>
                  </a-card>
                </a-col>
                <a-col :span="12">
                  <a-card size="small" title="术语转换">
                    <a-space style="margin-bottom:8px"><a-button size="small" @click="openTermCreate">新增术语</a-button></a-space>
                    <a-list size="small" bordered :data-source="terms">
                      <template #renderItem="{ item }">
                        <a-list-item>
                          <div>{{ item.source_term }} → {{ item.normalized_term }}</div>
                        </a-list-item>
                      </template>
                    </a-list>
                  </a-card>
                </a-col>
              </a-row>
            </a-tab-pane>

            <a-tab-pane key="monitor" tab="监控">
              <a-row :gutter="12">
                <a-col :span="12">
                  <a-card size="small" title="质量统计">
                    <a-table :data-source="qualityStats" rowKey="id" size="small" :pagination="{ pageSize: 10 }">
                      <a-table-column title="日期" dataIndex="stat_date" />
                      <a-table-column title="总数" dataIndex="total_queries" />
                      <a-table-column title="成功" dataIndex="success_queries" />
                      <a-table-column title="失败" dataIndex="failed_queries" />
                    </a-table>
                  </a-card>
                </a-col>
                <a-col :span="12">
                  <a-card size="small" title="最近查询日志">
                    <a-table :data-source="queryLogs" rowKey="log_id" size="small" :pagination="{ pageSize: 10 }">
                      <a-table-column title="状态" dataIndex="execution_status" />
                      <a-table-column title="问题" dataIndex="question" ellipsis />
                      <a-table-column title="耗时ms" dataIndex="duration_ms" />
                    </a-table>
                  </a-card>
                </a-col>
              </a-row>
            </a-tab-pane>
          </a-tabs>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { dataQueryApi } from '../../api'

const agents = ref([])
const currentAgentId = ref('')
const currentAgent = ref(null)
const activeTab = ref('basic')

const datasourceBindings = ref([])
const dictionaryItems = ref([])
const codeMappings = ref([])
const examples = ref([])
const terms = ref([])
const queryLogs = ref([])
const qualityStats = ref([])

async function loadAgents() {
  const res = await dataQueryApi.listAgents({ page_size: 100 })
  agents.value = res.items || []
  if (!currentAgentId.value && agents.value.length) {
    selectAgent(agents.value[0])
  }
}

async function selectAgent(agent) {
  currentAgentId.value = agent.dq_agent_id
  currentAgent.value = JSON.parse(JSON.stringify(agent))
  await Promise.all([
    loadDatasources(),
    loadDictionary(),
    loadMappings(),
    loadExamples(),
    loadTerms(),
    loadLogs(),
    loadQualityStats(),
  ])
}

async function loadDatasources() {
  if (!currentAgentId.value) return
  const list = await dataQueryApi.getDatasources(currentAgentId.value)
  datasourceBindings.value = (list || []).map((x, idx) => ({ ...x, row_key: `${x.id || 'n'}_${idx}` }))
}

async function loadDictionary() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listDictionary(currentAgentId.value, { page_size: 200 })
  dictionaryItems.value = res.items || []
}

async function loadMappings() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listCodeMappings(currentAgentId.value, { page_size: 200 })
  codeMappings.value = res.items || []
}

async function loadExamples() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listExamples(currentAgentId.value, { page_size: 200 })
  examples.value = res.items || []
}

async function loadTerms() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listTerms(currentAgentId.value, { page_size: 200 })
  terms.value = res.items || []
}

async function loadLogs() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listLogs(currentAgentId.value, { page_size: 50 })
  queryLogs.value = res.items || []
}

async function loadQualityStats() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listQualityStats(currentAgentId.value, { page_size: 50 })
  qualityStats.value = res.items || []
}

async function openCreateAgent() {
  const payload = {
    name: `dq_agent_${Date.now()}`,
    description: '',
    model_service_id: '',
    temperature: 0.1,
    max_tokens: 2048,
    default_limit: 200,
    timeout_seconds: 30,
    strict_mode: true,
    allow_cross_datasource: false,
    status: 'ACTIVE',
  }
  try {
    const res = await dataQueryApi.createAgent(payload)
    message.success('创建成功，请补充模型服务ID')
    await loadAgents()
    await selectAgent(res)
  } catch (e) {
    message.error(e.message)
  }
}

async function saveCurrentAgent() {
  try {
    await dataQueryApi.updateAgent(currentAgentId.value, currentAgent.value)
    message.success('基础配置已保存')
    await loadAgents()
  } catch (e) {
    message.error(e.message)
  }
}

function addDatasource() {
  datasourceBindings.value.push({
    row_key: `new_${Date.now()}`,
    datasource_id: '',
    datasource_name: '',
    db_type: 'sqlite',
    db_url: '',
    schema_name: '',
    table_whitelist: [],
    sensitive_columns: [],
    default_limit: 200,
    timeout_seconds: 30,
    status: 'ACTIVE',
  })
}

function removeDatasource(index) {
  datasourceBindings.value.splice(index, 1)
}

function onWhitelistChange(record, text) {
  record.table_whitelist = (text || '').split(',').map(s => s.trim()).filter(Boolean)
}

async function saveDatasourceBindings() {
  try {
    await dataQueryApi.updateDatasources(currentAgentId.value, {
      bindings: datasourceBindings.value.map(({ row_key, id, created_at, updated_at, ...rest }) => rest),
    })
    message.success('数据源绑定已保存')
    await loadDatasources()
  } catch (e) {
    message.error(e.message)
  }
}

async function openDictionaryCreate() {
  try {
    await dataQueryApi.createDictionary(currentAgentId.value, {
      datasource_id: datasourceBindings.value[0]?.datasource_id || '',
      table_name: 'your_table',
      column_name: 'your_column',
      business_name: '业务名称',
      description: '',
      value_type: 'string',
      synonyms: [],
      metric_formula: '',
    })
    message.success('已创建默认字典项，请编辑')
    await loadDictionary()
  } catch (e) {
    message.error(e.message)
  }
}

async function openMappingCreate() {
  try {
    await dataQueryApi.createCodeMapping(currentAgentId.value, {
      datasource_id: datasourceBindings.value[0]?.datasource_id || '',
      table_name: '',
      column_name: 'status_code',
      code_value: '1',
      display_name: '示例名称',
      aliases: [],
    })
    message.success('已创建默认映射项，请编辑')
    await loadMappings()
  } catch (e) {
    message.error(e.message)
  }
}

async function openExampleCreate() {
  try {
    await dataQueryApi.createExample(currentAgentId.value, {
      datasource_id: datasourceBindings.value[0]?.datasource_id || '',
      intent_tag: 'demo',
      nl_question: '上月销售额是多少',
      sql_template: 'SELECT 1 AS amount',
      variables: {},
      explanation: '',
      quality_score: 0.5,
      enabled: true,
    })
    message.success('已创建默认样例，请编辑')
    await loadExamples()
  } catch (e) {
    message.error(e.message)
  }
}

async function openTermCreate() {
  try {
    await dataQueryApi.createTerm(currentAgentId.value, {
      source_term: '离职人数',
      normalized_term: '员工离职人数',
      mapping_type: 'synonym',
      priority: 100,
      enabled: true,
    })
    message.success('已创建默认术语，请编辑')
    await loadTerms()
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  try {
    await loadAgents()
  } catch (e) {
    message.error(e.message)
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin: 0;
}
.meta-line {
  color: #999;
  font-size: 12px;
}
.active {
  background: #f0f5ff;
}
</style>

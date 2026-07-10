<template>
  <div>
    <div class="page-header">
      <h2 class="page-title">数据访问</h2>
      <a-space>
        <a-button @click="openCreateAgent">新建 DataQueryAgent</a-button>
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
                  <a-col :span="12">
                    <a-form-item label="主模型服务">
                      <a-select
                        v-model:value="currentAgent.model_service_id"
                        show-search
                        option-filter-prop="label"
                        placeholder="请选择模型服务"
                        :options="modelServiceOptions"
                      />
                    </a-form-item>
                  </a-col>
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
                <a-table-column title="状态" key="status" width="130">
                  <template #default="{ record }">
                    <a-select v-model:value="record.status">
                      <a-select-option value="ACTIVE">ACTIVE</a-select-option>
                      <a-select-option value="INACTIVE">INACTIVE</a-select-option>
                    </a-select>
                  </template>
                </a-table-column>
                <a-table-column title="连接串" key="db_url">
                  <template #default="{ record }"><a-input v-model:value="record.db_url" :placeholder="dbUrlPlaceholder(record.db_type)" /></template>
                </a-table-column>
                <a-table-column title="表白名单(逗号)" key="table_whitelist">
                  <template #default="{ record }"><a-input :value="(record.table_whitelist||[]).join(',')" @change="onWhitelistChange(record, $event.target.value)" /></template>
                </a-table-column>
                <a-table-column title="操作" key="action" width="80">
                  <template #default="{ index }"><a-button danger size="small" @click="removeDatasource(index)">删</a-button></template>
                </a-table-column>
              </a-table>
              <div style="margin-top:12px">
                <a-button type="primary" :disabled="!currentAgentId" @click="saveDatasourceBindings">保存数据源绑定</a-button>
              </div>
              <a-card size="small" style="margin-top:12px">
                <template #title>nl2sql_query 按普通工具方式接入</template>
                <template #extra>
                  <a-button
                    type="primary"
                    size="small"
                    :disabled="!currentAgentId"
                    :loading="generatingTool"
                    @click="generateNl2sqlTool"
                  >
                    一键生成工具
                  </a-button>
                </template>
                <a-alert
                  type="info"
                  show-icon
                  description="在工具管理中创建/更新工具：name=nl2sql_query，tool_type=restful(或mcp/local_python)，并在 config 中设置 adapter=dataquery_agent 与 dq_agent_id。"
                />
              </a-card>
            </a-tab-pane>

            <a-tab-pane key="dictionary" tab="数据字典">
              <a-space style="margin-bottom:12px">
                <span>数据源</span>
                <a-select
                  v-model:value="selectedDictionaryDatasourceId"
                  :options="datasourceOptions"
                  placeholder="请选择数据源"
                  style="width: 280px"
                  @change="onDictionaryTabDatasourceChange"
                />
              </a-space>
              <a-table
                :data-source="schemaTables"
                rowKey="table_name"
                size="small"
                :loading="schemaTablesLoading"
                :pagination="{ pageSize: 20 }"
              >
                <a-table-column title="表代码" dataIndex="table_name" />
                <a-table-column title="名称" key="business_name">
                  <template #default="{ record }">{{ record.business_name || '-' }}</template>
                </a-table-column>
                <a-table-column title="描述" key="description" ellipsis>
                  <template #default="{ record }">{{ formatTableDescription(record) }}</template>
                </a-table-column>
                <a-table-column title="别名" key="synonyms">
                  <template #default="{ record }">{{ (record.synonyms || []).join(', ') || '-' }}</template>
                </a-table-column>
                <a-table-column title="操作" key="action" width="160">
                  <template #default="{ record }">
                    <a-space>
                      <a-button size="small" @click="openTableAnnotate(record)">标注</a-button>
                      <a-button size="small" @click="openTableDetail(record)">详情</a-button>
                    </a-space>
                  </template>
                </a-table-column>
              </a-table>
            </a-tab-pane>

            <a-tab-pane key="mapping" tab="代码映射">
              <a-space style="margin-bottom:12px">
                <span>数据源</span>
                <a-select
                  v-model:value="selectedMappingDatasourceId"
                  :options="mappingFilterOptions"
                  placeholder="全部数据源"
                  allow-clear
                  style="width: 280px"
                  @change="loadMappings"
                />
                <a-button @click="openMappingCreate">新增映射</a-button>
              </a-space>
              <a-table :data-source="codeMappings" rowKey="id" size="small" :pagination="{ pageSize: 20 }">
                <a-table-column title="表名" dataIndex="table_name" />
                <a-table-column title="列名" dataIndex="column_name" />
                <a-table-column title="代码" dataIndex="code_value" />
                <a-table-column title="名称" dataIndex="display_name" />
                <a-table-column title="操作" key="action" width="140">
                  <template #default="{ record }">
                    <a-space>
                      <a-button size="small" @click="openMappingEdit(record)">编辑</a-button>
                      <a-button danger size="small" @click="deleteMapping(record)">删除</a-button>
                    </a-space>
                  </template>
                </a-table-column>
              </a-table>
            </a-tab-pane>

            <a-tab-pane key="examples" tab="样例">
              <a-space style="margin-bottom:12px">
                <a-button @click="openExampleCreate">新增样例</a-button>
              </a-space>
              <a-list size="small" bordered :data-source="examples">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <div style="flex:1">
                      <div>{{ item.nl_question }}</div>
                      <div class="meta-line">{{ item.intent_tag }}</div>
                    </div>
                    <a-space>
                      <a-button size="small" @click="openExampleEdit(item)">编辑</a-button>
                      <a-button danger size="small" @click="deleteExample(item)">删除</a-button>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>

            <a-tab-pane key="terms" tab="术语转换">
              <a-space style="margin-bottom:12px">
                <a-button @click="openTermCreate">新增术语</a-button>
              </a-space>
              <a-list size="small" bordered :data-source="terms">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <div style="flex:1">{{ item.source_term }} → {{ item.normalized_term }}</div>
                    <a-space>
                      <a-button size="small" @click="openTermEdit(item)">编辑</a-button>
                      <a-button danger size="small" @click="deleteTerm(item)">删除</a-button>
                    </a-space>
                  </a-list-item>
                </template>
              </a-list>
            </a-tab-pane>

            <a-tab-pane key="monitor" tab="监控">
              <a-card size="small" title="质量统计" style="margin-bottom:16px">
                <a-table :data-source="qualityStats" rowKey="id" size="small" :pagination="monitorPagination">
                  <a-table-column title="日期" dataIndex="stat_date" />
                  <a-table-column title="总数" dataIndex="total_queries" />
                  <a-table-column title="成功" dataIndex="success_queries" />
                  <a-table-column title="失败" dataIndex="failed_queries" />
                </a-table>
              </a-card>
              <a-card size="small" title="最近查询日志">
                <a-table :data-source="queryLogs" rowKey="log_id" size="small" :pagination="monitorPagination">
                  <a-table-column title="状态" dataIndex="execution_status" />
                  <a-table-column title="问题" dataIndex="question" ellipsis />
                  <a-table-column title="耗时ms" dataIndex="duration_ms" />
                </a-table>
              </a-card>
            </a-tab-pane>
          </a-tabs>
        </a-card>
      </a-col>
    </a-row>

    <a-modal
      v-model:open="tableAnnotateModalOpen"
      title="表标注"
      @ok="submitTableAnnotate"
      @cancel="tableAnnotateModalOpen = false"
    >
      <a-form layout="vertical">
        <a-form-item label="表代码"><a-input :value="tableAnnotateForm.table_name" disabled /></a-form-item>
        <a-form-item label="业务名称"><a-input v-model:value="tableAnnotateForm.business_name" placeholder="为表增加业务名称" /></a-form-item>
        <a-form-item label="别名(逗号分隔)"><a-input v-model:value="tableAnnotateForm.synonyms_text" placeholder="例如：订单表,order" /></a-form-item>
        <a-form-item label="补充描述"><a-textarea v-model:value="tableAnnotateForm.description" :rows="3" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="columnDetailModalOpen"
      :title="`字段详情：${currentDetailTableName}`"
      width="900px"
      @ok="submitColumnDetails"
      @cancel="columnDetailModalOpen = false"
    >
      <a-table :data-source="columnDetailRows" rowKey="column_name" size="small" :pagination="false">
        <a-table-column title="字段代码" dataIndex="column_name" width="140" />
        <a-table-column title="名称" dataIndex="business_name" width="140" />
        <a-table-column title="描述" dataIndex="db_comment" ellipsis />
        <a-table-column title="补充描述" key="description">
          <template #default="{ record }">
            <a-input v-model:value="record.description" placeholder="补充字段描述" />
          </template>
        </a-table-column>
      </a-table>
    </a-modal>

    <a-modal
      v-model:open="mappingModalOpen"
      :title="mappingModalMode === 'create' ? '新增代码映射' : '编辑代码映射'"
      @ok="submitMapping"
      @cancel="mappingModalOpen = false"
    >
      <a-form layout="vertical">
        <a-form-item label="数据源">
          <a-select
            v-model:value="mappingForm.datasource_id"
            :disabled="mappingModalMode === 'edit'"
            :options="datasourceOptions"
            placeholder="请选择数据源"
            @change="onMappingDatasourceChange"
          />
        </a-form-item>
        <a-form-item label="表名">
          <a-select
            v-model:value="mappingForm.table_name"
            :disabled="mappingModalMode === 'edit'"
            :options="mappingTableOptions"
            placeholder="请选择表"
            @change="onMappingTableChange"
          />
        </a-form-item>
        <a-form-item label="列名">
          <a-select
            v-model:value="mappingForm.column_name"
            :disabled="mappingModalMode === 'edit'"
            :options="mappingColumnOptions"
            placeholder="请选择列"
          />
        </a-form-item>
        <a-form-item label="代码"><a-input v-model:value="mappingForm.code_value" :disabled="mappingModalMode === 'edit'" /></a-form-item>
        <a-form-item label="显示名"><a-input v-model:value="mappingForm.display_name" /></a-form-item>
        <a-form-item label="别名(逗号分隔)"><a-input v-model:value="mappingForm.aliases_text" /></a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="exampleModalOpen"
      :title="exampleModalMode === 'create' ? '新增样例' : '编辑样例'"
      width="760px"
      @ok="submitExample"
      @cancel="exampleModalOpen = false"
    >
      <a-form layout="vertical">
        <a-form-item label="数据源">
          <a-select
            v-model:value="exampleForm.datasource_id"
            :disabled="exampleModalMode === 'edit'"
            :options="datasourceOptions"
            placeholder="请选择数据源"
          />
        </a-form-item>
        <a-form-item label="意图标签"><a-input v-model:value="exampleForm.intent_tag" /></a-form-item>
        <a-form-item label="自然语言问题"><a-input v-model:value="exampleForm.nl_question" /></a-form-item>
        <a-form-item label="SQL 模板"><a-textarea v-model:value="exampleForm.sql_template" :rows="4" /></a-form-item>
        <a-form-item label="变量(JSON)">
          <a-textarea v-model:value="exampleForm.variables_text" :rows="3" />
        </a-form-item>
        <a-form-item label="说明"><a-textarea v-model:value="exampleForm.explanation" :rows="2" /></a-form-item>
        <a-row :gutter="12">
          <a-col :span="12"><a-form-item label="质量分"><a-input-number v-model:value="exampleForm.quality_score" :min="0" :max="1" :step="0.1" style="width:100%" /></a-form-item></a-col>
          <a-col :span="12"><a-form-item label="启用"><a-switch v-model:checked="exampleForm.enabled" /></a-form-item></a-col>
        </a-row>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="termModalOpen"
      :title="termModalMode === 'create' ? '新增术语' : '编辑术语'"
      @ok="submitTerm"
      @cancel="termModalOpen = false"
    >
      <a-form layout="vertical">
        <a-form-item label="原术语"><a-input v-model:value="termForm.source_term" :disabled="termModalMode === 'edit'" /></a-form-item>
        <a-form-item label="标准术语"><a-input v-model:value="termForm.normalized_term" /></a-form-item>
        <a-form-item label="映射类型"><a-input v-model:value="termForm.mapping_type" /></a-form-item>
        <a-form-item label="优先级"><a-input-number v-model:value="termForm.priority" :min="1" :max="1000" style="width:100%" /></a-form-item>
        <a-form-item label="启用"><a-switch v-model:checked="termForm.enabled" /></a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { dataQueryApi, serviceApi, toolApi } from '../../api'

const agents = ref([])
const currentAgentId = ref('')
const currentAgent = ref(null)
const activeTab = ref('basic')

const datasourceBindings = ref([])
const schemaTables = ref([])
const schemaTablesLoading = ref(false)
const selectedDictionaryDatasourceId = ref('')
const selectedMappingDatasourceId = ref('')
const codeMappings = ref([])
const examples = ref([])
const terms = ref([])
const queryLogs = ref([])
const qualityStats = ref([])
const monitorPagination = { pageSize: 20, showSizeChanger: false }
const modelServices = ref([])
const generatingTool = ref(false)

const tableAnnotateModalOpen = ref(false)
const tableAnnotateForm = ref({
  table_name: '',
  business_name: '',
  synonyms_text: '',
  description: '',
})

const columnDetailModalOpen = ref(false)
const currentDetailTableName = ref('')
const columnDetailRows = ref([])

const mappingModalOpen = ref(false)
const mappingModalMode = ref('create')
const mappingModalTables = ref([])
const mappingModalColumns = ref([])
const mappingForm = ref({
  id: null,
  datasource_id: '',
  table_name: '',
  column_name: '',
  code_value: '',
  display_name: '',
  aliases_text: '',
})

const exampleModalOpen = ref(false)
const exampleModalMode = ref('create')
const exampleForm = ref({
  example_id: '',
  datasource_id: '',
  intent_tag: '',
  nl_question: '',
  sql_template: '',
  variables_text: '{}',
  explanation: '',
  quality_score: 0.5,
  enabled: true,
})

const termModalOpen = ref(false)
const termModalMode = ref('create')
const termForm = ref({
  id: null,
  source_term: '',
  normalized_term: '',
  mapping_type: 'synonym',
  priority: 100,
  enabled: true,
})

async function loadModelServices() {
  const res = await serviceApi.list({ page_size: 100 })
  modelServices.value = res.items || []
}

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
  selectedDictionaryDatasourceId.value = ''
  schemaTables.value = []
  await Promise.all([
    loadDatasources(),
    loadMappings(),
    loadExamples(),
    loadTerms(),
    loadLogs(),
    loadQualityStats(),
  ])
  if (datasourceBindings.value.length) {
    selectedDictionaryDatasourceId.value = datasourceBindings.value[0].datasource_id
    await loadSchemaTables()
  }
}

async function loadDatasources() {
  if (!currentAgentId.value) return
  const prevSelected = selectedDictionaryDatasourceId.value
  const list = await dataQueryApi.getDatasources(currentAgentId.value)
  datasourceBindings.value = (list || []).map((x, idx) => ({
    ...x,
    status: x.status || 'ACTIVE',
    row_key: `${x.id || 'n'}_${idx}`,
  }))
  if (prevSelected && datasourceBindings.value.some((x) => x.datasource_id === prevSelected)) {
    selectedDictionaryDatasourceId.value = prevSelected
  }
}

async function loadSchemaTables() {
  if (!currentAgentId.value || !selectedDictionaryDatasourceId.value) {
    schemaTables.value = []
    return
  }
  schemaTablesLoading.value = true
  try {
    const list = await dataQueryApi.listSchemaTables(currentAgentId.value, {
      datasource_id: selectedDictionaryDatasourceId.value,
    })
    schemaTables.value = list || []
  } catch (e) {
    schemaTables.value = []
    message.error(e.message)
  } finally {
    schemaTablesLoading.value = false
  }
}

async function onDictionaryTabDatasourceChange() {
  await loadSchemaTables()
}

async function loadMappings() {
  if (!currentAgentId.value) return
  const params = { page_size: 200 }
  if (selectedMappingDatasourceId.value) {
    params.datasource_id = selectedMappingDatasourceId.value
  }
  const res = await dataQueryApi.listCodeMappings(currentAgentId.value, params)
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
  const res = await dataQueryApi.listLogs(currentAgentId.value, { page_size: 100 })
  queryLogs.value = res.items || []
}

async function loadQualityStats() {
  if (!currentAgentId.value) return
  const res = await dataQueryApi.listQualityStats(currentAgentId.value, { page_size: 200 })
  qualityStats.value = res.items || []
}

async function openCreateAgent() {
  if (!modelServices.value.length) {
    message.error('没有可用模型服务，请先在“模型服务”中创建并激活模型')
    return
  }
  const defaultModelId = modelServices.value[0].model_service_id
  const payload = {
    name: `dq_agent_${Date.now()}`,
    description: '',
    model_service_id: defaultModelId,
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
    message.success('创建成功')
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

function dbUrlPlaceholder(dbType) {
  if (dbType === 'mysql') return 'mysql://user:pass@host:3306/dbname'
  if (dbType === 'postgresql') return 'postgresql://user:pass@host:5432/dbname'
  return 'sqlite:///path/to.db'
}

async function saveDatasourceBindings() {
  try {
    const payloadBindings = datasourceBindings.value.map(({ row_key, id, created_at, updated_at, ...rest }) => ({
      ...rest,
      status: rest.status || 'ACTIVE',
    }))
    await dataQueryApi.updateDatasources(currentAgentId.value, {
      bindings: payloadBindings,
    })
    message.success('数据源绑定已保存')
    const prevSelected = selectedDictionaryDatasourceId.value
    await loadDatasources()
    if (prevSelected && datasourceBindings.value.some((x) => x.datasource_id === prevSelected)) {
      selectedDictionaryDatasourceId.value = prevSelected
    } else if (datasourceBindings.value.length && !selectedDictionaryDatasourceId.value) {
      selectedDictionaryDatasourceId.value = datasourceBindings.value[0].datasource_id
    }
    const selectedBinding = datasourceBindings.value.find((x) => x.datasource_id === selectedDictionaryDatasourceId.value)
    if (selectedBinding && selectedBinding.status === 'INACTIVE') {
      message.info('当前选择的数据源状态为 INACTIVE，不会参与查询执行')
    }
    await loadSchemaTables()
  } catch (e) {
    message.error(e.message)
  }
}

async function loadMappingModalTables(datasourceId) {
  if (!currentAgentId.value || !datasourceId) {
    mappingModalTables.value = []
    return
  }
  const list = await dataQueryApi.listSchemaTables(currentAgentId.value, { datasource_id: datasourceId })
  mappingModalTables.value = list || []
}

async function loadMappingModalColumns(datasourceId, tableName) {
  if (!currentAgentId.value || !datasourceId || !tableName) {
    mappingModalColumns.value = []
    return
  }
  const list = await dataQueryApi.listSchemaColumns(currentAgentId.value, tableName, { datasource_id: datasourceId })
  mappingModalColumns.value = list || []
}

async function onMappingDatasourceChange(value) {
  mappingForm.value.table_name = ''
  mappingForm.value.column_name = ''
  mappingModalColumns.value = []
  try {
    await loadMappingModalTables(value)
    const firstTable = mappingModalTables.value[0]?.table_name
    if (firstTable) {
      mappingForm.value.table_name = firstTable
      await onMappingTableChange(firstTable)
    }
  } catch (e) {
    message.error(e.message)
  }
}

async function onMappingTableChange(value) {
  mappingForm.value.column_name = ''
  try {
    await loadMappingModalColumns(mappingForm.value.datasource_id, value)
    const firstColumn = mappingModalColumns.value[0]?.column_name
    if (firstColumn) mappingForm.value.column_name = firstColumn
  } catch (e) {
    message.error(e.message)
  }
}

async function openMappingCreate() {
  const defaultDatasourceId = selectedMappingDatasourceId.value || datasourceBindings.value[0]?.datasource_id || ''
  mappingModalMode.value = 'create'
  mappingForm.value = {
    id: null,
    datasource_id: defaultDatasourceId,
    table_name: '',
    column_name: '',
    code_value: '',
    display_name: '',
    aliases_text: '',
  }
  mappingModalTables.value = []
  mappingModalColumns.value = []
  if (defaultDatasourceId) {
    try {
      await onMappingDatasourceChange(defaultDatasourceId)
    } catch (e) {
      message.error(e.message)
    }
  }
  mappingModalOpen.value = true
}

async function openExampleCreate() {
  exampleModalMode.value = 'create'
  exampleForm.value = {
    example_id: '',
    datasource_id: datasourceBindings.value[0]?.datasource_id || '',
    intent_tag: '',
    nl_question: '',
    sql_template: '',
    variables_text: '{}',
    explanation: '',
    quality_score: 0.5,
    enabled: true,
  }
  exampleModalOpen.value = true
}

async function openTermCreate() {
  termModalMode.value = 'create'
  termForm.value = {
    id: null,
    source_term: '',
    normalized_term: '',
    mapping_type: 'synonym',
    priority: 100,
    enabled: true,
  }
  termModalOpen.value = true
}

function parseCsv(text) {
  return (text || '').split(',').map(s => s.trim()).filter(Boolean)
}

function stringifyCsv(list) {
  return (list || []).join(',')
}

const datasourceOptions = computed(() =>
  (datasourceBindings.value || [])
    .filter((x) => x.datasource_id)
    .map((x) => ({
      value: x.datasource_id,
      label: x.datasource_name ? `${x.datasource_name} (${x.datasource_id})` : x.datasource_id,
    }))
)

const mappingFilterOptions = computed(() => datasourceOptions.value)

const mappingTableOptions = computed(() =>
  (mappingModalTables.value || []).map((t) => ({
    value: t.table_name,
    label: t.table_name,
  }))
)

const mappingColumnOptions = computed(() =>
  (mappingModalColumns.value || []).map((c) => ({
    value: c.column_name,
    label: c.column_name,
  }))
)

const modelServiceOptions = computed(() =>
  (modelServices.value || [])
    .filter((x) => x.status === 'ACTIVE')
    .map((x) => ({
      value: x.model_service_id,
      label: `${x.display_name} (${x.model_name})`,
    }))
)

function formatTableDescription(record) {
  const parts = []
  if (record.db_comment) parts.push(record.db_comment)
  if (record.description) parts.push(record.description)
  return parts.join(' | ') || '-'
}

function openTableAnnotate(record) {
  tableAnnotateForm.value = {
    table_name: record.table_name,
    business_name: record.business_name || '',
    synonyms_text: stringifyCsv(record.synonyms),
    description: record.description || '',
  }
  tableAnnotateModalOpen.value = true
}

async function submitTableAnnotate() {
  try {
    await dataQueryApi.upsertTableDictionary(currentAgentId.value, {
      datasource_id: selectedDictionaryDatasourceId.value,
      table_name: tableAnnotateForm.value.table_name,
      business_name: tableAnnotateForm.value.business_name,
      description: tableAnnotateForm.value.description,
      synonyms: parseCsv(tableAnnotateForm.value.synonyms_text),
    })
    message.success('表标注已保存')
    tableAnnotateModalOpen.value = false
    await loadSchemaTables()
  } catch (e) {
    message.error(e.message)
  }
}

async function openTableDetail(record) {
  currentDetailTableName.value = record.table_name
  try {
    const list = await dataQueryApi.listSchemaColumns(currentAgentId.value, record.table_name, {
      datasource_id: selectedDictionaryDatasourceId.value,
    })
    columnDetailRows.value = (list || []).map((x) => ({ ...x }))
    columnDetailModalOpen.value = true
  } catch (e) {
    message.error(e.message)
  }
}

async function submitColumnDetails() {
  try {
    await dataQueryApi.batchUpsertDictionary(currentAgentId.value, {
      datasource_id: selectedDictionaryDatasourceId.value,
      table_name: currentDetailTableName.value,
      columns: columnDetailRows.value.map(({ column_name, description }) => ({
        column_name,
        description: description || '',
      })),
    })
    message.success('字段补充描述已保存')
    columnDetailModalOpen.value = false
  } catch (e) {
    message.error(e.message)
  }
}

function openMappingEdit(item) {
  mappingModalMode.value = 'edit'
  mappingForm.value = {
    id: item.id,
    datasource_id: item.datasource_id,
    table_name: item.table_name || '',
    column_name: item.column_name,
    code_value: item.code_value,
    display_name: item.display_name || '',
    aliases_text: stringifyCsv(item.aliases),
  }
  mappingModalTables.value = item.table_name ? [{ table_name: item.table_name }] : []
  mappingModalColumns.value = item.column_name ? [{ column_name: item.column_name }] : []
  mappingModalOpen.value = true
}

async function submitMapping() {
  try {
    if (mappingModalMode.value === 'create') {
      if (!mappingForm.value.datasource_id || !mappingForm.value.table_name || !mappingForm.value.column_name) {
        message.warning('请选择数据源、表名和列名')
        return
      }
      if (!mappingForm.value.code_value || !mappingForm.value.display_name) {
        message.warning('请填写代码和显示名')
        return
      }
    }
    const payload = {
      datasource_id: mappingForm.value.datasource_id,
      table_name: mappingForm.value.table_name,
      column_name: mappingForm.value.column_name,
      code_value: mappingForm.value.code_value,
      display_name: mappingForm.value.display_name,
      aliases: parseCsv(mappingForm.value.aliases_text),
    }
    if (mappingModalMode.value === 'create') {
      await dataQueryApi.createCodeMapping(currentAgentId.value, payload)
      message.success('代码映射已创建')
    } else {
      await dataQueryApi.updateCodeMapping(currentAgentId.value, mappingForm.value.id, {
        display_name: payload.display_name,
        aliases: payload.aliases,
      })
      message.success('代码映射已更新')
    }
    mappingModalOpen.value = false
    await loadMappings()
  } catch (e) {
    message.error(e.message)
  }
}

function deleteMapping(item) {
  Modal.confirm({
    title: '确认删除该代码映射？',
    content: `${item.column_name}=${item.code_value}`,
    okType: 'danger',
    onOk: async () => {
      await dataQueryApi.deleteCodeMapping(currentAgentId.value, item.id)
      message.success('代码映射已删除')
      await loadMappings()
    },
  })
}

function openExampleEdit(item) {
  exampleModalMode.value = 'edit'
  exampleForm.value = {
    example_id: item.example_id,
    datasource_id: item.datasource_id,
    intent_tag: item.intent_tag || '',
    nl_question: item.nl_question || '',
    sql_template: item.sql_template || '',
    variables_text: JSON.stringify(item.variables || {}, null, 2),
    explanation: item.explanation || '',
    quality_score: item.quality_score ?? 0.5,
    enabled: item.enabled !== false,
  }
  exampleModalOpen.value = true
}

async function submitExample() {
  try {
    let variables = {}
    try {
      variables = JSON.parse(exampleForm.value.variables_text || '{}')
    } catch {
      message.error('变量必须是合法 JSON')
      return
    }
    const payload = {
      datasource_id: exampleForm.value.datasource_id,
      intent_tag: exampleForm.value.intent_tag,
      nl_question: exampleForm.value.nl_question,
      sql_template: exampleForm.value.sql_template,
      variables,
      explanation: exampleForm.value.explanation,
      quality_score: exampleForm.value.quality_score,
      enabled: exampleForm.value.enabled,
    }
    if (exampleModalMode.value === 'create') {
      await dataQueryApi.createExample(currentAgentId.value, payload)
      message.success('样例已创建')
    } else {
      await dataQueryApi.updateExample(currentAgentId.value, exampleForm.value.example_id, {
        intent_tag: payload.intent_tag,
        nl_question: payload.nl_question,
        sql_template: payload.sql_template,
        variables: payload.variables,
        explanation: payload.explanation,
        quality_score: payload.quality_score,
        enabled: payload.enabled,
      })
      message.success('样例已更新')
    }
    exampleModalOpen.value = false
    await loadExamples()
  } catch (e) {
    message.error(e.message)
  }
}

function deleteExample(item) {
  Modal.confirm({
    title: '确认删除该样例？',
    content: item.nl_question,
    okType: 'danger',
    onOk: async () => {
      await dataQueryApi.deleteExample(currentAgentId.value, item.example_id)
      message.success('样例已删除')
      await loadExamples()
    },
  })
}

function openTermEdit(item) {
  termModalMode.value = 'edit'
  termForm.value = {
    id: item.id,
    source_term: item.source_term,
    normalized_term: item.normalized_term,
    mapping_type: item.mapping_type || 'synonym',
    priority: item.priority ?? 100,
    enabled: item.enabled !== false,
  }
  termModalOpen.value = true
}

async function submitTerm() {
  try {
    const payload = {
      source_term: termForm.value.source_term,
      normalized_term: termForm.value.normalized_term,
      mapping_type: termForm.value.mapping_type,
      priority: termForm.value.priority,
      enabled: termForm.value.enabled,
    }
    if (termModalMode.value === 'create') {
      await dataQueryApi.createTerm(currentAgentId.value, payload)
      message.success('术语已创建')
    } else {
      await dataQueryApi.updateTerm(currentAgentId.value, termForm.value.id, {
        normalized_term: payload.normalized_term,
        mapping_type: payload.mapping_type,
        priority: payload.priority,
        enabled: payload.enabled,
      })
      message.success('术语已更新')
    }
    termModalOpen.value = false
    await loadTerms()
  } catch (e) {
    message.error(e.message)
  }
}

function deleteTerm(item) {
  Modal.confirm({
    title: '确认删除该术语映射？',
    content: `${item.source_term} → ${item.normalized_term}`,
    okType: 'danger',
    onOk: async () => {
      await dataQueryApi.deleteTerm(currentAgentId.value, item.id)
      message.success('术语已删除')
      await loadTerms()
    },
  })
}

async function generateNl2sqlTool() {
  if (!currentAgentId.value) {
    message.warning('请先选择 DataQueryAgent')
    return
  }
  generatingTool.value = true
  try {
    const existing = await toolApi.list({ page_size: 100 })
    const found = (existing.items || []).find((t) => t.name === 'nl2sql_query')
    const toolPayload = {
      display_name: 'NL2SQL 查询工具',
      description: '将自然语言问题交给 DataQueryAgent 执行 NL2SQL 查询',
      config: {
        adapter: 'dataquery_agent',
        dq_agent_id: currentAgentId.value,
      },
      parameters_schema: {
        type: 'object',
        properties: {
          question: { type: 'string', description: '自然语言查询问题' },
          datasource_id: { type: 'string', description: '可选，指定数据源ID' },
          top_k: { type: 'integer', description: '可选，返回行数上限', default: 200 },
          strict_mode: { type: 'boolean', description: '可选，是否严格模式', default: true },
          return_sql_only: { type: 'boolean', description: '可选，仅返回 SQL', default: false },
          session_id: { type: 'string', description: '可选，会话ID' },
        },
        required: ['question'],
      },
    }
    if (found) {
      await toolApi.update(found.tool_id, toolPayload)
      message.success('已更新 nl2sql_query 工具并绑定当前 DataQueryAgent')
    } else {
      await toolApi.create({
        name: 'nl2sql_query',
        tool_type: 'restful',
        ...toolPayload,
      })
      message.success('已创建 nl2sql_query 工具并绑定当前 DataQueryAgent')
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    generatingTool.value = false
  }
}

onMounted(async () => {
  try {
    await loadModelServices()
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

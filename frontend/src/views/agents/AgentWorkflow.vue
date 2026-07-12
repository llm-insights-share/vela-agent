<template>
  <div class="workflow-page">
    <div class="page-header">
      <h2 class="page-title">工作流编排</h2>
      <a-space>
        <a-button @click="goBack">返回</a-button>
        <a-button @click="handleValidate">校验</a-button>
        <a-button type="primary" :loading="saving" @click="handleSave">保存</a-button>
      </a-space>
    </div>

    <a-spin :spinning="loading">
      <div class="workflow-layout">
        <!-- 节点面板 -->
        <div class="node-palette">
          <div class="palette-title">节点类型</div>
          <div
            v-for="item in nodePalette"
            :key="item.type"
            class="palette-item"
            :style="{ borderColor: item.color }"
            draggable="true"
            @dragstart="onDragStart($event, item.type)"
          >
            <span class="palette-dot" :style="{ background: item.color }"></span>
            {{ item.label }}
          </div>
        </div>

        <!-- 画布 -->
        <div class="canvas-area" @drop="onDrop" @dragover.prevent>
          <VueFlow
            v-model:nodes="nodes"
            v-model:edges="edges"
            :default-viewport="{ zoom: 1 }"
            :min-zoom="0.3"
            :max-zoom="2"
            fit-view-on-init
            @node-click="onNodeClick"
            @connect="onConnect"
          >
            <Background pattern-color="#e8e4dc" :gap="16" />
            <Controls />

            <template #node-start="nodeProps">
              <div class="wf-node wf-node-start" @click="onNodeClick({ node: nodeProps })">
                <Handle type="source" :position="Position.Bottom" />
                <div class="wf-node-label">
                  <span>开始</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
              </div>
            </template>
            <template #node-end="nodeProps">
              <div class="wf-node wf-node-end" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>结束</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
              </div>
            </template>
            <template #node-llm="nodeProps">
              <div class="wf-node wf-node-llm" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || 'LLM' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle type="source" :position="Position.Bottom" />
              </div>
            </template>
            <template #node-tool="nodeProps">
              <div class="wf-node wf-node-tool" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || '工具' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle type="source" :position="Position.Bottom" />
              </div>
            </template>
            <template #node-condition="nodeProps">
              <div class="wf-node wf-node-condition" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || '条件' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle id="true" type="source" :position="Position.Bottom" style="left: 30%" />
                <Handle id="false" type="source" :position="Position.Bottom" style="left: 70%" />
                <div class="handle-labels"><span>T</span><span>F</span></div>
              </div>
            </template>
            <template #node-hitl="nodeProps">
              <div class="wf-node wf-node-hitl" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || 'HITL' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle type="source" :position="Position.Bottom" />
              </div>
            </template>
            <template #node-cron="nodeProps">
              <div class="wf-node wf-node-cron" @click="onNodeClick({ node: nodeProps })">
                <Handle type="source" :position="Position.Bottom" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || 'Cron' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
              </div>
            </template>
            <template #node-subgraph="nodeProps">
              <div class="wf-node wf-node-subgraph" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || '子图' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle type="source" :position="Position.Bottom" />
              </div>
            </template>
            <template #node-screenpilot="nodeProps">
              <div class="wf-node wf-node-screenpilot" @click="onNodeClick({ node: nodeProps })">
                <Handle type="target" :position="Position.Top" />
                <div class="wf-node-label">
                  <span>{{ nodeProps.data.label || '驭屏' }}</span>
                  <span class="wf-node-id">{{ nodeProps.id }}</span>
                </div>
                <Handle type="source" :position="Position.Bottom" />
              </div>
            </template>
          </VueFlow>
        </div>
      </div>
    </a-spin>

    <!-- 节点属性抽屉 -->
    <a-drawer
      v-model:open="drawerVisible"
      width="480"
      @close="selectedNode = null"
    >
      <template #title>
        <span class="drawer-title-wrap">
          <span>节点配置: {{ selectedNode?.data?.label || selectedNode?.id || '' }}</span>
          <span class="drawer-title-id">{{ selectedNode?.id || '' }}</span>
        </span>
      </template>
      <a-form v-if="selectedNode" layout="vertical">
        <a-form-item label="节点名称">
          <a-input v-model:value="selectedNode.data.label" />
          <div class="current-vars">
            <span class="current-vars-label">当前可用变量：</span>
            <a-tag v-for="v in availableNodeVariables" :key="v" class="var-tag">{{ v }}</a-tag>
          </div>
          <span class="form-hint">仅展示当前节点可引用变量（不包含后续节点变量）</span>
        </a-form-item>

        <template v-if="selectedNode.type === 'llm'">
          <a-form-item label="Prompt">
            <a-textarea v-model:value="selectedNode.data.prompt" :rows="4" placeholder="支持 {{input}} {{node_id.output}}" />
          </a-form-item>
          <a-form-item label="模型服务">
            <a-select v-model:value="selectedNode.data.model_service_id" placeholder="选择模型" allowClear>
              <a-select-option v-for="s in modelServices" :key="s.model_service_id" :value="s.model_service_id">
                {{ s.display_name || s.model_name }}
              </a-select-option>
            </a-select>
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'tool'">
          <a-form-item label="工具">
            <a-select v-model:value="selectedNode.data.tool_id" placeholder="选择工具">
              <a-select-option v-for="t in toolList" :key="t.tool_id" :value="t.tool_id">
                {{ t.display_name || t.name }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="参数 (JSON)">
            <a-textarea v-model:value="selectedNode.data.parameters" :rows="3" placeholder='{"key": "value"}' />
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'condition'">
          <a-form-item label="条件表达式">
            <a-input v-model:value="selectedNode.data.expression" placeholder='{{llm_1.output}} contains "风险"' />
            <span class="form-hint">支持 contains / equals / regex</span>
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'hitl'">
          <a-form-item label="审批预览模板">
            <a-textarea v-model:value="selectedNode.data.preview_template" :rows="3" />
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'cron'">
          <a-form-item label="Cron 表达式">
            <a-input v-model:value="selectedNode.data.cron_expression" placeholder="0 9 * * *" />
            <span class="form-hint">标准 5 段 cron，必须能到达 HITL 节点</span>
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'subgraph'">
          <a-form-item label="嵌入单体 Agent">
            <a-select v-model:value="selectedNode.data.child_agent_id" placeholder="选择 Agent">
              <a-select-option v-for="c in candidates" :key="c.agent_id" :value="c.agent_id">
                {{ c.name }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="输入模板">
            <a-textarea v-model:value="selectedNode.data.input_template" :rows="2" placeholder="{{input}}" />
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'screenpilot'">
          <a-form-item label="操作类型">
            <a-select v-model:value="selectedNode.data.operation">
              <a-select-option value="navigate">navigate 导航</a-select-option>
              <a-select-option value="observe">observe 观测</a-select-option>
              <a-select-option value="replay">replay 重放技能</a-select-option>
              <a-select-option value="run_task">run_task 高级任务</a-select-option>
              <a-select-option value="extract">extract 提取文本</a-select-option>
              <a-select-option value="act">act 原子动作</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="目标系统">
            <a-select v-model:value="selectedNode.data.system_id" placeholder="选择驭屏系统" allowClear>
              <a-select-option v-for="s in screenSystems" :key="s.system_id" :value="s.system_id">
                {{ s.name }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="selectedNode.data.operation === 'navigate'" label="URL">
            <a-input v-model:value="selectedNode.data.url" placeholder="留空使用系统入口" />
          </a-form-item>
          <a-form-item v-if="selectedNode.data.operation === 'replay'" label="技能">
            <a-select v-model:value="selectedNode.data.skill_id" placeholder="选择 UI 技能" allowClear>
              <a-select-option v-for="sk in uiSkills" :key="sk.skill_id" :value="sk.skill_id">
                {{ sk.name }}
              </a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="浏览器会话 ID">
            <a-input v-model:value="selectedNode.data.screen_session_id" placeholder="{{__screen_session_id__}} 或留空自动创建" />
          </a-form-item>
          <a-form-item v-if="selectedNode.data.operation === 'act'" label="动作">
            <a-select v-model:value="selectedNode.data.action">
              <a-select-option value="click">click</a-select-option>
              <a-select-option value="type">type</a-select-option>
              <a-select-option value="select">select</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="selectedNode.data.operation === 'act'" label="SoM 编号">
            <a-input v-model:value="selectedNode.data.target_ref" placeholder="[7]" />
          </a-form-item>
          <a-form-item v-if="selectedNode.data.operation === 'act'" label="值">
            <a-input v-model:value="selectedNode.data.value" />
          </a-form-item>
          <a-form-item label="参数 (JSON)">
            <a-textarea v-model:value="selectedNode.data.parameters" :rows="2" placeholder='run_task: {"goal": "{{input}}"}' />
          </a-form-item>
        </template>

        <template v-if="selectedNode.type === 'end'">
          <a-form-item label="输出模板">
            <a-textarea v-model:value="selectedNode.data.output_template" :rows="2" placeholder="留空则使用上一节点输出" />
          </a-form-item>
        </template>

        <template v-if="!['start', 'end', 'cron'].includes(selectedNode.type)">
          <a-divider>执行策略</a-divider>
          <a-form-item label="超时(秒)">
            <a-input-number v-model:value="selectedNode.data.timeout_seconds" :min="5" :max="600" style="width: 100%" />
          </a-form-item>
          <a-form-item label="重试次数">
            <a-input-number v-model:value="selectedNode.data.retry_count" :min="0" :max="10" style="width: 100%" />
          </a-form-item>
          <a-form-item label="重试间隔(秒)">
            <a-input-number v-model:value="selectedNode.data.retry_interval_seconds" :min="1" :max="60" style="width: 100%" />
          </a-form-item>
          <a-form-item label="失败后">
            <a-select v-model:value="selectedNode.data.on_failure">
              <a-select-option value="retry">重试后终止</a-select-option>
              <a-select-option value="skip">跳过继续</a-select-option>
              <a-select-option value="abort">终止流程</a-select-option>
            </a-select>
          </a-form-item>
        </template>

        <a-form-item>
          <a-button danger @click="deleteSelectedNode">删除节点</a-button>
        </a-form-item>
      </a-form>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { VueFlow, Handle, Position } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import { workflowApi, serviceApi, toolApi, screenpilotApi } from '../../api'

const route = useRoute()
const router = useRouter()
const agentId = route.params.agent_id

const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const selectedNode = ref(null)
const modelServices = ref([])
const toolList = ref([])
const candidates = ref([])
const screenSystems = ref([])
const uiSkills = ref([])

const nodes = ref([])
const edges = ref([])

const availableNodeVariables = computed(() => {
  const vars = ['{{input}}', '{{history}}']
  const currentNodeId = selectedNode.value?.id
  if (!currentNodeId) return vars

  const outputTypes = new Set(['llm', 'tool', 'condition', 'subgraph', 'screenpilot'])
  const incomingMap = new Map()
  for (const e of edges.value) {
    if (!e?.target || !e?.source) continue
    if (!incomingMap.has(e.target)) incomingMap.set(e.target, [])
    incomingMap.get(e.target).push(e.source)
  }

  const visited = new Set()
  const queue = [...(incomingMap.get(currentNodeId) || [])]
  while (queue.length > 0) {
    const nodeId = queue.shift()
    if (!nodeId || visited.has(nodeId)) continue
    visited.add(nodeId)
    for (const prev of incomingMap.get(nodeId) || []) {
      if (!visited.has(prev)) queue.push(prev)
    }
  }

  for (const n of nodes.value) {
    if (!n?.id || n.id === currentNodeId) continue
    if (!visited.has(n.id)) continue
    if (!outputTypes.has(n.type)) continue
    vars.push(`{{${n.id}.output}}`)
  }
  return vars
})

const nodePalette = [
  { type: 'start', label: '开始', color: '#52c41a' },
  { type: 'llm', label: 'LLM', color: '#1890ff' },
  { type: 'tool', label: '工具', color: '#722ed1' },
  { type: 'condition', label: '条件分支', color: '#fa8c16' },
  { type: 'hitl', label: 'HITL 审批', color: '#eb2f96' },
  { type: 'cron', label: 'Cron 触发', color: '#13c2c2' },
  { type: 'subgraph', label: '子图 Agent', color: '#2f54eb' },
  { type: 'screenpilot', label: '驭屏任务', color: '#08979c' },
  { type: 'end', label: '结束', color: '#f5222d' },
]

let nodeIdCounter = 1

function defaultNodeData(type) {
  const base = {
    label: nodePalette.find(p => p.type === type)?.label || type,
    timeout_seconds: 60,
    retry_count: 0,
    retry_interval_seconds: 5,
    on_failure: 'abort',
  }
  if (type === 'llm') {
    return { ...base, prompt: '{{input}}', model_service_id: null }
  }
  if (type === 'tool') {
    return { ...base, tool_id: null, parameters: '{}' }
  }
  if (type === 'condition') {
    return { ...base, expression: '{{input}} contains "test"' }
  }
  if (type === 'hitl') {
    return { ...base, preview_template: '请审批工作流执行结果：\n{{input}}' }
  }
  if (type === 'cron') {
    return { label: 'Cron', cron_expression: '0 9 * * *' }
  }
  if (type === 'subgraph') {
    return { ...base, child_agent_id: null, input_template: '{{input}}' }
  }
  if (type === 'screenpilot') {
    return {
      ...base,
      operation: 'navigate',
      system_id: null,
      skill_id: null,
      screen_session_id: '',
      url: '',
      action: 'click',
      target_ref: '',
      value: '',
      parameters: '{}',
    }
  }
  if (type === 'end') {
    return { label: '结束', output_template: '' }
  }
  return base
}

function onDragStart(event, type) {
  event.dataTransfer.setData('application/vueflow', type)
  event.dataTransfer.effectAllowed = 'move'
}

function onDrop(event) {
  const type = event.dataTransfer.getData('application/vueflow')
  if (!type) return

  const bounds = event.currentTarget.getBoundingClientRect()
  const x = event.clientX - bounds.left - 60
  const y = event.clientY - bounds.top - 20

  const id = `${type}_${nodeIdCounter++}`
  nodes.value.push({
    id,
    type,
    position: { x, y },
    data: defaultNodeData(type),
  })
}

function onConnect(params) {
  edges.value.push({
    id: `e_${params.source}_${params.target}_${Date.now()}`,
    source: params.source,
    target: params.target,
    sourceHandle: params.sourceHandle || 'default',
  })
}

function onNodeClick({ node }) {
  selectedNode.value = node
  drawerVisible.value = true
}

function deleteSelectedNode() {
  if (!selectedNode.value) return
  const id = selectedNode.value.id
  nodes.value = nodes.value.filter(n => n.id !== id)
  edges.value = edges.value.filter(e => e.source !== id && e.target !== id)
  drawerVisible.value = false
  selectedNode.value = null
}

function buildDefinition() {
  return {
    version: 1,
    nodes: nodes.value.map(n => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: { ...n.data },
    })),
    edges: edges.value.map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || 'default',
    })),
  }
}

async function handleSave() {
  saving.value = true
  try {
    await workflowApi.update(agentId, buildDefinition())
    message.success('工作流已保存')
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function handleValidate() {
  try {
    await workflowApi.update(agentId, buildDefinition())
    const res = await workflowApi.validate(agentId)
    if (res.passed) {
      message.success('校验通过' + (res.warnings?.length ? `（${res.warnings.length} 条警告）` : ''))
    } else {
      const errs = (res.errors || []).map(e => e.message).join('\n')
      message.error('校验失败:\n' + errs)
    }
  } catch (e) {
    message.error(e.message)
  }
}

function goBack() {
  router.push('/agents')
}

onMounted(async () => {
  loading.value = true
  try {
    const [wf, svc, tools, cands] = await Promise.all([
      workflowApi.get(agentId),
      serviceApi.list({ page_size: 100 }),
      toolApi.list({ page_size: 100 }),
      workflowApi.candidates(agentId),
    ])
    modelServices.value = svc.items || []
    toolList.value = tools.items || []
    candidates.value = cands.candidates || []

    try {
      const spStatus = await screenpilotApi.status()
      if (spStatus.enabled) {
        const [systems, skills] = await Promise.all([
          screenpilotApi.listSystems(),
          screenpilotApi.listSkills(),
        ])
        screenSystems.value = systems || []
        uiSkills.value = skills || []
      }
    } catch (_) {
      /* ScreenPilot 未启用时忽略 */
    }

    const def = wf.workflow_definition || {}
    if (def.nodes?.length) {
      nodes.value = def.nodes.map(n => ({
        id: n.id,
        type: n.type,
        position: n.position || { x: 0, y: 0 },
        data: n.data || defaultNodeData(n.type),
      }))
      edges.value = (def.edges || []).map(e => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || 'default',
      }))
      const maxId = Math.max(...nodes.value.map(n => {
        const m = n.id.match(/_(\d+)$/)
        return m ? parseInt(m[1]) : 0
      }), 0)
      nodeIdCounter = maxId + 1
    } else {
      nodes.value = [{
        id: 'start_1',
        type: 'start',
        position: { x: 250, y: 50 },
        data: { label: '开始' },
      }]
      nodeIdCounter = 2
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.workflow-page { padding: 0; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 700;
  color: #1a1714;
  margin: 0;
}
.workflow-layout {
  display: flex;
  height: calc(100vh - 180px);
  border: 1px solid #ddd8ce;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.node-palette {
  width: 160px;
  padding: 12px;
  border-right: 1px solid #ddd8ce;
  background: #faf8f5;
  overflow-y: auto;
}
.palette-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
  margin-bottom: 12px;
}
.palette-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid #ddd;
  border-radius: 6px;
  cursor: grab;
  font-size: 13px;
  background: #fff;
}
.palette-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.canvas-area {
  flex: 1;
  position: relative;
}
.wf-node {
  padding: 10px 16px;
  border-radius: 8px;
  border: 2px solid;
  background: #fff;
  min-width: 100px;
  text-align: center;
  font-size: 12px;
  cursor: pointer;
}
.wf-node-start { border-color: #52c41a; background: #f6ffed; }
.wf-node-end { border-color: #f5222d; background: #fff1f0; }
.wf-node-llm { border-color: #1890ff; background: #e6f7ff; }
.wf-node-tool { border-color: #722ed1; background: #f9f0ff; }
.wf-node-condition { border-color: #fa8c16; background: #fff7e6; min-width: 120px; }
.wf-node-hitl { border-color: #eb2f96; background: #fff0f6; }
.wf-node-cron { border-color: #13c2c2; background: #e6fffb; }
.wf-node-subgraph { border-color: #2f54eb; background: #f0f5ff; }
.wf-node-screenpilot { border-color: #08979c; background: #e6fffb; }
.wf-node-label {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  font-weight: 600;
}
.wf-node-id {
  font-size: 10px;
  color: #888;
  font-weight: 400;
}
.handle-labels {
  display: flex;
  justify-content: space-around;
  font-size: 10px;
  color: #999;
  margin-top: 4px;
}
.form-hint { font-size: 12px; color: #999; }
.current-vars {
  margin-bottom: 8px;
}
.current-vars-label {
  font-size: 12px;
  color: #666;
  margin-right: 6px;
}
.var-tag {
  margin-bottom: 4px;
}
.drawer-title-wrap {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
}
.drawer-title-id {
  font-size: 11px;
  color: #999;
  font-weight: 400;
}
</style>

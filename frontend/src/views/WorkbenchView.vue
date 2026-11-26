<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button v-if="canCreate" class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <template v-for="action in meta.actions" :key="action">
              <button
                v-if="isActionAvailable(meta.key, row, action)"
                class="link"
                type="button"
                :data-testid="`action-${row.id}-${action}`"
                :disabled="busyKey === busyIdOf(row, action)"
                @click="runAction(action, row)"
              >
                {{ busyKey === busyIdOf(row, action) ? '提交中…' : action }}
              </button>
            </template>
            <span v-if="!meta.actions.some((a) => isActionAvailable(meta.key, row, a))" class="muted-text">
              无可执行动作
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <HandoffPanel v-if="showHandoffPanel" ref="handoffPanel" />
    <ArchiveBatchPanel v-if="meta.key === 'exp_archive'" ref="archivePanel" />

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in createFieldList" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="successMessage" class="ok-text" data-testid="success-message">{{ successMessage }}</span>
      <span v-if="errorMessage" class="error-text" data-testid="error-message">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import ArchiveBatchPanel from '@/components/ArchiveBatchPanel.vue'
import HandoffPanel from '@/components/HandoffPanel.vue'
import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import { isActionAvailable, newFinishRequestId } from '@/domain/exp_design'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const busyKey = ref('')
const handoffPanel = ref<InstanceType<typeof HandoffPanel> | null>(null)
const archivePanel = ref<InstanceType<typeof ArchiveBatchPanel> | null>(null)

const showHandoffPanel = computed(
  () => props.moduleKey === 'exp_design' || props.moduleKey === 'exp_archive',
)
// 结束交接单是系统自动登记的只读凭证；结论修订须在归档批次面板登记，均不开放通用登记。
const canCreate = computed(
  () => props.moduleKey !== 'finish_handoff' && props.moduleKey !== 'conclusion_revision',
)
// 登记表单只收集业务可填字段，轮次号/归档号等系统字段不出现。
const createFieldList = computed(() => meta.createFields ?? meta.fields)

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function busyIdOf(row: EntryRow, action: string): string {
  return `${row.id}-${action}`
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(createFieldList.value.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  successMessage.value = ''
  const key = busyIdOf(row, action)
  busyKey.value = key
  // 结束实验附带客户端请求标识；服务端按轮次幂等，重发不会重复交接。
  const extra =
    meta.key === 'exp_design' && action === '结束实验'
      ? { requestId: newFinishRequestId(String(row.实验编码), Number(row.轮次号) || 1) }
      : {}
  try {
    const result = await applyAction(meta.key, Number(row.id), action, extra)
    if (!result.ok) throw new Error(result.message)
    const archiveNo = result.entry?.归档号
    successMessage.value =
      action === '结束实验' && archiveNo
        ? `${result.message}（归档号：${archiveNo}，可在下方交接面板核查）`
        : result.message
    await reload()
    if (showHandoffPanel.value) void handoffPanel.value?.load()
  } catch (error) {
    // 按钮等候中断（超时/网络异常）：引导用户核查已受理的结束申请及归档号。
    const base = error instanceof Error ? error.message : '操作失败'
    errorMessage.value =
      action === '结束实验'
        ? `${base}。结束申请可能已受理，请在下方「结束申请核查」按实验编码或归档号确认，勿重复提交。`
        : base
  } finally {
    busyKey.value = ''
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(() => {
  void reload()
  if (showHandoffPanel.value) void handoffPanel.value?.load()
})
</script>

<style scoped>
.muted-text {
  color: var(--muted);
  font-size: 12px;
}
.ok-text {
  color: #15803d;
}
.link:disabled {
  color: var(--muted);
  cursor: wait;
}
</style>

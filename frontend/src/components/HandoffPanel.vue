<template>
  <section class="handoff-panel" data-testid="handoff-panel">
    <header class="panel-head">
      <h3>结束申请核查（结束记录 ↔ 归档号）</h3>
      <p class="page-desc">
        按钮等候中断或响应超时时，在此核查已受理的结束申请及归档号；同一轮次重发只交接一份。
      </p>
    </header>
    <form class="filter-bar" @submit.prevent="load">
      <label class="filter-item">
        <span>实验编码</span>
        <input v-model="expCode" data-testid="handoff-filter-code" placeholder="按实验编码回查" />
      </label>
      <label class="filter-item">
        <span>归档号</span>
        <input v-model="archiveNo" data-testid="handoff-filter-archive" placeholder="按归档号回查" />
      </label>
      <button class="btn primary" data-testid="handoff-query" type="submit">核查交接</button>
      <button class="btn ghost" type="button" @click="reset">重置</button>
    </form>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <table v-if="rows.length" class="data-table">
      <thead>
        <tr>
          <th>结束申请号</th>
          <th>实验编码</th>
          <th>轮次号</th>
          <th>归档号</th>
          <th>受理状态</th>
          <th>申请时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id" :data-testid="`handoff-row-${row.id}`">
          <td>{{ row.结束申请号 }}</td>
          <td>{{ row.实验编码 }}</td>
          <td>第{{ row.轮次号 }}轮</td>
          <td>{{ row.归档号 }}</td>
          <td>{{ row.受理状态 }}</td>
          <td>{{ row.申请时间 }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">暂无交接记录，可输入实验编码或归档号核查</p>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { listHandoffs } from '@/api/backend-service'
import type { HandoffRow } from '@/data/types'

const props = defineProps<{ initialCode?: string; initialArchiveNo?: string }>()

const expCode = ref(props.initialCode ?? '')
const archiveNo = ref(props.initialArchiveNo ?? '')
const rows = ref<HandoffRow[]>([])
const errorMessage = ref('')

async function load() {
  errorMessage.value = ''
  try {
    const payload = await listHandoffs({
      expCode: expCode.value.trim() || undefined,
      archiveNo: archiveNo.value.trim() || undefined,
    })
    rows.value = payload.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交接记录读取失败'
  }
}

function reset() {
  expCode.value = ''
  archiveNo.value = ''
  rows.value = []
  errorMessage.value = ''
}

defineExpose({ load })
</script>

<style scoped>
.handoff-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  margin: 16px 0;
}
.panel-head h3 {
  margin: 0 0 4px;
  font-size: 15px;
}
</style>

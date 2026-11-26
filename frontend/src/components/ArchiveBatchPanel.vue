<template>
  <section class="archive-panel" data-testid="archive-batch-panel">
    <header class="panel-head">
      <h3>归档批次领取与恢复核查</h3>
      <p class="page-desc">
        输入归档号打开完整归档批次：结束时实验编码、原结论、历史明细与晚到修订确认记录。
      </p>
    </header>

    <form class="filter-bar" @submit.prevent="load">
      <label class="filter-item">
        <span>归档号</span>
        <input v-model="archiveNo" data-testid="batch-archive-input" placeholder="如 AR-EXP_-0003-R1" />
      </label>
      <button class="btn primary" data-testid="batch-open" type="submit">打开归档批次</button>
    </form>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <article v-if="batch" class="batch-card">
      <dl class="batch-meta">
        <dt>归档号</dt>
        <dd>{{ batch.归档记录.归档号 }}</dd>
        <dt>实验编码 / 轮次</dt>
        <dd>{{ batch.归档记录.实验编码 }} · 第{{ batch.归档记录.轮次号 }}轮</dd>
        <dt>结束时间</dt>
        <dd>{{ batch.归档记录.结束时间 }}</dd>
        <dt>当前结论状态</dt>
        <dd data-testid="batch-status">{{ batch.归档记录.status }}</dd>
        <dt>结束时原结论</dt>
        <dd data-testid="batch-original-summary">{{ batch.归档记录.原结论摘要 }}</dd>
        <dt>当前展示摘要</dt>
        <dd>{{ batch.归档记录.结论摘要 }}</dd>
        <dt>交接单</dt>
        <dd>{{ batch.交接单 ? `${batch.交接单.结束申请号}（${batch.交接单.受理状态}）` : '无' }}</dd>
        <dt>历史明细条数</dt>
        <dd>{{ batch.批次明细条数 }}</dd>
      </dl>

      <h4>历史明细（恢复时用于重建切片）</h4>
      <table class="data-table">
        <thead>
          <tr><th>来源模块</th><th>明细类型</th><th>内容</th><th>记录时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="(d, i) in details" :key="i">
            <td>{{ d.来源模块 }}</td>
            <td>{{ d.明细类型 }}</td>
            <td>{{ d.内容 }}</td>
            <td>{{ d.记录时间 }}</td>
          </tr>
        </tbody>
      </table>

      <h4>结论修订确认记录</h4>
      <table v-if="batch.修订记录.length" class="data-table">
        <thead>
          <tr><th>修订编号</th><th>修订内容</th><th>状态</th><th>确认批次</th><th>确认人</th><th>确认时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in batch.修订记录" :key="r.id" :data-testid="`revision-row-${r.id}`">
            <td>{{ r.修订编号 }}</td>
            <td>{{ r.修订内容 }}</td>
            <td>{{ r.status }}</td>
            <td>{{ r.确认批次 || '—' }}</td>
            <td>{{ r.确认人 || '—' }}</td>
            <td>{{ r.确认时间 || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">暂无修订记录</p>

      <form class="revision-form" @submit.prevent="submitRevision">
        <h4>登记晚到结论修订（如 C2，不改原结论）</h4>
        <label class="create-field">
          <span>修订编号</span>
          <input v-model="revisionCode" data-testid="revision-code" placeholder="如 C2" />
        </label>
        <label class="create-field">
          <span>修订内容</span>
          <input v-model="revisionContent" data-testid="revision-content" placeholder="晚到的更正结论" required />
        </label>
        <button class="btn primary" data-testid="revision-submit" type="submit" :disabled="submitting">
          {{ submitting ? '提交中…' : '登记修订' }}
        </button>
        <span v-if="revisionMessage" :class="revisionOk ? 'ok-text' : 'error-text'">{{ revisionMessage }}</span>
      </form>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { getArchiveBatch, registerRevision } from '@/api/backend-service'
import type { ArchiveBatch, BatchDetail } from '@/data/types'

const props = defineProps<{ initialArchiveNo?: string }>()

const archiveNo = ref(props.initialArchiveNo ?? '')
const batch = ref<ArchiveBatch | null>(null)
const errorMessage = ref('')
const revisionCode = ref('')
const revisionContent = ref('')
const revisionMessage = ref('')
const revisionOk = ref(false)
const submitting = ref(false)

const details = computed<BatchDetail[]>(
  () => (batch.value?.归档记录.批次明细 as BatchDetail[] | undefined) ?? [],
)

async function load() {
  errorMessage.value = ''
  batch.value = null
  const no = archiveNo.value.trim()
  if (!no) {
    errorMessage.value = '请输入归档号'
    return
  }
  try {
    batch.value = await getArchiveBatch(no)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '归档批次读取失败'
  }
}

async function submitRevision() {
  if (!batch.value) return
  submitting.value = true
  revisionMessage.value = ''
  try {
    const result = await registerRevision({
      exp_code: String(batch.value.归档记录.实验编码),
      archive_no: String(batch.value.归档记录.归档号),
      content: revisionContent.value,
      revision_code: revisionCode.value.trim() || undefined,
    })
    revisionOk.value = result.ok
    revisionMessage.value = result.message
    if (result.ok) {
      revisionCode.value = ''
      revisionContent.value = ''
      await load()
    }
  } catch (error) {
    revisionOk.value = false
    revisionMessage.value = error instanceof Error ? error.message : '修订登记失败'
  } finally {
    submitting.value = false
  }
}

defineExpose({ load })
</script>

<style scoped>
.archive-panel {
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
.batch-card h4 {
  margin: 14px 0 6px;
  font-size: 13px;
}
.batch-meta {
  display: grid;
  grid-template-columns: 130px 1fr;
  gap: 4px 12px;
  margin: 0;
  font-size: 13px;
}
.batch-meta dt {
  color: var(--muted);
}
.batch-meta dd {
  margin: 0;
}
.revision-form {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.ok-text {
  color: #15803d;
  margin-left: 8px;
}
</style>

/** 实验设计页领域规则：动作可用性与结束申请幂等标识。 */
import { moduleMeta } from '@/data/modules'
import type { EntryRow } from '@/data/types'

/** 仅对本次改造涉及的模块做状态门控；其余模块维持按钮常显的原始行为。 */
export function isActionAvailable(moduleKey: string, row: EntryRow, action: string): boolean {
  const meta = moduleMeta(moduleKey)
  const target = meta.actionTargets[action]
  if (!target) return false

  if (moduleKey === 'exp_design') {
    // 只有运行中的实验轮次能结束；旧归档恢复后的轮次保留自己的结束状态。
    if (action === '结束实验') return row.status === '运行中' && row.轮次状态 === '运行中'
    if (action === '提交审批') return row.status === '设计中'
    if (action === '启动实验') return row.status === '待审批'
  }
  if (moduleKey === 'exp_archive') {
    if (action === '执行归档') return row.status === '待归档'
    if (action === '恢复实验') return row.status === '已归档'
  }
  if (moduleKey === 'conclusion_revision') {
    return row.status === '待确认'
  }
  // 未定制模块保持原始行为：动作按钮始终展示，由后端做业务校验。
  return true
}

/** 结束申请的客户端请求标识：超时重发时复用同一标识，服务端按轮次幂等。 */
export function newFinishRequestId(expCode: string, roundNo: number | string): string {
  const rand =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `EF-${expCode}-R${roundNo}-${rand}`
}

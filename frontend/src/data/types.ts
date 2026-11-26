/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  /** 登记表单实际需要填写的字段；系统生成的轮次/归档号等不在其中。缺省取 fields。 */
  createFields?: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
  entry?: EntryRow | null
}

export type HandoffRow = {
  id: number
  结束申请号: string
  请求标识?: string
  实验编码: string
  实验名称: string
  轮次号: number
  归档号: string
  原结论摘要: string
  受理状态: string
  申请时间: string
  领取时间?: string
}

export type BatchDetail = {
  来源模块: string
  实验编码: string
  轮次号: number
  明细类型: string
  内容: string
  记录时间: string
}

export type ArchiveBatch = {
  归档记录: EntryRow
  交接单: HandoffRow | null
  修订记录: EntryRow[]
  批次明细条数: number
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

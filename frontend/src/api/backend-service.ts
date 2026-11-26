import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  ArchiveBatch,
  EntryRow,
  HandoffRow,
  OverviewResult,
  PageResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
  extra: { requestId?: string; remark?: string } = {},
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      request_id: extra.requestId,
      remark: extra.remark,
    }),
  })
  return await response.json()
}

/** 查询结束记录与归档号对应关系；两个页面共用。 */
export async function listHandoffs(params: {
  expCode?: string
  archiveNo?: string
}): Promise<{ items: HandoffRow[]; total: number }> {
  const query = new URLSearchParams()
  if (params.expCode) query.set('exp_code', params.expCode)
  if (params.archiveNo) query.set('archive_no', params.archiveNo)
  const response = await request(`/api/handoffs?${query.toString()}`)
  if (!response.ok) throw new Error('结束交接记录读取失败')
  return await response.json()
}

/** 归档库按归档号打开完整归档批次（原结论、明细、修订确认记录）。 */
export async function getArchiveBatch(archiveNo: string): Promise<ArchiveBatch> {
  const response = await request(`/api/archive-batches/${encodeURIComponent(archiveNo)}`)
  if (!response.ok) throw new Error('归档批次读取失败')
  return await response.json()
}

/** 登记晚到结论修订（如 C2），不改写原结论，进入待确认队列。 */
export async function registerRevision(payload: {
  exp_code: string
  archive_no: string
  content: string
  revision_code?: string
}): Promise<{ ok: boolean; message: string; 修订编号?: string }> {
  const response = await request(
    `/api/archive-batches/${encodeURIComponent(payload.archive_no)}/revisions`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

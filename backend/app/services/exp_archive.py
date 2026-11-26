"""实验归档库领域服务：管理已结束实验的结论归档、保留等级与恢复流转。

数据链路位置：归档存储层，是实验评估数据沉淀的终点，消费实验设计与报告生成
的结论数据，按保留等级归档，支持恢复供切片分析复用历史明细。

跨页交接约定：
- 归档记录携带与实验设计页一致的「归档号」，归档号按实验轮次生成，全链路唯一。
- 执行归档（领取）前核对结束申请交接单；领取后状态转为「可领取/已归档」结论状态。
- 恢复时按归档批次里的完整历史明细重建切片，且不回改实验设计页那一轮的结束状态。
- 晚到的结论修订（如 C2）单独登记、单独确认，不覆盖结束时的原结论摘要，
  原结论与每次修订的确认记录都可按归档号回查。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


class ExpArchiveService(BaseModuleService):
    MODULE = "exp_archive"
    ENTITY = "归档实验"
    OPERATION_TERM = "归档"
    LIST_FIELDS = [
        "实验编码", "结束时间", "结论摘要", "归档位置", "保留等级",
        "归档号", "结束申请号", "轮次号",
    ]
    REQUIRED_FIELDS = ["实验编码", "结束时间", "结论摘要"]
    STATUS_ORDER = ["待归档", "已归档", "恢复中"]
    ACTION_RULES = {"执行归档": "已归档", "恢复实验": "恢复中"}
    NEGATIVE_ACTIONS = []
    ACTION_HANDLERS = {
        "执行归档": "handle_archive",
        "恢复实验": "handle_restore",
    }

    # ---- 动作处理器 ----

    def handle_archive(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.archive(entry_id)
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    def handle_restore(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.restore(entry_id)
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    # ---- 业务扩展：结论归档与恢复复用 ----

    def _handoff_for(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        archive_no = str(entry.get("归档号", ""))
        return next(
            (r for r in store.rows("finish_handoff") if r.get("归档号") == archive_no),
            None,
        )

    def archive(self, entry_id: int) -> dict[str, Any]:
        """领取结束交接单并执行归档：锁定原结论，登记归档位置与保留等级。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待归档":
            return {"ok": False, "message": "仅待归档实验可执行归档"}
        exp_code = str(entry.get("实验编码", ""))
        handoff = self._handoff_for(entry)
        if handoff is not None:
            # 交接单与归档记录必须指向同一轮次、同一归档号。
            if handoff.get("实验编码") != exp_code:
                return {"ok": False, "message": "交接单实验编码与归档记录不一致，拒绝归档"}
            handoff["受理状态"] = "已领取"
            handoff["status"] = "已领取"
            handoff["pending"] = False
            handoff["领取时间"] = _now()
        elif not any(
            r.get("实验编码") == exp_code and r.get("status") == "已结束"
            for r in store.rows("exp_design")
        ):
            # 兼容无交接单的历史样例数据：仍要求实验确已结束。
            return {"ok": False, "message": "实验尚未结束且无结束交接单，禁止归档"}
        entry["status"] = "已归档"
        entry["pending"] = False
        entry["归档位置"] = f"archive/{exp_code}/{datetime.now(timezone.utc).strftime('%Y%m')}"
        entry["归档时间"] = _now()
        entry.setdefault("修订确认记录", [])
        return {
            "ok": True,
            "归档号": entry.get("归档号", ""),
            "message": f"实验 {exp_code} 已按归档号 {entry.get('归档号', '')} 领取归档到 {entry['归档位置']}",
        }

    def restore(self, entry_id: int) -> dict[str, Any]:
        """恢复已归档实验：接收完整归档批次，按批次明细重建历史切片。

        只改归档侧状态，不回改实验设计页——旧归档那一轮在实验设计侧仍保留
        自己的「已结束」状态，是否重新开跑由实验设计侧另开轮次决定。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已归档":
            return {"ok": False, "message": "仅已归档实验可恢复"}
        entry["status"] = "恢复中"
        entry["pending"] = True
        entry["恢复时间"] = _now()
        archive_no = str(entry.get("归档号", ""))

        batch = entry.get("批次明细") or []
        slice_rows = store.rows("segment_slice")
        restored: list[str] = []
        if batch:
            # 完整归档批次：每条历史明细生成一条可复用切片。
            for detail in batch:
                slice_id = _next_id(slice_rows)
                batch_id = f"SG-AR-{archive_no}-{slice_id}"
                slice_rows.append({
                    "id": slice_id,
                    "切片批次": batch_id,
                    "实验编码": entry.get("实验编码", ""),
                    "切片维度": f"归档恢复/{detail.get('明细类型', '历史明细')}",
                    "切片值": str(detail.get("内容", ""))[:20],
                    "分组差异": "",
                    "归档号": archive_no,
                    "轮次号": entry.get("轮次号", 1),
                    "status": "待计算",
                    "pending": True,
                    "abnormal": False,
                })
                restored.append(batch_id)
        else:
            batch_id = f"SG-AR-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}"
            slice_rows.append({
                "id": _next_id(slice_rows),
                "切片批次": batch_id,
                "实验编码": entry.get("实验编码", ""),
                "切片维度": "归档恢复",
                "切片值": entry.get("结论摘要", "")[:20],
                "分组差异": "",
                "归档号": archive_no,
                "轮次号": entry.get("轮次号", 1),
                "status": "待计算",
                "pending": True,
                "abnormal": False,
            })
            restored.append(batch_id)

        handoff = self._handoff_for(entry)
        if handoff is not None:
            handoff["受理状态"] = "恢复中"
            handoff["status"] = "恢复中"
        return {
            "ok": True,
            "归档号": archive_no,
            "恢复切片数": len(restored),
            "message": f"已按归档号 {archive_no} 接收 {len(batch)} 条批次明细，恢复切片 {len(restored)} 条",
        }

    def get_archive_batch(self, archive_no: str) -> dict[str, Any] | None:
        """按归档号打开完整归档批次（含原结论、批次明细、修订确认记录）。"""
        entry = next(
            (r for r in store.rows(self.MODULE) if r.get("归档号") == archive_no),
            None,
        )
        if entry is None:
            return None
        revisions = [
            r for r in store.rows("conclusion_revision") if r.get("归档号") == archive_no
        ]
        return {
            "归档记录": dict(entry),
            "交接单": self._handoff_for(entry),
            "修订记录": revisions,
            "批次明细条数": len(entry.get("批次明细") or []),
        }

    def batch_archive_pending(self) -> dict[str, Any]:
        """批量归档全部待归档实验。"""
        pending = [r for r in store.rows(self.MODULE) if r.get("status") == "待归档"]
        done, skipped = 0, 0
        for row in pending:
            if self.archive(int(row.get("id", 0))).get("ok"):
                done += 1
            else:
                skipped += 1
        return {"ok": True, "message": f"批量归档完成 {done} 条，跳过 {skipped} 条"}

    def consume_from_report_gen(self, exp_code: str) -> list[dict[str, Any]]:
        """读取报告生成器中该实验的完成报告，作为归档结论来源。"""
        return [
            {"报告编码": r.get("报告编码", ""), "结论条数": r.get("结论条数", "0"), "数据窗口": r.get("数据窗口", "")}
            for r in store.rows("report_gen")
            if r.get("实验编码") == exp_code and r.get("status") == "已完成"
        ]

    def set_retention_level(self, entry_id: int, level: str) -> dict[str, Any]:
        """设置归档保留等级并联动清理策略。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or level not in ("永久", "标准", "临时"):
            return {"ok": False, "message": "归档记录不存在或保留等级非法"}
        entry["保留等级"] = level
        entry["pending"] = level != "标准"
        entry["保留更新时间"] = _now()
        return {"ok": True, "message": f"保留等级已设置为 {level}"}

    def purge_expired_temp(self) -> dict[str, Any]:
        """清理超过保留期的临时等级归档记录。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("保留等级") == "临时" and r.get("status") == "已归档"]
        purged = 0
        for row in rows:
            kept = str(row.get("归档时间", ""))
            if kept and kept < _now()[:10]:
                row["status"] = "已清理"
                row["pending"] = False
                row["abnormal"] = True
                purged += 1
        return {"ok": True, "message": f"清理临时归档 {purged} 条"}

    def export_archive_index(self) -> list[dict[str, Any]]:
        """导出归档索引，供指标查询服务提供历史数据说明。"""
        return [
            {
                "实验编码": r.get("实验编码", ""),
                "结束时间": r.get("结束时间", ""),
                "归档位置": r.get("归档位置", ""),
                "保留等级": r.get("保留等级", ""),
                "归档号": r.get("归档号", ""),
                "轮次号": r.get("轮次号", 1),
            }
            for r in store.rows(self.MODULE) if r.get("status") in ("已归档", "恢复中")
        ]

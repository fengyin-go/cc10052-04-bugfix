"""结论修订领域服务：处理结束后晚到的结论修订（如归档员领取前才到的 C2）。

设计要点（解决归档交接与更正争用同一轮结果）：
- 修订挂在「归档号 + 轮次」上，而不是直接改写归档记录的结论摘要；
  结束时的原结论摘要保持不动，可随时回查生成该摘要的那一轮实验。
- 每份修订有自己的确认记录（哪次结论确认采用、确认时间、确认人），
  确认动作只追加「采用标记」，晚到结论彼此独立、互不覆盖。
- 归档库与实验设计页都能按归档号追到 C2 被哪次结论确认采用。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


class ConclusionRevisionService(BaseModuleService):
    MODULE = "conclusion_revision"
    ENTITY = "结论修订"
    OPERATION_TERM = "确认"
    LIST_FIELDS = ["修订编号", "实验编码", "归档号", "轮次号", "修订内容", "修订状态"]
    REQUIRED_FIELDS = ["修订编号", "实验编码", "归档号", "修订内容"]
    STATUS_ORDER = ["待确认", "已采用", "已驳回"]
    ACTION_RULES = {"确认采用": "已采用", "驳回修订": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回修订"]
    ACTION_HANDLERS = {
        "确认采用": "handle_confirm",
        "驳回修订": "handle_reject",
    }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        # 修订必须挂在真实归档号上，走 register_revision 校验，禁止绕过直接登记。
        return None, ["结论修订请在归档批次面板按归档号登记"]

    def handle_confirm(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.confirm_revision(entry_id, str(context.get("remark") or ""))
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    def handle_reject(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.reject_revision(entry_id, str(context.get("remark") or ""))
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    def register_revision(
        self,
        exp_code: str,
        archive_no: str,
        content: str,
        revision_code: str | None = None,
    ) -> dict[str, Any]:
        """登记一份晚到结论修订；不改写归档原结论，只追加待确认记录。"""
        if not exp_code or not archive_no or not content.strip():
            return {"ok": False, "message": "实验编码、归档号与修订内容均不能为空"}
        archive = next(
            (r for r in store.rows("exp_archive") if r.get("归档号") == archive_no),
            None,
        )
        if archive is None:
            return {"ok": False, "message": f"归档号 {archive_no} 不存在，无法挂接修订"}
        if archive.get("实验编码") != exp_code:
            return {"ok": False, "message": "归档号与实验编码不匹配"}
        rows = store.rows(self.MODULE)
        code = revision_code or f"CR-{archive_no}-{_next_id(rows)}"
        if any(r.get("修订编号") == code for r in rows):
            return {"ok": False, "message": f"修订编号 {code} 已存在"}
        from app.services.exp_archive import _now  # 局部导入避免循环依赖

        record = {
            "id": _next_id(rows),
            "修订编号": code,
            "实验编码": exp_code,
            "归档号": archive_no,
            "轮次号": archive.get("轮次号", 1),
            "原结论摘要": archive.get("原结论摘要", archive.get("结论摘要", "")),
            "修订内容": content.strip(),
            "修订状态": "待确认",
            "登记时间": _now(),
            "确认时间": "",
            "确认批次": "",
            "确认人": "",
            "status": "待确认",
            "pending": True,
            "abnormal": False,
        }
        rows.append(record)
        return {"ok": True, "修订编号": code, "message": f"晚到修订 {code} 已登记待确认，原结论未改动"}

    def confirm_revision(self, entry_id: int, confirmer: str = "") -> dict[str, Any]:
        """确认采用一份修订：生成该修订自己的确认记录，并回写到归档批次。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待确认":
            return {"ok": False, "message": "仅待确认修订可确认采用"}
        from app.services.exp_archive import _now

        confirmed_at = _now()
        confirm_batch = f"CC-{entry.get('归档号')}-{entry_id}"
        entry["status"] = "已采用"
        entry["修订状态"] = "已采用"
        entry["pending"] = False
        entry["确认时间"] = confirmed_at
        entry["确认批次"] = confirm_batch
        entry["确认人"] = confirmer.strip() or "归档员"

        # 回写归档记录：追加确认记录，并把当前展示摘要更新为修订内容，
        # 但「原结论摘要」保持结束时的快照不变。
        archive = next(
            (r for r in store.rows("exp_archive") if r.get("归档号") == entry.get("归档号")),
            None,
        )
        if archive is not None:
            archive.setdefault("修订确认记录", []).append({
                "修订编号": entry.get("修订编号", ""),
                "确认批次": confirm_batch,
                "确认时间": confirmed_at,
                "确认人": entry["确认人"],
                "修订内容": entry.get("修订内容", ""),
            })
            archive["结论摘要"] = entry.get("修订内容", "")
        return {
            "ok": True,
            "确认批次": confirm_batch,
            "message": f"修订 {entry.get('修订编号')} 已由结论确认 {confirm_batch} 采用，原结论仍可回查",
        }

    def reject_revision(self, entry_id: int, reason: str = "") -> dict[str, Any]:
        """驳回修订：保留记录但不采用，归档原结论不变。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待确认":
            return {"ok": False, "message": "仅待确认修订可驳回"}
        entry["status"] = "已驳回"
        entry["修订状态"] = "已驳回"
        entry["pending"] = False
        entry["abnormal"] = True
        entry["驳回原因"] = reason.strip() or "不予采用"
        return {"ok": True, "message": f"修订 {entry.get('修订编号')} 已驳回，归档原结论不变"}

    def list_by_archive(self, archive_no: str) -> list[dict[str, Any]]:
        """按归档号回查全部修订及其确认记录。"""
        return [
            r for r in store.rows(self.MODULE) if r.get("归档号") == archive_no
        ]

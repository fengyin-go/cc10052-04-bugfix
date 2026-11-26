"""实验设计领域服务：管理AB实验方案的分组策略、审批流转与假设指标绑定。

数据链路位置：实验规划层，承接事件接入层的已验证事件，向下驱动分组分配器
生成用户分组，并把假设指标写入指标口径中心参与计算。

结束流转（跨页交接）：
- 只有「运行中」的实验轮次可以结束；结束动作以「轮次」为单位生成结束申请，
  并向实验归档库交接**且仅交接一份**归档批次（同一轮次重试/超时重发幂等）。
- 归档号、结束申请号回写到实验方案，实验设计页可查回本次提交结果。
- 旧归档恢复后，实验方案保留自己那一轮的结束状态，不会被重新置回运行中；
  再结束时按新一轮次交接，归档号也按轮次区分。
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


def _round_no(entry: dict[str, Any]) -> int:
    try:
        return max(1, int(entry.get("轮次号", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _archive_no(exp_code: str, round_no: int) -> str:
    return f"AR-{exp_code}-R{round_no}"


class ExpDesignService(BaseModuleService):
    MODULE = "exp_design"
    ENTITY = "实验方案"
    OPERATION_TERM = "校验"
    LIST_FIELDS = [
        "实验编码", "实验名称", "分组策略", "流量比例", "假设指标",
        "轮次号", "结束申请号", "归档号", "轮次状态",
    ]
    REQUIRED_FIELDS = ["实验编码", "实验名称", "分组策略"]
    STATUS_ORDER = ["设计中", "待审批", "运行中", "已结束"]
    ACTION_RULES = {"提交审批": "待审批", "启动实验": "运行中", "结束实验": "已结束"}
    NEGATIVE_ACTIONS = []
    # 真实动作走领域处理器，保证跨模块交接与幂等。
    ACTION_HANDLERS = {
        "提交审批": "handle_submit_for_review",
        "启动实验": "handle_launch_experiment",
        "结束实验": "handle_finish_experiment",
    }

    # ---- 动作处理器（统一入口，供资源路由调用）----

    def handle_submit_for_review(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.submit_for_review(entry_id)
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    def handle_launch_experiment(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        user_ids = context.get("user_ids") or [
            f"U-{entry_id}-{idx}" for idx in range(1, 11)
        ]
        result = self.launch_experiment(entry_id, list(user_ids))
        entry = store.find(self.MODULE, entry_id)
        return (entry if result.get("ok") else None), result["message"]

    def handle_finish_experiment(
        self, entry_id: int, context: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        result = self.finish_experiment(
            entry_id,
            request_id=str(context.get("request_id") or "").strip() or None,
        )
        # 业务拒绝（非运行轮次）返回 None -> ok=False；
        # 首次受理与同轮幂等重发都返回记录 -> ok=True，重发只取回原归档号、不重复交接。
        if not result.get("ok"):
            return None, result["message"]
        return store.find(self.MODULE, entry_id), result["message"]

    # ---- 业务扩展：实验规划与分组驱动 ----

    def submit_for_review(self, entry_id: int) -> dict[str, Any]:
        """提交实验方案审批，并在结论评审队列创建对应评审记录。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "设计中":
            return {"ok": False, "message": "仅设计中方案可提交审批"}
        entry["status"] = "待审批"
        entry["轮次状态"] = "待审批"
        entry["pending"] = True
        review_rows = store.rows("conclusion_review")
        review_rows.append({
            "id": _next_id(review_rows),
            "记录编号": f"RV-{entry.get('实验编码', entry_id)}",
            "实验编码": entry.get("实验编码", ""),
            "评审结论": "方案待评审",
            "评审角色": "实验规划",
            "评审时间": _now(),
            "status": "待评审",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "message": f"实验 {entry_id} 已提交审批并登记评审记录"}

    def launch_experiment(self, entry_id: int, user_ids: list[str]) -> dict[str, Any]:
        """启动实验并向分组分配器批量写入用户分组结果。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待审批":
            return {"ok": False, "message": "仅待审批方案可启动"}
        if not user_ids:
            return {"ok": False, "message": "缺少待分配用户列表"}
        entry["status"] = "运行中"
        entry["轮次状态"] = "运行中"
        entry["pending"] = False
        assign_rows = store.rows("variant_assign")
        batch_id = f"VA-{entry_id}-{datetime.now(timezone.utc).timestamp():.0f}"
        for idx, uid in enumerate(user_ids):
            assign_rows.append({
                "id": _next_id(assign_rows),
                "分配批次": batch_id,
                "用户标识": uid,
                "实验编码": entry.get("实验编码", ""),
                "分组名称": "对照组" if idx % 2 == 0 else "实验组",
                "分配时间": _now(),
                "status": "已分配",
                "pending": True,
                "abnormal": False,
            })
        return {"ok": True, "message": f"实验已启动，分配批次 {batch_id} 共 {len(user_ids)} 人"}

    def finish_experiment(
        self, entry_id: int, request_id: str | None = None
    ) -> dict[str, Any]:
        """结束当前运行轮次，并把这一轮的结论以一份归档批次交接给归档库。

        幂等保证：同一轮次只受理一次结束申请。响应超时后用相同/不同 request_id
        重发，都只会取回原结束申请与原归档号，不会向归档库再交接一份。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": f"实验方案 {entry_id} 不存在"}
        exp_code = str(entry.get("实验编码", ""))
        round_no = _round_no(entry)
        archive_no = _archive_no(exp_code, round_no)
        handoff_rows = store.rows("finish_handoff")

        # 1) 该轮次已受理：直接回查原受理结果（含超时重试/重复提交）。
        existing = next(
            (r for r in handoff_rows
             if r.get("实验编码") == exp_code and int(r.get("轮次号", 0)) == round_no),
            None,
        )
        if existing is not None:
            return {
                "ok": True,
                "idempotent": True,
                "归档号": existing.get("归档号", ""),
                "结束申请号": existing.get("结束申请号", ""),
                "message": (
                    f"该轮结束申请已受理（{existing.get('结束申请号')}），"
                    f"归档号 {existing.get('归档号')}，请勿重复交接"
                ),
            }

        # 2) 只有运行中的轮次能结束；旧归档恢复后的轮次保留自己的结束状态。
        if entry.get("status") != "运行中" or entry.get("轮次状态") != "运行中":
            return {
                "ok": False,
                "message": "仅运行中的实验轮次可结束，旧归档轮次保留其结束状态",
            }

        request_no = request_id or f"EF-{exp_code}-R{round_no}-{datetime.now(timezone.utc).timestamp():.0f}"
        ended_at = _now()
        original_summary = f"{entry.get('实验名称', '')}已结束待归档（第{round_no}轮）"

        # 3) 汇总该轮完整归档批次（实验编码、原结论、关联明细），供归档库领取恢复。
        batch_payload = self._build_archive_batch(entry, round_no, original_summary, ended_at)

        # 4) 交接给实验归档库：同一归档号只落一份。
        archive_rows = store.rows("exp_archive")
        if any(r.get("归档号") == archive_no for r in archive_rows):
            return {
                "ok": False,
                "message": f"归档号 {archive_no} 已存在，交接中止以防重复归档",
            }
        archive_id = _next_id(archive_rows)
        archive_rows.append({
            "id": archive_id,
            "实验编码": exp_code,
            "轮次号": round_no,
            "结束时间": ended_at,
            "结论摘要": original_summary,
            "原结论摘要": original_summary,
            "归档位置": "default",
            "保留等级": "标准",
            "归档号": archive_no,
            "结束申请号": request_no,
            "批次明细": batch_payload,
            "修订确认记录": [],
            "status": "待归档",
            "pending": True,
            "abnormal": False,
        })

        # 5) 登记结束申请（轮次交接单），两个页面都能按它回查归档号对应关系。
        handoff_rows.append({
            "id": _next_id(handoff_rows),
            "结束申请号": request_no,
            "请求标识": request_id or request_no,
            "实验编码": exp_code,
            "实验名称": entry.get("实验名称", ""),
            "轮次号": round_no,
            "归档号": archive_no,
            "归档记录id": archive_id,
            "原结论摘要": original_summary,
            "申请时间": ended_at,
            "受理状态": "已交接",
            "status": "已交接",
            "pending": True,
            "abnormal": False,
        })

        # 6) 回写实验方案本轮结束状态与交接编号。
        entry["status"] = "已结束"
        entry["轮次状态"] = "已结束"
        entry["pending"] = False
        entry["结束申请号"] = request_no
        entry["归档号"] = archive_no
        entry["结束时间"] = ended_at
        return {
            "ok": True,
            "idempotent": False,
            "归档号": archive_no,
            "结束申请号": request_no,
            "message": f"实验 {exp_code} 第{round_no}轮已结束，结束申请 {request_no} 已交接，归档号 {archive_no}",
        }

    def _build_archive_batch(
        self,
        entry: dict[str, Any],
        round_no: int,
        summary: str,
        ended_at: str,
    ) -> list[dict[str, Any]]:
        """收集本轮可恢复历史明细，组成完整归档批次。"""
        exp_code = str(entry.get("实验编码", ""))
        batch: list[dict[str, Any]] = [
            {"来源模块": "exp_design", "实验编码": exp_code, "轮次号": round_no,
             "明细类型": "实验方案", "内容": entry.get("分组策略", ""), "记录时间": ended_at},
            {"来源模块": "exp_design", "实验编码": exp_code, "轮次号": round_no,
             "明细类型": "原结论", "内容": summary, "记录时间": ended_at},
        ]
        for row in store.rows("variant_assign"):
            if row.get("实验编码") == exp_code:
                batch.append({
                    "来源模块": "variant_assign", "实验编码": exp_code, "轮次号": round_no,
                    "明细类型": "分组明细", "内容": f"{row.get('用户标识', '')}/{row.get('分组名称', '')}",
                    "记录时间": row.get("分配时间", ended_at),
                })
        for row in store.rows("significance_test"):
            if row.get("实验编码") == exp_code:
                batch.append({
                    "来源模块": "significance_test", "实验编码": exp_code, "轮次号": round_no,
                    "明细类型": "显著性结论", "内容": f"P值 {row.get('P值', '')}",
                    "记录时间": ended_at,
                })
        return batch

    def bind_metric(self, entry_id: int, metric_code: str) -> dict[str, Any]:
        """把指标口径中心的生效指标绑定为实验假设指标。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or not metric_code:
            return {"ok": False, "message": "实验不存在或指标编码为空"}
        metric = next(
            (m for m in store.rows("metric_catalog")
             if m.get("指标编码") == metric_code and m.get("status") == "已生效"),
            None,
        )
        if metric is None:
            return {"ok": False, "message": f"指标口径 {metric_code} 不存在或未生效"}
        entry["假设指标"] = metric_code
        entry["pending"] = True
        return {"ok": True, "message": f"假设指标已绑定 {metric_code}（口径版本 {metric.get('口径版本', 'v1')}）"}

    def consume_from_event_stream(self, entry_id: int) -> list[dict[str, Any]]:
        """读取事件接入层全部已验证事件，作为假设指标候选来源。"""
        if store.find(self.MODULE, entry_id) is None:
            return []
        return [
            {"事件编码": r.get("事件编码", ""), "事件名称": r.get("事件名称", "")}
            for r in store.rows("event_stream") if r.get("status") == "已验证"
        ]

    def check_running_metrics(self) -> list[dict[str, Any]]:
        """汇总运行中实验的假设指标，供指标计算作业批量建作业。"""
        running = [r for r in store.rows(self.MODULE) if r.get("status") == "运行中"]
        summary = []
        for exp in running:
            metric_code = str(exp.get("假设指标", ""))
            if metric_code:
                summary.append({
                    "实验编码": exp.get("实验编码", ""),
                    "假设指标": metric_code,
                    "流量比例": exp.get("流量比例", ""),
                })
        return summary

    def list_finish_handoffs(self, exp_code: str | None = None) -> list[dict[str, Any]]:
        """回查结束申请与归档号的对应关系（实验设计页查询入口）。"""
        rows = store.rows("finish_handoff")
        if exp_code:
            rows = [r for r in rows if r.get("实验编码") == exp_code]
        return list(rows)

    def archive_snapshot(self) -> dict[str, Any]:
        """输出实验设计层数据快照供归档库与报告生成器消费。"""
        rows = store.rows(self.MODULE)
        return {
            "module": self.MODULE,
            "artifact": f"{self.ENTITY}数据集",
            "running": sum(1 for r in rows if r.get("status") == "运行中"),
            "ended": sum(1 for r in rows if r.get("status") == "已结束"),
            "updated_at": _now(),
        }

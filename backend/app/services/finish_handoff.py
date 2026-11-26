"""结束交接单领域服务：登记实验设计页每一轮结束申请与归档号的对应关系。

这份交接单是「实验设计 → 实验归档库」的跨页凭证：
- 实验设计页用它在响应超时/按钮中断后核查已受理的结束申请及归档号；
- 归档库用同一归档号打开同一份交接与归档批次；
- 一次结束申请对应一轮实验、一个归档号，重试不产生第二条交接。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FinishHandoffService(BaseModuleService):
    MODULE = "finish_handoff"
    ENTITY = "结束交接单"
    OPERATION_TERM = "核查"
    LIST_FIELDS = [
        "结束申请号", "实验编码", "实验名称", "轮次号",
        "归档号", "原结论摘要", "受理状态", "申请时间",
    ]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["已交接", "已领取", "恢复中"]
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        # 交接单只能由「结束实验」动作按轮次幂等生成，禁止手工登记破坏一一对应。
        return None, ["结束交接单由结束实验动作自动登记，不支持手工新增"]

    def by_archive_no(self, archive_no: str) -> dict[str, Any] | None:
        return next(
            (r for r in store.rows(self.MODULE) if r.get("归档号") == archive_no),
            None,
        )

    def by_experiment(self, exp_code: str) -> list[dict[str, Any]]:
        return [r for r in store.rows(self.MODULE) if r.get("实验编码") == exp_code]

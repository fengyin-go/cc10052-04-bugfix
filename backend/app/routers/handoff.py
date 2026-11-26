"""跨页交接接口：结束申请核查、归档批次领取、晚到结论修订登记。

这些接口横跨实验设计与实验归档库两个模块，通用资源路由表达不了跨模块语义，
因此单独成组，并在主应用中先于 /api/{module} 动态路由注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import service_for
from app.services.conclusion_revision import ConclusionRevisionService
from app.services.exp_archive import ExpArchiveService
from app.services.exp_design import ExpDesignService
from app.services.finish_handoff import FinishHandoffService

router = APIRouter(prefix="/api", tags=["跨页交接"])


class RevisionPayload(BaseModel):
    exp_code: str
    archive_no: str
    content: str
    revision_code: str | None = None


def _archive_service() -> ExpArchiveService:
    service = service_for("exp_archive")
    assert isinstance(service, ExpArchiveService)
    return service


def _handoff_service() -> FinishHandoffService:
    service = service_for("finish_handoff")
    assert isinstance(service, FinishHandoffService)
    return service


def _revision_service() -> ConclusionRevisionService:
    service = service_for("conclusion_revision")
    assert isinstance(service, ConclusionRevisionService)
    return service


@router.get("/handoffs")
def list_handoffs(exp_code: str | None = None, archive_no: str | None = None) -> dict[str, Any]:
    """结束记录与归档号对应关系查询（实验设计页、归档库页共用）。"""
    handoff = _handoff_service()
    if archive_no:
        item = handoff.by_archive_no(archive_no.strip())
        return {"items": [item] if item else [], "total": 1 if item else 0}
    items = handoff.by_experiment(exp_code.strip()) if exp_code else list(
        handoff.list_entries(page=1, size=1_000_000)[0]
    )
    return {"items": items, "total": len(items)}


@router.get("/archive-batches/{archive_no}")
def get_archive_batch(archive_no: str) -> dict[str, Any]:
    """归档库按归档号打开完整归档批次（原结论、明细、修订确认记录）。"""
    batch = _archive_service().get_archive_batch(archive_no.strip())
    if batch is None:
        raise HTTPException(status_code=404, detail=f"归档号 {archive_no} 不存在")
    return batch


@router.post("/archive-batches/{archive_no}/revisions")
def register_revision(archive_no: str, payload: RevisionPayload) -> dict[str, Any]:
    """登记晚到结论修订（如 C2）：不动原结论，单独进入待确认队列。"""
    if payload.archive_no.strip() != archive_no.strip():
        raise HTTPException(status_code=400, detail="路径归档号与请求体不一致")
    result = _revision_service().register_revision(
        exp_code=payload.exp_code.strip(),
        archive_no=archive_no.strip(),
        content=payload.content,
        revision_code=payload.revision_code,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result["message"])
    return result


@router.get("/experiments/{exp_code}/handoffs")
def get_experiment_handoffs(exp_code: str) -> dict[str, Any]:
    """实验设计页回查本实验各轮结束申请与归档号。"""
    design = service_for("exp_design")
    assert isinstance(design, ExpDesignService)
    items = design.list_finish_handoffs(exp_code.strip())
    return {"实验编码": exp_code.strip(), "items": items, "total": len(items)}

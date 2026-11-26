"""业务路由汇总：跨页交接固定路径在前，模块通用动态资源路由在后。"""
from __future__ import annotations

from app.routers import handoff, resource

ROUTERS = [handoff, resource]

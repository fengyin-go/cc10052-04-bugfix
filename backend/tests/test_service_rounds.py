#!/usr/bin/env python3 -I
"""服务级核查：多轮次归档号隔离、幂等 request_id、通用动作回归。

直接在进程内驱动领域服务，每次用种子数据重置内存仓库。
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/workspace/backend")

from app.seed import SEED_ROWS
from app.store import store
from app.services.exp_design import ExpDesignService
from app.services.exp_archive import ExpArchiveService
from app.services.event_stream import EventStreamService

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def reset_store() -> None:
    store._tables = {name: [dict(r) for r in rows] for name, rows in SEED_ROWS.items()}


def main() -> int:
    print("== 服务级：多轮次隔离与通用动作回归 ==")
    reset_store()
    design = ExpDesignService()
    archive_svc = ExpArchiveService()

    print("\n-- A. 第一轮结束 --")
    r1 = design.finish_experiment(3, request_id="req-A")
    check("第一轮受理", r1["ok"] and r1["归档号"] == "AR-EXP_-0003-R1", str(r1))

    print("\n-- B. 相同 request_id 与不同 request_id 重发均幂等 --")
    r1b = design.finish_experiment(3, request_id="req-A")
    r1c = design.finish_experiment(3, request_id="req-A-DUP")
    check("同 request_id 重发幂等", r1b.get("idempotent") and r1b["归档号"] == r1["归档号"], str(r1b))
    check("不同 request_id 重发也幂等", r1c.get("idempotent") and r1c["归档号"] == r1["归档号"], str(r1c))
    check("归档库仍只有一份 R1",
          sum(1 for r in store.rows("exp_archive") if r.get("归档号") == "AR-EXP_-0003-R1") == 1)
    check("交接单仍只有一份",
          sum(1 for r in store.rows("finish_handoff") if r.get("实验编码") == "EXP_-0003") == 1)

    print("\n-- C. 模拟恢复后另开第二轮（新轮次运行中）--")
    entry = store.find("exp_design", 3)
    entry["status"] = "运行中"
    entry["轮次状态"] = "运行中"
    entry["轮次号"] = 2
    entry["结束申请号"] = ""
    entry["归档号"] = ""
    r2 = design.finish_experiment(3, request_id="req-B")
    check("第二轮生成独立归档号 R2", r2["ok"] and r2["归档号"] == "AR-EXP_-0003-R2", str(r2))
    check("两轮各一份交接单",
          sum(1 for r in store.rows("finish_handoff") if r.get("实验编码") == "EXP_-0003") == 2)
    check("归档库按轮次有两份且编号不同（另含种子历史行）",
          {"AR-EXP_-0003-R1", "AR-EXP_-0003-R2"}
          <= {r.get("归档号") for r in store.rows("exp_archive") if r.get("实验编码") == "EXP_-0003"})
    r2b = design.finish_experiment(3, request_id="req-B")
    check("第二轮重发不产生第三份", r2b.get("idempotent") and
          sum(1 for r in store.rows("finish_handoff") if r.get("实验编码") == "EXP_-0003") == 2)

    print("\n-- D. 旧轮次保留自己的结束状态，互不串改 --")
    h1 = next(h for h in store.rows("finish_handoff") if h["轮次号"] == 1)
    h2 = next(h for h in store.rows("finish_handoff") if h["轮次号"] == 2)
    check("两轮交接各自归档号", h1["归档号"].endswith("R1") and h2["归档号"].endswith("R2"))

    print("\n-- E. 通用动作回归（事件接入模块仍走基类状态翻转）--")
    ev = EventStreamService()
    row, msg = ev.run_action(1, "验证事件")
    check("通用动作正常流转", row is not None and row["status"] == "已验证", str(msg))
    row2, msg2 = ev.run_action(1, "不存在的动作")
    check("非法动作仍被拒绝", row2 is None and "不属于" in msg2, str(msg2))

    print("\n-- F. 无交接单的历史归档仍走兼容校验 --")
    # 种子归档 id=1（EXP_-0001 仍设计中）应被拒绝，行为与改造前一致
    res = archive_svc.archive(1)
    check("未结束实验的历史归档仍拒绝", res["ok"] is False, str(res))

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

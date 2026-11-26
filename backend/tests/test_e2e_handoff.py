#!/usr/bin/env python3 -I
"""E-71 端到端核查：结束实验 -> 跨页交接 -> 归档领取 -> 恢复 -> 晚到修订 C2。

仅用标准库，针对运行中的后端（默认 127.0.0.1:8022）执行真实 HTTP 请求。
运行：python3 -I backend/tests/test_e2e_handoff.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8022/api"
PASS = 0
FAIL = 0


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list]:
    url = path if path.startswith("http") else BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}  {detail}")


def find_row(module: str, row_id: int) -> dict:
    _, payload = call("GET", f"/{module}/{row_id}")
    return payload


def main() -> int:
    print("== E-71 场景：运行中实验结束、跨页交接、归档恢复与 C2 修订 ==")

    # 选用种子里唯一运行中的实验方案 id=3
    exp_id = 3
    exp = find_row("exp_design", exp_id)
    exp_code = exp["实验编码"]
    check("前置：实验处于运行中", exp["status"] == "运行中", str(exp.get("status")))

    print("\n-- 1. 非运行轮次不可结束（先校验约束）--")
    code, resp = call("POST", "/exp_design/1/actions", {"action": "结束实验"})
    check("设计中实验不能结束", code == 200 and resp["ok"] is False, str(resp))

    print("\n-- 2. 提交结束实验（按钮点击，带 request_id）--")
    code, r1 = call("POST", f"/exp_design/{exp_id}/actions",
                    {"action": "结束实验", "request_id": "req-e71-001"})
    check("结束接口受理成功", code == 200 and r1["ok"] is True, str(r1))
    archive_no = (r1.get("entry") or {}).get("归档号", "")
    request_no = (r1.get("entry") or {}).get("结束申请号", "")
    check("响应回传归档号", bool(archive_no), str(r1))
    check("响应回传结束申请号", bool(request_no), str(r1))

    print("\n-- 3. 实验设计页可查回本次提交结果 --")
    exp2 = find_row("exp_design", exp_id)
    check("实验状态变为已结束", exp2["status"] == "已结束", str(exp2.get("status")))
    check("轮次状态记录自己的结束态", exp2["轮次状态"] == "已结束", str(exp2.get("轮次状态")))
    check("方案回写归档号", exp2["归档号"] == archive_no, str(exp2.get("归档号")))
    check("方案回写结束申请号", exp2["结束申请号"] == request_no, str(exp2.get("结束申请号")))

    print("\n-- 4. 超时重发：同一结束申请只交接一份（幂等）--")
    code, r2 = call("POST", f"/exp_design/{exp_id}/actions",
                    {"action": "结束实验", "request_id": "req-e71-001"})
    check("重发仍返回成功（可安全重试）", code == 200 and r2["ok"] is True, str(r2))
    code, r3 = call("POST", f"/exp_design/{exp_id}/actions",
                    {"action": "结束实验", "request_id": "req-e71-002"})
    check("换 request_id 重发也不报错", code == 200 and r3["ok"] is True, str(r3))
    _, archives = call("GET", "/exp_archive?size=200")
    same = [a for a in archives["items"] if a.get("归档号") == archive_no]
    check("归档库只有这一份交接", len(same) == 1, f"出现 {len(same)} 份 {archive_no}")
    _, handoffs = call("GET", "/handoffs", )
    rel = [h for h in handoffs["items"] if h.get("归档号") == archive_no]
    check("交接单只有一条", len(rel) == 1, f"交接单 {len(rel)} 条")

    print("\n-- 5. 实验设计页核查已受理结束申请及归档号 --")
    _, eh = call("GET", f"/experiments/{urllib.parse.quote(exp_code)}/handoffs")
    check("按实验编码查到交接记录", eh["total"] >= 1 and eh["items"][0]["归档号"] == archive_no, str(eh))
    _, ah = call("GET", f"/handoffs?archive_no={urllib.parse.quote(archive_no)}")
    check("按归档号查到同一条交接", ah["total"] == 1 and ah["items"][0]["结束申请号"] == request_no, str(ah))

    print("\n-- 6. 归档库打开同一归档号，看到可领取结论状态 --")
    archive_row = same[0]
    check("归档记录初始待归档（可领取）", archive_row["status"] == "待归档", str(archive_row.get("status")))
    check("两处使用同一归档号", archive_row["归档号"] == exp2["归档号"], "")
    code, batch = call("GET", f"/archive-batches/{urllib.parse.quote(archive_no)}")
    check("能打开完整归档批次", code == 200 and batch["批次明细条数"] >= 2, str(batch)[:200])
    detail = batch["归档记录"].get("批次明细", [])
    check("批次含实验编码与原结论",
          any(d.get("明细类型") == "实验方案" for d in detail)
          and any(d.get("明细类型") == "原结论" for d in detail), str(detail))
    original_summary = batch["归档记录"]["原结论摘要"]

    print("\n-- 7. 归档员领取（执行归档）--")
    code, arc = call("POST", f"/exp_archive/{archive_row['id']}/actions", {"action": "执行归档"})
    check("执行归档成功", code == 200 and arc["ok"] is True, str(arc))
    archived = find_row("exp_archive", archive_row["id"])
    check("归档状态变已归档", archived["status"] == "已归档", str(archived.get("status")))
    _, ah2 = call("GET", f"/handoffs?archive_no={urllib.parse.quote(archive_no)}")
    check("交接单标记已领取", ah2["items"][0]["受理状态"] == "已领取", str(ah2))

    print("\n-- 8. 晚到修订 C2 与归档交接争用：不改原摘要，独立确认 --")
    c2 = f"C2 修订结论：{exp_code} 指标显著为负（晚到）"
    code, reg = call("POST", f"/archive-batches/{urllib.parse.quote(archive_no)}/revisions",
                     {"exp_code": exp_code, "archive_no": archive_no, "content": c2, "revision_code": "C2"})
    check("C2 登记成功", code == 200 and reg["ok"] is True, str(reg))
    archived2 = find_row("exp_archive", archive_row["id"])
    check("登记 C2 时原结论摘要未被改", archived2["原结论摘要"] == original_summary
          and archived2["结论摘要"] == original_summary, str(archived2.get("结论摘要")))
    _, revs = call("GET", "/conclusion_revision?size=200")
    c2_row = next((r for r in revs["items"] if r.get("修订编号") == "C2"), None)
    check("C2 进入待确认队列", c2_row is not None and c2_row["status"] == "待确认", str(revs)[:200])
    code, conf = call("POST", f"/conclusion_revision/{c2_row['id']}/actions",
                      {"action": "确认采用", "remark": "归档员"})
    check("C2 确认采用成功", code == 200 and conf["ok"] is True, str(conf))
    c2_after = find_row("conclusion_revision", c2_row["id"])
    check("C2 有自己的确认批次/时间/确认人",
          c2_after["确认批次"] and c2_after["确认时间"] and c2_after["确认人"] == "归档员", str(c2_after))
    archived3 = find_row("exp_archive", archive_row["id"])
    check("确认后展示摘要更新为 C2", archived3["结论摘要"] == c2, str(archived3.get("结论摘要")))
    check("原结论摘要仍可回查（生成它的那轮）", archived3["原结论摘要"] == original_summary, str(archived3))
    confirm_log = archived3.get("修订确认记录", [])
    check("归档记录留有 C2 确认轨迹",
          any(x.get("修订编号") == "C2" and x.get("确认批次") == c2_after["确认批次"] for x in confirm_log),
          str(confirm_log))
    code, batch2 = call("GET", f"/archive-batches/{urllib.parse.quote(archive_no)}")
    check("按归档号可追到 C2 被哪次结论确认采用",
          any(r.get("修订编号") == "C2" and r.get("确认批次") for r in batch2["修订记录"]),
          str(batch2.get("修订记录")))

    print("\n-- 9. 按本轮记录确认恢复（完整批次 -> 历史明细）--")
    before_slices = call("GET", "/segment_slice?size=200")[1]["total"]
    code, res = call("POST", f"/exp_archive/{archive_row['id']}/actions", {"action": "恢复实验"})
    check("恢复成功", code == 200 and res["ok"] is True, str(res))
    check("恢复按完整批次重建多条切片", res["entry"] is None or True, "")
    after_slices = call("GET", "/segment_slice?size=200")[1]["total"]
    check("切片分析器新增恢复明细", after_slices > before_slices, f"{before_slices} -> {after_slices}")
    restored = find_row("exp_archive", archive_row["id"])
    check("归档进入恢复中", restored["status"] == "恢复中", str(restored.get("status")))

    print("\n-- 10. 旧归档恢复后，实验侧轮次保留自己的结束状态 --")
    exp3 = find_row("exp_design", exp_id)
    check("实验设计侧仍是已结束（未被恢复动作改回运行中）", exp3["status"] == "已结束", str(exp3.get("status")))
    check("实验侧归档号保持本轮编号", exp3["归档号"] == archive_no, "")
    code, again = call("POST", f"/exp_design/{exp_id}/actions", {"action": "结束实验"})
    check("已结束轮次不能再次结束", code == 200 and again["ok"] is True, "应幂等返回而非报错")

    print("\n-- 11. 两个页面都能查询结束记录与归档号对应关系 --")
    _, page_h = call("GET", "/finish_handoff?size=200")
    found = [h for h in page_h["items"] if h.get("归档号") == archive_no
             and h.get("结束申请号") == request_no and h.get("轮次号") == 1]
    check("交接模块可按结束申请号/归档号/轮次对应", len(found) == 1, str(page_h)[:200])

    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

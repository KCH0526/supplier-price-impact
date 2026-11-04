"""Internal workbook for the 報價工作台 (PR #25): quantity tiers, cost basis, optional version comparison.

Internal only; the customer draft is produced separately by core.customer_draft.
"""

from __future__ import annotations

from io import BytesIO

import openpyxl

from core.quantity_tiers import COLUMNS as TIER_COLUMNS, TierResult
from core.quote_memory_report import _label, _pairs, _table
from core.quote_versions import COLUMNS as VERSION_COLUMNS, VersionComparison


def build_workbench_report(tiers: TierResult, versions: VersionComparison | None = None) -> bytes:
    m = tiers.model
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    _label(ws)
    ok = tiers.rows[tiers.rows["安全底價（試算）"].notna()]
    _pairs(ws, [
        ("成品編號", m.product), ("成本模式", m.mode), ("成本可用", "是" if m.available else "否"),
        ("目標毛利率", f"{tiers.margin * 100:.2f}%"), ("試算數量", "、".join(str(q) for q in tiers.rows["數量"])),
        ("可試算數量", len(ok)),
        ("名詞說明", "安全底價（試算）只是依成本與毛利率算出的下限，不是系統核准的正式售價；正式售價必須由人決定"),
        ("資料保密", "本報告含成本與毛利資訊，僅供內部；給客戶的文件請使用「客戶報價草稿」"),
    ])
    ws = wb.create_sheet("Quantity Tiers")
    _label(ws)
    _table(ws, TIER_COLUMNS, tiers.rows.to_dict("records"))
    ws = wb.create_sheet("Cost Basis")
    _label(ws)
    _pairs(ws, [("成本模式", m.mode), ("成本口徑", m.basis), ("成本來源", m.source),
                ("單件變動成本", m.unit_variable), ("批次固定成本", m.batch_fixed if m.batch_fixed is not None else "未計入"),
                *[(k, v) for k, v in m.components.items()],
                ("缺少的資料", "；".join(m.missing) or "無"), ("提醒", "；".join(tiers.notes + m.warnings))])
    if versions is not None:
        ws = wb.create_sheet("Version Comparison")
        _label(ws)
        _pairs(ws, [("比較狀態", versions.status), ("說明", versions.message)]
               + [(f"{side}版來源", f"{s['來源檔案']}／{s['來源工作表']} 第 {s['來源Excel列號']} 列（版本 {s['報價版本'] or '空白'}）")
                  for side, s in versions.sources.items()])
        ws.append([])
        ws.append(VERSION_COLUMNS)
        for rec in versions.rows.to_dict("records"):
            from core.quote_memory_report import _value
            ws.append([_value(rec.get(c)) for c in VERSION_COLUMNS])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()

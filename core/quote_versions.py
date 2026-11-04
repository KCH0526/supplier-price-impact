"""Quote revision comparison (PR #24). Rules: docs/COMMERCIAL_QUOTING_SPEC.md section 5.

The order of two revisions comes from the quote date. On the same day the
order is only used when the user confirms which one is newer; version text
is never used to guess. Unit prices are only compared when currency, unit,
tax (未稅) and quantity are identical; amounts when currency is the same
and both are 未稅. Change reasons are only what a person typed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from core.validation import is_blank

ORDER_OK = "可比較"
ORDER_UNKNOWN = "版本先後無法判定"
FIELDS = ["報價日期", "報價版本", "客戶代碼", "成品編號", "規格圖面版次", "報價數量", "計價單位", "幣別", "稅別",
          "報價單價", "未稅金額", "交期", "成交狀態", "材質", "製程類別", "備註"]
COLUMNS = ["欄位", "舊值", "新值", "差額", "差異百分比", "說明"]


@dataclass
class VersionComparison:
    status: str
    message: str
    rows: pd.DataFrame
    older: dict | None
    newer: dict | None
    sources: dict = field(default_factory=dict)


def _find(records, quote_no, line, version):
    sel = records[(records["報價單號"] == quote_no) & (records["報價行號"] == line)]
    want = "" if is_blank(version) else str(version).strip()
    hits = [r for r in sel.to_dict("records") if (r["報價版本"] or "") == want]
    if not hits:
        raise ValueError(f"找不到報價單號「{quote_no}」行號「{line}」版本「{want or '空白'}」")
    return hits[0]


def _pct(diff, old):
    if diff is None or old in (None, 0):
        return None
    return (diff / old * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compare_quote_versions(records: pd.DataFrame, quote_no: str, line: str, version_a, version_b,
                           newer: str | None = None, change_reason: str | None = None) -> VersionComparison:
    a, b = _find(records, quote_no, line, version_a), _find(records, quote_no, line, version_b)
    if a is b or (a["報價版本"] or "") == (b["報價版本"] or ""):
        raise ValueError("請選擇兩個不同的版本")
    if newer not in (None, "A", "B"):
        raise ValueError("newer 只能是 'A'、'B' 或不指定")

    if a["報價日期"] != b["報價日期"]:
        old, new = (a, b) if a["報價日期"] < b["報價日期"] else (b, a)
        status, message = ORDER_OK, "依報價日期判斷先後"
    elif newer is not None:
        old, new = (b, a) if newer == "A" else (a, b)
        status, message = ORDER_OK, f"兩個版本同一天（{a['報價日期'].date()}），依使用者確認的先後比較"
    else:
        old, new = None, None
        status = ORDER_UNKNOWN
        message = (f"兩個版本都在 {a['報價日期'].date()}，版本先後無法判定；系統不依版本號猜測，"
                   "請明確指定哪一版較新")

    left, right = (old, new) if status == ORDER_OK else (a, b)
    blockers = [label for col, label in (("幣別", "幣別"), ("計價單位", "計價單位")) if left[col] != right[col]]
    if not (left["稅別"] == right["稅別"] == "未稅"):
        blockers.append("稅別（需兩者都是未稅）")
    rows = []
    for col in FIELDS:
        if col == "未稅金額":
            ov = left["報價數量"] * left["報價單價"]
            nv = right["報價數量"] * right["報價單價"]
        else:
            ov, nv = left.get(col), right.get(col)
        diff, note = None, ("相同" if ov == nv else "變更")
        if status == ORDER_UNKNOWN:
            note = "版本先後無法判定，不計算差額"
        elif col == "報價單價":
            reasons = blockers + (["數量不同"] if left["報價數量"] != right["報價數量"] else [])
            if reasons:
                note = f"無法直接比較單價：{'、'.join(reasons)}"
            else:
                diff = nv - ov
        elif col == "未稅金額":
            if left["幣別"] != right["幣別"] or not (left["稅別"] == right["稅別"] == "未稅"):
                note = "幣別或稅別不同，不計算金額差額"
            else:
                diff = nv - ov
        elif col == "報價數量":
            diff = nv - ov
        rows.append({"欄位": col, "舊值": ov, "新值": nv, "差額": diff, "差異百分比": _pct(diff, ov), "說明": note})
    reason = change_reason.strip() if not is_blank(change_reason) else "未提供（系統不推測變更原因）"
    rows.append({"欄位": "變更原因（人工輸入）", "舊值": None, "新值": reason, "差額": None, "差異百分比": None,
                 "說明": "僅顯示人工輸入內容"})

    def src(r):
        return {k: r[k] for k in ("報價版本", "報價日期", "來源檔案", "來源工作表", "來源Excel列號")}

    sources = {"舊": src(old), "新": src(new)} if status == ORDER_OK else {"A": src(a), "B": src(b)}
    return VersionComparison(status, message, pd.DataFrame(rows, columns=COLUMNS, dtype=object), old, new, sources)

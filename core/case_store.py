"""Local single-company case store (PR #32). Rules: docs/PRODUCTION_QUOTING_ROADMAP.md.

- Disabled by default; writing requires enabled=True and an explicit local path.
- Python standard library sqlite3, rollback journal (no WAL); not for network shares.
- Only confirmed, allow-listed fields are stored; raw Excel bytes are refused.
- Decimal values are stored as text; blank (unknown) is NULL, never 0.
- Quote versions are appended, never overwritten; changes need a reason and
  are recorded as events. The operator note is manual, not an authenticated signature.
- Backup uses the SQLite online backup API; restore checks integrity and schema
  version, requires confirmation and keeps a copy of the current database.
- SQLite files are NOT encrypted; use operating-system disk encryption.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

SCHEMA_VERSION = 1
MIGRATIONS: dict = {}          # {from_version: fn(connection)} applied in order up to SCHEMA_VERSION
ACTOR = "人工填寫（未經身分驗證）"
CASE_FIELDS = ("case_id", "customer_code", "rfq_no", "rfq_date", "status", "source_file")
LINE_FIELDS = ("line_no", "product", "drawing_version", "quantity", "unit", "currency", "required_date",
               "source_sheet", "source_row")

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE cases (
  case_id TEXT PRIMARY KEY, customer_code TEXT NOT NULL, rfq_no TEXT, rfq_date TEXT, status TEXT NOT NULL,
  source_file TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE case_lines (
  case_id TEXT NOT NULL REFERENCES cases(case_id), line_no TEXT NOT NULL, product TEXT NOT NULL,
  drawing_version TEXT, quantity TEXT, unit TEXT, currency TEXT, required_date TEXT, source_sheet TEXT,
  source_row INTEGER, PRIMARY KEY (case_id, line_no));
CREATE TABLE quote_versions (
  case_id TEXT NOT NULL, line_no TEXT NOT NULL, version INTEGER NOT NULL, unit_price TEXT, quantity TEXT,
  cost_snapshot TEXT NOT NULL, created_at TEXT NOT NULL, reason TEXT NOT NULL,
  PRIMARY KEY (case_id, line_no, version), FOREIGN KEY (case_id, line_no) REFERENCES case_lines(case_id, line_no));
CREATE TABLE outcomes (
  case_id TEXT NOT NULL, line_no TEXT NOT NULL, version INTEGER NOT NULL, revision INTEGER NOT NULL,
  data TEXT NOT NULL, recorded_at TEXT NOT NULL, reason TEXT NOT NULL,
  PRIMARY KEY (case_id, line_no, version, revision),
  FOREIGN KEY (case_id, line_no, version) REFERENCES quote_versions(case_id, line_no, version));
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, entity TEXT NOT NULL, action TEXT NOT NULL,
  old_value TEXT, new_value TEXT, reason TEXT NOT NULL, actor TEXT NOT NULL, source TEXT, at TEXT NOT NULL);
"""


class StoreError(Exception):
    """Any refused or failed store operation (user-facing message)."""


class StorageDisabled(StoreError):
    pass


class IncompatibleSchema(StoreError):
    pass


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def encode(value):
    """JSON-safe encoding that keeps Decimal exact and None as null."""
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        raise StoreError("不保存原始檔案內容")
    return value


def decode(value):
    if isinstance(value, dict):
        if set(value) == {"__decimal__"}:
            return Decimal(value["__decimal__"])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def _text(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        raise StoreError("不保存原始檔案內容")
    return str(value)


def _insert_event(con, case_id, entity, action, old, new, reason, source):
    con.execute("INSERT INTO events (case_id, entity, action, old_value, new_value, reason, actor, source, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (case_id, entity, action, old, new, reason, ACTOR, source, _now()))


def check_integrity(path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"ok": False, "schema_version": None, "message": "檔案不存在"}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = con.execute("PRAGMA integrity_check").fetchone()[0]
            row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "schema_version": None, "message": f"不是可用的案件資料庫：{exc}"}
    version = int(row[0]) if row else None
    ok = result == "ok" and version is not None
    return {"ok": ok, "schema_version": version, "message": "完整" if ok else f"完整性檢查失敗：{result}"}


class CaseStore:
    def __init__(self, path, enabled: bool = False):
        if path is None or not str(path).strip():
            raise StoreError("請明確指定本機資料庫路徑")
        text = str(path)
        if text.startswith(("\\\\", "//")):
            raise StoreError("資料庫不可放在網路共享磁碟，請指定本機路徑")
        self.path = Path(text)
        self.enabled = bool(enabled)

    # ---------- connection ----------
    def _require(self):
        if not self.enabled:
            raise StorageDisabled("本機保存尚未啟用，不會寫入任何資料")

    def _connect(self):
        con = sqlite3.connect(self.path, isolation_level=None)
        con.execute("PRAGMA journal_mode=DELETE")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _write(self, fn):
        """Run fn(con) in one transaction; roll back and raise StoreError on any failure."""
        self._require()
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            result = fn(con)
            con.execute("COMMIT")
            return result
        except StoreError:
            con.execute("ROLLBACK")
            raise
        except sqlite3.Error as exc:
            con.execute("ROLLBACK")
            raise StoreError(f"寫入失敗，已復原（rollback）：{exc}") from exc
        finally:
            con.close()

    def _read(self, sql, params=()):
        con = self._connect()
        try:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(sql, params).fetchall()]
        finally:
            con.close()

    # ---------- schema ----------
    def initialize(self):
        self._require()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = self._connect()
        try:
            has_meta = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
            if not has_meta:
                con.execute("BEGIN IMMEDIATE")
                for stmt in filter(str.strip, SCHEMA.split(";")):
                    con.execute(stmt)
                con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                con.execute("COMMIT")
                return
            version = int(con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise IncompatibleSchema(f"資料庫版本 {version} 比程式支援的 {SCHEMA_VERSION} 新，請更新程式後再開啟")
            if version < SCHEMA_VERSION:
                con.execute("BEGIN IMMEDIATE")
                try:
                    while version < SCHEMA_VERSION:
                        if version not in MIGRATIONS:
                            raise IncompatibleSchema(f"沒有從版本 {version} 升級的程序")
                        MIGRATIONS[version](con)
                        version += 1
                    con.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(version),))
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        finally:
            con.close()

    def schema_version(self) -> int:
        return int(self._read("SELECT value FROM meta WHERE key='schema_version'")[0]["value"])

    # ---------- cases ----------
    def add_case(self, case: dict, lines: list[dict], reason: str, source: str | None = None):
        self._require()
        for rec, allowed, label in ((case, CASE_FIELDS, "案件"), *((l, LINE_FIELDS, "明細") for l in lines)):
            extra = set(rec) - set(allowed)
            if extra:
                raise StoreError(f"{label}含有不允許保存的欄位：{'、'.join(sorted(extra))}")
            for v in rec.values():
                _text(v)
        if not case.get("case_id") or not case.get("customer_code") or not case.get("status"):
            raise StoreError("案件編號、客戶代碼、狀態都必須填寫")
        if not lines or any(not l.get("line_no") or not l.get("product") for l in lines):
            raise StoreError("至少需要一行明細，且每行都要有行號與成品")
        if not str(reason or "").strip():
            raise StoreError("請填寫原因")

        def run(con):
            now = _now()
            con.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        tuple(_text(case.get(k)) for k in CASE_FIELDS) + (now, now))
            for l in lines:
                con.execute("INSERT INTO case_lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (_text(case["case_id"]), *(_text(l.get(k)) for k in LINE_FIELDS)))
            _insert_event(con, case["case_id"], "case", "新增案件", None, case["status"], reason, source)
        self._write(run)

    def get_case(self, case_id: str) -> dict | None:
        rows = self._read("SELECT * FROM cases WHERE case_id=?", (case_id,))
        if not rows:
            return None
        case = rows[0]
        case["lines"] = self._read("SELECT * FROM case_lines WHERE case_id=? ORDER BY rowid", (case_id,))
        for l in case["lines"]:
            l["quantity"] = None if l["quantity"] is None else Decimal(l["quantity"])
        return case

    def list_cases(self) -> list[dict]:
        return self._read("SELECT case_id, customer_code, rfq_no, status, updated_at FROM cases ORDER BY case_id")

    def update_case_status(self, case_id: str, new_status: str, reason: str, source: str | None = None,
                           validator=None):
        if not str(reason or "").strip():
            raise StoreError("變更狀態必須填寫原因")

        def run(con):
            row = con.execute("SELECT status FROM cases WHERE case_id=?", (case_id,)).fetchone()
            if row is None:
                raise StoreError(f"找不到案件 {case_id}")
            if validator:
                validator(row[0], new_status)
            con.execute("UPDATE cases SET status=?, updated_at=? WHERE case_id=?", (new_status, _now(), case_id))
            _insert_event(con, case_id, "case", "變更狀態", row[0], new_status, reason, source)
        self._write(run)

    # ---------- quote versions ----------
    def add_quote_version(self, case_id, line_no, unit_price, quantity, cost_snapshot: dict, reason: str,
                          source: str | None = None) -> int:
        if not str(reason or "").strip():
            raise StoreError("新增報價版本必須填寫原因")
        snapshot = json.dumps(encode(cost_snapshot), ensure_ascii=False)

        def run(con):
            if not con.execute("SELECT 1 FROM case_lines WHERE case_id=? AND line_no=?", (case_id, line_no)).fetchone():
                raise StoreError(f"找不到案件 {case_id} 的明細 {line_no}")
            version = con.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM quote_versions WHERE case_id=? AND line_no=?",
                                  (case_id, line_no)).fetchone()[0]
            con.execute("INSERT INTO quote_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (case_id, line_no, version, _text(unit_price), _text(quantity), snapshot, _now(), reason))
            _insert_event(con, case_id, "quote_version", "新增報價版本", None, f"{line_no}#v{version}", reason, source)
            return version
        return self._write(run)

    def quote_versions(self, case_id, line_no) -> list[dict]:
        rows = self._read("SELECT * FROM quote_versions WHERE case_id=? AND line_no=? ORDER BY version", (case_id, line_no))
        for r in rows:
            r["unit_price"] = None if r["unit_price"] is None else Decimal(r["unit_price"])
            r["quantity"] = None if r["quantity"] is None else Decimal(r["quantity"])
            r["cost_snapshot"] = decode(json.loads(r["cost_snapshot"]))
        return rows

    def events(self, case_id) -> list[dict]:
        return self._read("SELECT * FROM events WHERE case_id=? ORDER BY id", (case_id,))

    # ---------- backup / restore ----------
    def backup(self, dest) -> Path:
        dest = Path(dest)
        if dest.exists():
            raise StoreError(f"備份檔 {dest.name} 已存在，不會覆蓋")
        dest.parent.mkdir(parents=True, exist_ok=True)
        src, dst = self._connect(), sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return dest

    def restore(self, backup_path, confirm: bool = False) -> Path:
        self._require()
        info = check_integrity(backup_path)
        if not info["ok"]:
            raise StoreError(f"備份檔無法使用：{info['message']}")
        if info["schema_version"] != SCHEMA_VERSION:
            raise StoreError(f"備份檔版本 {info['schema_version']} 與程式版本 {SCHEMA_VERSION} 不同")
        if not confirm:
            raise StoreError("還原會覆蓋目前的資料庫，請明確確認後再執行")
        stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
        previous = self.backup(self.path.with_name(f"{self.path.stem}.before_restore_{stamp}{self.path.suffix}"))
        src, dst = sqlite3.connect(f"file:{Path(backup_path)}?mode=ro", uri=True), self._connect()
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return previous

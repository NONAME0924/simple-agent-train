"""實驗室公帳：獨立的 finance.db（請款單、照片、事件、只增不改的流水帳）與依身分分層的唯讀查詢。
金額一律是新台幣整數。使用者資料仍在 memory.db，這裡只存使用者 ID 與當時的帳號名稱快照。"""
import datetime
import json
import re
import sqlite3
from pathlib import Path
from app.config import APP_DIR, FINANCE_DB_PATH
from app.logging_setup import log

MAX_AMOUNT = 100_000_000
MAX_IMAGES = 4
STATUSES = ("pending", "approved", "rejected", "withdrawn")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class FinanceError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_AMOUNT:
        raise FinanceError(f"金額須為 1～{MAX_AMOUNT:,} 的整數（新台幣）。")
    return value


def _text(value, label, limit):
    value = (value or "").strip()
    if not value or len(value) > limit:
        raise FinanceError(f"{label}須為 1～{limit} 個字。")
    return value


def real_name_map(user_ids):
    """{使用者 ID: 實名}；沒填實名（舊帳號）的不在表內。實名放在使用者表，這裡只在顯示時查。"""
    ids = sorted({i for i in user_ids if i})
    if not ids:
        return {}
    from app.storage.users import user_manager
    with user_manager._conn() as conn:
        rows = conn.execute(f"SELECT id, real_name FROM users WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {row["id"]: row["real_name"] for row in rows if row["real_name"]}


def label_for(names, user_id, username):
    real = names.get(user_id)
    return f"{real}（{username}）" if real else username


SCHEMA = """
CREATE TABLE IF NOT EXISTS expense_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, user_name TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    original_amount INTEGER CHECK(original_amount IS NULL OR original_amount > 0),
    adjust_note TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','withdrawn')),
    reject_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, decided_at TEXT, decided_by TEXT, decided_by_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_req_user ON expense_requests(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_req_status ON expense_requests(status, id DESC);
CREATE INDEX IF NOT EXISTS idx_req_created ON expense_requests(created_at);
CREATE TABLE IF NOT EXISTS expense_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES expense_requests(id),
    image_id TEXT NOT NULL, name TEXT NOT NULL, position INTEGER NOT NULL,
    UNIQUE(request_id, image_id)
);
CREATE TABLE IF NOT EXISTS request_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES expense_requests(id),
    kind TEXT NOT NULL CHECK(kind IN ('submitted','amount_adjusted','approved','rejected','withdrawn','corrected','revoked')),
    actor_id TEXT NOT NULL, actor_name TEXT NOT NULL,
    amount_before INTEGER, amount_after INTEGER,
    note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_request ON request_events(request_id, id);
CREATE TABLE IF NOT EXISTS fund_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('add','subtract','expense')),
    amount INTEGER NOT NULL,
    note TEXT NOT NULL,
    request_id INTEGER REFERENCES expense_requests(id),
    actor_id TEXT NOT NULL, actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON fund_ledger(created_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class FinanceManager:
    def __init__(self, path=None, legacy_path=None):
        self.path = Path(path or FINANCE_DB_PATH)
        self.legacy_path = Path(legacy_path or APP_DIR / "memory.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._upgrade_events_table(conn)
            for table in ("fund_ledger", "request_events"):  # 帳務紀錄只能新增
                for action in ("UPDATE", "DELETE"):
                    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT, '帳務紀錄只能新增，不能修改或刪除'); END""")
        self._migrate_legacy()

    @staticmethod
    def _upgrade_events_table(conn):
        """舊資料庫的事件表不認得 corrected／revoked；SQLite 不能改 CHECK，只能重建一次（資料原樣搬過去）。"""
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='request_events'").fetchone()[0]
        if "'revoked'" in sql:
            return
        try:
            conn.executescript("""BEGIN;
                CREATE TABLE request_events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL REFERENCES expense_requests(id),
                    kind TEXT NOT NULL CHECK(kind IN ('submitted','amount_adjusted','approved','rejected','withdrawn','corrected','revoked')),
                    actor_id TEXT NOT NULL, actor_name TEXT NOT NULL,
                    amount_before INTEGER, amount_after INTEGER,
                    note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
                INSERT INTO request_events_new (id, request_id, kind, actor_id, actor_name, amount_before, amount_after, note, created_at)
                    SELECT id, request_id, kind, actor_id, actor_name, amount_before, amount_after, note, created_at FROM request_events;
                DROP TABLE request_events;
                ALTER TABLE request_events_new RENAME TO request_events;
                CREATE INDEX IF NOT EXISTS idx_event_request ON request_events(request_id, id);
                COMMIT;""")
        except sqlite3.Error:
            conn.rollback()
            raise
        log("finance.events_table_upgraded")

    def _conn(self, readonly=False):
        if readonly:  # 查詢一律走唯讀連線，物理上改不了帳。
            conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            conn.execute("PRAGMA query_only=ON")
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ---------- 從舊版（放在 memory.db）一次性搬移 ----------
    def _migrate_legacy(self):
        if not self.legacy_path.is_file():
            return
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM meta WHERE key='migrated_from_memory_db'").fetchone():
                return
        try:
            old = sqlite3.connect(self.legacy_path.resolve().as_uri() + "?mode=ro", uri=True)
            old.row_factory = sqlite3.Row
            tables = {row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.Error:
            return
        with old, self._conn() as conn:
            if "expense_requests" in tables:
                names = {row[0]: row[1] for row in old.execute("SELECT id, username FROM users")} if "users" in tables else {}
                has_orig = "original_amount" in {row[1] for row in old.execute("PRAGMA table_info(expense_requests)")}
                for r in old.execute("SELECT * FROM expense_requests ORDER BY id"):
                    original = r["original_amount"] if has_orig else None
                    conn.execute("""INSERT INTO expense_requests (id, user_id, user_name, amount, original_amount, adjust_note, description,
                        status, reject_reason, created_at, decided_at, decided_by, decided_by_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r["id"], r["user_id"], names.get(r["user_id"], "（已移除）"), r["amount"], original,
                         r["adjust_note"] if has_orig else "", r["description"], r["status"], r["reject_reason"], r["created_at"],
                         r["decided_at"], r["decided_by"], r["decided_by_name"]))
                    for position, image in enumerate(json.loads(r["images"] or "[]")):
                        conn.execute("INSERT OR IGNORE INTO expense_images (request_id, image_id, name, position) VALUES (?,?,?,?)",
                                     (r["id"], image["id"], image.get("name", "image.png"), position))
                    first = original if original else r["amount"]
                    self._event(conn, r["id"], "submitted", r["user_id"], names.get(r["user_id"], "（已移除）"), None, first, "", r["created_at"])
                    if original:
                        self._event(conn, r["id"], "amount_adjusted", r["decided_by"] or "", r["decided_by_name"] or "會計", original, r["amount"], r["adjust_note"] if has_orig else "", r["created_at"])
                    if r["status"] in ("approved", "rejected", "withdrawn"):
                        self._event(conn, r["id"], r["status"], r["decided_by"] or r["user_id"], r["decided_by_name"] or names.get(r["user_id"], ""),
                                    None, r["amount"] if r["status"] == "approved" else None, r["reject_reason"], r["decided_at"] or r["created_at"])
            if "fund_ledger" in tables:
                for r in old.execute("SELECT * FROM fund_ledger ORDER BY id"):
                    conn.execute("INSERT INTO fund_ledger (id, kind, amount, note, request_id, actor_id, actor_name, created_at) VALUES (?,?,?,?,?,?,?,?)",
                                 (r["id"], r["kind"], r["amount"], r["note"], r["request_id"], r["actor_id"], r["actor_name"], r["created_at"]))
            conn.execute("INSERT INTO meta VALUES ('migrated_from_memory_db', ?)", (_now(),))
        log("finance.migrated", source=str(self.legacy_path))

    @staticmethod
    def _event(conn, request_id, kind, actor_id, actor_name, before, after, note, when=None):
        conn.execute("""INSERT INTO request_events (request_id, kind, actor_id, actor_name, amount_before, amount_after, note, created_at)
            VALUES (?,?,?,?,?,?,?,?)""", (request_id, kind, actor_id, actor_name, before, after, note, when or _now()))

    # ---------- 讀取輔助 ----------
    @staticmethod
    def _attach(conn, rows):
        items = [dict(row, requester=row["user_name"], images=[]) for row in rows]
        if items:
            by_id = {item["id"]: item for item in items}
            marks = ",".join("?" * len(by_id))
            for image in conn.execute(f"SELECT request_id, image_id, name FROM expense_images WHERE request_id IN ({marks}) ORDER BY position", tuple(by_id)):
                by_id[image["request_id"]]["images"].append({"id": image["image_id"], "name": image["name"]})
        return items

    def get_request(self, request_id):
        with self._conn(readonly=True) as conn:
            rows = conn.execute("SELECT * FROM expense_requests WHERE id=?", (request_id,)).fetchall()
            items = self._attach(conn, rows)
        return items[0] if items else None

    def list_requests(self, user_id=None, status=None, limit=200):
        with self._conn(readonly=True) as conn:
            rows = conn.execute("""SELECT * FROM expense_requests WHERE (? IS NULL OR user_id=?) AND (? IS NULL OR status=?)
                ORDER BY id DESC LIMIT ?""", (user_id, user_id, status, status, limit)).fetchall()
            return self._attach(conn, rows)

    def pending_count(self):
        with self._conn(readonly=True) as conn:
            return conn.execute("SELECT COUNT(*) FROM expense_requests WHERE status='pending'").fetchone()[0]

    def count_for_user(self, user_id):
        with self._conn(readonly=True) as conn:
            return conn.execute("SELECT COUNT(*) FROM expense_requests WHERE user_id=?", (user_id,)).fetchone()[0]

    # ---------- 請款 ----------
    def create_request(self, user, amount, description, images):
        amount, description = _amount(amount), _text(description, "事由", 500)
        if not 1 <= len(images) <= MAX_IMAGES:
            raise FinanceError(f"請附上 1～{MAX_IMAGES} 張收據或單據照片。")
        now = _now()
        with self._conn() as conn:
            request_id = conn.execute("INSERT INTO expense_requests (user_id, user_name, amount, description, created_at) VALUES (?,?,?,?,?)",
                                      (user["id"], user["username"], amount, description, now)).lastrowid
            for position, image in enumerate(images):
                conn.execute("INSERT INTO expense_images (request_id, image_id, name, position) VALUES (?,?,?,?)",
                             (request_id, image["id"], image["name"], position))
            self._event(conn, request_id, "submitted", user["id"], user["username"], None, amount, "", now)
        log("finance.request_created", request_id=request_id, user_id=user["id"], amount=amount)
        return self.get_request(request_id)

    def withdraw(self, request_id, user):
        with self._conn() as conn:
            changed = conn.execute("UPDATE expense_requests SET status='withdrawn', decided_at=? WHERE id=? AND user_id=? AND status='pending'",
                                   (_now(), request_id, user["id"])).rowcount
            if not changed:
                raise FinanceError("只能撤回自己仍在審核中的請款。", 409)
            self._event(conn, request_id, "withdrawn", user["id"], user["username"], None, None, "")
        log("finance.request_withdrawn", request_id=request_id, user_id=user["id"])
        return self.get_request(request_id)

    # ---------- 審核（會計） ----------
    def adjust_request_amount(self, request_id, amount, note, actor):
        """會計調整審核中請款的金額；原申請金額與調整原因保留給申請人看。"""
        amount, note = _amount(amount), _text(note, "調整原因", 300)
        with self._conn() as conn:
            row = conn.execute("SELECT amount, original_amount, status FROM expense_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise FinanceError("找不到這筆請款。", 404)
            if row["status"] != "pending":
                raise FinanceError("只能調整審核中的請款金額。", 409)
            original = row["original_amount"] if row["original_amount"] is not None else row["amount"]
            conn.execute("UPDATE expense_requests SET amount=?, original_amount=?, adjust_note=? WHERE id=?",
                         (amount, None if amount == original else original, "" if amount == original else note, request_id))
            self._event(conn, request_id, "amount_adjusted", actor["id"], actor["username"], row["amount"], amount, note)
        log("finance.request_amount_adjusted", request_id=request_id, actor=actor["id"], before=row["amount"], after=amount)
        return self.get_request(request_id)

    def approve(self, request_id, actor, force=False):
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")  # 先鎖住，避免兩位會計同時核准、餘額算錯。
            row = conn.execute("SELECT * FROM expense_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise FinanceError("找不到這筆請款。", 404)
            if row["status"] != "pending":
                raise FinanceError("這筆請款已處理過。", 409)
            remaining = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger").fetchone()[0]
            if row["amount"] > remaining and not force:
                raise FinanceError(f"請款 {row['amount']:,} 元大於目前剩餘 {remaining:,} 元；仍要通過會讓餘額變成負數。",
                                   409, needs_confirm=True, remaining=remaining)
            now = _now()
            conn.execute("INSERT INTO fund_ledger (kind, amount, note, request_id, actor_id, actor_name, created_at) VALUES ('expense',?,?,?,?,?,?)",
                         (-row["amount"], row["description"], request_id, actor["id"], actor["username"], now))
            conn.execute("UPDATE expense_requests SET status='approved', decided_at=?, decided_by=?, decided_by_name=? WHERE id=?",
                         (now, actor["id"], actor["username"], request_id))
            self._event(conn, request_id, "approved", actor["id"], actor["username"], None, row["amount"], "", now)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        log("finance.approved", request_id=request_id, actor=actor["id"], amount=row["amount"], forced=force)
        return self.get_request(request_id)

    # ---------- 通過後的更正（只有會計） ----------
    # 帳本只增不改：更正與撤銷都是再寫一筆 'expense' 流水（金額為差額／退回的錢，正數代表錢回到剩餘），
    # 所以「已核銷＝−expense 合計」「剩餘」自動正確，歷史紀錄完整保留。
    def correct_approved(self, request_id, amount, note, actor, force=False):
        amount, note = _amount(amount), _text(note, "更正原因", 300)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM expense_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise FinanceError("找不到這筆請款。", 404)
            if row["status"] != "approved":
                raise FinanceError("只有已通過的請款可以更正金額。", 409)
            delta = amount - row["amount"]
            if delta == 0:
                raise FinanceError("新金額與目前相同，不需要更正。")
            remaining = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger").fetchone()[0]
            if delta > remaining and not force:
                raise FinanceError(f"多扣 {delta:,} 元會超過目前剩餘 {remaining:,} 元；仍要更正會讓餘額變成負數。",
                                   409, needs_confirm=True, remaining=remaining)
            now = _now()
            original = row["original_amount"] if row["original_amount"] is not None else row["amount"]
            conn.execute("INSERT INTO fund_ledger (kind, amount, note, request_id, actor_id, actor_name, created_at) VALUES ('expense',?,?,?,?,?,?)",
                         (-delta, f"更正 #{request_id}（{row['amount']:,}→{amount:,}）：{note}", request_id, actor["id"], actor["username"], now))
            conn.execute("UPDATE expense_requests SET amount=?, original_amount=?, adjust_note=? WHERE id=?",
                         (amount, None if amount == original else original, "" if amount == original else note, request_id))
            self._event(conn, request_id, "corrected", actor["id"], actor["username"], row["amount"], amount, note, now)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        log("finance.corrected", request_id=request_id, actor=actor["id"], before=row["amount"], after=amount, forced=force)
        return self.get_request(request_id)

    def revoke_approval(self, request_id, actor, note):
        """撤銷通過：錢退回剩餘，請款回到審核中，會計可再調整、通過或退回。"""
        note = _text(note, "撤銷原因", 300)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM expense_requests WHERE id=?", (request_id,)).fetchone()
            if not row:
                raise FinanceError("找不到這筆請款。", 404)
            if row["status"] != "approved":
                raise FinanceError("只有已通過的請款可以撤銷通過。", 409)
            now = _now()
            conn.execute("INSERT INTO fund_ledger (kind, amount, note, request_id, actor_id, actor_name, created_at) VALUES ('expense',?,?,?,?,?,?)",
                         (row["amount"], f"撤銷通過 #{request_id}：{note}", request_id, actor["id"], actor["username"], now))
            conn.execute("UPDATE expense_requests SET status='pending', decided_at=NULL, decided_by=NULL, decided_by_name=NULL WHERE id=?", (request_id,))
            self._event(conn, request_id, "revoked", actor["id"], actor["username"], row["amount"], None, note, now)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        log("finance.revoked", request_id=request_id, actor=actor["id"], amount=row["amount"])
        return self.get_request(request_id)

    def reject(self, request_id, actor, reason):
        reason = _text(reason, "退回原因", 300)
        with self._conn() as conn:
            changed = conn.execute("""UPDATE expense_requests SET status='rejected', reject_reason=?, decided_at=?, decided_by=?, decided_by_name=?
                WHERE id=? AND status='pending'""", (reason, _now(), actor["id"], actor["username"], request_id)).rowcount
            if not changed:
                raise FinanceError("找不到審核中的這筆請款。", 409)
            self._event(conn, request_id, "rejected", actor["id"], actor["username"], None, None, reason)
        log("finance.rejected", request_id=request_id, actor=actor["id"])
        return self.get_request(request_id)

    # ---------- 經費 ----------
    def summary(self):
        """total＝累計撥入減手動減少；spent＝已通過的請款；remaining＝total－spent。"""
        with self._conn(readonly=True) as conn:
            total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger WHERE kind IN ('add','subtract')").fetchone()[0]
            spent = -conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger WHERE kind='expense'").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM expense_requests WHERE status='pending'").fetchone()[0]
        return {"total": total, "spent": spent, "remaining": total - spent, "pending": pending}

    def adjust(self, kind, amount, note, actor):
        if kind not in ("add", "subtract"):
            raise FinanceError("操作須為 add 或 subtract。")
        amount, note = _amount(amount), _text(note, "備註", 300)
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            remaining = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger").fetchone()[0]
            if kind == "subtract" and amount > remaining:
                raise FinanceError(f"減少 {amount:,} 元會超過目前剩餘 {remaining:,} 元。", 409)
            conn.execute("INSERT INTO fund_ledger (kind, amount, note, actor_id, actor_name, created_at) VALUES (?,?,?,?,?,?)",
                         (kind, amount if kind == "add" else -amount, note, actor["id"], actor["username"], _now()))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        log("finance.adjusted", kind=kind, amount=amount, actor=actor["id"])
        return self.summary()

    def ledger(self, limit=100, before=None):
        with self._conn(readonly=True) as conn:
            rows = conn.execute("SELECT * FROM fund_ledger WHERE (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?", (before, before, limit)).fetchall()
        return [dict(row) for row in rows]

    def export_data(self, since=None, until=None, limit=100_000):
        """匯出用：總覽、含「當時餘額」的流水帳、請款明細；日期依建立時間，until 含當天。申請人顯示實名（帳號）。"""
        until_exclusive = _next_day(until)
        with self._conn(readonly=True) as conn:
            balance, ledger = 0, []
            for row in conn.execute("SELECT * FROM fund_ledger ORDER BY id"):
                balance += row["amount"]
                if (since is None or row["created_at"] >= since) and (until_exclusive is None or row["created_at"] < until_exclusive):
                    ledger.append({**dict(row), "balance": balance})
            requests = [dict(row) for row in conn.execute("""SELECT r.*, (SELECT COUNT(*) FROM expense_images i WHERE i.request_id=r.id) AS images FROM expense_requests r
                WHERE (? IS NULL OR r.created_at>=?) AND (? IS NULL OR r.created_at<?) ORDER BY r.id LIMIT ?""", (since, since, until_exclusive, until_exclusive, limit))]
        names = real_name_map([r["user_id"] for r in requests])
        for r in requests:
            r["requester"] = label_for(names, r["user_id"], r["user_name"])
        return {"summary": self.summary(), "ledger": ledger[:limit], "requests": requests, "since": since, "until": until}


finance_manager = FinanceManager()


# ======================================================================
# Agent 用的唯讀查詢：身分由系統帶入，並在查詢當下再向使用者表確認一次（雙重驗證）。
# ======================================================================
class Principal:
    def __init__(self, user_id, username, is_treasurer, is_admin):
        self.id, self.username, self.is_treasurer, self.is_admin = user_id, username, is_treasurer, is_admin

    @property
    def can_view_all(self):
        return self.is_treasurer or self.is_admin


def resolve_principal(asker):
    """第一層：asker 是系統依登入狀態綁定的提問者（模型不能指定）。
    第二層：這裡不信任 asker 內的角色，改從使用者表即時取得；帳號停用或不再是會計都立刻生效。"""
    from app.storage.users import user_manager
    if not asker or not asker.get("id"):
        raise PermissionError("需要登入身分才能查詢財務資料。")
    live = user_manager.get(asker["id"])
    if not live or live["status"] != "active":
        raise PermissionError("帳號已停用或不存在，無法查詢財務資料。")
    return Principal(live["id"], live["username"], bool(live["is_treasurer"]), live["role"] == "admin")


def _money(value):
    return f"{'-' if value < 0 else ''}${abs(value):,}"


def _date(value, label):
    value = (value or "").strip()
    if value:
        try:
            if not DATE_RE.fullmatch(value):
                raise ValueError
            datetime.date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{label} 須為真實存在的 YYYY-MM-DD 日期。") from None
    return value or None


def _like(keyword):
    keyword = (keyword or "").strip()[:50]
    if not keyword:
        return None
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _next_day(value):
    return (datetime.date.fromisoformat(value) + datetime.timedelta(days=1)).isoformat() if value else None


def _line(item, who=None):
    extra = f"（原申請 {_money(item['original_amount'])}）" if item["original_amount"] else ""
    reason = f"｜退回原因：{item['reject_reason']}" if item["status"] == "rejected" else ""
    description = item["description"].replace("\n", " ")[:80]
    return (f"#{item['id']} {item['created_at'][:10]} {who or item['user_name']} {_money(item['amount'])}{extra} "
            f"{ {'pending': '審核中', 'approved': '已通過', 'rejected': '已退回', 'withdrawn': '已撤回'}[item['status']] }"
            f"｜事由「{description}」｜照片 {item['images']} 張{reason}")


class FinanceReader:
    """每個方法第一個參數都是 Principal；個人查詢一律在 SQL 加上 user_id 條件，全域查詢要求會計或管理員。"""

    def __init__(self, manager):
        self.manager = manager

    @staticmethod
    def _need_all(p):
        if not p.can_view_all:
            raise PermissionError("只有會計與管理員可以查詢全實驗室的財務資料；你可以查詢自己的請款。")

    def _requests(self, conn, scope_user, status, since, until, keyword, limit):
        clauses, params = [], []
        if scope_user is not None:
            ids = [scope_user] if isinstance(scope_user, str) else list(scope_user)
            clauses.append(f"r.user_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        for sql, value in (("r.status=?", status or None), ("r.created_at>=?", since),
                           ("r.created_at<?", _next_day(until)), ("r.description LIKE ? ESCAPE '\\'", _like(keyword))):
            if value is not None:
                clauses.append(sql)
                params.append(value)
        where = " AND ".join(clauses) or "1=1"  # 條件文字都是固定字串，使用者輸入只走參數。
        rows = conn.execute(f"""SELECT r.*, (SELECT COUNT(*) FROM expense_images i WHERE i.request_id=r.id) AS images
            FROM expense_requests r WHERE {where} ORDER BY r.id DESC LIMIT ?""", (*params, max(1, min(int(limit), 50)))).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM expense_requests r WHERE {where}", tuple(params)).fetchone()[0]
        return rows, total

    def requests_text(self, p, *, mine, user="", status="", since="", until="", keyword="", limit=20):
        if status and status not in STATUSES:
            raise ValueError("status 須為 pending、approved、rejected、withdrawn 之一。")
        since, until = _date(since, "since"), _date(until, "until")
        if mine:
            scope = p.id
        else:
            self._need_all(p)
            scope = None
            if user:  # 可用帳號或實名查；帳號已刪除的人用請款當時留下的帳號名稱找。
                from app.storage.users import user_manager
                name = user.strip()
                with user_manager._conn() as conn:
                    ids = {r[0] for r in conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE OR real_name=?", (name, name))}
                with self.manager._conn(readonly=True) as conn:
                    ids |= {r[0] for r in conn.execute("SELECT DISTINCT user_id FROM expense_requests WHERE user_name=? COLLATE NOCASE", (name,))}
                if not ids:
                    return f"找不到 {user} 的請款紀錄。"
                scope = sorted(ids)
        with self.manager._conn(readonly=True) as conn:
            rows, total = self._requests(conn, scope, status, since, until, keyword, limit)
        if not rows:
            return "沒有符合條件的請款。"
        names = {} if mine else real_name_map([row["user_id"] for row in rows])
        return f"共 {total} 筆，顯示最新 {len(rows)} 筆：\n" + "\n".join(
            _line(dict(row), None if mine else label_for(names, row["user_id"], row["user_name"])) for row in rows)

    def my_summary(self, p):
        with self.manager._conn(readonly=True) as conn:
            by_status = conn.execute("SELECT status, COUNT(*) n, COALESCE(SUM(amount),0) s FROM expense_requests WHERE user_id=? GROUP BY status", (p.id,)).fetchall()
            by_month = conn.execute("""SELECT substr(created_at,1,7) m, COUNT(*) n, COALESCE(SUM(amount),0) s FROM expense_requests
                WHERE user_id=? AND status='approved' GROUP BY m ORDER BY m DESC LIMIT 12""", (p.id,)).fetchall()
        if not by_status:
            return "你還沒有送出過請款。"
        names = {"pending": "審核中", "approved": "已通過", "rejected": "已退回", "withdrawn": "已撤回"}
        lines = [f"{names[r['status']]}：{r['n']} 筆，合計 {_money(r['s'])}" for r in by_status]
        if by_month:
            lines.append("已通過的每月合計：" + "；".join(f"{r['m']} {_money(r['s'])}（{r['n']} 筆）" for r in by_month))
        return "你的請款合計\n" + "\n".join(lines)

    def detail(self, p, request_id):
        item = self.manager.get_request(request_id)
        if not item or (item["user_id"] != p.id and not p.can_view_all):
            return "找不到這筆請款，或你沒有權限查看。"  # 兩種情況回同一句，不洩漏他人請款是否存在。
        with self.manager._conn(readonly=True) as conn:
            events = conn.execute("SELECT * FROM request_events WHERE request_id=? ORDER BY id", (request_id,)).fetchall()
        names = {"submitted": "送出", "amount_adjusted": "會計調整金額", "approved": "通過並扣款", "rejected": "退回", "withdrawn": "申請人撤回",
                 "corrected": "會計更正已通過金額", "revoked": "會計撤銷通過"}
        trail = []
        for e in events:
            money = f"（{_money(e['amount_before'])}→{_money(e['amount_after'])}）" if e["kind"] in ("amount_adjusted", "corrected") else ""
            note = f"：{e['note']}" if e["note"] else ""
            trail.append(f"{e['created_at']} {names[e['kind']]}{money} {e['actor_name']}{note}")
        who = label_for(real_name_map([item["user_id"]]), item["user_id"], item["user_name"]) if p.can_view_all else None
        head = _line({**item, "images": len(item["images"])}, who)
        return head + "\n處理紀錄：\n" + "\n".join(trail)

    def fund(self, p):
        self._need_all(p)
        s = self.manager.summary()
        return f"總金額 {_money(s['total'])}｜已核銷 {_money(s['spent'])}｜目前剩餘 {_money(s['remaining'])}｜待審 {s['pending']} 筆"

    def ledger(self, p, kind="", since="", until="", limit=30):
        self._need_all(p)
        if kind and kind not in ("add", "subtract", "expense"):
            raise ValueError("kind 須為 add、subtract、expense。")
        since, until = _date(since, "since"), _date(until, "until")
        until_exclusive = _next_day(until)
        with self.manager._conn(readonly=True) as conn:
            rows = conn.execute("""SELECT * FROM fund_ledger WHERE (? IS NULL OR kind=?) AND (? IS NULL OR created_at>=?) AND (? IS NULL OR created_at<?)
                ORDER BY id DESC LIMIT ?""", (kind or None, kind or None, since, since, until_exclusive, until_exclusive, max(1, min(int(limit), 50)))).fetchall()
        names = {"add": "加錢", "subtract": "減錢", "expense": "請款核銷"}
        def name(r):
            return "核銷更正／撤銷" if r["kind"] == "expense" and r["amount"] > 0 else names[r["kind"]]
        return "\n".join(f"{r['created_at']} {name(r)} {'+' if r['amount'] > 0 else '-'}{abs(r['amount']):,}｜{r['note'][:60]}（{r['actor_name']}）"
                         for r in rows) or "沒有符合條件的流水帳。"

    def spending(self, p, group_by="user", since="", until=""):
        self._need_all(p)
        if group_by not in ("user", "month"):
            raise ValueError("group_by 須為 user 或 month。")
        since, until = _date(since, "since"), _date(until, "until")
        until_exclusive = _next_day(until)
        key = "user_id" if group_by == "user" else "substr(created_at,1,7)"
        with self.manager._conn(readonly=True) as conn:
            rows = conn.execute(f"""SELECT {key} k, MAX(user_name) u, COUNT(*) n, SUM(amount) s FROM expense_requests WHERE status='approved'
                AND (? IS NULL OR created_at>=?) AND (? IS NULL OR created_at<?) GROUP BY k ORDER BY s DESC LIMIT 50""",
                (since, since, until_exclusive, until_exclusive)).fetchall()
        names = real_name_map([r["k"] for r in rows]) if group_by == "user" else {}
        return ("已通過請款彙總（依" + ("申請人" if group_by == "user" else "月份") + "）：\n"
                + "\n".join(f"{label_for(names, r['k'], r['u']) if group_by == 'user' else r['k']}：{_money(r['s'])}（{r['n']} 筆）" for r in rows)) if rows else "沒有已通過的請款。"


finance_reader = FinanceReader(finance_manager)

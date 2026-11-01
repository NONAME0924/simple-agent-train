"""實驗室公帳：請款單、審核與只增不改的流水帳。金額一律是新台幣整數。"""
import datetime
import json
import sqlite3
from app.logging_setup import log
from app.storage.memory import memory_manager

MAX_AMOUNT = 100_000_000
MAX_IMAGES = 4


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


def _request(row):
    item = dict(row)
    item["images"] = json.loads(item["images"])
    return item


class FinanceManager:
    def _conn(self):
        return memory_manager._get_connection()

    # ---------- 請款 ----------
    def create_request(self, user, amount, description, images):
        amount, description = _amount(amount), _text(description, "事由", 500)
        if not 1 <= len(images) <= MAX_IMAGES:
            raise FinanceError(f"請附上 1～{MAX_IMAGES} 張收據或單據照片。")
        with self._conn() as conn:
            cursor = conn.execute("INSERT INTO expense_requests (user_id, amount, description, images, created_at) VALUES (?,?,?,?,?)",
                                  (user["id"], amount, description, json.dumps(images, ensure_ascii=False), _now()))
            request_id = cursor.lastrowid
        log("finance.request_created", request_id=request_id, user_id=user["id"], amount=amount)
        return self.get_request(request_id)

    _SELECT = """SELECT r.*, u.username AS requester FROM expense_requests r LEFT JOIN users u ON u.id = r.user_id"""

    def get_request(self, request_id):
        with self._conn() as conn:
            row = conn.execute(f"{self._SELECT} WHERE r.id=?", (request_id,)).fetchone()
        return _request(row) if row else None

    def list_requests(self, user_id=None, status=None, limit=200):
        with self._conn() as conn:
            rows = conn.execute(f"""{self._SELECT} WHERE (? IS NULL OR r.user_id=?) AND (? IS NULL OR r.status=?)
                ORDER BY r.id DESC LIMIT ?""", (user_id, user_id, status, status, limit)).fetchall()
        return [_request(row) for row in rows]

    def pending_count(self):
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM expense_requests WHERE status='pending'").fetchone()[0]

    def withdraw(self, request_id, user_id):
        with self._conn() as conn:
            changed = conn.execute("UPDATE expense_requests SET status='withdrawn', decided_at=? WHERE id=? AND user_id=? AND status='pending'",
                                   (_now(), request_id, user_id)).rowcount
        if not changed:
            raise FinanceError("只能撤回自己仍在審核中的請款。", 409)
        log("finance.request_withdrawn", request_id=request_id, user_id=user_id)
        return self.get_request(request_id)

    # ---------- 審核（會計） ----------
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
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        log("finance.approved", request_id=request_id, actor=actor["id"], amount=row["amount"], forced=force)
        return self.get_request(request_id)

    def reject(self, request_id, actor, reason):
        reason = _text(reason, "退回原因", 300)
        with self._conn() as conn:
            changed = conn.execute("""UPDATE expense_requests SET status='rejected', reject_reason=?, decided_at=?, decided_by=?, decided_by_name=?
                WHERE id=? AND status='pending'""", (reason, _now(), actor["id"], actor["username"], request_id)).rowcount
        if not changed:
            raise FinanceError("找不到審核中的這筆請款。", 409)
        log("finance.rejected", request_id=request_id, actor=actor["id"])
        return self.get_request(request_id)

    # ---------- 經費 ----------
    def summary(self):
        """total＝累計撥入減手動減少；spent＝已通過的請款；remaining＝total－spent。"""
        with self._conn() as conn:
            total = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger WHERE kind IN ('add','subtract')").fetchone()[0]
            spent = -conn.execute("SELECT COALESCE(SUM(amount),0) FROM fund_ledger WHERE kind='expense'").fetchone()[0]
        return {"total": total, "spent": spent, "remaining": total - spent, "pending": self.pending_count()}

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
        with self._conn() as conn:
            rows = conn.execute("""SELECT * FROM fund_ledger WHERE (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?""",
                                (before, before, limit)).fetchall()
        return [dict(row) for row in rows]


finance_manager = FinanceManager()

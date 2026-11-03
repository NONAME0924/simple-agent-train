"""站內通知：一個通用的 notify(通知誰, 誰通知, 通知啥)。哪個事件要通知誰由呼叫的地方決定，這裡不寫死。
通知存在 memory.db（和使用者同一個資料庫，帳號刪除時一併刪除），保留 90 天。"""
import datetime
from app.logging_setup import log

KEEP_DAYS = 90
ROLES = {
    "role:admin": "role='admin'",
    "role:treasurer": "is_treasurer=1",
    "role:equipment": "is_equipment_manager=1",
    "all": "1=1",
}


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class NotificationManager:
    def __init__(self, memory):
        self.memory = memory
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                sender_id TEXT NOT NULL DEFAULT 'system', sender_name TEXT NOT NULL DEFAULT '系統',
                title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', link TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, read_at TEXT)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, id DESC)")

    def _conn(self):
        return self.memory._get_connection()

    def recipients(self, to):
        """to：使用者 ID、ID 清單、"role:admin"／"role:treasurer"／"role:equipment"、"all"，也可混在清單裡。
        身分在發送當下才查，所以新指派的會計之後自然會收到；停用或待核准的帳號不會收到。"""
        targets = [to] if isinstance(to, str) else list(to or [])
        ids = set()
        with self._conn() as conn:
            for target in targets:
                if target in ROLES:
                    rows = conn.execute(f"SELECT id FROM users WHERE status='active' AND {ROLES[target]}").fetchall()
                elif isinstance(target, str) and target.startswith("role:"):
                    raise ValueError(f"未知的通知對象：{target}")
                else:
                    rows = conn.execute("SELECT id FROM users WHERE status='active' AND id=?", (target,)).fetchall()
                ids.update(row[0] for row in rows)
        return ids

    def notify(self, to, sender, title, body="", link="", include_sender=False):
        """通知誰（to）、誰通知（sender：使用者 dict、使用者 ID 或 "system"）、通知啥（title／body／link）。
        預設不通知發送者自己（例如會計自己送請款，不必通知自己）。回傳實際送出的人數。
        通知失敗只記 log、不往外丟錯，避免影響核准、請款等主要動作。"""
        try:
            title = (title or "").strip()[:120]
            if not title:
                raise ValueError("通知需要標題。")
            if isinstance(sender, dict):
                sender_id, sender_name = sender["id"], sender.get("real_name") or sender["username"]
            elif sender and sender != "system":
                from app.storage.users import user_manager
                row = user_manager.get(sender) or {}
                sender_id, sender_name = sender, row.get("real_name") or row.get("username") or "（已移除）"
            else:
                sender_id, sender_name = "system", "系統"
            ids = self.recipients(to)
            if not include_sender:
                ids.discard(sender_id)
            now = _now()
            with self._conn() as conn:
                conn.executemany("""INSERT INTO notifications (user_id, sender_id, sender_name, title, body, link, created_at)
                    VALUES (?,?,?,?,?,?,?)""", [(uid, sender_id, sender_name, title, (body or "")[:1000], (link or "")[:200], now) for uid in sorted(ids)])
                cutoff = (datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("DELETE FROM notifications WHERE created_at < ?", (cutoff,))
            log("notify.sent", to=str(to)[:80], sender=sender_id, count=len(ids), title=title)
            return len(ids)
        except ValueError:
            raise
        except Exception:
            log("notify.failed", level=40, exc_info=True, title=title)
            return 0

    def list(self, user_id, limit=50):
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
            unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (user_id,)).fetchone()[0]
        return {"notifications": [dict(row) for row in rows], "unread": unread}

    def unread(self, user_id):
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL", (user_id,)).fetchone()[0]

    def mark_read(self, user_id, notification_id=None):
        with self._conn() as conn:  # 一律加上 user_id 條件：只能標自己的通知
            conn.execute("UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL AND (? IS NULL OR id=?)",
                         (_now(), user_id, notification_id, notification_id))


from app.storage.memory import memory_manager  # noqa: E402

notification_manager = NotificationManager(memory_manager)
notify = notification_manager.notify

"""帳號、登入狀態與管理員操作；資料與對話放在同一個 SQLite。"""
import datetime
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
import uuid
from app.config import ADMIN_PASSWORD, ADMIN_USERNAME, AUTH_SESSION_DAYS
from app.logging_setup import log

USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,32}")
MIN_PASSWORD, MAX_PASSWORD = 8, 128
ROLES = ("admin", "user")
STATUSES = ("pending", "active", "disabled")
_SCRYPT = (2 ** 14, 8, 1)


class AuthError(Exception):
    """帶 HTTP 狀態碼的帳號錯誤，由 API 轉成回應。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def hash_password(password):
    n, r, p = _SCRYPT
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return scheme == "scrypt" and hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def check_username(username):
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise AuthError("帳號須為 3～32 個英數字、底線、點或連字號。")
    return username


def check_password(password):
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
        raise AuthError(f"密碼須為 {MIN_PASSWORD}～{MAX_PASSWORD} 個字元。")
    return password


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public(row):
    """不含密碼雜湊的使用者資料。"""
    item = {k: row[k] for k in ("id", "username", "role", "status", "created_at", "last_login_at")}
    item["is_treasurer"] = bool(row["is_treasurer"])
    return item


class Throttle:
    """同一組帳號＋來源連續失敗太多次就暫時拒絕；只存在記憶體。"""

    def __init__(self, limit, window):
        self.limit, self.window, self.hits, self.lock = limit, window, {}, threading.Lock()

    def blocked(self, key):
        with self.lock:
            hits = [t for t in self.hits.get(key, []) if time.monotonic() - t < self.window]
            self.hits[key] = hits
            return len(hits) >= self.limit

    def add(self, key):
        with self.lock:
            self.hits.setdefault(key, []).append(time.monotonic())

    def clear(self, key):
        with self.lock:
            self.hits.pop(key, None)


login_throttle = Throttle(5, 300)
register_throttle = Throttle(5, 3600)


class UserManager:
    def __init__(self, memory):
        self.memory = memory

    def _conn(self):
        return self.memory._get_connection()

    # ---------- 建立與查詢 ----------
    def create_user(self, username, password, role="user", status="pending"):
        username, password = check_username(username), check_password(password)
        if role not in ROLES or status not in STATUSES:
            raise AuthError("角色或狀態無效。")
        user_id = f"u_{uuid.uuid4().hex[:12]}"
        try:
            with self._conn() as conn:
                conn.execute("INSERT INTO users (id, username, password_hash, role, status, created_at) VALUES (?,?,?,?,?,?)",
                             (user_id, username, hash_password(password), role, status, _now()))
        except sqlite3.IntegrityError:
            raise AuthError("這個帳號名稱已被使用。", 409)
        log("auth.user_created", user_id=user_id, username=username, role=role, status=status)
        return self.get(user_id)

    def get(self, user_id):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def find(self, username):
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        return dict(row) if row else None

    def list_users(self):
        with self._conn() as conn:
            rows = conn.execute("""SELECT u.*,
                (SELECT COUNT(*) FROM chat_sessions s WHERE s.owner_id=u.id) AS session_count,
                (SELECT COUNT(*) FROM projects p WHERE p.owner_id=u.id) AS project_count
                FROM users u ORDER BY CASE u.status WHEN 'pending' THEN 0 ELSE 1 END, u.created_at""").fetchall()
        return [{**public(r), "session_count": r["session_count"], "project_count": r["project_count"]} for r in rows]

    def active_admins(self, excluding=None):
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='active' AND id IS NOT ?",
                                (excluding,)).fetchone()[0]

    # ---------- 登入 ----------
    def authenticate(self, username, password, source=""):
        key = f"{(username or '').lower()}|{source}"
        if login_throttle.blocked(key):
            raise AuthError("嘗試次數過多，請 5 分鐘後再試。", 429)
        user = self.find(username or "") if isinstance(password, str) else None
        # 帳號不存在也做一次雜湊，避免從耗時差異猜出帳號是否存在。
        ok = verify_password(password, user["password_hash"] if user else hash_password("x"))
        if not user or not ok:
            login_throttle.add(key)
            log("auth.login_failed", username=username, source=source, level=30)
            raise AuthError("帳號或密碼錯誤。", 401)
        if user["status"] == "pending":
            raise AuthError("帳號正在等待管理員核准。", 403)
        if user["status"] == "disabled":
            raise AuthError("帳號已停用，請聯絡管理員。", 403)
        login_throttle.clear(key)
        with self._conn() as conn:
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (_now(), user["id"]))
        log("auth.login", user_id=user["id"], username=user["username"], source=source)
        return user

    def new_token(self, user_id):
        token = secrets.token_urlsafe(32)
        expires = (datetime.datetime.now() + datetime.timedelta(days=AUTH_SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (_now(),))
            conn.execute("INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                         (_hash_token(token), user_id, _now(), expires))
        return token

    def user_for_token(self, token):
        if not token:
            return None
        with self._conn() as conn:
            row = conn.execute("""SELECT u.* FROM auth_tokens t JOIN users u ON u.id=t.user_id
                WHERE t.token_hash=? AND t.expires_at>=? AND u.status='active'""", (_hash_token(token), _now())).fetchone()
        return dict(row) if row else None

    def revoke_token(self, token):
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token_hash=?", (_hash_token(token or ""),))

    def revoke_user_tokens(self, user_id, keep_token=None):
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_tokens WHERE user_id=? AND token_hash IS NOT ?",
                         (user_id, _hash_token(keep_token) if keep_token else None))

    # ---------- 管理 ----------
    def _require(self, user_id):
        user = self.get(user_id)
        if not user:
            raise AuthError("找不到這個帳號。", 404)
        return user

    def _keep_one_admin(self, user, what):
        if user["role"] == "admin" and user["status"] == "active" and not self.active_admins(excluding=user["id"]):
            raise AuthError(f"至少要保留一位可用的管理員，無法{what}。", 409)

    def set_status(self, user_id, status, actor_id):
        user = self._require(user_id)
        if status not in STATUSES:
            raise AuthError("狀態無效。")
        if status != "active":
            if user_id == actor_id:
                raise AuthError("不能停用自己的帳號。", 409)
            self._keep_one_admin(user, "停用")
        with self._conn() as conn:
            conn.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))
        if status != "active":
            self.revoke_user_tokens(user_id)
        log("auth.status_changed", user_id=user_id, status=status, actor=actor_id)
        return self.get(user_id)

    def set_role(self, user_id, role, actor_id):
        user = self._require(user_id)
        if role not in ROLES:
            raise AuthError("角色無效。")
        if role != "admin":
            if user_id == actor_id:
                raise AuthError("不能降低自己的權限。", 409)
            self._keep_one_admin(user, "降級")
        with self._conn() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        log("auth.role_changed", user_id=user_id, role=role, actor=actor_id)
        return self.get(user_id)

    def set_treasurer(self, user_id, value, actor_id):
        user = self._require(user_id)
        if value and user["status"] != "active":
            raise AuthError("只能指派使用中的帳號擔任會計。", 409)
        with self._conn() as conn:
            conn.execute("UPDATE users SET is_treasurer=? WHERE id=?", (1 if value else 0, user_id))
        log("auth.treasurer_changed", user_id=user_id, value=bool(value), actor=actor_id)
        return self.get(user_id)

    def set_password(self, user_id, password, keep_token=None):
        password = check_password(password)
        self._require(user_id)
        with self._conn() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
        self.revoke_user_tokens(user_id, keep_token)
        log("auth.password_changed", user_id=user_id)

    def delete_user(self, user_id, actor_id):
        user = self._require(user_id)
        if user_id == actor_id:
            raise AuthError("不能刪除自己的帳號。", 409)
        self._keep_one_admin(user, "刪除")
        with self._conn() as conn:
            from app.storage.finance import finance_manager  # 請款在獨立的 finance.db
            owned = conn.execute("SELECT (SELECT COUNT(*) FROM chat_sessions WHERE owner_id=?)+(SELECT COUNT(*) FROM projects WHERE owner_id=?)",
                                 (user_id, user_id)).fetchone()[0] + finance_manager.count_for_user(user_id)
            if owned:
                raise AuthError("這個帳號仍有對話、專案或請款紀錄；請改用「停用」，資料會保留。", 409)
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        log("auth.user_deleted", user_id=user_id, username=user["username"], actor=actor_id)

    # ---------- 啟動時確保有管理員 ----------
    def bootstrap(self):
        """回傳 (管理員帳號, 隨機密碼或 None)；只有自動產生密碼時才需要顯示。"""
        generated = None
        if not self.active_admins():
            name, password = ADMIN_USERNAME, ADMIN_PASSWORD
            existing = self.find(name) if name else None
            if existing:  # 指定的帳號已存在：升為管理員並啟用，密碼不覆蓋。
                with self._conn() as conn:
                    conn.execute("UPDATE users SET role='admin', status='active' WHERE id=?", (existing["id"],))
            else:
                if not (name and password):
                    name, password = "admin", secrets.token_urlsafe(12)
                    generated = password
                if self.find(name):
                    name = f"admin_{secrets.token_hex(3)}"
                self.create_user(name, password, "admin", "active")
        with self._conn() as conn:
            admin = conn.execute("SELECT id, username FROM users WHERE role='admin' AND status='active' ORDER BY created_at LIMIT 1").fetchone()
            # 升級前建立的對話與專案沒有擁有者，歸給最早的管理員。
            for table in ("chat_sessions", "projects"):
                conn.execute(f"UPDATE {table} SET owner_id=? WHERE owner_id IS NULL", (admin["id"],))
        return admin["username"], generated


from app.storage.memory import memory_manager  # noqa: E402  (放最後避免循環匯入)

user_manager = UserManager(memory_manager)

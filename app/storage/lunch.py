"""午餐輪盤：大家一起填的餐廳清單（名稱、類型、價位、備註），放在獨立的 lunch.db。
類型與價位都是自由填寫，畫面上的下拉選單直接用清單裡出現過的值，所以新增就是填一個新的字。"""
import datetime
import re
import sqlite3
from pathlib import Path
from app.config import LUNCH_DB_PATH
from app.logging_setup import log

LIMITS = {"name": ("店名", 60), "category": ("類型", 20), "price": ("價位", 20), "note": ("備註", 200)}


class LunchError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean(data, partial=False):
    out = {}
    for key, (label, limit) in LIMITS.items():
        if key not in data:
            if not partial and key == "name":
                raise LunchError("請填寫店名。")
            continue
        value = re.sub(r"[\x00-\x1f\x7f]", " ", str(data[key] or ""))
        value = " ".join(value.split())
        if len(value) > limit:
            raise LunchError(f"{label}最多 {limit} 個字。")
        if key == "name" and not value:
            raise LunchError("請填寫店名。")
        out[key] = value
    return out


class LunchManager:
    def __init__(self, path=None):
        self.path = Path(path or LUNCH_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category TEXT NOT NULL DEFAULT '', price TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL, created_by_name TEXT NOT NULL, created_at TEXT NOT NULL)""")

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def list(self, category="", price=""):
        with self._conn() as conn:
            rows = conn.execute("""SELECT * FROM restaurants WHERE (?='' OR category=?) AND (?='' OR price=?)
                ORDER BY category, name COLLATE NOCASE""", (category, category, price, price)).fetchall()
            categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM restaurants WHERE category<>'' ORDER BY category")]
            prices = [r[0] for r in conn.execute("SELECT DISTINCT price FROM restaurants WHERE price<>'' ORDER BY length(price), price")]
        return {"restaurants": [dict(r) for r in rows], "categories": categories, "prices": prices}

    def _get(self, conn, restaurant_id):
        row = conn.execute("SELECT * FROM restaurants WHERE id=?", (restaurant_id,)).fetchone()
        if not row:
            raise LunchError("找不到這家店。", 404)
        return row

    @staticmethod
    def _may_edit(row, user):
        if row["created_by"] != user["id"] and user["role"] != "admin":
            raise LunchError("只有新增這家店的人或管理員可以修改或刪除。", 403)

    def create(self, data, user):
        fields = clean(data)
        try:
            with self._conn() as conn:
                new_id = conn.execute("""INSERT INTO restaurants (name, category, price, note, created_by, created_by_name, created_at)
                    VALUES (?,?,?,?,?,?,?)""", (fields["name"], fields.get("category", ""), fields.get("price", ""), fields.get("note", ""),
                                                user["id"], user.get("real_name") or user["username"], _now())).lastrowid
                row = self._get(conn, new_id)
        except sqlite3.IntegrityError:
            raise LunchError("這家店已經在清單裡了。", 409)
        log("lunch.created", restaurant_id=new_id, user_id=user["id"])
        return dict(row)

    def update(self, restaurant_id, data, user):
        fields = clean(data, partial=True)
        if not fields:
            raise LunchError("沒有任何變更。")
        try:
            with self._conn() as conn:
                self._may_edit(self._get(conn, restaurant_id), user)
                conn.execute(f"UPDATE restaurants SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), restaurant_id))
                row = self._get(conn, restaurant_id)
        except sqlite3.IntegrityError:
            raise LunchError("已經有同名的店了。", 409)
        return dict(row)

    def delete(self, restaurant_id, user):
        with self._conn() as conn:
            row = self._get(conn, restaurant_id)
            self._may_edit(row, user)
            conn.execute("DELETE FROM restaurants WHERE id=?", (restaurant_id,))
        log("lunch.deleted", restaurant_id=restaurant_id, name=row["name"], user_id=user["id"])


lunch_manager = LunchManager()

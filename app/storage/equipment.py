"""實驗室設備清單：獨立的 equipment.db。設備表是「目前狀態」，每次新增、修改、改狀態都另外記一筆異動（只增不改），
所以每台機器的完整經歷都查得到。設備不刪除，不用了就改成「報廢」。"""
import datetime
import json
import re
import sqlite3
from pathlib import Path
from app.config import EQUIPMENT_DB_PATH
from app.logging_setup import log

STATUSES = {"normal": "正常", "repair": "維修中", "retired": "報廢"}
# 欄位：名稱、長度上限。順序也是畫面與匯出的順序。
FIELDS = {"name": ("名稱", 100), "model": ("型號", 100), "asset_no": ("財產編號", 60), "serial_no": ("序號", 100),
          "location": ("存放位置", 100), "custodian": ("保管人", 60), "purchased_on": ("購入日期", 10),
          "price": ("金額", None), "note": ("備註", 1000)}
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', asset_no TEXT NOT NULL DEFAULT '', serial_no TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '', custodian TEXT NOT NULL DEFAULT '', purchased_on TEXT NOT NULL DEFAULT '',
    price INTEGER, note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_equipment_asset ON equipment(asset_no) WHERE asset_no <> '';
CREATE TABLE IF NOT EXISTS equipment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    kind TEXT NOT NULL,
    changes TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL, actor_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_equipment_events ON equipment_events(equipment_id, id);
"""


class EquipmentError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _actor_name(actor):
    return actor.get("real_name") or actor["username"]


def clean(data, partial=False):
    """檢查並整理欄位；partial=True 時只處理有給的欄位（修改用）。"""
    out = {}
    for key, (label, limit) in FIELDS.items():
        if key not in data:
            if not partial and key == "name":
                raise EquipmentError("請填寫設備名稱。")
            continue
        value = data[key]
        if key == "price":
            if value in (None, ""):
                out[key] = None
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000_000:
                raise EquipmentError("金額須為 0 以上的整數（新台幣），不知道可留空。")
            out[key] = value
            continue
        value = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or "")).strip()
        if key != "note":
            value = " ".join(value.split())
        if len(value) > limit:
            raise EquipmentError(f"{label}最多 {limit} 個字。")
        if key == "name" and not value:
            raise EquipmentError("請填寫設備名稱。")
        if key == "purchased_on" and value:
            try:
                if not DATE_RE.fullmatch(value):
                    raise ValueError
                datetime.date.fromisoformat(value)
            except ValueError:
                raise EquipmentError("購入日期須為 YYYY-MM-DD。") from None
        out[key] = value
    return out


class EquipmentManager:
    def __init__(self, path=None):
        self.path = Path(path or EQUIPMENT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            for action in ("UPDATE", "DELETE"):  # 異動紀錄只能新增
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS equipment_events_no_{action.lower()} BEFORE {action} ON equipment_events
                    BEGIN SELECT RAISE(ABORT, '設備異動紀錄只能新增，不能修改或刪除'); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS equipment_no_delete BEFORE DELETE ON equipment
                BEGIN SELECT RAISE(ABORT, '設備不能刪除，請改成報廢'); END""")

    def _conn(self, readonly=False):
        if readonly:
            conn = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            conn.execute("PRAGMA query_only=ON")
        else:
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _event(conn, equipment_id, kind, changes, note, actor, when):
        conn.execute("""INSERT INTO equipment_events (equipment_id, kind, changes, note, actor_id, actor_name, created_at)
            VALUES (?,?,?,?,?,?,?)""", (equipment_id, kind, json.dumps(changes, ensure_ascii=False), note, actor["id"], _actor_name(actor), when))

    @staticmethod
    def _note(note):
        note = (note or "").strip()
        if len(note) > 300:
            raise EquipmentError("原因最多 300 個字。")
        return note

    # ---------- 讀取 ----------
    def list(self, keyword="", status="", location=""):
        if status and status not in STATUSES:
            raise EquipmentError("狀態須為 normal、repair、retired。")
        like = None
        if keyword.strip():
            like = "%" + keyword.strip()[:50].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        with self._conn(readonly=True) as conn:
            rows = conn.execute("""SELECT * FROM equipment WHERE (? IS NULL OR status=?) AND (? IS NULL OR location=?)
                AND (? IS NULL OR name LIKE ? ESCAPE '\\' OR model LIKE ? ESCAPE '\\' OR asset_no LIKE ? ESCAPE '\\'
                     OR serial_no LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\' OR custodian LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')
                ORDER BY CASE status WHEN 'normal' THEN 0 WHEN 'repair' THEN 1 ELSE 2 END, name COLLATE NOCASE""",
                (status or None, status or None, location or None, location or None, like, *([like] * 7))).fetchall()
        return [dict(row) for row in rows]

    def get(self, equipment_id):
        with self._conn(readonly=True) as conn:
            row = conn.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
            if not row:
                return None
            events = [dict(e, changes=json.loads(e["changes"])) for e in conn.execute(
                "SELECT * FROM equipment_events WHERE equipment_id=? ORDER BY id DESC", (equipment_id,))]
        return {**dict(row), "events": events}

    def locations(self):
        with self._conn(readonly=True) as conn:
            return [r[0] for r in conn.execute("SELECT DISTINCT location FROM equipment WHERE location<>'' ORDER BY location")]

    # ---------- 寫入（設備管理） ----------
    def create(self, data, actor):
        fields = clean(data)
        now = _now()
        try:
            with self._conn() as conn:
                cols = list(fields)
                equipment_id = conn.execute(f"INSERT INTO equipment ({','.join(cols)}, created_at, updated_at) VALUES ({','.join('?' * len(cols))},?,?)",
                                            (*fields.values(), now, now)).lastrowid
                self._event(conn, equipment_id, "created", {k: [None, v] for k, v in fields.items() if v not in ("", None)}, "", actor, now)
        except sqlite3.IntegrityError:
            raise EquipmentError("這個財產編號已經登記過了。", 409)
        log("equipment.created", equipment_id=equipment_id, actor=actor["id"])
        return self.get(equipment_id)

    def update(self, equipment_id, data, actor, note=""):
        fields, note = clean(data, partial=True), self._note(note)
        now = _now()
        try:
            with self._conn() as conn:
                row = conn.execute("SELECT * FROM equipment WHERE id=?", (equipment_id,)).fetchone()
                if not row:
                    raise EquipmentError("找不到這台設備。", 404)
                changes = {k: [row[k], v] for k, v in fields.items() if row[k] != v}
                if not changes:
                    raise EquipmentError("沒有任何變更。")
                conn.execute(f"UPDATE equipment SET {', '.join(f'{k}=?' for k in changes)}, updated_at=? WHERE id=?",
                             (*(v[1] for v in changes.values()), now, equipment_id))
                self._event(conn, equipment_id, "updated", changes, note, actor, now)
        except sqlite3.IntegrityError:
            raise EquipmentError("這個財產編號已經登記過了。", 409)
        log("equipment.updated", equipment_id=equipment_id, actor=actor["id"], fields=list(changes))
        return self.get(equipment_id)

    def set_status(self, equipment_id, status, actor, note=""):
        if status not in STATUSES:
            raise EquipmentError("狀態須為 normal、repair、retired。")
        note = self._note(note)
        if status != "normal" and not note:
            raise EquipmentError("送修或報廢請填原因。")
        now = _now()
        with self._conn() as conn:
            row = conn.execute("SELECT status FROM equipment WHERE id=?", (equipment_id,)).fetchone()
            if not row:
                raise EquipmentError("找不到這台設備。", 404)
            if row["status"] == status:
                raise EquipmentError(f"目前已經是「{STATUSES[status]}」。")
            conn.execute("UPDATE equipment SET status=?, updated_at=? WHERE id=?", (status, now, equipment_id))
            self._event(conn, equipment_id, "status", {"status": [row["status"], status]}, note, actor, now)
        log("equipment.status", equipment_id=equipment_id, actor=actor["id"], status=status)
        return self.get(equipment_id)

    # ---------- Agent 用的唯讀文字 ----------
    def summary_text(self, keyword="", status="", location="", limit=30):
        items = self.list(keyword, status, location)
        if not items:
            return "沒有符合條件的設備。"
        lines = []
        for e in items[:max(1, min(int(limit), 50))]:
            parts = [f"#{e['id']} {e['name']}", e["model"], f"財產編號 {e['asset_no']}" if e["asset_no"] else "",
                     f"位置：{e['location']}" if e["location"] else "", f"保管人：{e['custodian']}" if e["custodian"] else "",
                     STATUSES[e["status"]], f"備註：{e['note'][:60]}" if e["note"] else ""]
            lines.append("｜".join(p for p in parts if p))
        return f"共 {len(items)} 台，顯示 {len(lines)} 台：\n" + "\n".join(lines)


equipment_manager = EquipmentManager()

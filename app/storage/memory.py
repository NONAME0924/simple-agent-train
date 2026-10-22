import sqlite3
import json
import datetime
import re
from app.logging_setup import log
from typing import List, Dict, Optional
from app.config import APP_DIR

DB_PATH = str(APP_DIR / "memory.db")


class MemoryManager:
    """
    SQLite 專案、對話與歷史檢索管理器。
    支援：
    projects: 對話的專案歸屬與 L2 專案記憶的範圍。
    1. chat_sessions: 左側邊欄多會話管理 (CRUD、標題自動命名、最後更新時間排序)。
    2. chat_messages: 右側聊天視窗還原 (單一會話歷史隔離)。
    3. search_memory: 同專案歷史對話關鍵字檢索。
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # 開啟外鍵約束支援 (級聯刪除)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        """初始化資料表與索引，移除舊版未使用的衍生索引。"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            project_columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
            if "memory_version" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN memory_version INTEGER NOT NULL DEFAULT 0")
            if "pinned_memory" not in project_columns:
                conn.execute("ALTER TABLE projects ADD COLUMN pinned_memory TEXT NOT NULL DEFAULT ''")
            # 1. 會話主表 (左側清單)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # 舊資料庫補上專案欄位，原本對話保留在一般對話。
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_sessions)")}
            if "project_id" not in columns:
                conn.execute("ALTER TABLE chat_sessions ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project ON chat_sessions(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON chat_sessions(updated_at DESC);")

            # 2. 訊息流水表 (右側視窗)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, created_at ASC);")
            message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)")}
            if "images" not in message_columns:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN images TEXT NOT NULL DEFAULT '[]'")
            conn.execute("""CREATE TABLE IF NOT EXISTS working_context (
                session_id TEXT PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
                model TEXT NOT NULL, messages TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS project_memory (
                project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                summary TEXT NOT NULL, source_cursor INTEGER NOT NULL, updated_at TEXT NOT NULL
            )""")

            # 移除舊版未使用的衍生索引；原始對話資料保留。
            conn.execute("DROP TRIGGER IF EXISTS trg_messages_ai")
            conn.execute("DROP TRIGGER IF EXISTS trg_messages_ad")
            try:
                conn.execute("DROP TABLE IF EXISTS fts_messages")
            except sqlite3.OperationalError:
                log("memory.legacy_fts_cleanup_failed", level=30, exc_info=True)

            conn.commit()

    # ==========================================
    # 會話管理 (Sessions CRUD)
    # ==========================================

    def list_projects(self) -> List[Dict]:
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY created_at DESC, id")]

    def get_project(self, project_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row) if row else None

    def save_project(self, project_id: str, name: str) -> Dict:
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("專案名稱須為 1～80 個字。")
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO projects (id, name) VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET name = excluded.name
            """, (project_id, name))
        log("project.saved", project_id=project_id, name=name)
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        """刪除分類，透過外鍵將對話改歸一般對話，保留所有訊息。"""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM working_context WHERE session_id IN (SELECT id FROM chat_sessions WHERE project_id=?)", (project_id,))
            deleted = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount > 0
        log("project.deleted", project_id=project_id, ok=deleted)
        return deleted

    def get_session(self, session_id: str) -> Optional[Dict]:
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT s.*, p.name AS project_name FROM chat_sessions s
                LEFT JOIN projects p ON p.id = s.project_id WHERE s.id = ?
            """, (session_id,)).fetchone()
            return dict(row) if row else None

    def move_session(self, session_id: str, project_id: Optional[str]) -> bool:
        with self._get_connection() as conn:
            old = conn.execute("SELECT project_id FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
            if old and old["project_id"] != project_id:
                conn.execute("DELETE FROM project_memory WHERE project_id IN (?, ?)", (old["project_id"], project_id))
                conn.execute("UPDATE projects SET memory_version=memory_version+1 WHERE id IN (?, ?)", (old["project_id"], project_id))
                conn.execute("DELETE FROM working_context WHERE session_id=?", (session_id,))
            moved = conn.execute("UPDATE chat_sessions SET project_id = ? WHERE id = ?", (project_id, session_id)).rowcount > 0
        log("session.moved", session_id=session_id, project_id=project_id, ok=moved)
        return moved

    def create_or_get_session(self, session_id: str, title: Optional[str] = None, project_id: Optional[str] = None) -> Dict:
        """建立或取得會話"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # 新建會話
            default_title = title.strip() if title and title.strip() else "新對話"
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO chat_sessions (id, title, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, default_title, project_id, now_str, now_str)
            )
            conn.commit()
            log("session.created", session_id=session_id, project_id=project_id, title=default_title)
            return {"id": session_id, "title": default_title, "project_id": project_id, "created_at": now_str, "updated_at": now_str}

    def list_sessions(self) -> List[Dict]:
        """取得所有會話清單（依最後活躍時間降序）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chat_sessions ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def get_session_messages(self, session_id: str) -> List[Dict]:
        """取得指定會話的所有純淨歷史訊息（供右側視窗載入）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, role, content, created_at, images FROM chat_messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            )
            return [{**dict(row), "images": json.loads(row["images"])} for row in cursor.fetchall()]

    def delete_session(self, session_id: str) -> bool:
        """刪除會話（CASCADE 自動清除相關訊息與工作上下文）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM project_memory WHERE project_id = (SELECT project_id FROM chat_sessions WHERE id = ?)", (session_id,))
            cursor.execute("UPDATE projects SET memory_version=memory_version+1 WHERE id = (SELECT project_id FROM chat_sessions WHERE id = ?)", (session_id,))
            cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            conn.commit()
            log("session.deleted", session_id=session_id, ok=cursor.rowcount > 0)
            return cursor.rowcount > 0

    def get_working_context(self, session_id, model):
        import json
        with self._get_connection() as conn:
            row = conn.execute("SELECT messages FROM working_context WHERE session_id = ? AND model = ?",
                               (session_id, model)).fetchone()
            return json.loads(row["messages"]) if row else None

    def save_working_context(self, session_id, model, messages):
        import json
        with self._get_connection() as conn:
            conn.execute("""INSERT INTO working_context VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET model=excluded.model,
                messages=excluded.messages, updated_at=excluded.updated_at""",
                (session_id, model, json.dumps(messages, ensure_ascii=False), datetime.datetime.now().isoformat()))

    def get_project_memory(self, project_id):
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM project_memory WHERE project_id = ?", (project_id,)).fetchone()
            return dict(row) if row else None

    def project_messages_after(self, project_id, cursor, limit=80):
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute("""SELECT m.* FROM chat_messages m
                JOIN chat_sessions s ON s.id=m.session_id
                WHERE s.project_id=? AND m.id>? ORDER BY m.id LIMIT ?""", (project_id, cursor, limit))]

    def save_project_memory(self, project_id, summary, cursor, version):
        with self._get_connection() as conn:
            changed = conn.execute("""INSERT INTO project_memory
                SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM projects WHERE id=? AND memory_version=?)
                ON CONFLICT(project_id) DO UPDATE SET summary=excluded.summary,
                source_cursor=excluded.source_cursor, updated_at=excluded.updated_at""",
                (project_id, summary, cursor, datetime.datetime.now().isoformat(), project_id, version))
            if changed.rowcount:
                conn.execute("UPDATE projects SET memory_version=memory_version+1 WHERE id=?", (project_id,))
            return changed.rowcount > 0

    def edit_project_memory(self, project_id, summary, pinned, version):
        """使用者修改與自動摘要共用版本鎖；清空時略過已存在的舊來源。"""
        with self._get_connection() as conn:
            changed = conn.execute("""UPDATE projects SET pinned_memory=?, memory_version=memory_version+1
                WHERE id=? AND memory_version=?""", (pinned, project_id, version))
            if not changed.rowcount:
                raise ValueError("記憶已變更，請重新載入後再儲存。")
            previous = conn.execute("SELECT source_cursor FROM project_memory WHERE project_id=?", (project_id,)).fetchone()
            latest = conn.execute("""SELECT COALESCE(MAX(m.id),0) FROM chat_messages m
                JOIN chat_sessions s ON s.id=m.session_id WHERE s.project_id=?""", (project_id,)).fetchone()[0]
            cursor = previous["source_cursor"] if previous and summary.strip() else latest
            conn.execute("""INSERT INTO project_memory VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET summary=excluded.summary,
                source_cursor=excluded.source_cursor, updated_at=excluded.updated_at""",
                (project_id, summary.strip(), cursor, datetime.datetime.now().isoformat()))
        log("memory.user_edited", project_id=project_id, summary=summary, pinned=pinned)

    def project_memory_sources(self, project_id, cursor, before=None):
        with self._get_connection() as conn:
            return [dict(row) for row in conn.execute("""SELECT m.id, m.session_id, s.title,
                m.role, substr(m.content,1,2000) AS content, m.created_at
                FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id
                WHERE s.project_id=? AND m.id<=? AND m.id<? ORDER BY m.id DESC LIMIT 30""",
                (project_id, cursor, before or cursor + 1))]

    # ==========================================
    # 問答存檔與 RAG 檢索
    # ==========================================

    def save_turn(self, session_id: str, user_message: str, assistant_message: str, images=(), assistant_images=()):
        """
        記錄一輪純淨問答：
        1. 寫入 chat_messages。
        2. 若為第一輪對話且標題為預設，自動以用戶前 25 字命名標題。
        3. 更新 chat_sessions 的 updated_at。
        """
        if not user_message.strip() and not assistant_message.strip():
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 確保 session 存在
            cursor.execute("SELECT title FROM chat_sessions WHERE id = ?", (session_id,))
            session_row = cursor.fetchone()

            if not session_row:
                # 自動截取首句為標題
                clean_title = re.sub(r"[\n\r]+", " ", user_message.strip())[:25] or "新對話"
                cursor.execute(
                    "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, clean_title, now_str, now_str)
                )
            else:
                # 若已有 session，且目前標題是預設的「新對話」，自動換成問題概要
                current_title = session_row["title"]
                if current_title in ("新對話", "New Chat") and user_message.strip():
                    new_title = re.sub(r"[\n\r]+", " ", user_message.strip())[:25]
                    cursor.execute("UPDATE chat_sessions SET title = ? WHERE id = ?", (new_title, session_id))

            # 寫入訊息
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, created_at, images) VALUES (?, 'user', ?, ?, ?)",
                (session_id, user_message, now_str, json.dumps(list(images)))
            )
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, content, created_at, images) VALUES (?, 'assistant', ?, ?, ?)",
                (session_id, assistant_message, now_str, json.dumps(list(assistant_images)))
            )

            # 更新 session 最後活躍時間
            cursor.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now_str, session_id))
            conn.commit()
        log("memory.turn_saved", session_id=session_id, user=user_message, assistant=assistant_message,
            images=list(images), assistant_images=list(assistant_images))

    def search_memory(self, keywords: str, limit: int = 3, session_id: Optional[str] = None) -> str:
        """
        搜尋歷史記憶；提供目前對話時，只搜尋同一專案內的對話。
        支援多關鍵字比對，命中關聯對話與當時所屬會話名稱。
        """
        if not keywords or not keywords.strip():
            return "請提供具體的記憶檢索關鍵字。"

        raw_terms = re.split(r"[\s,，、]+", keywords.strip())
        terms = [t for t in raw_terms if len(t) >= 1]
        if not terms:
            terms = [keywords.strip()]

        scope_sql, scope_params, scope_label = "", (), "歷史對話"
        if session_id is not None:
            session = self.get_session(session_id)
            if session is None:
                return "找不到目前對話，無法確認記憶搜尋範圍。"
            scope_sql, scope_params = ("WHERE s.project_id = ?", (session["project_id"],)) if session["project_id"] else ("WHERE s.id = ?", (session_id,))
            scope_label = f"專案「{session['project_name']}」" if session["project_id"] else "一般對話"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT m.id, m.session_id, s.title as session_title, m.role, m.content, m.created_at
                FROM chat_messages m
                LEFT JOIN chat_sessions s ON m.session_id = s.id
                {scope_sql}
                ORDER BY m.id DESC
            """, scope_params)
            all_rows = cursor.fetchall()

        if not all_rows:
            return f"{scope_label}中尚無任何對話紀錄。"

        # 計算評分
        scored = []
        for row in all_rows:
            score = 0
            matched_terms = []
            text_corpus = row["content"]
            for term in terms:
                if term in text_corpus:
                    score += 1
                    matched_terms.append(term)
            if score > 0:
                scored.append((score, row, matched_terms))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_results = scored[:limit]

        if not top_results:
            return f"在{scope_label}中未找到與「{keywords}」相關的紀錄。"

        output = [f"【{scope_label}的記憶檢索結果（關鍵字：{', '.join(terms)}）】：\n"]
        for i, (score, row, matched) in enumerate(top_results, 1):
            sess_name = row["session_title"] or row["session_id"]
            role_display = "用戶問" if row["role"] == "user" else "助理答"
            output.append(f"[{i}] 會話：{sess_name} (時間：{row['created_at']} | 命中：{', '.join(matched)})")
            output.append(f"    {role_display}：{row['content']}")
            output.append("-" * 35)

        return "\n".join(output)


# 單例記憶管理器
memory_manager = MemoryManager()

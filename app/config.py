import os
from pathlib import Path
from dotenv import load_dotenv

# 原始資料位置不跟隨程式碼搬移，避免產生第二份資料庫或工作區。
APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
WORKSPACE_DIR = str(APP_DIR / "workspace")
STATIC_DIR = APP_DIR / "app" / "web" / "static"

load_dotenv(APP_DIR / ".env", override=False, encoding="utf-8-sig")

# Ollama API 服務設定
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "").strip()
MODEL_READ_TIMEOUT = max(1.0, float(os.getenv("AGENT_MODEL_READ_TIMEOUT", "600")))
MAX_AUTONOMOUS_STEPS = max(1, int(os.getenv("AGENT_MAX_STEPS", "15")))

# 實際請求同步傳入 num_ctx；不把模型理論最大長度當成配置值。
CONTEXT_TOKENS = max(4096, int(os.getenv("AGENT_CONTEXT_TOKENS", "32768")))
OUTPUT_TOKENS = min(CONTEXT_TOKENS // 4, max(512, int(os.getenv("AGENT_OUTPUT_TOKENS", "4096"))))
COMPACT_RATIO = 0.8

# 伺服器配置
# 預設只開本機；0.0.0.0 會開放給同網路的所有裝置，請務必搭配帳號系統。
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# 帳號系統：首次啟動若沒有管理員，會用這組建立；兩者留空則產生隨機密碼並顯示一次。
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
AUTH_SESSION_DAYS = max(1, int(os.getenv("AUTH_SESSION_DAYS", "7")))
# 使用 HTTPS（例如反向代理）時設為 1，Cookie 才會加上 Secure。
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"}

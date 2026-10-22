from app.logging_setup import log
from app.tools.registry import ToolResult
import httpx
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin


def read_web_page(url: str, max_chars: int = 4000) -> str:
    """閱讀指定網頁，保留安裝指令區塊及連結網址；也支援純文字／Markdown。

    當遇到以下情況時調用此工具：
    1. 使用者提供了一個具體網址，要求深入閱讀、分析或總結該文章內容。
    2. 透過 google_search 找到關鍵網頁後，需要深入獲取該文章的完整內文或技術細節。

    Args:
        url: 目標網頁的完整 URL (包含 http:// 或 https://)
        max_chars: 讀取字數上限，預設 4000 字
    """
    if not url or not url.strip().startswith(("http://", "https://")):
        return ToolResult.failed(f"請提供以 http:// 或 https:// 開頭的有效網址，您輸入的是：{url}")

    clean_url = url.strip()
    max_chars = max(1000, min(max_chars, 20000))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(clean_url)
            if resp.status_code != 200:
                return ToolResult.failed(f"無法讀取網頁內容 (HTTP 狀態碼: {resp.status_code})")

            html = resp.text
            if "html" not in resp.headers.get("content-type", "").lower() and not html.lstrip().startswith(("<!DOCTYPE", "<html", "<HTML")):
                return f"【文字內容】\n網址：{resp.url}\n\n{html[:max_chars]}"
            soup = BeautifulSoup(html, "html.parser")

            # 剔除導航、頁腳、廣告、腳本等無效雜訊
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "svg"]):
                tag.decompose()

            title = soup.title.string.strip() if soup.title and soup.title.string else "無標題"

            # 擷取主體段落與標題
            blocks = []
            for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre"]):
                text = elem.get_text(separator="\n" if elem.name == "pre" else " ", strip=True)
                if text and len(text) > 5:
                    blocks.append(text)

            content = "\n\n".join(blocks)
            # 多重換行清理
            content = re.sub(r"\n{3,}", "\n\n", content)

            if not content.strip():
                # 若未找到 p/h 標籤，降級抓取全部文字
                content = soup.get_text(separator="\n", strip=True)

            truncated = content[:max_chars]
            char_count = len(truncated)
            links = {}
            for anchor in soup.find_all("a", href=True):
                href = urljoin(str(resp.url), anchor["href"])
                if href.startswith(("https://", "http://")) and not anchor["href"].startswith("#"):
                    links.setdefault(href, anchor.get_text(" ", strip=True)[:100])
            link_text = "\n".join(f"- {label or '連結'}：{href}" for href, label in list(links.items())[:60])[:6000]

            return (
                f"【網頁閱讀成功】\n"
                f"網址：{clean_url}\n"
                f"標題：{title}\n"
                f"內容摘要（前 {char_count} 字）：\n\n"
                f"{truncated}\n\n"
                f"頁面連結（含下載來源）：\n{link_text or '未找到連結'}\n\n"
                f"(若需特定部分請針對段落進一步分析)"
            )

    except httpx.ConnectTimeout:
        log("web.timeout", level=40, exc_info=True, url=url)
        return ToolResult.failed(f"連線至目標網頁逾時 ({clean_url})")
    except Exception as e:
        log("web.failed", level=40, exc_info=True, url=url)
        return ToolResult.failed(f"讀取網頁發生錯誤 ({clean_url}): {str(e)}")

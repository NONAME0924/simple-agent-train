from app.logging_setup import log
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from typing import List, Dict


def google_news_search(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """透過 Google News 即時檢索相關新聞與時事"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            tree = ET.fromstring(resp.read())
            items = tree.findall(".//item")
            for item in items[:max_results]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                source = item.find("source").text if item.find("source") is not None else "Google News"
                results.append({
                    "title": title,
                    "link": link,
                    "snippet": f"發布日期: {pub_date} | 來源: {source}",
                    "source": "Google News"
                })
    except Exception:
        log("search.provider_failed", level=40, exc_info=True, query=query)
        return None
    return results


def web_general_search(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """透過網頁檢索通用網頁資料與百科資訊"""
    results = []
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for r in soup.find_all("div", class_="result")[:max_results]:
                title_elem = r.find("a", class_="result__a")
                snippet_elem = r.find("a", class_="result__snippet")
                if not title_elem:
                    continue

                raw_link = title_elem.get("href", "")
                # 解析實際外部連結
                real_link = raw_link
                if "uddg=" in raw_link:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                    if "uddg" in qs and qs["uddg"]:
                        real_link = qs["uddg"][0]

                title = title_elem.get_text(strip=True)
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                results.append({
                    "title": title,
                    "link": real_link,
                    "snippet": snippet,
                    "source": "Web"
                })
    except Exception:
        log("search.provider_failed", level=40, exc_info=True, query=query)
        return None
    return results


def google_search(query: str) -> str:
    """使用 Google 與網路檢索查詢即時資料、最新現狀，或在對任何事實不確定時進行查證。

    當遇到以下情況時應積極調用此工具：
    1. 需要最新或即時資訊（時事、天氣、最新版本、近期動態等）。
    2. 對特定事實、數據、年份、規格或現況有任何不確定或需進一步核實時。
    切勿因問題看似簡短或簡單就忽略查證。

    Args:
        query: 精準的搜尋關鍵字，例如「Node.js 最新 LTS 版本」或「台北今天天氣」
    """
    if not query or not query.strip():
        return "請提供有效的搜尋關鍵字。"

    # 同時檢索 Google News 與網頁資料
    news_items = google_news_search(query.strip(), max_results=3)
    web_items = web_general_search(query.strip(), max_results=3)

    if news_items is None and web_items is None:
        raise RuntimeError("網路搜尋服務均失敗；完整例外已記入 log。")
    all_items = (news_items or []) + (web_items or [])

    if not all_items:
        return f"針對關鍵字「{query}」未檢索到相關即時資料，請嘗試換個關鍵字。"

    output_lines = [f"【搜尋關鍵字】：{query}", "【檢索到的網路資訊】："]
    for i, item in enumerate(all_items, 1):
        output_lines.append(f"[{i}] {item['title']}")
        if item.get("snippet"):
            output_lines.append(f"    摘要: {item['snippet']}")
        output_lines.append(f"    來源連結: {item['link']}")
        output_lines.append("")

    return "\n".join(output_lines)

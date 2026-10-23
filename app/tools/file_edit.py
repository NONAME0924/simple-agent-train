"""唯一區塊替換；只容許換行與行尾空白差異，保留前導縮排判斷。"""
import difflib


def replace_text(content, old_string, new_string):
    old_string = old_string.replace("\r\n", "\n").replace("\r", "\n")
    new_string = new_string.replace("\r\n", "\n").replace("\r", "\n")
    if not old_string.strip():
        raise ValueError("old_string 不能為空白；請先讀取檔案，提供含上下文的原文。")
    if old_string == new_string:
        raise ValueError("old_string 與 new_string 相同，沒有變更；不需重複修改。")
    start = content.find(old_string)
    if start >= 0:
        if content.find(old_string, start + 1) >= 0:
            raise ValueError("原文有多處匹配，未修改檔案。請擴大 old_string 的上下文，使其唯一。")
        return content[:start] + new_string + content[start + len(old_string):], "精確匹配"

    lines = content.splitlines(keepends=True)
    target = old_string.splitlines(keepends=True)
    normalize = lambda line: line.rstrip("\n").rstrip(" \t")
    keys = [normalize(line) for line in lines]
    wanted = [normalize(line) for line in target]
    matches, offset = [], 0
    for index, line in enumerate(lines):
        end_line = index + len(target)
        if keys[index:end_line] == wanted:
            last = lines[end_line - 1]
            if not old_string.endswith("\n") or last.endswith("\n"):
                end = offset + sum(map(len, lines[index:end_line]))
                if last.endswith("\n") and not old_string.endswith("\n"):
                    end -= 1
                matches.append((offset, end))
                if len(matches) > 1:
                    raise ValueError("忽略行尾空白後仍有多處匹配，未修改檔案。請擴大 old_string 的上下文。")
        offset += len(line)
    if matches:
        start, end = matches[0]
        return content[:start] + new_string + content[end:], "忽略行尾空白"

    anchor = next(line.strip() for line in target if line.strip())
    candidates = [line.strip() for line in lines]
    closest = difflib.get_close_matches(anchor, candidates, n=1, cutoff=0.6)
    hint = "請用 read_workspace_file(path=..., start_line=..., end_line=...) 重新讀取，保留前導縮排，不要把顯示行號放進 old_string。"
    if closest:
        index = candidates.index(closest[0])
        first, last = max(0, index - 2), min(len(lines), index + 3)
        snippet = "\n".join(f"{number + 1}: {lines[number].rstrip()[:180]}" for number in range(first, last))
        hint += f"\n可能相關區域（第 {first + 1}～{last} 行，僅供定位，不會自動套用）：\n{snippet}"
    else:
        hint += "\n也可用 search_workspace_code 搜尋關鍵字。"
    raise ValueError("找不到可唯一替換的原文，未修改檔案。" + hint)

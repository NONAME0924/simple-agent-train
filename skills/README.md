# 本機 Skill 與來源

[English](README.en.md)

Git 只保留本頁及英文版與本專案自帶的 `mcp`；其餘技能內容不提交。

## 來源

| 技能 | 來源與差異 |
| --- | --- |
| `sdd` | 作者的 [spec-driven-development](https://github.com/NONAME0924/spec-driven-development)；本機版為三文件精簡調整。 |
| `mcp` | 本專案自帶，隨原始碼提交；以 Skill 方式連接 MCP server，說明見 [skills/mcp](mcp/README.md)。 |
| `pptx` | [Anthropic Skills](https://github.com/anthropics/skills/tree/main/skills/pptx)；保留限制性 LICENSE.txt。 |

技能載入只讀 SKILL.md 或指定參考檔，不把目錄內 README 當成系統提示。參考檔按需讀取，不自動安裝執行依賴。GitHub 原始碼不含技能內容，請在本機準備已取得使用權的技能；不是直接複製上游 SDD 就具有本機精簡版的相同行為。來源與授權範圍見 [第三方說明](../docs/third-party.md)。

Agent 首次只讀開頭 60 行及章節索引，已有足夠指引就執行，需要細節再依行號補讀；每次最多選讀 200 行，不要求依序讀完。

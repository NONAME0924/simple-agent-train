# 第三方與 Skill 來源

[English](third-party.en.md) · [首頁](../README.md)

| 項目 | 來源 | 本專案使用方式 |
| --- | --- | --- |
| SDD Skill | [NONAME0924/spec-driven-development](https://github.com/NONAME0924/spec-driven-development)，作者提供的專案 | 本機 `skills/sdd/SKILL.md` 是精簡調整版：以 save_sdd 保存 spec、plan、tasks；不等同完整上游工作流程。 |
| PPTX Skill | [Anthropic Skills / pptx](https://github.com/anthropics/skills/tree/main/skills/pptx) | 本機工作說明、腳本與 OOXML Schema；保留原始 LICENSE.txt，技能內容不提交。 |

SDD 上游倉庫標示 MIT；作者與授權以[上游 LICENSE](https://github.com/NONAME0924/spec-driven-development/blob/main/LICENSE)為準。本地精簡版不是上游完整副本，也沒有記錄可供對應的原始 commit。

PPTX 本地 `LICENSE.txt` 與[上游授權檔](https://github.com/anthropics/skills/blob/main/skills/pptx/LICENSE.txt)含複製、修改與散布限制，不能把它視為整包 MIT 或僅靠註明來源就取得公開散布權。Git 已排除技能內容；若另交付含技能的壓縮檔，仍須依實際授權處理。

其餘 Python 套件版本見 `requirements.lock.txt`，各依賴保有自己的授權。前端使用 Marked 與 Mermaid，引用位置在 `app/web/static/index.html`。Windows runtime 是 Python 與第三方套件的發行內容，不屬於本專案原創程式。

本頁是來源紀錄，不替第三方重新授權；尚未為本專案主程式新增整體授權檔。

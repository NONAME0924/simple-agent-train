# Blender MCP

Agent、MCP 與 Blender 在同一台電腦執行。Windows 已內附 MCP SDK 1.30.0、mcp-for-blender 2.2.2 與相容套件；Linux／macOS 執行 `sh run.sh --no-browser` 時，會自動建立專案環境並依 requirements.lock.txt 安裝，無需手動執行 pip。首次需要網路、Python 3.10+ 與對應 venv／ensurepip 支援。無需 Node、uv 或另外的 MCP 框架。

依賴清單變更或必要模組缺少時會重新安裝，成功才啟動 Agent；不會把 Windows runtime 當成 Linux 環境。請透過 run.sh 啟動，避免自行使用另一個 Python 執行服務；Blender 的正常安裝與插件啟用仍須完成。

## 開始使用

1. 開啟 Agent 的「專案面板 → MCP」，下載 Blender 插件。
2. 在 Blender「偏好設定 → 附加元件 → 從磁碟安裝」選擇下載的 Python 檔並啟用。已有舊版先停用／更新，再重新啟用或重啟 Blender，避免同時載入兩份。
3. 開啟 Blender 側欄的 MCP 面板，按「Start MCP Server」。預設 127.0.0.1:9876。
4. 在 Agent 選擇要工作的專案／對話，按「連線」。此動作只取得工具及讀取場景資訊，不修改物件。
5. MCP 程序與 Blender 場景狀態分開顯示。確認場景可用後，可輸入「用 Blender 製作一個簡單杯子，保留目前其他物件並保存到工作區」。

也可以在對話要求連線 Blender：模型先載入 skills/blender/SKILL.md，再呼叫 connect_mcp。連線後下一輪提供外部工具；只表示 MCP 可用，仍需查詢 Blender 場景。

## 設定與範圍

- 未提供 mcp.json 時使用內附 mcp.example.json，已預設 Blender。要自訂先複製為 mcp.json；本機設定不提交、不打包。
- ${PYTHON} 指向執行 Agent 的 Python，移到其他電腦不會綁死舊路徑。BLENDER_HOST、BLENDER_PORT 可在 .env 調整，修改後重啟 Agent。
- 修改 mcp.json 後先中斷舊連線再重新連線。stdio 的 command 與 args 分開傳遞，不經 shell；另支援以 url 與 headers 設定 Streamable HTTP。
- 預設提供 get_addon_status、get_scene_info、execute_blender_code、look；工具 Schema 從 MCP 實際取得。要開放其他工具再調整 include。
- read_only 是本專案明確允許規劃階段使用的工具，不憑名稱或伺服器標記自動判定。execute_blender_code 只在實作模式開放。
- 綁定存放 data/mcp-bindings.json；同專案共用，一般對話各自綁定。同一 instance 只綁一個範圍；切換專案要先在原處中斷並解除綁定。這是連線實例綁定，不會自動開啟指定 .blend 或隔離 Blender 檔案系統權限。
- 同一實例按 Agent 任務排隊，使用到的實例保留至該任務結束。暫停不停止已送出的操作；逾時標示結果未確認，不自動重送。
- 狀態只在開啟面板、連線或手動重新整理時取得，沒有定時輪詢。

## 圖片、紀錄與檔案

look 回傳圖片會沿用附件儲存與視覺模型流程；聊天可展開查看，最後四張結果會保存到助理訊息，重新開啟對話仍可查看。圖片本體不放入 JSON log；文字、參數、錯誤與圖片引用沿用專案／對話 log。

Blender Skill 提供場景查詢、bpy 操作與視覺檢視的順序；MCP 提供實際工具。Skill 並非 MCP 協定的必要條件，此版針對 Blender 搭配提供，既有 PPTX／SDD Skill 保持原樣。

程式分工：app/mcp/config.py 管設定與綁定；client.py 管連線、生命週期與排隊；adapter.py 管 Schema 驗證及文字／圖片結果；app/web/mcp_api.py 與 mcp-panel.js 管畫面入口。

來源：[MCP for Blender 上游倉庫](https://github.com/ahujasid/mcp-for-blender)。內附插件由相同套件的 bundled/addon.py 提供，下載入口不會自動安裝或變更使用者 Blender 設定。

## 連線失敗與遠端部署

介面分開顯示「MCP 程序連線」與「Blender 場景可用」。展開該 MCP 項目的錯誤，可看到巢狀例外、程序啟動錯誤的 stderr 尾端或場景查詢的原始錯誤；Log 可選「MCP 連線＋ERROR」查啟動問題，選「工具＋ERROR」查場景工具問題。

已結束的失敗程序可按「連線」重試；首次啟動失敗會解除剛建立的綁定，不需重啟整個 Agent。僅重啟連線，不重送任何修改場景的工具呼叫。若已顯示 MCP 連線成功但場景未就緒，先確認 Blender 插件啟用、Start MCP Server、位址與連接埠，再按「重新確認」。

位址由 Agent 後端連線，與瀏覽器所在電腦無關。Agent 在遠端 Linux、Blender 在自己的電腦時，預設 127.0.0.1:9876 會連到 Linux，無法直接連到自己的 Blender。可在執行 Blender 的電腦開啟 SSH 反向轉送：

```sh
ssh -N -o ExitOnForwardFailure=yes -R 9876:127.0.0.1:9876 user@agent-host
```

將 user@agent-host 換成 Agent 主機的 SSH 登入位置，保持此連線開啟；Agent 端沿用 BLENDER_HOST=127.0.0.1、BLENDER_PORT=9876。若遠端連接埠已占用，可將指令的第一個 9876 改成其他空閒連接埠，並同步調整 Agent 的 BLENDER_PORT，重啟 Agent。若 Agent 在容器內，還需確保轉送端點能從該容器到達。這與官方建議以 SSH 轉送連接遠端 Blender 的方式一致，不需要將 Blender Socket 直接公開。

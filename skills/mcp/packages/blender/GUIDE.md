# Blender（MCP 套件：blender）

連 Blender 內的 **Blender Lab 橋接**（TCP，預設 127.0.0.1:9876）。工具：
`get_blender_status`、`get_scene_info`、`execute_blender_code`、`launch_blender`。

## 前提
- Blender 5.1 以上已開啟，Blender Lab 附加元件的橋接已啟動（偏好設定可看位址與埠號）。
- Agent 與 Blender 在同一台電腦。
- 連不上時先回報這一點，不要反覆重試。
- 埠號不同時：`configure blender --env BLENDER_PORT=埠號`（只影響這台電腦）。
- `launch_blender` 需要 Blender 可執行檔路徑：`configure blender --env BLENDER_PATH=完整路徑`，或設定同名環境變數。
- **不要改用社群版 `mcp-for-blender`**：它的協議與 Lab 橋接不相容，會卡在握手。

## 做法
1. 先 `get_blender_status` 確認可用，再用 `get_scene_info` 了解場景。預設場景有 Cube／Camera／Light，新物件可能與 Cube 重疊。
2. 建模把多個操作寫成**一段完整 Python**，用 `execute_blender_code` 一次送出，不要一個操作一輪；長腳本寫成 `@args.json`：`{"code": "..."}`。
3. 每批操作後再取一次 `get_scene_info` 確認，與預期不符先修正，不要疊加。
4. `redraw` 預設為 true，成功後會重繪 3D 視口；要調整視角，自己用 `temp_override` 搭配 `view3d.view_selected()`。
5. 渲染或寫檔的輸出路徑，用 Blender 所在電腦能寫入的絕對路徑。

## 安全
橋接沒有任何防護，腳本會直接改動使用者的場景與檔案。刪除物件、清空場景、覆寫或儲存檔案前，先向使用者確認。

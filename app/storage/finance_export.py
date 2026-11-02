"""公帳匯出：CSV（流水帳或請款明細各一份）與 Excel（總覽＋流水帳＋請款明細）。
申請人的事由等文字是使用者輸入，開頭是 = + - @ 的儲存格一律當成純文字，避免用 Excel 開啟時被當成公式執行。"""
import csv
import datetime
import io

STATUS = {"pending": "審核中", "approved": "已通過", "rejected": "已退回", "withdrawn": "已撤回"}
KIND = {"add": "加錢", "subtract": "減錢", "expense": "請款核銷"}
LEDGER_HEAD = ["時間", "種類", "金額", "當時餘額", "備註", "經手人", "請款單號"]
REQUEST_HEAD = ["單號", "送出時間", "申請人", "事由", "申請金額", "核定金額", "狀態", "審核人", "審核時間", "退回原因", "調整或更正原因", "照片張數"]
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _kind(row):
    return "核銷更正／撤銷" if row["kind"] == "expense" and row["amount"] > 0 else KIND[row["kind"]]


def ledger_rows(data):
    return [[r["created_at"], _kind(r), r["amount"], r["balance"], r["note"], r["actor_name"], r["request_id"] or ""] for r in data["ledger"]]


def request_rows(data):
    rows = []
    for r in data["requests"]:
        rows.append([r["id"], r["created_at"], r["requester"], r["description"],
                     r["original_amount"] if r["original_amount"] else r["amount"],
                     r["amount"] if r["status"] in ("approved", "pending") else "",
                     STATUS[r["status"]], r["decided_by_name"] or "" if r["status"] in ("approved", "rejected") else "",
                     r["decided_at"] or "" if r["status"] in ("approved", "rejected") else "",
                     r["reject_reason"] if r["status"] == "rejected" else "", r["adjust_note"] or "",
                     r.get("images", "")])
    return rows


def _safe(value):
    return "'" + value if isinstance(value, str) and value.startswith(_FORMULA_START) else value


def build_csv(data, table):
    head, rows = (LEDGER_HEAD, ledger_rows(data)) if table == "ledger" else (REQUEST_HEAD, request_rows(data))
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(head)
    for row in rows:
        writer.writerow([_safe(cell) for cell in row])
    return ("﻿" + out.getvalue()).encode("utf-8")  # BOM：Excel 直接開啟中文才不會亂碼


def build_xlsx(data):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="E8F0F7")

    def sheet(ws, head, rows, money_cols, widths):
        ws.append(head)
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True), head_fill
        for row in rows:
            ws.append(row)
        for line in ws.iter_rows(min_row=2):
            for cell in line:
                if isinstance(cell.value, str):
                    cell.data_type = "s"  # 就算以 = 開頭也只是文字，不會被執行
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
                elif cell.column in money_cols:
                    cell.number_format = "#,##0;[Red]-#,##0"
        for index, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + index)].width = width
        ws.freeze_panes = "A2"

    s = data["summary"]
    ws = wb.active
    ws.title = "總覽"
    period = f"{data['since'] or '最早'} ～ {data['until'] or '今天'}"
    for label, value in (("匯出時間", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")), ("資料期間（流水帳與請款）", period),
                         ("總金額", s["total"]), ("已核銷", s["spent"]), ("目前剩餘", s["remaining"]), ("待審筆數", s["pending"])):
        ws.append([label, value])
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    for row in ws.iter_rows(min_row=3, max_row=5, min_col=2, max_col=2):
        row[0].number_format = "#,##0;[Red]-#,##0"
    ws.append([])
    ws.append(["總金額、已核銷、目前剩餘是截至匯出當下的全部累計，不受日期期間影響。"])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 24
    sheet(wb.create_sheet("流水帳"), LEDGER_HEAD, ledger_rows(data), {3, 4}, [20, 14, 12, 14, 44, 14, 10])
    sheet(wb.create_sheet("請款明細"), REQUEST_HEAD, request_rows(data), {5, 6}, [8, 20, 22, 40, 12, 12, 10, 14, 20, 30, 30, 10])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

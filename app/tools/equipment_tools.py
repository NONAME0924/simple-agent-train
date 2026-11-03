"""Agent 的唯讀設備查詢：所有登入者本來就看得到設備清單，所以不分身分。"""
from app.storage.equipment import EquipmentError, equipment_manager
from app.tools.registry import ToolResult


def equipment_query(keyword: str = "", status: str = "", location: str = "", limit: int = 20) -> str:
    """查詢實驗室設備清單（唯讀）。keyword 比對名稱、型號、財產編號、序號、位置、保管人、備註；
    status：normal 正常｜repair 維修中｜retired 報廢；location 精確比對存放位置。新增或修改設備請到網頁的「設備」頁。"""
    try:
        return equipment_manager.summary_text(keyword, status, location, limit)
    except EquipmentError as error:
        return ToolResult.failed(str(error))

def finish_task(conclusion: str) -> str:
    """結案並交付最終回答，會終止本輪。成果、檔案位置、失敗、阻塞、未完成或仍在執行的背景工作都要如實交代；
    不重播過程或貼工具原始紀錄。「現在開始寫」是進度，不是結論。

    Args:
        conclusion: 最終回答。
    """
    return conclusion

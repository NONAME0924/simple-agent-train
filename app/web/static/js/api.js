/* 各面板共用 JSON API 請求；檔案上傳與 SSE 保留各自的串流流程。 */
async function api(url, method = "GET", body) {
  const response = await fetch(url, {
    method,
    ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "操作失敗，請確認輸入或重新載入資料。");
  return data;
}

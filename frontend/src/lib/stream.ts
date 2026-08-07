import { ApiError } from "@/lib/api"
import { getToken } from "@/lib/auth"
import type { Citation } from "@/lib/types"

export interface SSEHandlers {
  onStatus?: (text: string) => void
  onChunk?: (text: string) => void
  onCitations?: (items: Citation[]) => void
  onDone?: (messageId: string) => void
  onError?: (text: string) => void
}

function dispatchBlock(block: string, handlers: SSEHandlers) {
  let event = ""
  let data = ""
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim()
    else if (line.startsWith("data:")) data = line.slice(5).trim()
  }
  if (!data) return
  let payload: { text?: string; items?: Citation[]; message_id?: string }
  try {
    payload = JSON.parse(data)
  } catch {
    return
  }
  switch (event) {
    case "status":
      handlers.onStatus?.(payload.text ?? "")
      break
    case "chunk":
      handlers.onChunk?.(payload.text ?? "")
      break
    case "citations":
      handlers.onCitations?.(payload.items ?? [])
      break
    case "done":
      handlers.onDone?.(payload.message_id ?? "")
      break
    case "error":
      handlers.onError?.(payload.text ?? "生成失败")
      break
  }
}

export async function streamChat(
  url: string,
  body: unknown,
  handlers: SSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok) {
    let detail = `请求失败 (${resp.status})`
    try {
      const j = await resp.json()
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* keep default */
    }
    throw new ApiError(resp.status, detail)
  }
  if (!resp.body) return
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      if (block.trim()) dispatchBlock(block, handlers)
    }
  }
}

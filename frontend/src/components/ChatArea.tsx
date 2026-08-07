import { useCallback, useEffect, useRef, useState } from "react"
import { MessageSquare, Plus, Send, Square } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"
import { streamChat, type SSEHandlers } from "@/lib/stream"
import type { Citation, Conversation, Message } from "@/lib/types"

interface ChatAreaProps {
  kbId: string
}

function ChatArea({ kbId }: ChatAreaProps) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [convId, setConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [statusText, setStatusText] = useState("")
  const [streamAnswer, setStreamAnswer] = useState("")
  const [streamCitations, setStreamCitations] = useState<Citation[]>([])
  const abortRef = useRef<AbortController | null>(null)
  const answerRef = useRef("")
  const citationsRef = useRef<Citation[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const fetchConversations = useCallback(async () => {
    try {
      const list = await api.get<Conversation[]>(`/api/v1/conversations?kb_id=${kbId}`)
      setConversations(list)
      setConvId((cur) => {
        if (cur && list.some((c) => c.id === cur)) return cur
        return list.length > 0 ? list[0].id : null
      })
    } catch {
      /* 401 由 api.ts 处理 */
    }
  }, [kbId])

  const loadMessages = useCallback(async (cid: string) => {
    try {
      const msgs = await api.get<Message[]>(`/api/v1/conversations/${cid}/messages`)
      setMessages(msgs)
    } catch {
      toast.error("加载历史消息失败")
    }
  }, [])

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  useEffect(() => {
    abortRef.current?.abort()
    setMessages([])
    setStreamAnswer("")
    setStreamCitations([])
    setStatusText("")
    if (convId) loadMessages(convId)
  }, [convId, loadMessages])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streamAnswer, statusText])

  async function handleNewConv() {
    try {
      const conv = await api.post<Conversation>("/api/v1/conversations", { kb_id: kbId })
      setConversations((prev) => [conv, ...prev])
      setConvId(conv.id)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "新建会话失败")
    }
  }

  function finalizeStream(partial: boolean) {
    const answer = answerRef.current
    const cits = citationsRef.current
    answerRef.current = ""
    citationsRef.current = []
    if (!answer || !convId) return
    setMessages((prev) => [
      ...prev,
      {
        id: `local-${Date.now()}${partial ? "-partial" : ""}`,
        conversation_id: convId,
        role: "assistant",
        content: answer,
        citations_json: cits.length > 0 ? cits : null,
        created_at: new Date().toISOString(),
      },
    ])
  }

  const streamHandlers: SSEHandlers = {
    onStatus: (t) => setStatusText(t),
    onChunk: (t) => {
      answerRef.current += t
      setStreamAnswer(answerRef.current)
    },
    onCitations: (items) => {
      citationsRef.current = items
      setStreamCitations(items)
    },
    onDone: () => {
      setStatusText("")
    },
    onError: (t) => setStatusText(t),
  }

  async function handleSend() {
    const question = input.trim()
    if (!question || !convId || streaming) return
    setInput("")
    setStreaming(true)
    setStatusText("正在检索知识库...")
    setStreamAnswer("")
    setStreamCitations([])
    answerRef.current = ""
    citationsRef.current = []
    setMessages((prev) => [
      ...prev,
      {
        id: `local-user-${Date.now()}`,
        conversation_id: convId,
        role: "user",
        content: question,
        citations_json: null,
        created_at: new Date().toISOString(),
      },
    ])
    const abort = new AbortController()
    abortRef.current = abort
    try {
      await streamChat(`/api/v1/conversations/${convId}/messages`, { question }, streamHandlers, abort.signal)
      finalizeStream(false)
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        finalizeStream(true)
      } else {
        setStatusText(err instanceof ApiError ? err.message : "网络错误")
      }
    } finally {
      setStreaming(false)
      setStatusText("")
      abortRef.current = null
    }
  }

  function handleStop() {
    abortRef.current?.abort()
  }

  function renderCitations(cits: Citation[] | null | undefined) {
    if (!cits || cits.length === 0) return null
    return (
      <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
        {cits.map((c) => (
          <span
            key={c.n}
            className="rounded-md bg-background px-2 py-0.5 text-xs text-muted-foreground"
            title={c.snippet}
          >
            [{c.n}] {c.doc_name} · 第{c.page}页
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b px-4 py-2">
        <select
          value={convId ?? ""}
          onChange={(e) => setConvId(e.target.value || null)}
          className="h-8 max-w-64 rounded-md border bg-background px-2 text-sm outline-none"
        >
          {conversations.length === 0 && <option value="">暂无会话</option>}
          {conversations.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <Button size="sm" variant="outline" onClick={handleNewConv}>
          <Plus className="size-4" />
          新对话
        </Button>
      </div>

      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !streaming && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <MessageSquare className="size-8" />
            <p className="text-sm">向知识库提问, 基于已上传文档获得带引用的回答</p>
          </div>
        )}
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2 text-sm text-primary-foreground">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={m.id} className="flex justify-start">
              <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm">
                <p className="whitespace-pre-wrap">{m.content}</p>
                {renderCitations(m.citations_json)}
              </div>
            </div>
          ),
        )}
        {streaming && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm">
              <p className="whitespace-pre-wrap">
                {streamAnswer || (
                  <span className="text-muted-foreground">{statusText || "思考中…"}</span>
                )}
              </p>
              {renderCitations(streamCitations)}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="shrink-0 border-t p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder={convId ? "输入问题, Enter 发送" : "请先新建会话"}
            rows={1}
            disabled={!convId || streaming}
            className="min-h-[40px] max-h-40 flex-1 resize-none rounded-lg border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          />
          {streaming ? (
            <Button size="icon" variant="outline" onClick={handleStop} title="停止生成">
              <Square className="size-4" />
            </Button>
          ) : (
            <Button size="icon" onClick={handleSend} disabled={!convId || !input.trim()}>
              <Send className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatArea

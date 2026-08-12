import { useCallback, useEffect, useRef, useState } from "react"
import { MessageSquare, Send, Square } from "lucide-react"
import { toast } from "sonner"
import AnswerMarkdown from "@/components/AnswerMarkdown"
import CitationCard from "@/components/CitationCard"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"
import { streamChat, type SSEHandlers } from "@/lib/stream"
import type { Citation, Message } from "@/lib/types"
import { cn } from "@/lib/utils"

interface ChatAreaProps {
  kbId: string
  convId: string | null
  onNewConv: () => void
  onConversationUpdated: () => void
}

function ChatArea({ kbId, convId, onNewConv, onConversationUpdated }: ChatAreaProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [statusText, setStatusText] = useState("")
  const [streamAnswer, setStreamAnswer] = useState("")
  const [streamCitations, setStreamCitations] = useState<Citation[]>([])
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const answerRef = useRef("")
  const citationsRef = useRef<Citation[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const loadMessages = useCallback(async (cid: string) => {
    try {
      const msgs = await api.get<Message[]>(`/api/v1/conversations/${cid}/messages`)
      setMessages(msgs)
    } catch {
      toast.error("加载历史消息失败")
    }
  }, [])

  useEffect(() => {
    abortRef.current?.abort()
    setMessages([])
    setStreamAnswer("")
    setStreamCitations([])
    setStatusText("")
    if (convId) loadMessages(convId)
  }, [convId, loadMessages, kbId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streamAnswer, statusText])

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
      onConversationUpdated()
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

  function openCitation(cits: Citation[] | null | undefined, n: number) {
    const c = cits?.find((x) => x.n === n)
    if (c) setActiveCitation(c)
  }

  function renderCitations(cits: Citation[] | null | undefined) {
    if (!cits || cits.length === 0) return null
    return (
      <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
        {cits.map((c) => (
          <button
            key={c.n}
            onClick={() => setActiveCitation(c)}
            title={c.verified ? c.snippet : `${c.doc_name} · 第${c.page}页`}
            className={cn(
              "rounded-md px-2 py-0.5 text-xs transition-colors",
              c.verified
                ? "bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                : "border border-dashed border-muted-foreground/40 text-muted-foreground/60 hover:bg-accent hover:text-accent-foreground",
            )}
          >
            [{c.n}] {c.doc_name} · 第{c.page}页
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
        {!convId ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <MessageSquare className="size-8" />
            <p className="text-sm">该知识库还没有会话</p>
            <Button size="sm" variant="outline" onClick={onNewConv}>
              新建会话
            </Button>
          </div>
        ) : messages.length === 0 && !streaming ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
            <MessageSquare className="size-8" />
            <p className="text-sm">向知识库提问, 基于已上传文档获得带引用的回答</p>
          </div>
        ) : (
          <>
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
                    <AnswerMarkdown
                      content={m.content}
                      citations={m.citations_json}
                      onCitationClick={(n) => openCitation(m.citations_json, n)}
                    />
                    {renderCitations(m.citations_json)}
                  </div>
                </div>
              ),
            )}
            {streaming && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-2 text-sm">
                  {streamAnswer ? (
                    <AnswerMarkdown
                      content={streamAnswer}
                      citations={streamCitations}
                      onCitationClick={(n) => openCitation(streamCitations, n)}
                    />
                  ) : (
                    <p className="text-muted-foreground">{statusText || "思考中…"}</p>
                  )}
                  {renderCitations(streamCitations)}
                </div>
              </div>
            )}
          </>
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
            placeholder={convId ? "输入问题, Enter 发送" : "请先在左侧新建会话"}
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

      <CitationCard citation={activeCitation} onClose={() => setActiveCitation(null)} />
    </div>
  )
}

export default ChatArea

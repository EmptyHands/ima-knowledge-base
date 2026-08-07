import { useCallback, useEffect, useRef, useState } from "react"
import { FileText, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"
import type { Document } from "@/lib/types"
import { cn } from "@/lib/utils"

const STATUS_META: Record<
  Document["status"],
  { label: string; className: string; pulse?: boolean }
> = {
  pending: { label: "排队中", className: "bg-muted text-muted-foreground" },
  processing: {
    label: "解析中",
    className: "bg-blue-100 text-blue-700",
    pulse: true,
  },
  ready: { label: "已就绪", className: "bg-green-100 text-green-700" },
  failed: { label: "失败", className: "bg-red-100 text-red-700" },
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function DocList({ kbId }: { kbId: string }) {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const pollRef = useRef<number | null>(null)

  const fetchDocs = useCallback(async () => {
    try {
      const list = await api.get<Document[]>(`/api/v1/documents?kb_id=${kbId}`)
      setDocs(list)
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        toast.error("加载文档失败")
      }
    } finally {
      setLoading(false)
    }
  }, [kbId])

  useEffect(() => {
    setLoading(true)
    fetchDocs()
    pollRef.current = window.setInterval(fetchDocs, 3000)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [fetchDocs])

  async function handleDelete(doc: Document) {
    if (!window.confirm(`确定删除「${doc.filename}」？向量数据将一并移除。`)) return
    try {
      await api.del(`/api/v1/documents/${doc.id}`)
      toast.success("文档已删除")
      fetchDocs()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "删除失败")
    }
  }

  if (loading && docs.length === 0) {
    return <p className="px-6 py-8 text-sm text-muted-foreground">加载中…</p>
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
        <FileText className="size-8" />
        <p className="text-sm">该知识库还没有文档</p>
        <p className="text-xs">点击右上角「上传文档」添加 PDF / Word / TXT / Markdown</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 p-4">
      {docs.map((doc) => {
        const meta = STATUS_META[doc.status]
        return (
          <div
            key={doc.id}
            className="flex items-center gap-3 rounded-lg border px-4 py-3"
          >
            <FileText className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{doc.filename}</p>
              <p className="text-xs text-muted-foreground">
                {formatSize(doc.file_size)}
                {doc.page_count != null && ` · ${doc.page_count} 页`}
                {doc.chunk_count != null && ` · ${doc.chunk_count} 块`}
                {doc.status === "failed" && doc.error_msg && ` · ${doc.error_msg}`}
              </p>
            </div>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-xs font-medium",
                meta.className,
                meta.pulse && "animate-pulse",
              )}
            >
              {meta.label}
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0"
              title="删除文档"
              onClick={() => handleDelete(doc)}
            >
              <Trash2 className="size-4 text-muted-foreground" />
            </Button>
          </div>
        )
      })}
    </div>
  )
}

export default DocList

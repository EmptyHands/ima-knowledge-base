import { useCallback, useRef, useState } from "react"
import { CheckCircle2, CloudUpload, FileText, XCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { getToken } from "@/lib/auth"
import { cn } from "@/lib/utils"

interface UploadItem {
  file: File
  progress: number
  status: "uploading" | "done" | "failed"
  message?: string
}

interface UploadDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  kbId: string
  onUploaded: () => void
}

function UploadDialog({ open, onOpenChange, kbId, onUploaded }: UploadDialogProps) {
  const [items, setItems] = useState<UploadItem[]>([])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback((files: FileList | File[]) => {
    const next = Array.from(files).map((file) => ({
      file,
      progress: 0,
      status: "uploading" as const,
    }))
    setItems((prev) => [...prev, ...next])
  }, [])

  const uploadOne = useCallback(
    (item: UploadItem) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      form.append("files", item.file)

      xhr.open("POST", `/api/v1/documents?kb_id=${kbId}`)
      xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100)
          setItems((prev) =>
            prev.map((it) => (it.file === item.file ? { ...it, progress: pct } : it)),
          )
        }
      }
      xhr.onload = () => {
        let ok = xhr.status >= 200 && xhr.status < 300
        let message = ""
        try {
          const res = JSON.parse(xhr.responseText)
          if (res[0]?.duplicate) {
            ok = false
            message = "重复文件，已跳过"
          }
        } catch {
          /* ignore */
        }
        setItems((prev) =>
          prev.map((it) =>
            it.file === item.file
              ? { ...it, status: ok ? "done" : "failed", message: message || undefined }
              : it,
          ),
        )
      }
      xhr.onerror = () => {
        setItems((prev) =>
          prev.map((it) =>
            it.file === item.file ? { ...it, status: "failed", message: "网络错误" } : it,
          ),
        )
      }
      xhr.send(form)
    },
    [kbId],
  )

  const startUpload = useCallback(() => {
    const pending = items.filter((it) => it.status === "uploading" && it.progress === 0)
    pending.forEach((it) => uploadOne(it))
  }, [items, uploadOne])

  function handleClose() {
    const allDone = items.every((it) => it.status !== "uploading" || it.progress > 0)
    const hasDone = items.some((it) => it.status === "done")
    if (allDone && hasDone) onUploaded()
    setItems([])
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => (v ? undefined : handleClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>上传文档</DialogTitle>
          <DialogDescription>支持 PDF / Word / TXT / Markdown，单文件不超过 20MB</DialogDescription>
        </DialogHeader>

        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files)
          }}
        />

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            addFiles(e.dataTransfer.files)
          }}
          className={cn(
            "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-muted-foreground transition-colors",
            dragging ? "border-primary bg-primary/5 text-primary" : "hover:bg-muted/50",
          )}
        >
          <CloudUpload className="size-8" />
          <p className="text-sm font-medium">
            {dragging ? "松开以添加文件" : "点击或拖拽文件到此处"}
          </p>
          <p className="text-xs">可一次选择多个文件</p>
        </button>

        {items.length > 0 && (
          <div className="flex max-h-56 flex-col gap-2 overflow-y-auto">
            {items.map((it, idx) => (
              <div key={idx} className="flex items-center gap-2 rounded-md border px-3 py-2">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium">{it.file.name}</p>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${it.progress}%` }}
                    />
                  </div>
                  {it.message && (
                    <p className="text-xs text-destructive">{it.message}</p>
                  )}
                </div>
                {it.status === "done" ? (
                  <CheckCircle2 className="size-4 shrink-0 text-green-600" />
                ) : it.status === "failed" ? (
                  <XCircle className="size-4 shrink-0 text-destructive" />
                ) : (
                  <span className="text-xs text-muted-foreground">{it.progress}%</span>
                )}
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            关闭
          </Button>
          <Button onClick={startUpload}>开始上传</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default UploadDialog

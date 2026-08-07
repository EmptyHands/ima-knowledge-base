import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ApiError, api } from "@/lib/api"
import type { KnowledgeBase } from "@/lib/types"

interface KbDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing: KnowledgeBase | null
  onSaved: () => void
}

function KbDialog({ open, onOpenChange, editing, onSaved }: KbDialogProps) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (open) {
      setName(editing?.name ?? "")
      setDescription(editing?.description ?? "")
      setError("")
    }
  }, [open, editing])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError("")
    try {
      if (editing) {
        await api.put(`/api/v1/knowledge-bases/${editing.id}`, { name, description })
        toast.success("知识库已更新")
      } else {
        await api.post("/api/v1/knowledge-bases", { name, description })
        toast.success("知识库已创建")
      }
      onOpenChange(false)
      onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败，请稍后重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? "重命名知识库" : "新建知识库"}</DialogTitle>
          <DialogDescription>
            {editing ? "修改知识库名称与描述" : "创建后即可上传文档进行问答"}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <Input
            placeholder="知识库名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Input
            placeholder="描述（可选）"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default KbDialog

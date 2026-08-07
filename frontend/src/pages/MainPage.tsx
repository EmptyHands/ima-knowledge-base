import { useCallback, useEffect, useState } from "react"
import { CloudUpload } from "lucide-react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import ChatArea from "@/components/ChatArea"
import DocList from "@/components/DocList"
import KbDialog from "@/components/KbDialog"
import Sidebar from "@/components/Sidebar"
import UploadDialog from "@/components/UploadDialog"
import { Button } from "@/components/ui/button"
import { ApiError, api } from "@/lib/api"
import { clearToken } from "@/lib/auth"
import type { KnowledgeBase } from "@/lib/types"
import { cn } from "@/lib/utils"

type Tab = "docs" | "chat"

function MainPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>("chat")
  const [kbDialogOpen, setKbDialogOpen] = useState(false)
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)

  const fetchKbs = useCallback(async () => {
    try {
      const list = await api.get<KnowledgeBase[]>("/api/v1/knowledge-bases")
      setKbs(list)
      setSelectedKbId((cur) => {
        if (cur && list.some((k) => k.id === cur)) return cur
        return list.length > 0 ? list[0].id : null
      })
    } catch {
      /* 401 由 api.ts 处理 */
    }
  }, [])

  useEffect(() => {
    api
      .get<{ username: string }>("/api/v1/auth/me")
      .then((res) => setUsername(res.username))
      .catch(() => {})
    fetchKbs()
  }, [fetchKbs])

  const handleSelectKb = useCallback((id: string) => {
    setSelectedKbId(id)
    setTab("chat")
  }, [])

  function handleCreateKb() {
    setEditingKb(null)
    setKbDialogOpen(true)
  }

  function handleRenameKb(kb: KnowledgeBase) {
    setEditingKb(kb)
    setKbDialogOpen(true)
  }

  async function handleDeleteKb(kb: KnowledgeBase) {
    if (!window.confirm(`确定删除知识库「${kb.name}」？文档与向量数据将一并删除。`)) return
    try {
      await api.del(`/api/v1/knowledge-bases/${kb.id}`)
      toast.success("知识库已删除")
      fetchKbs()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "删除失败")
    }
  }

  function handleLogout() {
    clearToken()
    navigate("/login")
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <Sidebar
        kbs={kbs}
        selectedKbId={selectedKbId}
        username={username}
        onSelectKb={handleSelectKb}
        onCreateKb={handleCreateKb}
        onRenameKb={handleRenameKb}
        onDeleteKb={handleDeleteKb}
        onLogout={handleLogout}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        {selectedKbId && (
          <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
            <div className="flex items-center gap-1">
              {(["docs", "chat"] as Tab[]).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm transition-colors",
                    tab === t
                      ? "bg-accent font-medium text-accent-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {t === "docs" ? "文档" : "问答"}
                </button>
              ))}
            </div>
            {tab === "docs" && (
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                <CloudUpload className="size-4" />
                上传文档
              </Button>
            )}
          </header>
        )}

        <div className="flex flex-1 overflow-hidden">
          {selectedKbId ? (
            tab === "docs" ? (
              <DocList kbId={selectedKbId} />
            ) : (
              <ChatArea />
            )
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
              <p className="text-sm">请在左侧创建并选择一个知识库</p>
            </div>
          )}
        </div>
      </main>

      <KbDialog
        open={kbDialogOpen}
        onOpenChange={setKbDialogOpen}
        editing={editingKb}
        onSaved={fetchKbs}
      />
      {selectedKbId && (
        <UploadDialog
          open={uploadOpen}
          onOpenChange={setUploadOpen}
          kbId={selectedKbId}
          onUploaded={fetchKbs}
        />
      )}
    </div>
  )
}

export default MainPage

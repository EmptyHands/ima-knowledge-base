import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import ChatArea from "@/components/ChatArea"
import Sidebar from "@/components/Sidebar"
import { api } from "@/lib/api"
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

  useEffect(() => {
    api
      .get<{ username: string }>("/api/v1/auth/me")
      .then((res) => setUsername(res.username))
      .catch(() => {})

    api
      .get<KnowledgeBase[]>("/api/v1/knowledge-bases")
      .then((list) => {
        setKbs(list)
        if (list.length > 0 && !selectedKbId) {
          setSelectedKbId(list[0].id)
        }
      })
      .catch(() => {})
  }, [])

  const handleSelectKb = useCallback((id: string) => {
    setSelectedKbId(id)
    setTab("chat")
  }, [])

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
        onCreateKb={() => setTab("docs")}
        onLogout={handleLogout}
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        {selectedKbId && (
          <header className="flex h-14 shrink-0 items-center gap-1 border-b px-4">
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
          </header>
        )}

        <div className="flex flex-1 overflow-hidden">
          {selectedKbId ? (
            tab === "docs" ? (
              <div className="flex flex-1 items-center justify-center text-muted-foreground">
                <p className="text-sm">文档列表将在 Task 13 实现</p>
              </div>
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
    </div>
  )
}

export default MainPage

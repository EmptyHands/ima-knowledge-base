import { BookOpen, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { KnowledgeBase } from "@/lib/types"

interface SidebarProps {
  kbs: KnowledgeBase[]
  selectedKbId: string | null
  username: string
  onSelectKb: (id: string) => void
  onCreateKb: () => void
  onLogout: () => void
}

function Sidebar({
  kbs,
  selectedKbId,
  username,
  onSelectKb,
  onCreateKb,
  onLogout,
}: SidebarProps) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r bg-background">
      <div className="flex h-14 items-center justify-between border-b px-4">
        <div className="flex items-center gap-2 font-semibold">
          <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <BookOpen className="size-4" />
          </span>
          知识库
        </div>
        <Button variant="ghost" size="icon" onClick={onCreateKb} title="新建知识库">
          <Plus className="size-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        {kbs.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
            <p className="text-sm font-medium">创建你的第一个知识库</p>
            <p className="text-xs text-muted-foreground">
              上传文档后即可基于知识库提问
            </p>
            <Button size="sm" className="mt-2" onClick={onCreateKb}>
              <Plus className="size-4" />
              新建知识库
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5 p-2">
            {kbs.map((kb) => (
              <button
                key={kb.id}
                onClick={() => onSelectKb(kb.id)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                  kb.id === selectedKbId
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <BookOpen className="size-4 shrink-0" />
                <span className="truncate">{kb.name}</span>
              </button>
            ))}
          </div>
        )}
      </ScrollArea>

      <div className="border-t p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">{username}</span>
          <Button variant="ghost" size="sm" onClick={onLogout}>
            退出
          </Button>
        </div>
      </div>
    </aside>
  )
}

export default Sidebar

import { BookOpen, MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react"
import ConversationList from "@/components/ConversationList"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ScrollArea } from "@/components/ui/scroll-area"
import type { Conversation, KnowledgeBase } from "@/lib/types"
import { cn } from "@/lib/utils"

interface SidebarProps {
  kbs: KnowledgeBase[]
  selectedKbId: string | null
  conversations: Conversation[]
  selectedConvId: string | null
  username: string
  onSelectKb: (id: string) => void
  onCreateKb: () => void
  onRenameKb: (kb: KnowledgeBase) => void
  onDeleteKb: (kb: KnowledgeBase) => void
  onSelectConv: (id: string) => void
  onCreateConv: () => void
  onDeleteConv: (conv: Conversation) => void
  onLogout: () => void
}

function Sidebar({
  kbs,
  selectedKbId,
  conversations,
  selectedConvId,
  username,
  onSelectKb,
  onCreateKb,
  onRenameKb,
  onDeleteKb,
  onSelectConv,
  onCreateConv,
  onDeleteConv,
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
              <div
                key={kb.id}
                className={cn(
                  "group flex min-w-0 items-center rounded-md transition-colors",
                  kb.id === selectedKbId
                    ? "bg-accent text-accent-foreground font-medium"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <button
                  onClick={() => onSelectKb(kb.id)}
                  className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm"
                >
                  <BookOpen className="size-4 shrink-0" />
                  <span className="truncate">{kb.name}</span>
                </button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="mr-1 size-6 opacity-0 transition-opacity group-hover:opacity-100"
                    >
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onRenameKb(kb)}>
                      <Pencil className="size-4" />
                      重命名
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant="destructive"
                      onClick={() => onDeleteKb(kb)}
                    >
                      <Trash2 className="size-4" />
                      删除
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            ))}
          </div>
        )}
        <div className="mt-2 border-t pt-1">
          <ConversationList
            conversations={conversations}
            selectedConvId={selectedConvId}
            onSelect={onSelectConv}
            onCreate={onCreateConv}
            onDelete={onDeleteConv}
          />
        </div>
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

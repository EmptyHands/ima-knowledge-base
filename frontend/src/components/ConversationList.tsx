import { MessageSquare, Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Conversation } from "@/lib/types"
import { cn } from "@/lib/utils"

interface ConversationListProps {
  conversations: Conversation[]
  selectedConvId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  onDelete: (conv: Conversation) => void
}

function ConversationList({
  conversations,
  selectedConvId,
  onSelect,
  onCreate,
  onDelete,
}: ConversationListProps) {
  return (
    <div className="flex flex-col gap-0.5 p-2">
      <div className="flex items-center justify-between px-3 pb-1">
        <span className="text-xs text-muted-foreground">会话</span>
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={onCreate}
          title="新建会话"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>
      {conversations.length === 0 ? (
        <p className="px-3 py-1 text-xs text-muted-foreground">
          暂无会话, 点击右上角 + 新建
        </p>
      ) : (
        conversations.map((c) => (
          <div
            key={c.id}
            className={cn(
              "group flex min-w-0 items-center rounded-md transition-colors",
              c.id === selectedConvId
                ? "bg-accent font-medium text-accent-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <button
              onClick={() => onSelect(c.id)}
              className="flex min-w-0 flex-1 items-center gap-2 px-3 py-1.5 text-left text-sm"
            >
              <MessageSquare className="size-3.5 shrink-0" />
              <span className="truncate">{c.title}</span>
            </button>
            <Button
              variant="ghost"
              size="icon"
              className="mr-1 size-6 opacity-0 transition-opacity group-hover:opacity-100"
              title="删除会话"
              onClick={() => onDelete(c)}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))
      )}
    </div>
  )
}

export default ConversationList

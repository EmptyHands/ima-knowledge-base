import { CheckCircle2, ExternalLink, FileText } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import type { Citation } from "@/lib/types"

interface CitationCardProps {
  citation: Citation | null
  onClose: () => void
}

function CitationCard({ citation, onClose }: CitationCardProps) {
  const isWeb = Boolean(citation?.url)
  return (
    <Dialog open={citation !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-4 shrink-0" />
            [{citation?.n}] {citation?.doc_name}
          </DialogTitle>
          <DialogDescription>
            {isWeb ? citation?.url : `第 ${citation?.page ?? 0} 页`}
          </DialogDescription>
        </DialogHeader>
        {citation && citation.verified && (
          <>
            <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
              <CheckCircle2 className="size-3.5" />
              {isWeb ? "网络搜索结果来源" : "该结论有原文依据"}
            </div>
            <blockquote className="max-h-60 overflow-y-auto rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              {citation.snippet}
            </blockquote>
            {isWeb && (
              <a
                href={citation.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <ExternalLink className="size-3.5" />
                打开网页
              </a>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default CitationCard

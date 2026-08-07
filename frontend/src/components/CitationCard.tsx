import { AlertTriangle, CheckCircle2, FileText } from "lucide-react"
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
  return (
    <Dialog open={citation !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="size-4 shrink-0" />
            [{citation?.n}] {citation?.doc_name}
          </DialogTitle>
          <DialogDescription>
            {citation ? `第 ${citation.page} 页` : ""}
          </DialogDescription>
        </DialogHeader>
        {citation && (
          <>
            {citation.verified ? (
              <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
                <CheckCircle2 className="size-3.5" />
                该结论有原文依据
              </div>
            ) : (
              <div className="flex items-center gap-1.5 text-xs font-medium text-amber-600">
                <AlertTriangle className="size-3.5" />
                该结论无直接引用来源
              </div>
            )}
            <blockquote className="max-h-60 overflow-y-auto rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              {citation.snippet}
            </blockquote>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default CitationCard

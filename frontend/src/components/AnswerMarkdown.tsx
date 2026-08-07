import DOMPurify from "dompurify"
import { marked } from "marked"
import type { MouseEvent } from "react"
import type { Citation } from "@/lib/types"

interface AnswerMarkdownProps {
  content: string
  citations: Citation[] | null
  onCitationClick?: (n: number) => void
}

const FOOTER_MARK = "## 引用"
const BADGE_CLASS =
  "mx-0.5 inline-block cursor-pointer rounded bg-accent px-1 align-[0.85em] text-xs font-semibold text-accent-foreground transition-colors hover:bg-primary hover:text-primary-foreground"

function withoutFooter(content: string): string {
  const idx = content.indexOf(FOOTER_MARK)
  return idx === -1 ? content : content.slice(0, idx)
}

function badgeify(content: string): string {
  return content.replace(/\[(\d+)\]/g, `<span data-citation="$1" class="${BADGE_CLASS}">[$1]</span>`)
}

function AnswerMarkdown({ content, citations, onCitationClick }: AnswerMarkdownProps) {
  const html = DOMPurify.sanitize(marked.parse(badgeify(withoutFooter(content))) as string)

  const handleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!onCitationClick) return
    const el = (e.target as HTMLElement).closest("[data-citation]")
    if (el) {
      const n = Number(el.getAttribute("data-citation"))
      if (!Number.isNaN(n)) onCitationClick(n)
    }
  }

  void citations
  return (
    <div
      className="whitespace-pre-wrap"
      onClick={handleClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default AnswerMarkdown

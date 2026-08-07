export interface KnowledgeBase {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  kb_id: string
  filename: string
  file_size: number
  status: "pending" | "processing" | "ready" | "failed"
  error_msg: string | null
  page_count: number | null
  chunk_count: number | null
  created_at: string
}

export interface Conversation {
  id: string
  kb_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface Citation {
  n: number
  doc_name: string
  page: number
  snippet: string
  verified: boolean
}

export interface Message {
  id: string
  conversation_id: string
  role: "user" | "assistant"
  content: string
  citations_json: Citation[] | null
  created_at: string
}

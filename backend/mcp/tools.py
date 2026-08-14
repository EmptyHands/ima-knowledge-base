"""MCP 内置工具 - 封装现有检索/搜索能力, 复用 backend/core/retrieval.py"""
from backend.core import retrieval
from backend.core.database import get_db_session
from backend.models.database import Document, KnowledgeBase
from backend.mcp.registry import ToolError, tool


@tool(
    name="web_search",
    description="联网搜索(Tavily): 获取最新网络信息, 返回标题/URL/摘要列表",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "返回条数, 默认 5"},
        },
        "required": ["query"],
    },
)
async def web_search(arguments: dict) -> dict:
    results = await retrieval.web_search(arguments["query"], arguments.get("max_results", 5))
    return {"results": results}


@tool(
    name="vector_search",
    description="知识库语义检索(三级降级: 向量→关键词→空), 返回带文档名/页码的片段",
    input_schema={
        "type": "object",
        "properties": {
            "kb_id": {"type": "string", "description": "知识库 ID"},
            "question": {"type": "string", "description": "查询问题"},
            "top_k": {"type": "integer", "description": "返回条数, 默认 5"},
        },
        "required": ["kb_id", "question"],
    },
)
async def vector_search(arguments: dict) -> dict:
    chunks = await retrieval.vector_search(arguments["kb_id"], arguments["question"],
                                           arguments.get("top_k", 5))
    return {"chunks": chunks}


@tool(
    name="kb_status",
    description="查询知识库状态: 文档数/就绪数/总块数",
    input_schema={
        "type": "object",
        "properties": {"kb_id": {"type": "string", "description": "知识库 ID"}},
        "required": ["kb_id"],
    },
)
async def kb_status(arguments: dict) -> dict:
    db = get_db_session()
    try:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == arguments["kb_id"]).first()
        if kb is None:
            raise ToolError(f"知识库不存在: {arguments['kb_id']}")
        docs = db.query(Document).filter(Document.kb_id == kb.id).all()
        return {
            "kb_id": kb.id,
            "name": kb.name,
            "document_count": len(docs),
            "ready_count": sum(1 for d in docs if d.status == "ready"),
            "chunk_count": sum(d.chunk_count or 0 for d in docs),
        }
    finally:
        db.close()

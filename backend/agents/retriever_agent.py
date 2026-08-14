"""RetrieverAgent - 检索智能体: 三级降级检索 + 意图识别网络搜索(经 MCP 注册表调用工具)"""
from backend.core.retrieval import detect_web_intent
from backend.mcp.registry import registry


async def retrieve(question: str, kb_id: str, top_k: int = 5, force_web: bool = False) -> dict:
    """检索入口, 返回 {"chunks": [...], "web_results": [...]}

    force_web=True 时无条件触发网络搜索(反问确认后的重检索)
    """
    chunks = (await registry.call("vector_search", {"kb_id": kb_id, "question": question, "top_k": top_k}))["chunks"]
    web_results = []
    if force_web or detect_web_intent(question):
        web_results = (await registry.call("web_search", {"query": question}))["results"]
    return {"chunks": chunks, "web_results": web_results}

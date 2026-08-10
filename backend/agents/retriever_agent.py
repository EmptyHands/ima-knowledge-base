"""RetrieverAgent - 检索智能体: 三级降级检索 + 意图识别网络搜索"""
from backend.core.retrieval import detect_web_intent, vector_search, web_search


async def retrieve(question: str, kb_id: str, top_k: int = 5, force_web: bool = False) -> dict:
    """检索入口, 返回 {"chunks": [...], "web_results": [...]}

    force_web=True 时无条件触发网络搜索(反问确认后的重检索)
    """
    chunks = await vector_search(kb_id, question, top_k=top_k)
    web_results = []
    if force_web or detect_web_intent(question):
        web_results = await web_search(question)
    return {"chunks": chunks, "web_results": web_results}

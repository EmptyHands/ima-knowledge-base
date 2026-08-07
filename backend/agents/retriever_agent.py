"""RetrieverAgent - 检索智能体: 向量检索 + 意图识别网络搜索"""
from backend.core.retrieval import detect_web_intent, vector_search, web_search


async def retrieve(question: str, kb_id: str, top_k: int = 5) -> dict:
    """检索入口, 返回 {"chunks": [{text, doc_id, page, doc_name, score}], "web_results": [...]}"""
    chunks = await vector_search(kb_id, question, top_k=top_k)
    web_results = []
    if detect_web_intent(question):
        web_results = await web_search(question)
    return {"chunks": chunks, "web_results": web_results}

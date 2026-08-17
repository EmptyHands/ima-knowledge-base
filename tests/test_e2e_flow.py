"""全链路 e2e 测试 - 注册→建库→上传 PDF→轮询 ready→提问→SSE 事件与引用校验"""
import hashlib
import time

import pytest

import backend.core.llm_adapter as llm_adapter_module
from backend.core.vector_store import VectorStore

PDF_TEXT = "Transformer uses self-attention mechanism, which is the core principle."

# 伪 LLM 回答逐字引用 PDF 文本, 使 [1] 引用通过重叠率校验
E2E_TOKENS = [PDF_TEXT, "[1]", "。\n## 引用\n", "[1] e2e_test.pdf, 第1页"]


class E2EFakeLLM:
    async def astream(self, messages, system_prompt=None):
        for token in E2E_TOKENS:
            yield token

    async def ainvoke(self, messages, system_prompt=None, **kwargs):
        return "".join(E2E_TOKENS)


def _minimal_pdf(text: str) -> bytes:
    """生成可被 pdfplumber 解析的最小单页 PDF(Helvetica 编码 ASCII 文本)"""
    esc = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = f"BT /F1 12 Tf 72 720 Td ({esc}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF").encode()
    return bytes(out)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """解析 SSE 文本为 [(event, data_dict)]"""
    events = []
    for block in body.split("\n\n"):
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        if event and data is not None:
            import json
            events.append((event, json.loads(data)))
    return events


@pytest.fixture()
def fake_embed(monkeypatch):
    """确定性伪向量注入 VectorStore._embed: 上传入库与检索共用, 不依赖 Ollama/网络"""

    async def _embed(self, text: str) -> list[float]:
        dim = getattr(self, "_embed_dim", 768)
        h = hashlib.md5(text.encode("utf-8")).digest()
        v = list(h * (dim // 16 + 1))[:dim]
        norm = sum(x * x for x in v) ** 0.5
        return [x / norm for x in v]

    monkeypatch.setattr(VectorStore, "_embed", _embed)
    return _embed


@pytest.fixture()
def e2e_llm(monkeypatch):
    monkeypatch.setattr(llm_adapter_module, "_llm_adapter", E2EFakeLLM())
    return E2EFakeLLM()


def test_full_chain_upload_to_citation(app_client, auth_headers, fake_embed, e2e_llm):
    # 1. 创建知识库
    resp = app_client.post("/api/v1/knowledge-bases", headers=auth_headers,
                           json={"name": "e2e 测试库"})
    assert resp.status_code == 200, resp.text
    kb_id = resp.json()["id"]

    try:
        # 2. 上传 PDF
        resp = app_client.post(f"/api/v1/documents?kb_id={kb_id}", headers=auth_headers,
                               files={"files": ("e2e_test.pdf", _minimal_pdf(PDF_TEXT),
                                                "application/pdf")})
        assert resp.status_code == 200, resp.text
        doc_id = resp.json()[0]["id"]

        # 3. 轮询直到解析完成
        docs = []
        for _ in range(50):
            docs = app_client.get(f"/api/v1/documents?kb_id={kb_id}",
                                  headers=auth_headers).json()
            if docs and docs[0]["status"] == "ready":
                break
            time.sleep(0.1)
        assert docs and docs[0]["status"] == "ready", f"文档未处理完成: {docs}"
        assert docs[0]["page_count"] == 1
        assert docs[0]["chunk_count"] >= 1

        # 4. 新建会话并提问
        conv = app_client.post("/api/v1/conversations", headers=auth_headers,
                               json={"kb_id": kb_id}).json()
        resp = app_client.post(f"/api/v1/conversations/{conv['id']}/messages",
                               headers=auth_headers,
                               json={"question": "What is the core principle?"})
        assert resp.status_code == 200, resp.text

        # 5. SSE 事件序列: status → chunk... → citations → done
        events = _parse_sse(resp.text)
        types = [e[0] for e in events]
        assert types[0] == "status"
        assert "chunk" in types
        assert types[-2] == "citations"
        assert types[-1] == "done"

        # 6. 引用校验: [1] 指向 PDF 原文, verified=True
        citations = events[-2][1]["items"]
        assert len(citations) >= 1
        c = citations[0]
        assert c["n"] == 1
        assert c["doc_name"] == "e2e_test.pdf"
        assert c["page"] == 1
        assert c["verified"] is True

        # 7. 消息入库且 citations_json 持久化
        msgs = app_client.get(f"/api/v1/conversations/{conv['id']}/messages",
                              headers=auth_headers).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[1]["citations_json"][0]["doc_name"] == "e2e_test.pdf"
        assert msgs[1]["citations_json"][0]["verified"] is True

        # 8. 首条提问自动生成会话标题
        convs = app_client.get(f"/api/v1/conversations?kb_id={kb_id}",
                               headers=auth_headers).json()
        assert convs[0]["title"] == "What is the core pri"
    finally:
        app_client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)

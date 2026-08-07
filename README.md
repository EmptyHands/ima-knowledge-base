# 智能知识库问答系统 (Web 版 ima 精简实现)

基于文档的知识库问答系统:上传 PDF/Word/TXT → 向量化入库 → 多 Agent 问答(检索/回答/引用校验) → 流式输出带引用溯源的回答。所有结论附文档名+页码+原文片段,编造引用会被校验 Agent 识别并灰显。

## 功能

- **文档管理**: 多格式上传(PDF/Word/TXT/Markdown),解析状态机(pending → processing → ready/failed)
- **RAG 问答**: 向量检索 + LLM 生成,SSE 流式打字机输出,多轮会话上下文
- **引用溯源**: 回答中 `[n]` 角标可点击弹出引用卡片(文档名/页码/原文);Jaccard 重叠率校验(阈值 0.6)标记真实/编造引用,编造引用灰显「无直接引用来源」
- **混合检索**: 问题含「最新/实时/网络」等意图时自动触发 Tavily 网络搜索,与知识库结果一并交给 LLM
- **多用户**: JWT 认证,用户/知识库/文档/会话/消息五张表隔离

## 架构

```mermaid
flowchart LR
    subgraph 前端 [React + Vite + Tailwind + shadcn/ui]
        U[用户] --> LOGIN[登录/注册]
        U --> UPLOAD[上传对话框]
        U --> CHAT[聊天区]
        CHAT --> SSE[SSE 流式解析]
        SSE --> MARKDOWN[Markdown 渲染 + [n] 角标]
        MARKDOWN --> CARD[引用卡片]
    end
    subgraph 后端 [FastAPI]
        AUTH[JWT 认证]
        DOC[文档路由]
        DOC --> PARSE[文件解析 pdfplumber/python-docx]
        PARSE --> CHUNK[分块器 800字符/100重叠]
        CHUNK --> EMBED[Embedding bge-m3]
        EMBED --> QDRANT[(Qdrant 向量库)]
        ASK[问答路由 SSE]
        ASK --> RET[RetrieverAgent]
        RET --> QDRANT
        RET --> WEB[Tavily 网络搜索]
        RET --> ANS[AnswerAgent]
        ANS --> CIT[CitationAgent 引用校验]
        ANS --> CHAT
        CIT --> SSE
    end
    META[(SQLite: 用户/知识库/文档/会话/消息)]
    DOC --> META
    ASK --> META
```

**问答链路数据流**:

1. 用户提问 → 后端持久化 user 消息,下发 `status` 事件
2. RetrieverAgent: 问题向量化 → Qdrant 检索 top-k 片段(附文档名/页码);意图判断触发网络搜索(可选)
3. AnswerAgent: 检索片段+历史(最近 10 条)拼进 prompt,流式返回 `chunk` 事件;提示词要求句末标 `[n]` 并输出 `## 引用` 列表
4. CitationAgent: 对每个 `[n]` 提取所在句子,与对应片段做字符二元组 Jaccard 重叠率校验,≥0.6 标记 verified
5. 校验结果以 `citations` 事件结构化下发(不解析 LLM 原文格式),回答+引用入库,`done` 事件结束

## 技术选型理由

| 选型 | 替代方案 | 选择理由 |
|------|---------|---------|
| React + Vite + Tailwind + shadcn/ui | Next.js / Vue | 纯 SPA 无 SSR 需求;shadcn 组件源码在项目内可直接改,AI 修复友好;Vite dev 秒级热更新 |
| 手写 RAG 多 Agent 管线 | LangChain / LlamaIndex | 检索→回答→引用校验三段逻辑清晰可讲,依赖少易调试;面试答辩可展示系统设计能力 |
| Qdrant 向量库 | Chroma / Milvus | Docker 一条命令启动,Python 客户端简单;支持 filter 按 kb_id 隔离 |
| FastAPI + SQLAlchemy | Django / Flask | 原生 SSE/异步流式支持,自动 OpenAPI 文档,SQLite 起步可平滑切 PostgreSQL |
| DeepSeek(OpenAI 兼容) + Ollama bge-m3 | 全云 / 全本地 | LLM 便宜可用,embedding 本地免费跑;bge-m3 中文检索质量优于 nomic-embed-text |

## 快速开始

前置依赖: [Docker](https://www.docker.com/)、[Ollama](https://ollama.com/) (含 `bge-m3`)、Python 3.10+、Node.js 18+

```bash
# 1. 配置 (填 LLM_API_KEY; DeepSeek 或任意 OpenAI 兼容服务)
cp .env.example .env

# 2. 一键启动 (检查依赖 → Qdrant → Ollama → 后端 → 前端)
bash scripts/start.sh
```

或手动分步启动:

```bash
# Qdrant
docker compose up -d qdrant

# 后端
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows (Git Bash)
# venv/bin/python -m pip install -r requirements.txt         # macOS/Linux
venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000

# 前端 (另开终端)
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 → 注册 → 新建知识库 → 上传文档 → 提问。

## 测试

```bash
venv/Scripts/python.exe -m pytest tests/ -v
```

51 个测试全绿,不消耗 API 费用、不依赖网络:

- **单元**: 文件解析(页码提取)、分块(不跨页)、引用校验(真实/编造/混合引用)、密码哈希、向量库(确定性伪向量)
- **集成**: `test_e2e_flow.py` 全链路——注册→建库→上传最小 PDF→轮询 ready→提问→断言 SSE 事件序列与引用校验结果,使用 fake LLM(固定输出注入)+ 伪 embedding,离线可跑

## 已知限制

- 只支持**文本型** PDF(扫描件无文本层会标记解析失败);OCR 见扩展方向
- LLM 引用标注格式不稳定:引用列表走 SSE 结构化下发 + 校验 Agent 兜底,不解析 LLM 原文格式

## 未来扩展

- **混合检索**: 关键词(BM25)+ 向量融合,提升长尾查询召回
- **Rerank**: 交叉编码器重排检索结果,提升 top-k 质量
- **OCR**: 扫描件解析(PaddleOCR 本地化)
- **部署上云**: SQLite → PostgreSQL,本地存储 → S3,静态前端托管 Vercel(.env 全配置化,不改代码)

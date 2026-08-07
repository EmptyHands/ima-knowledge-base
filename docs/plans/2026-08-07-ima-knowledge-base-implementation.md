# 智能知识库问答系统(Web 版 ima)实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 从零构建 ima 风格的个人知识库问答系统 MVP:用户注册登录 → 上传 PDF/Word/TXT → 向量入库 → 多 Agent 流式问答(带引用溯源),4 周交付可演示作品。

**Architecture:** 前后端分离。后端 FastAPI(迁移自 `study-assistant` 的 core/ 层:config/database/llm_adapter/vector_store/file_parser),新增 JWT 用户系统与 5 张表数据模型,文档解析按页分块(带页码)存入 Qdrant,多 Agent 问答管线(检索→回答→引用校验)通过 SSE 流式输出。前端 React + Vite + Tailwind + shadcn/ui,ima 风格布局(左侧知识库/会话,右侧聊天)。

**Tech Stack:** FastAPI, SQLAlchemy+SQLite, Qdrant, LangGraph(现有迁移), OpenAI 兼容 LLM(DeepSeek), React 18, Vite, TailwindCSS, shadcn/ui, SSE。

**关键上下文:**
- 需求文档:`docs/plans/2026-08-07-ima-knowledge-base-prd.md`(逐节确认过)
- 复用来源:`E:\py_code\Agent\AgentTry\study-assistant\backend\core\{config,database,llm_adapter,vector_store}.py` 与 `utils\file_parser.py`
- 粒度说明:任务按"可验证增量"划分(30 分钟~半天),比标准 TDD 粒度大,因为本项目多数任务是迁移+集成,每任务都有明确验证命令与完成定义
- 每周五必须可演示;W3 核心闭环优先,其余可降级

---

## M0: 项目骨架与后端迁移(第 1 周 · 周一~周二)

### Task 1: 项目目录与基础文件

**Files:**
- Create: `backend/__init__.py`, `backend/core/__init__.py`, `backend/api/__init__.py`, `backend/api/routes/__init__.py`
- Create: `.gitignore`, `.env.example`, `requirements.txt`
- Create: `data/.gitkeep`, `data/uploads/.gitkeep`

**Step 1:** 建目录树,`.gitignore` 含 `venv/ __pycache__/ .env data/uploads/* !data/uploads/.gitkeep *.db`
**Step 2:** `requirements.txt` 复制自 study-assistant 并删除不迁移的依赖(不迁移 Git/OCR,但 pdfplumber/python-docx/sqlalchemy/fastapi/uvicorn/qdrant-client/openai/passlib/python-jose/bcrypt 保留)
**Step 3:** `.env.example` 复制现有并精简(LLM/EMBEDDING/QDRANT/JWT_SECRET/DATABASE_URL/STORAGE_DIR)

**验证:** `python -c "import fastapi, sqlalchemy, qdrant_client, openai"` 无报错
**Commit:** `chore: init project skeleton`

### Task 2: 迁移核心模块(config/database/llm_adapter)

**Files:**
- Create: `backend/core/config.py`, `backend/core/database.py`, `backend/core/llm_adapter.py`(从 study-assistant 复制)
- Modify: 删除 config 中不迁移的字段(git/ocr/search 相关),新增 `JWT_SECRET`、`JWT_EXPIRE_DAYS=7`、`DATABASE_URL`、`STORAGE_DIR`

**Step 1:** 复制三个文件
**Step 2:** 精简 config;database.py 的 `Base` 保留原样
**Step 3:** 冒烟:`uvicorn backend.main:app`(main.py 暂为最小入口,见 Task 4)

**验证:** `python -c "from backend.core.config import get_config; print(get_config().database_url)"` 输出 SQLite 路径
**Commit:** `chore: migrate config/database/llm_adapter`

### Task 3: 迁移向量存储并扩展 payload

**Files:**
- Create: `backend/core/vector_store.py`
- Modify: `add_documents()` 的 payload 增加 `user_id, doc_id, page, chunk_index`(PRD §5)

**Step 1:** 复制现有 vector_store.py
**Step 2:** 重写 `add_documents` 签名:`async def add_documents(self, kb_id, doc_id, chunks: list[dict], metadata=None)`,其中 `chunks` 为 `[{"text":..., "page": int, "chunk_index": int}]`,payload 含 `kb_id, doc_id, page, chunk_index, text, user_id`
**Step 3:** 新增 `async def delete_document(self, doc_id)`(按 payload 过滤删除)与 `async def search(self, kb_id, query, top_k=5)`(返回含 page/doc_id 的 dict 列表)
**Step 4:** 写测试 `tests/test_vector_store.py`(用 fake embedding 注入或直接调 `_embed` 的 mock)

**验证:** `pytest tests/test_vector_store.py -v` 全绿(需本地 Qdrant 运行,`docker run -p 6333:6333 qdrant/qdrant` 或下载二进制)
**Commit:** `feat: vector store with page-level payload`

### Task 4: 最小 FastAPI 入口 + 健康检查

**Files:**
- Create: `backend/main.py`(FastAPI 实例 + CORS + lifespan 初始化 DB + /health 检查 Qdrant 连通性)

**Step 1:** 写 main.py(参照 study-assistant 精简版)
**Step 2:** `uvicorn backend.main:app --port 8000`,访问 `/health` 返回 `{"status":"healthy","qdrant":true}`

**验证:** curl /health 返回 200 且 qdrant:true;停掉 Qdrant 再访问返回 qdrant:false(不崩溃)
**Commit:** `feat: app entry with health check`

### Task 5: 数据模型(5 张表)

**Files:**
- Create: `backend/models/database.py`(PRD §5 完整定义)
- Create: `tests/test_models.py`

**Step 1:** 定义 User/KnowledgeBase/Document/Conversation/Message,含级联删除(删库→删文档+会话;文档删除时由 service 层同步删向量)
**Step 2:** 测试:建表成功、级联删除行为、username 唯一约束

**验证:** `pytest tests/test_models.py -v` 全绿
**Commit:** `feat: ORM models (5 tables)`

---

## M1: 用户系统 + 知识库/文档/会话 API(第 1 周 · 周三~周五)

### Task 6: JWT 认证(注册/登录/依赖注入)

**Files:**
- Create: `backend/api/routes/auth.py`
- Create: `backend/core/security.py`(hash/verify 密码 + create/decode token)
- Modify: `backend/main.py` 注册 auth router,挂 `/api/v1/auth`
- Create: `tests/test_auth.py`

**Step 1:** security.py:passlib bcrypt 哈希、`python-jose` JWT(sub=user_id, exp=7d)
**Step 2:** auth.py:`POST /register`(校验用户名唯一、密码长度≥6)、`POST /login`(返回 `{"access_token":...}`)、`GET /me`
**Step 3:** 依赖注入 `get_current_user`(HTTPBearer,401 时抛 401)
**Step 4:** 测试:注册→登录→带 token 访问 /me;错误密码 401;重复用户名 400

**验证:** Swagger `/docs` 上完整跑通注册登录流程;`pytest tests/test_auth.py -v` 全绿
**Commit:** `feat: JWT auth (register/login/me)`

### Task 7: 知识库 CRUD(按用户隔离)

**Files:**
- Create: `backend/api/routes/knowledge_bases.py`
- Create: `tests/test_knowledge_bases.py`

**Step 1:** 路由:GET 列表(仅自己)、POST 创建、PUT 重命名、DELETE(级联删文档/会话/向量)
**Step 2:** 所有查询带 `user_id` 过滤;删除时先查库内文档逐个调用 vector_store.delete_document
**Step 3:** 测试:用户 A 看不到用户 B 的库;删除库后文档/会话清空

**验证:** Swagger 手动验证 + `pytest tests/test_knowledge_bases.py -v` 全绿
**Commit:** `feat: knowledge base CRUD with user isolation`

### Task 8: 文档上传与解析状态机

**Files:**
- Create: `backend/api/routes/documents.py`
- Create: `backend/services/document_service.py`
- Modify: `backend/utils/file_parser.py`(改造:`parse_pdf_pages()` 返回 `[{page_no, text}]`,`parse_docx_paragraphs()` 返回 `[{para_no, text}]`,TXT 按段落编号)
- Create: `backend/services/chunker.py`(不跨页分块,块大小/重叠从 config 读取,默认 800/100 字符)
- Create: `tests/test_file_parser.py`, `tests/test_chunker.py`

**Step 1:** file_parser 改造:PDF 按页、DOCX/TXT 按段落返回,保留 hash 去重(`get_file_hash`)
**Step 2:** chunker:输入页列表→输出 `[{text, page, chunk_index}]`,单页超长可拆多块,块不跨页
**Step 3:** document_service:校验扩展名/大小(20MB)→ 存盘 `{STORAGE_DIR}/uploads/{user_id}/{kb_id}/` → 建 Document(status=pending)→ 后台任务解析+分块+向量化+置 ready/failed
**Step 4:** documents.py:`POST /documents`(multipart 多文件)、`GET /documents?kb_id=`(含状态)、`DELETE /documents/{id}`(删盘+删向量)
**Step 5:** 测试:PDF 页码正确性、分块不跨页、重复上传去重、损坏文件→failed

**验证:** pytest 全绿;Swagger 上传 1 份真实 PDF → 轮询 GET 看到 pending→processing→ready 状态流转;停 Qdrant 上传 → failed 且 error_msg 可读
**Commit:** `feat: document upload pipeline with status machine`

### Task 9: 会话与消息 API

**Files:**
- Create: `backend/api/routes/chat.py`
- Create: `tests/test_chat.py`

**Step 1:** 会话:GET 列表(按 kb)、POST 新建(标题默认"新对话",可由首问生成)、DELETE
**Step 2:** 消息:GET 历史(按时间正序)、POST 提问(SSE,Task 14 前先返回占位流:"回答生成中,等待 W3 接入")
**Step 3:** 测试:会话隔离(其他用户的会话 404)、消息持久化

**验证:** pytest 全绿;Swagger 建会话→发消息→查历史
**Commit:** `feat: conversation & message API skeleton`

### 里程碑 W1 完成定义
- 后端 `/docs` 全部接口可用,注册→建库→传 PDF→建会话→提问(占位流)闭环跑通
- `pytest tests/ -v` 全绿
- 提交:每周五 `git tag w1` 后演示

---

## M2: 前端骨架(第 2 周)

### Task 10: Vite + React + Tailwind + shadcn 初始化

**Files:**
- Create: `frontend/`(Vite React-TS 模板)、`frontend/vite.config.ts`(代理 `/api` → `http://127.0.0.1:8000`)

**Step 1:** `npm create vite@latest frontend -- --template react-ts`
**Step 2:** 安装 TailwindCSS(标准 3 步:vite 插件 + tailwind.config + index.css 指令)
**Step 3:** 初始化 shadcn:`npx shadcn@latest init`(选择 zinc 色,无默认组件)→ `npx shadcn@latest add button input card dialog toast dropdown-menu scroll-area tooltip`
**Step 4:** 验证页面渲染一个 shadcn Button 成功

**验证:** `npm run dev` 打开页面显示 shadcn 按钮样式正确
**Commit:** `chore: frontend skeleton (vite+tailwind+shadcn)`

### Task 11: 路由与登录/注册页

**Files:**
- Create: `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/RegisterPage.tsx`, `frontend/src/lib/api.ts`(fetch 封装:baseURL、token 注入、401 跳转)
- Create: `frontend/src/lib/auth.ts`(token 存取 localStorage)

**Step 1:** 安装 react-router-dom;路由:`/login`、`/register`、`/`(MainPage,未登录重定向)
**Step 2:** LoginPage:表单(用户名/密码)→ 调 auth API → 存 token → 跳转 `/`
**Step 3:** RegisterPage 同构,成功即自动登录
**Step 4:** api.ts 统一错误处理(401 清 token 跳登录)

**验证:** 注册→登录→刷新页面仍在登录态;伪造 token 访问受保护页跳回登录
**Commit:** `feat: auth pages`

### Task 12: 主界面布局(ima 风格)

**Files:**
- Create: `frontend/src/pages/MainPage.tsx`(三栏:侧边栏/内容/聊天区,响应式折叠)
- Create: `frontend/src/components/Sidebar.tsx`, `frontend/src/components/KbList.tsx`, `frontend/src/components/ChatArea.tsx`(占位)

**Step 1:** 布局:左侧 260px 侧边栏(知识库列表+新建按钮+用户区),右侧主区(库内文档列表 Tab / 聊天 Tab)
**Step 2:** 用 Tailwind 实现(参考 ima/Notion 视觉:白底、细边框、圆角、灰字层次),不引入 UI 框架
**Step 3:** 空状态设计:无库时居中引导"创建你的第一个知识库"

**验证:** 布局在 1440px 与 900px 宽度下均不破版
**Commit:** `feat: main layout`

### Task 13: 知识库 CRUD UI + 文档列表/上传

**Files:**
- Create: `frontend/src/components/UploadDialog.tsx`(拖拽+多选+上传进度条 XMLHttpRequest `upload.onprogress`+失败重试)
- Create: `frontend/src/components/DocList.tsx`(状态徽章 pending/processing/ready/failed,轮询刷新)
- Create: `frontend/src/components/KbDialog.tsx`(新建/重命名)

**Step 1:** 知识库:列表、新建对话框、重命名、删除(confirm)
**Step 2:** 文档列表:选库后显示,状态徽章着色(processing=脉冲动画),3s 轮询直到无 processing
**Step 3:** 上传:拖拽高亮、多文件队列、逐文件进度条、成功/失败 toast、重复上传提示

**验证:** 上传 2 份 PDF 看到逐文件进度与状态流转;上传中断(停后端)显示失败可重试
**Commit:** `feat: kb CRUD + document upload UI`

### 里程碑 W2 完成定义
- 注册登录→建库→上传 PDF→看到解析状态 全链路走通
- 页面质感接近 ima(截图对比 PRD 验收标准 4)

---

## M3: 多 Agent 问答管线 + 流式聊天(第 3 周)

### Task 14: 检索 Agent

**Files:**
- Create: `backend/agents/retriever_agent.py`
- Create: `backend/core/retrieval.py`(分块参数与向量检索封装,迁移现有两阶段检索思路简化:top-k 直接取 chunk,不强制 parent)
- Create: `tests/test_retrieval.py`

**Step 1:** 输入 question + kb_id → vector_store.search(kb_id, question, top_k=5)
**Step 2:** 意图判断:问题含"最新/现在/网络/搜索"等词 → 并行触发 `web_search`(从 study-assistant 迁移 utils/web_search.py,无 key 时跳过)
**Step 3:** 返回 `{"chunks": [{text, doc_id, page, doc_name, score}], "web_results": [...]}`

**验证:** 对已入库 PDF 提问,返回 chunk 的 page 与文档页码一致;pytest 绿
**Commit:** `feat: retriever agent`

### Task 15: 回答 Agent(流式 + 引用规则)

**Files:**
- Create: `backend/agents/answer_agent.py`
- Create: `backend/agents/citation_agent.py`(先写校验逻辑,前端接入在 W4)

**Step 1:** 系统 prompt(引用规则):
```
你基于以下检索片段回答问题。规则:
1. 回答内容来自某片段时,句末标注 [n](n 为片段编号)
2. 无依据的部分明确说明"知识库中未找到相关依据"
3. 回答末尾输出"## 引用"列表: [n] 文档名, 第x页
4. 不要编造片段中不存在的内容
```
**Step 2:** 上下文:最近 10 条消息 + 检索片段(每个片段截断 800 字,附编号)
**Step 3:** `async def stream(question, history, chunks) -> AsyncGenerator[dict]`:yield status → llm.astream 逐 token yield chunk → 完成后 yield citations

**验证:** 用真实 LLM(DeepSeek)对已入库 PDF 提问,输出含 [1][2] 标注与引用列表
**Commit:** `feat: answer agent with citation rules`

### Task 16: SSE 问答端点

**Files:**
- Modify: `backend/api/routes/chat.py`(POST 消息改为真 SSE)
- Create: `tests/test_chat_stream.py`(fake LLM 注入)

**Step 1:** 实现 SSE:`StreamingResponse(media_type="text/event-stream")`,事件序列按 PRD §6.2
**Step 2:** 生成完成后:消息+引用写入数据库,`done` 事件返回 message_id
**Step 3:** fake LLM(在 llm_adapter 加 `LLMProvider` 抽象,测试注入固定输出)→ 测试事件序列完整

**验证:** curl `-N` 看到 status→chunk→done 事件流;pytest 绿
**Commit:** `feat: SSE chat endpoint`

### Task 17: 前端流式聊天(打字机)

**Files:**
- Create: `frontend/src/components/ChatArea.tsx`(重写为真实实现)
- Create: `frontend/src/lib/stream.ts`(fetch POST + ReadableStream 解析 SSE:按 `\n\n` 切分事件,分发 status/chunk/citations/done/error)

**Step 1:** stream.ts:通用 SSE 消费者(约 60 行,事件回调)
**Step 2:** ChatArea:消息气泡(用户右、AI 左)、发送中状态、逐字追加渲染、中断重试按钮
**Step 3:** 会话切换加载历史消息;新建会话

**验证:** 真实提问:打字机逐字输出、中断(停 LLM key)后保留已输出并可重试
**Commit:** `feat: streaming chat UI`

### Task 18: 会话管理 UI

**Files:**
- Create: `frontend/src/components/ConversationList.tsx`(按库分组,新建/重命名/删除)

**Step 1:** 侧边栏会话列表:当前库下的会话、新建按钮、删除确认
**Step 2:** 首次提问自动生成会话标题(取问题前 20 字)

**验证:** 切换会话恢复历史;新建/删除会话正常
**Commit:** `feat: conversation management UI`

### 里程碑 W3 完成定义
- **核心闭环可演示**:注册→建库→传 PDF→提问→流式回答(打字机)全程无卡顿
- 回答有 [n] 标注与引用列表(校验接入 W4)
- 会话历史可回溯

---

## M4: 引用溯源 + 打磨交付(第 4 周)

### Task 19: 引用校验 Agent

**Files:**
- Modify: `backend/agents/citation_agent.py`(完整实现)
- Create: `tests/test_citation.py`

**Step 1:** 校验逻辑:对回答中每个 `[n]`,取对应检索片段,计算引用上下文与片段的重叠率(字符重叠/编辑距离/简单 Jaccard),阈值 0.6
**Step 2:** 低于阈值 → `verified: false`(标注"该结论无直接引用来源");通过 → 附 doc_name/page/snippet
**Step 3:** 从回答文本中解析 `[n]` 位置(正则 `\[\d+\]`),供前端角标渲染

**验证:** 构造"真实引用"与"编造引用"两类回答,校验结果正确;pytest 绿
**Commit:** `feat: citation validator agent`

### Task 20: citations 事件接入 + 前端引用卡片

**Files:**
- Modify: `backend/api/routes/chat.py`(SSE 增加 citations 事件,含 verified 标记)
- Create: `frontend/src/components/CitationCard.tsx`, `frontend/src/components/AnswerMarkdown.tsx`(渲染 [n] 角标)

**Step 1:** 后端:生成完成 → citation_agent 校验 → citations 事件下发
**Step 2:** 前端:回答渲染——Markdown 渲染(marked/markdown-it)+ [n] 替换为可点击角标
**Step 3:** 点击角标 → 弹出引用卡片(文档名/页码/原文片段);底部引用列表;verified=false 灰显
**Step 4:** 消息持久化时 citations 存入 messages.citations_json,历史消息可重现引用

**验证:** 对已入库 PDF 提问 → 角标可点、卡片信息与 PDF 页码一致;伪造场景灰显
**Commit:** `feat: citation cards in chat UI`

### Task 21: 集成测试(全链路, fake LLM)

**Files:**
- Create: `tests/test_e2e_flow.py`(注册→建库→上传(临时 PDF)→轮询 ready→提问→校验事件序列与引用)

**Step 1:** fixture:临时 PDF(pdfplumber 可解析的文本型,用 reportlab 或手写最小 PDF)、fake LLM
**Step 2:** 全链路断言:文档状态流转、SSE 事件完整、citations 正确、消息入库

**验证:** `pytest tests/ -v` 全绿(不依赖真实 API key)
**Commit:** `test: e2e flow with fake LLM`

### Task 22: README + 架构图 + 启动脚本

**Files:**
- Create: `README.md`(按 PRD §14 清单)
- Create: `docker-compose.yml`(qdrant 服务)或 `scripts/start.sh`(检查依赖+启动 Qdrant+后端+前端)
- Create: `.env.example` 最终版(含注释)

**Step 1:** README:mermaid 架构图(上传链路/问答链路两条)、选型理由表、启动命令、截图
**Step 2:** 启动脚本:一键拉起 Qdrant + uvicorn + vite

**验证:** 全新克隆后按 README 一条命令跑通
**Commit:** `docs: README with architecture diagram`

### Task 23: 验收 + 演示视频

**Step 1:** 按 PRD §11 验收标准逐条过(3 份真实 PDF、5 个典型问题、断网/停 Qdrant 错误提示)
**Step 2:** 录 2 分钟演示视频(登录→上传→解析→问答→引用溯源)

**验证:** 验收清单 6 条全过
**Commit:** `chore: final polish`(如无改动仅打 tag)

---

## 执行说明

- **顺序执行**:任务 1~23 严格按序,每任务完成定义(验证命令)通过后进入下一任务
- **迁移注意**:复制现有代码后必须全局搜索 `study_assistant`/`StudyAssistant` 等命名并替换为项目名;删掉迁移模块中对已删功能的 import
- **风险触发点**(PRD §15):LLM 引用格式不稳定 → Task 15/16 先跑通"无引用"降级路径;Qdrant 维度错误 → 复用现有报错提示
- **周五演示**:W1/W2/W3 末各 `git tag` 一次

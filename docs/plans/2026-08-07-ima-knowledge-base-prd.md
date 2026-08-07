# 智能知识库问答系统(Web 版 ima)开发需求文档

- 版本:v1.0
- 日期:2026-08-07
- 状态:已确认(经 brainstorm 讨论,与用户逐节确认)
- 定位:个人能力展示作品(面试作品集),Agent/AI 方向为主场,前后端为辅助能力展示

---

## 1. 项目背景与定位

模仿腾讯 ima 知识库的核心形态,做一个"小而精"的 MVP:用户上传 PDF/Word/TXT 文档,系统自动解析存入个人知识库,用户基于知识库进行带**引用溯源**的 AI 智能问答。

**不是** ima 的全功能复刻。不做:多人协作、收藏夹、标签体系、社区分享、移动端。

### 核心设计原则

1. **Agent 是主场**:AI 部分(多 Agent 问答管线、引用校验)做得深、讲得清,是答辩核心亮点。
2. **前后端克制**:视觉上先进(Notion/ima 质感),复杂度上克制——所有出 bug 的地方,使用者必须能独立修复或借助 AI 修复。
3. **可迁移部署**:本地运行为主,所有外部依赖通过配置抽象,将来切云只改 `.env` 不改代码。
4. **复用优先**:现有 `study-assistant` 项目的后端(RAG、文件解析、LLM 适配、SSE 流式)约 60% 代码直接迁移复用,不推倒重来。

---

## 2. 目标与非目标

### 目标(必须交付)

| 编号 | 功能 | 说明 |
|------|------|------|
| F1 | 用户系统 | 注册/登录,极简 JWT,数据按用户隔离(私有知识库) |
| F2 | 文档上传 | 拖拽/点击上传 PDF/DOCX/TXT/MD,进度条,大小限制 20MB,支持多文件 |
| F3 | 文档解析入库 | 解析→按页分块→向量化→存入 Qdrant,文档状态机可见 |
| F4 | 知识库管理 | 创建/重命名/删除知识库,查看库内文档列表,删除单个文档 |
| F5 | 智能问答 | 基于知识库的多轮对话,SSE 流式打字机输出 |
| F6 | 引用溯源 | 回答中引用标注 [1][2],点击显示"引自《xxx》第 x 页"+原文片段 |
| F7 | 会话管理 | 每个知识库多个会话,新建/重命名/删除,消息持久化 |
| F8 | 部署与文档 | README(含架构图)、本地一键启动脚本、演示视频 |

### 非目标(明确不做,防范围蔓延)

- ❌ 后台管理、用户统计、增删改查后台
- ❌ 多人协作、文档分享
- ❌ 收藏夹、标签、笔记、脑图
- ❌ 费曼学习、学习日志、可学性判断(现有项目的这些功能不迁移)
- ❌ Git 仓库导入、图片 OCR(现有功能,不迁移;后续可扩展)
- ❌ 海量文件支撑(按 3~5 份 PDF 的性能设计即可)
- ❌ 前端组件单元测试(手动验证为主)

---

## 3. 用户场景

**场景 A(核心)**:用户注册登录 → 创建知识库"机器学习论文" → 拖入 3 份 PDF → 看到解析进度 → 进入聊天 → 提问"transformer 的 attention 机制如何计算?" → AI 流式回答,标注 [1][2],点开看到引自《xxx.pdf》第 3 页和原文片段 → 追问细节,多轮对话。

**场景 B**:用户换设备登录,看到自己的知识库、会话和聊天记录,与他人数据完全隔离。

---

## 4. 技术架构

### 4.1 架构图

```
┌──────────────────────────────────────────────────────┐
│ 前端  React + Vite + TailwindCSS + shadcn/ui         │
│  登录/注册页                                          │
│  主界面(ima 风): 左侧=知识库+会话列表, 右侧=聊天区    │
│  上传拖拽+进度条 · 打字机流式 · 引用卡片              │
└───────────────────────┬──────────────────────────────┘
                        │ REST + SSE(流式)
┌───────────────────────▼──────────────────────────────┐
│ 后端  FastAPI                                         │
│  用户系统: JWT 注册/登录, 所有数据按 user_id 隔离     │
│  文档管线: 上传→解析(记录页码)→分块→向量化→Qdrant     │
│  多 Agent 问答: 检索Agent→回答Agent→引用校验Agent     │
│  SSE 流式(携带 citation 元数据)                       │
└───────────────────────┬──────────────────────────────┘
        ┌────────┬──────┴─────┬───────────┐
     SQLite   Qdrant     本地磁盘     LLM API
   (可切PG) (可切云)    (可切S3)   (DeepSeek 等)
```

### 4.2 技术选型与理由

| 层级 | 选型 | 理由(写入 README/答辩) |
|------|------|------------------------|
| 前端 | React 18 + Vite + TailwindCSS + shadcn/ui | 组件代码全量落入项目,可读可修,契合"bug 可控"原则;视觉即 Notion/ima 极简质感;Vite 无 SSR 复杂度,部署即静态托管 |
| 后端 | FastAPI + Uvicorn | 自动生成 Swagger API 文档,接口规范可见;与现有代码一致 |
| AI 编排 | LangGraph + 手写 RAG(不用 LangChain) | 现有代码成熟;手写分块/两阶段检索能讲清原理,面试更被认可;LangGraph 支撑多 Agent 编排 |
| 向量库 | Qdrant(本地 Docker/二进制) | 已迁移复用;支持 payload 过滤(按 kb/doc 隔离检索);有云版可切换 |
| 关系库 | SQLite(可切 PostgreSQL) | SQLAlchemy 切换连接串即可 |
| LLM | OpenAI 兼容 API(DeepSeek 优先) | 便宜、国内可访问、兼容 ollama 本地模型 |
| Embedding | 已有三种后端:本地 / Ollama / API | 按 .env 切换,本地演示零成本 |
| 前端状态 | 轻量:React Query(或手写 fetch)+ 局部 state | 不用 Redux,状态管理复杂度最小化 |

### 4.3 复用清单(迁移自 study-assistant)

| 现有代码 | 处理 |
|----------|------|
| `core/config.py`(.env 配置) | ✅ 直接迁移 |
| `core/database.py`(SQLAlchemy 引擎) | ✅ 直接迁移 |
| `core/llm_adapter.py`(OpenAI 兼容 + astream 流式) | ✅ 直接迁移 |
| `core/vector_store.py`(Qdrant 封装) | ✅ 迁移,payload 增加 doc_id/page 字段 |
| `utils/file_parser.py` | 改造:`_parse_pdf` 改为按页返回 `page_texts[]`,DOCX 按段落编号 |
| 分块逻辑(retrieval 管线) | 迁移 + 改为不跨页分块、payload 带页码 |
| 问答 prompt 思路 | 改造为引用标注规则 |
| SSE 流式思路(app.js 中的实现) | 前端用 fetch + ReadableStream 重写 |
| 其余(费曼/日志/可学性/Git/OCR) | ❌ 不迁移 |

---

## 5. 数据模型(5 张表 + Qdrant payload)

```python
# SQLite / SQLAlchemy
users(id PK, username UNIQUE, password_hash)              # passlib bcrypt 加密
knowledge_bases(id PK, user_id FK, name, description, created_at, updated_at)
documents(id PK, kb_id FK, filename, file_path, file_size,
          status,            # pending / processing / ready / failed
          error_msg, page_count, chunk_count, created_at)
conversations(id PK, kb_id FK, user_id FK, title, created_at, updated_at)
messages(id PK, conversation_id FK, role,        # user / assistant
         content TEXT, citations_json JSON, created_at)

# Qdrant 单 collection(按 payload 过滤隔离)
# payload: kb_id, doc_id, page(页码), chunk_index, text
# TXT/MD 无页码 → page 存段落号;DOCX → 段落号
```

删除级联:删用户→删库;删库→删文档+会话;删文档→删对应 Qdrant 向量(用 doc_id 过滤删除)。

---

## 6. 核心数据流

### 6.1 上传链路(异步任务)

```
前端拖拽/选择 → POST /api/v1/documents (multipart, 单文件或批量)
  → 服务端校验类型/大小 → 存本地磁盘(data/uploads/{user_id}/{kb_id}/)
  → 创建 Document 记录(status=pending)
  → 后台任务(BackgroundTask 或独立 worker):
      解析(按页提取 page_texts[]) → 分块(不跨页,chunk 携带页码)
      → 向量化(批量 embed) → upsert 到 Qdrant
      → status=ready(成功) / failed(带 error_msg)
  → 前端轮询 GET /api/v1/documents?kb_id= 或 SSE 推送状态,渲染进度
```

- 解析阶段进度通过文档状态机呈现(显示"解析中 → 向量化中 → 完成"),无需真实百分比;上传进度条用 XMLHttpRequest 的 `upload.onprogress` 实现。
- 同文件重复上传:按内容 hash 去重(可复用现有 `get_file_hash`),提示"该文件已在知识库中"。

### 6.2 问答链路(SSE 流式)

```
POST /api/v1/chat/{conversation_id}/messages
  (不等待响应,以 SSE 返回,前端 fetch + ReadableStream 消费)

事件序列:
  event: status   {"text": "正在检索知识库..."}
  event: chunk    {"text": "..."}              # 逐字/逐token 输出,打字机效果
  event: citations {"items": [{"index":1,"doc_name":"xxx.pdf","page":3,"snippet":"..."}]}
  event: done     {"message_id": "..."}
  event: error    {"text": "..."}              # 中断时发出,已输出内容保留
```

- 历史消息:页面进入会话时拉取 `GET /api/v1/chat/{id}/messages`,完整消息记录直接渲染(非流式)。
- 多轮对话上下文:最近的 N 条消息(如 10 条)拼入 prompt,复用现有 ConversationContext 思路。
- 检索为空:Agent 明说"知识库中未找到相关内容",不编造。

### 6.3 多 Agent 问答管线(答辩核心亮点)

```
[RetrieverAgent]  用户问题 → 向量检索 top-k(按会话所在 kb 过滤)
                  问题含"最新/网络/搜索"等意图词 或 向量得分过低 → 并行触发网络搜索
[AnswerAgent]     拼装 prompt(系统规则+历史+检索片段) → LLM 流式生成
                  规则:引用处标注 [1][2],回答末尾输出引用列表
[CitationAgent]   生成完成后,逐条校验 [n] 对应的片段与检索到的 chunk 原文
                  是否匹配(子串/相似度阈值);伪造引用剔除并标注
```

校验结果随 `citations` 事件下发,被剔除的引用标记 `"verified": false`,前端灰显并提示"该结论无直接引用来源"。

---

## 7. 引用溯源设计(核心亮点)

1. **页码来源**:PDF 用 pdfplumber 按页提取 `page_texts[]`;分块**不跨页**(单页文本过长时可拆分,但块不越过页边界),每个 chunk 记录 `page`。TXT/MD 用段落号,DOCX 用段落号。
2. **检索返回**:Qdrant payload 含 `doc_id / page / chunk_index / text / kb_id`,检索结果即带页码。
3. **生成规则**:AnswerAgent 的 system prompt 强制:
   - 回答内容来自检索片段时,在句子末尾标注 `[n]`(n 为片段编号)
   - 回答末尾输出引用列表:编号 → 文档名 + 页码 + 原文片段
   - 无依据时直接说"未找到",不编造引用
4. **校验**:CitationAgent 比对回答中的 `[n]` 与检索片段,剔除伪造引用(相似度低于阈值)。
5. **前端渲染**:回答文本中 `[n]` 渲染为可点击角标;点击弹出引用卡片(文档名、页码、原文片段);底部可展开"引用列表"。校验失败的角标灰显。
6. **Prompt 注入**:引用列表通过 SSE 的 `citations` 事件下发,前端不解析 LLM 原文的引用格式,避免脆弱的字符串解析。

---

## 8. 用户系统设计

- 注册:`POST /api/v1/auth/register`(username + password,bcrypt 加密存储)
- 登录:`POST /api/v1/auth/login` → 返回 JWT(access token,过期时间 7 天)
- 鉴权:FastAPI 依赖注入 `get_current_user`,除 auth 外的所有路由强制校验
- 隔离:所有查询强制带 `user_id`(知识库/会话/文档),Qdrant payload 带 `user_id` 一并过滤
- 前端:token 存 localStorage,fetch 拦截器自动附带;401 时跳登录页
- 不做:邮箱验证、找回密码、刷新 token(MVP 从简)

---

## 9. API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/auth/register | 注册 |
| POST | /api/v1/auth/login | 登录(返回 JWT) |
| GET | /api/v1/knowledge-bases | 我的知识库列表 |
| POST | /api/v1/knowledge-bases | 创建知识库 |
| PUT/DELETE | /api/v1/knowledge-bases/{id} | 重命名/删除 |
| POST | /api/v1/documents | 上传文档(多文件) |
| GET | /api/v1/documents?kb_id= | 文档列表(含解析状态) |
| DELETE | /api/v1/documents/{id} | 删除文档(同步清向量) |
| GET/POST | /api/v1/conversations?kb_id= | 会话列表/新建 |
| DELETE | /api/v1/conversations/{id} | 删除会话 |
| GET | /api/v1/conversations/{id}/messages | 历史消息 |
| POST | /api/v1/conversations/{id}/messages | 提问(SSE 流式) |
| GET | /health | 健康检查(含 Qdrant 状态) |

---

## 10. 错误处理

| 场景 | 处理 |
|------|------|
| 文件类型不支持 / 超 20MB | 前端预校验 + 后端二次校验,toast 提示 |
| 解析失败(损坏 PDF) | 文档 status=failed + error_msg,前端显示原因,可删除重传 |
| Qdrant 未启动 | /health 标记依赖状态;接口返回 503 "向量库不可用,请先启动 Qdrant" |
| LLM 超时/流式中断 | 保留已输出内容,SSE 发 error,前端提示"回答中断,点击重试" |
| 检索结果为空 | Agent 明确告知,不编造 |
| 引用校验失败 | 剔除并灰显标注"无直接引用来源" |
| token 过期 | 401 → 前端跳登录页 |
| 同名文件重复上传 | 内容 hash 去重,提示已存在 |

---

## 11. 测试与验收标准

### 测试策略

- **单元测试(pytest)**:文件解析(页码提取正确性)、分块(不跨页、页码正确)、引用校验(伪造引用被剔除、真实引用通过)、用户密码哈希
- **集成测试(pytest)**:上传→解析→检索→问答全链路,使用 **fake LLM**(注入固定输出,不消耗 API,离线可跑)
- **前端**:手动验收清单(见下),不强制组件测试

### 验收标准(完成定义)

1. 注册登录后,3 份真实 PDF(含中文)上传成功,状态机走完 → ready
2. 5 个典型问题(概念解释、细节定位、跨文档比较、无依据问题)全部回答合理
3. 引用溯源:回答中引用点开能看到正确的文档名+页码+原文;编造引用场景(故意提问无依据内容)不出现伪造引用
4. 打字机流式、上传进度条、会话切换、知识库切换全部流畅
5. 断网/停 Qdrant/无效 token 时,前端有明确错误提示,不白屏不卡死
6. `pytest tests/ -v` 全绿

---

## 12. 4 周开发排期

| 周 | 内容 | 交付物 |
|----|------|--------|
| W1 | 新建项目骨架;迁移复用后端核心(config/database/llm/vector/file_parser);用户系统;知识库/文档/会话 API;5 张表 | 后端 API 全通,Swagger 可测;pytest 单元测试(解析/分块)绿 |
| W2 | 前端骨架(Vite+Tailwind+shadcn/ui);登录/注册页;主界面布局(侧边栏+聊天区);上传组件+进度条;文档状态轮询展示 | 能注册登录、上传文件并看到解析状态 |
| W3 | 多 Agent 问答管线(检索/回答/引用校验);SSE 流式接入前端;打字机效果;会话管理 UI;历史消息加载 | 核心闭环可演示(上传→提问→流式回答) |
| W4 | 引用溯源前端(角标渲染+引用卡片);README(背景/选型理由/架构图/启动命令);启动脚本(docker-compose 或一键脚本);集成测试;录 2 分钟演示视频 | 完整交付,可演示可部署 |

**节奏原则**:W3 核心闭环放在月中安全位置;W4 只做打磨不赌赶工;每周五有可演示成果。

---

## 13. 部署方案

### 本地部署(默认)

```
后端: uvicorn backend.main:app --port 8000
依赖: Qdrant 本地(提供启动脚本 / docker-compose.yml)
前端: npm run dev(Vite,代理 /api 到 8000)
```

### 上云切换(配置抽象,不改代码)

| 组件 | 本地 | 云(将来) | 切换方式 |
|------|------|-----------|---------|
| 数据库 | SQLite | PostgreSQL(Supabase/Neon 免费) | `.env` 改 DATABASE_URL |
| 向量库 | Qdrant 本地 | Qdrant 云 / Pinecone | `.env` 改 host+key |
| 文件存储 | 本地磁盘 | S3 兼容(OSS/MinIO) | 预留存储接口,`.env` 切换 |
| LLM/Embedding | DeepSeek/Ollama | 任意 OpenAI 兼容 | `.env` 已支持 |
| 前端 | Vite dev | Vercel 静态托管 | 静态产物直传 |

### 展示方式

- 本地演示 + 录屏视频(2 分钟:B 站/YouTube 不公开链接)
- README 含架构图(mermaid)+ 启动命令
- 若演示环境需要远程访问,可用内网穿透(花生壳/ngrok)临时暴露

---

## 14. README 内容清单(面试官会看)

1. 项目背景与定位(一句话:Web 版 ima 精简实现)
2. 架构图(mermaid)+ 完整数据流说明
3. 技术选型理由表(为什么 React+Vite 而非 Next、为什么手写 RAG 而非 LangChain、为什么 Qdrant)
4. 功能演示 GIF/截图(登录、上传、问答、引用卡片)
5. 本地启动命令(复制即用)
6. 测试运行方式 + 测试覆盖说明
7. 未来扩展方向(多模态 OCR、混合检索、Rerank、部署上云)

---

## 15. 风险与避坑

| 风险 | 应对 |
|------|------|
| 中文 PDF 解析效果差(扫描件无文本层) | MVP 只承诺文本型 PDF;README 说明限制;扫描件方案(OCR)列为扩展 |
| 引用标注格式不稳定(LLM 不按规则输出) | 引用列表走 SSE 结构化下发,不解析 LLM 原文;校验 Agent 兜底 |
| 分块质量影响回答 | 分块策略参数(块大小/重叠)在 config 中可调,答辩可讲调优过程 |
| Qdrant 维度不匹配(换 embedding 模型) | 复用现有维度校验逻辑,报错提示重建 collection |
| 前端出 bug 难修 | shadcn 组件源码在项目内;复杂逻辑集中在 lib/api.ts 单文件;不引入 Redux/SSR 等重概念 |
| 时间超支 | W3 核心闭环优先;引用溯源前端可降级为"引用列表面板"(不做角标内嵌) |

---

## 附:与现有项目的关系

- 新项目 `ima-knowledge-base/` 独立于 `study-assistant/`,独立 git 仓库,面试展示整洁
- 后端代码按 4.3 复用清单迁移,不复制无关模块(费曼/日志/可学性/Git/OCR)
- 前端全新编写,不复用原生 JS

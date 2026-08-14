# DEV-013 设计文档 — 手写轻量 MCP 工具注册发现系统

> 日期:2026-08-14
> 状态:✅ 已批准(2026-08-14)
> 版本:v1.1.0

## 背景

DEV-013(缺少 MCP 外部工具协议扩展):系统无任何现代 Agent 通信协议集成,工具全部硬编码(向量检索、关键词检索、Tavily 网络搜索),无法动态接入第三方 MCP 服务器。

本次目标:**自己搭建一个简单的 MCP 注册发现系统**,把现有工具(联网搜索、知识库检索、知识库状态)封装成 MCP 工具对外暴露,同时把内部 retriever_agent 的硬编码调用改为走注册表(进程内直调),验证"工具协议化"收益。后续可扩展更多工具。

## 已确认的决策

| 决策点 | 结论 |
|---|---|
| MCP 方向 | 自建 MCP Server 暴露现有工具(不是接第三方 client) |
| 实现方式 | 手写轻量 MCP:JSON-RPC 2.0 子集(initialize / ping / tools/list / tools/call / notifications/initialized),不引入 mcp SDK |
| 传输层 | HTTP + SSE over FastAPI(经典 SSE:GET /sse + POST /messages) |
| 架构 | 四层分离:registry / protocol / transport / tools |
| 鉴权 | 共享密钥 `MCP_API_KEY`,query 参数或 Authorization: Bearer 头;未配置时端点 404 禁用 |
| 工具范围 | web_search(必选)、vector_search、kb_status |
| 内部重构 | retriever_agent 改为通过注册表调用工具(进程内直调,无 HTTP 回环) |

## 架构

```
backend/mcp/
├── registry.py    # Tool 类 + ToolRegistry:注册/自描述/参数校验,纯 Python 无 I/O
├── protocol.py    # JSON-RPC 2.0 编解码 + MCP 方法分发,纯函数无 I/O
├── transport.py   # FastAPI router:GET /mcp/sse + POST /mcp/messages,鉴权、会话管理
└── tools.py       # web_search / vector_search / kb_status,复用 backend/core/retrieval.py
```

### registry.py — 工具注册表(核心扩展点)

- `Tool` dataclass:`name` / `description` / `input_schema`(JSON Schema dict)/ `handler`(async 函数,收 dict 参数,返回 dict)
- `ToolRegistry`:
  - `register(tool)` — 重复名称抛错
  - `list_tools() -> list[Tool]` — 供 `tools/list` 与内部发现
  - `async call(name, args) -> dict` — 查找 + 按 schema 校验参数(缺失/类型错抛 `ToolParamError`)+ 执行 handler
- 模块级单例 `registry = ToolRegistry()`,`@tool(...)` 装饰器注册
- 注册表即"注册发现系统"本体:`tools/list` 是发现接口,加新工具只动 tools.py + 一行注册

### protocol.py — MCP 协议层(纯函数)

- `parse_message(raw: str) -> dict` — JSON 解析,失败返回 -32700 错误响应
- `handle_request(msg: dict, registry) -> dict | None` — 方法分发:
  - `initialize` → `{protocolVersion: "2025-03-26", capabilities: {tools: {}}, serverInfo: {name, version}}`
  - `notifications/initialized` → None(通知无响应)
  - `ping` → `{}`
  - `tools/list` → `{tools: [{name, description, inputSchema}]}`
  - `tools/call` → 调注册表;成功 `{content: [{type: "text", text: json.dumps(result, ensure_ascii=False)}]}`;工具异常 `{content: [...], isError: true}`
  - 未知方法 → -32601;参数校验失败 → -32602;内部异常 → -32603
- 无 `id` 的请求(通知)除 initialized 外静默忽略

### transport.py — SSE 传输层(FastAPI router)

- `GET /mcp/sse` — 鉴权 → 生成 session_id → SSE 流,先发 `event: endpoint, data: /mcp/messages?session_id=<id>` → 阻塞读 session 队列,有消息发 `event: message`
- `POST /mcp/messages?session_id=<id>` — 鉴权 + 校验 session → parse → handle → 响应推入 session 队列
- 会话表:内存 dict `{session_id: asyncio.Queue}`,SSE 流断开(生成器 finally)时清理
- `main.py` 挂载 router

### tools.py — 三个工具

| 工具 | 参数 | 返回 | 底层 |
|---|---|---|---|
| `web_search` | `query`(必填), `max_results`(默认 5) | `{results: [{title, url, snippet}]}` | `retrieval.web_search` |
| `vector_search` | `kb_id`(必填), `question`(必填), `top_k`(默认 5) | `{chunks: [{score, text, doc_id, page, doc_name, search_type}]}` | `retrieval.vector_search` |
| `kb_status` | `kb_id`(必填) | `{kb_id, name, document_count, ready_count, chunk_count}` | DB 查询 KnowledgeBase/Document |

## 数据流

**外部客户端(如 MCP Inspector):**

```
GET /mcp/sse?api_key=xxx
  ← SSE 流 + endpoint 事件(/mcp/messages?session_id=abc)
POST /mcp/messages?session_id=abc  {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{...}}
  → JSON-RPC 结果经 SSE 流 message 事件返回
```

**内部 agent(重构后 retriever_agent):**

```python
chunks = (await registry.call("vector_search", {"kb_id": kb_id, "question": question, "top_k": top_k}))["chunks"]
web_results = []
if force_web or detect_web_intent(question):
    web_results = (await registry.call("web_search", {"query": question}))["results"]
```

- 返回结构 `{"chunks": [...], "web_results": [...]}` 不变 → chat.py 与现有测试不动
- `detect_web_intent` 仍直接 import(意图判断属于编排逻辑)
- `kb_status` 纯对外,不进内部流水线
- 内部调用进程内直调,**不经过**鉴权层,鉴权只存在于 SSE 边界

## 协议与错误处理

| 场景 | 处理 |
|---|---|
| JSON 解析失败 | -32700 Parse error |
| 缺 jsonrpc/method、id 类型错 | -32600 Invalid request |
| 未知方法 | -32601 Method not found |
| 工具参数缺失/类型错 | -32602 Invalid params(附带缺失字段名) |
| 工具 handler 抛异常 | 返回 `{content:[…], isError: true}`(不走 JSON-RPC error) |
| 无 id 的请求(通知) | 除 initialized 外静默忽略 |
| 未知 session_id | POST 404 |
| 鉴权失败 | 401 |

关键取舍:**不强制 initialize 先行**。规范要求先握手,但严格校验会繁琐化手写客户端/curl 调试;协议层只做方法分发,不维护会话协议状态机(会话仅用于 SSE 消息路由)。

## 鉴权

- 新增环境变量 `MCP_API_KEY`;未配置时 MCP 端点整体 404 禁用(与 Tavily 未配密钥优雅跳过风格一致)
- GET / POST 均支持 `?api_key=` query 参数或 `Authorization: Bearer` 头(头优先)
- 密钥比较用 `secrets.compare_digest` 常量时间比较

## 配置变更

- `config.py` 增加 `mcp_api_key` 字段,读 `MCP_API_KEY`
- `.env.example` 增加 `MCP_API_KEY=` 说明行
- `main.py` 挂载 MCP router

## 测试计划(全部离线,不烧 API、不联网)

| 文件 | 覆盖点 |
|---|---|
| `tests/test_mcp_registry.py` | 注册后 list_tools 自描述;重复名称抛错;call 正常执行;参数缺失/类型错抛 ToolParamError;未知工具抛错 |
| `tests/test_mcp_protocol.py` | initialize 响应字段;notifications/initialized → None;ping → {};tools/list 快照;tools/call 成功 content;工具异常 isError;坏 JSON -32700;缺字段 -32600;未知方法 -32601;参数错 -32602 |
| `tests/test_mcp_transport.py` | 无/错 api_key → 401;对 api_key → SSE + endpoint 事件;完整握手(initialize → tools/list → tools/call)SSE 往返;未知 session 404;未配置 MCP_API_KEY → 404 |
| `tests/test_mcp_tools.py` | monkeypatch retrieval.web_search / vector_search;kb_status 用临时 SQLite 断言统计 |
| 回归 | 现有全部测试全绿,尤其 test_retrieval / test_chat_stream 走重构后 retriever 链路 |

## 手动验证(MCP Inspector)

本地启动后,浏览器打开 MCP Inspector,填:
- URL:`http://localhost:8000/mcp/sse`
- Headers:`Authorization: Bearer <MCP_API_KEY>`

可视化调用三个工具看返回 —— 对外演示"注册发现系统"最直观的方式。写入 README。

## 交付物

1. `backend/mcp/` 四文件 + main.py 挂载 + config.py / .env.example 配置
2. retriever_agent.py 内部重构(行为不变)
3. 4 个新测试文件 + 全套回归绿
4. README 更新:架构图加 MCP 层、功能列表、.env 说明、MCP 连接示例
5. DEV_LOG.md DEV-013 标记 ✅(解决版本 v1.1.0),README 变更记录同步

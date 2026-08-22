"""LLM 适配器 - 支持 OpenAI 兼容接口"""
import logging
import asyncio
import inspect
import time
from abc import ABC, abstractmethod
from typing import Optional, AsyncGenerator
from openai import AsyncOpenAI
from .config import get_config
from backend.utils import detail_trace

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 抽象接口 - 生产实现为 LLMAdapter, 测试注入 FakeLLM"""

    @abstractmethod
    async def ainvoke(self, messages: list, system_prompt: str = None, **kwargs) -> str:
        ...

    @abstractmethod
    async def astream(self, messages: list, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        ...


def _build_api_messages(messages: list, system_prompt: str = None) -> list[dict]:
    """ChatMessage 列表 → OpenAI 请求消息体; system_prompt 插为第一条"""
    out = []
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
        else:
            out.append(m.to_api_dict())
    return out


def _summarize_messages(messages: list[dict]) -> str:
    """请求消息摘要(role + 内容截断), 供详细日志"""
    return "; ".join(f"{m.get('role')}: {detail_trace.trunc(m.get('content', ''), 200)}"
                     for m in messages)


class LLMAdapter(LLMProvider):
    """OpenAI 兼容接口的 LLM 适配器"""

    def __init__(self, model_name_override: str = None, base_url_override: str = None,
                 api_key_override: str = None, temperature_override: float = None,
                 max_tokens_override: int = None, timeout_override: int = None):
        config = get_config()
        self.model_name = model_name_override or config.llm.model_name
        self.temperature = temperature_override if temperature_override is not None else config.llm.temperature
        self.max_tokens = max_tokens_override or config.llm.max_tokens
        self.timeout = timeout_override or config.llm.timeout

        api_key = api_key_override or config.llm.api_key
        base_url = base_url_override or config.llm.base_url or "https://api.openai.com/v1"

        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=float(self.timeout),
            max_retries=2,
        )
        logger.info(f"LLM adapter initialized: model={self.model_name}")

    async def ainvoke(self, messages, system_prompt=None, **kwargs) -> str:
        return await self._chat(_build_api_messages(messages, system_prompt), **kwargs)

    async def _chat(self, messages: list, **kwargs) -> str:
        t0 = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens or 8000),
                ),
                timeout=self.timeout,
            )
            content = response.choices[0].message.content or ""
            message = response.choices[0].message
            reasoning = getattr(message, "reasoning_content", None) or ""
            detail_trace.capture_llm("invoke", _summarize_messages(messages),
                                     reasoning, time.perf_counter() - t0)
            return content
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            detail_trace.capture_llm("invoke", _summarize_messages(messages),
                                     "", time.perf_counter() - t0)
            raise

    async def astream(self, messages, system_prompt=None, **kwargs) -> AsyncGenerator[str, None]:
        """token 级流式输出"""
        api_messages = _build_api_messages(messages, system_prompt)
        reasoning_parts = []
        t0 = time.perf_counter()
        try:
            created = self.client.chat.completions.create(
                model=self.model_name,
                messages=api_messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens or 8000),
                stream=True,
            )
            if inspect.isawaitable(created):
                stream = await asyncio.wait_for(created, timeout=self.timeout)
            else:
                stream = created  # 兼容直接返回异步迭代器的实现(如测试替身)
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if detail_trace.trace_enabled() and getattr(delta, "reasoning_content", None):
                    reasoning_parts.append(delta.reasoning_content)
                if delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            detail_trace.capture_llm("stream", _summarize_messages(api_messages),
                                     "".join(reasoning_parts), time.perf_counter() - t0)
            raise
        detail_trace.capture_llm("stream", _summarize_messages(api_messages),
                                 "".join(reasoning_parts), time.perf_counter() - t0)

    def invoke_sync(self, messages, system_prompt=None, **kwargs) -> str:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.ainvoke(messages, system_prompt, **kwargs))


_llm_adapter: Optional[LLMAdapter] = None


def get_llm() -> LLMProvider:
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = LLMAdapter()
    return _llm_adapter

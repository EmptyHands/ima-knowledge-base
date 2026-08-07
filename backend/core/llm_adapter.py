"""LLM 适配器 - 支持 OpenAI 兼容接口"""
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, AsyncGenerator
from openai import AsyncOpenAI
from .config import get_config

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 抽象接口 - 生产实现为 LLMAdapter, 测试注入 FakeLLM"""

    @abstractmethod
    async def ainvoke(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        ...

    @abstractmethod
    async def astream(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        ...


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

    async def ainvoke(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages, **kwargs)

    async def _chat(self, messages: list, **kwargs) -> str:
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
            return response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            logger.error("LLM call timeout")
            raise
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def astream(self, prompt: str, system_prompt: str = None, **kwargs) -> AsyncGenerator[str, None]:
        """token 级流式输出"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            stream = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens or 8000),
                    stream=True,
                ),
                timeout=self.timeout,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
        except asyncio.TimeoutError:
            logger.error("LLM stream timeout")
            raise
        except Exception as e:
            logger.error(f"LLM stream failed: {e}")
            raise

    def invoke_sync(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.ainvoke(prompt, system_prompt, **kwargs))


_llm_adapter: Optional[LLMAdapter] = None


def get_llm() -> LLMProvider:
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = LLMAdapter()
    return _llm_adapter

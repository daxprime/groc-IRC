"""Grok API Client for groc-IRC - Customizable with headers, contexts, modes."""

import json
import time
import logging
import asyncio
from typing import Optional, Dict, List, Any, AsyncGenerator
from dataclasses import dataclass, field
from collections import defaultdict

import aiohttp

logger = logging.getLogger("groc-irc.api")


@dataclass
class GrokMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class GrokResponse:
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str
    raw: Dict[str, Any]
    latency_ms: float = 0.0


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class GrokAPIClient:
    """Customizable Grok API client with modes, custom headers, context management."""

    def __init__(self, api_key, base_url="https://api.x.ai/v1", model="grok-3",
                 max_tokens=1024, temperature=0.7, top_p=1.0, timeout=30,
                 system_prompt="", custom_headers=None, max_context_messages=10):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.system_prompt = system_prompt or "You are a helpful IRC assistant."
        self.custom_headers = custom_headers or {}
        self.max_context_messages = max_context_messages
        self._conversations: Dict[str, List[GrokMessage]] = defaultdict(list)
        self._channel_modes: Dict[str, str] = {}
        self._modes: Dict[str, Dict[str, Any]] = {}
        self._channel_contexts: Dict[str, str] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "groc-IRC/1.0",
        }
        headers.update(self.custom_headers)
        return headers

    def _get_effective_params(self, channel: str) -> Dict[str, Any]:
        mode_name = self._channel_modes.get(channel, "default")
        mode = self._modes.get(mode_name, {})
        return {
            "model": mode.get("model", self.model),
            "max_tokens": mode.get("max_tokens", self.max_tokens),
            "temperature": mode.get("temperature", self.temperature),
            "top_p": mode.get("top_p", self.top_p),
        }

    def _get_system_prompt(self, channel: str) -> str:
        if channel in self._channel_contexts:
            return self._channel_contexts[channel]
        mode_name = self._channel_modes.get(channel, "default")
        mode = self._modes.get(mode_name, {})
        return mode.get("system_prompt", self.system_prompt)

    def _build_messages(self, channel: str, user_message: str) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self._get_system_prompt(channel)}]
        history = self._conversations[channel][-self.max_context_messages:]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def chat(self, channel, user, message, override_params=None) -> GrokResponse:
        start_time = time.time()
        params = self._get_effective_params(channel)
        if override_params:
            params.update(override_params)
        contextualized = f"[{user}]: {message}"
        payload = {
            "model": params["model"],
            "messages": self._build_messages(channel, contextualized),
            "max_tokens": params["max_tokens"],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "stream": False,
        }
        session = await self._get_session()
        try:
            async with session.post(f"{self.base_url}/chat/completions",
                                    json=payload, headers=self._build_headers()) as response:
                body = await response.text()
                if response.status != 200:
                    raise APIError(f"Grok API returned {response.status}",
                                   response.status, body)
                data = json.loads(body)
                latency = (time.time() - start_time) * 1000
                content = data["choices"][0]["message"]["content"]
                self._conversations[channel].append(GrokMessage("user", contextualized))
                self._conversations[channel].append(GrokMessage("assistant", content))
                if len(self._conversations[channel]) > self.max_context_messages * 2:
                    self._conversations[channel] = self._conversations[channel][-self.max_context_messages * 2:]
                return GrokResponse(content=content, model=data.get("model", self.model),
                                    usage=data.get("usage", {}),
                                    finish_reason=data["choices"][0].get("finish_reason", "stop"),
                                    raw=data, latency_ms=latency)
        except aiohttp.ClientError as e:
            raise APIError(f"Connection error: {e}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise APIError(f"Invalid API response: {e}")

    async def chat_stream(self, channel, user, message) -> AsyncGenerator[str, None]:
        params = self._get_effective_params(channel)
        contextualized = f"[{user}]: {message}"
        payload = {
            "model": params["model"],
            "messages": self._build_messages(channel, contextualized),
            "max_tokens": params["max_tokens"],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "stream": True,
        }
        session = await self._get_session()
        full_response = ""
        try:
            async with session.post(f"{self.base_url}/chat/completions",
                                    json=payload, headers=self._build_headers()) as response:
                if response.status != 200:
                    body = await response.text()
                    raise APIError(f"API error {response.status}", response.status, body)
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith('data: '):
                        data_str = line[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            c = delta.get("content", "")
                            if c:
                                full_response += c
                                yield c
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
            self._conversations[channel].append(GrokMessage("user", contextualized))
            self._conversations[channel].append(GrokMessage("assistant", full_response))
        except aiohttp.ClientError as e:
            raise APIError(f"Stream connection error: {e}")

    # Mode management
    def register_mode(self, name, config):
        self._modes[name] = config

    def set_channel_mode(self, channel, mode_name) -> bool:
        if mode_name not in self._modes and mode_name != "default":
            return False
        self._channel_modes[channel] = mode_name
        return True

    def get_channel_mode(self, channel) -> str:
        return self._channel_modes.get(channel, "default")

    def list_modes(self) -> List[str]:
        return list(self._modes.keys())

    def remove_mode(self, name) -> bool:
        if name in self._modes:
            del self._modes[name]
            for ch in list(self._channel_modes.keys()):
                if self._channel_modes[ch] == name:
                    del self._channel_modes[ch]
            return True
        return False

    # Context management
    def set_channel_context(self, channel, context):
        self._channel_contexts[channel] = context

    def clear_channel_context(self, channel):
        self._channel_contexts.pop(channel, None)

    def get_channel_context(self, channel) -> str:
        return self._get_system_prompt(channel)

    # Header management
    def set_header(self, key, value):
        self.custom_headers[key] = value

    def remove_header(self, key) -> bool:
        if key in self.custom_headers:
            del self.custom_headers[key]
            return True
        return False

    def list_headers(self) -> Dict[str, str]:
        safe = {}
        for k, v in self.custom_headers.items():
            if 'auth' in k.lower() or 'key' in k.lower() or 'token' in k.lower():
                safe[k] = "***REDACTED***"
            else:
                safe[k] = v
        return safe

    # History
    def clear_history(self, channel):
        self._conversations[channel].clear()

    def clear_all_history(self):
        self._conversations.clear()

    def get_history_length(self, channel) -> int:
        return len(self._conversations.get(channel, []))

    # Parameter overrides
    def set_model(self, model):
        self.model = model

    def set_temperature(self, temp):
        self.temperature = max(0.0, min(2.0, temp))

    def set_max_tokens(self, tokens):
        self.max_tokens = max(1, min(4096, tokens))

    def update_api_key(self, new_key):
        self.api_key = new_key
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())
            self._session = None

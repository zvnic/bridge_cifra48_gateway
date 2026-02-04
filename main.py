"""
OpenAI-совместимый прокси-шлюз для bridge-back.admlr.lipetsk.ru.
Предназначен для подключения AI Agent в n8n (Base URL + API Key).
Проксирует X-API-Key на бэкенд bridge.
"""
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import aiohttp
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Настройка логирования (ключи не логируем)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Bridge OpenAI-Compatible Gateway",
    description="Прокси OpenAI-формата для n8n AI Agent → bridge-back.admlr.lipetsk.ru",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Конфигурация
BRIDGE_BASE_URL = os.getenv("BRIDGE_BASE_URL", "https://bridge-back.admlr.lipetsk.ru").rstrip("/")
BRIDGE_COMPLETIONS_URL = os.getenv("BRIDGE_COMPLETIONS_URL", f"{BRIDGE_BASE_URL}/api/v1/completions")
DEFAULT_API_KEY = os.getenv("DEFAULT_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v3")
BRIDGE_MODEL = os.getenv("BRIDGE_MODEL", "deepseek-ai/DeepSeek-V3-0324")
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)


def get_api_key(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    """Извлекает API-ключ из Authorization (Bearer) или X-API-Key."""
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:].strip()
    if DEFAULT_API_KEY:
        return DEFAULT_API_KEY
    raise HTTPException(status_code=401, detail="API key is required (Authorization: Bearer <key> or X-API-Key)")


# --- Pydantic-модели (OpenAI-совместимые) ---

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(default=MODEL_NAME)
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2)
    top_p: Optional[float] = Field(default=0.9, ge=0, le=1)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = Field(default=None, ge=1)
    presence_penalty: Optional[float] = Field(default=0, ge=-2, le=2)
    frequency_penalty: Optional[float] = Field(default=0, ge=-2, le=2)
    user: Optional[str] = None


# --- Запрос к bridge (нестриминг) ---

async def bridge_request_json(
    messages: List[Dict[str, Any]],
    api_key: str,
    stream: bool = False,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Отправляет запрос к bridge, возвращает JSON (для stream=False)."""
    headers = {
        "X-API-Key": api_key,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "messages": messages,
        "model": BRIDGE_MODEL,
        "stream": stream,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    payload.update({k: v for k, v in extra.items() if v is not None})

    async with aiohttp.ClientSession() as session:
        async with session.post(BRIDGE_COMPLETIONS_URL, headers=headers, json=payload) as resp:
            if resp.status != 200 and resp.status != 201:
                err_text = await resp.text()
                logger.error("Bridge error %s: %s", resp.status, err_text[:500])
                raise HTTPException(status_code=resp.status, detail=err_text or "Bridge error")
            return await resp.json()


# --- Стриминг: читаем SSE от bridge и отдаём в формате OpenAI ---

async def bridge_request_stream(
    messages: List[Dict[str, Any]],
    api_key: str,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    request_model: str = MODEL_NAME,
    **extra: Any,
) -> AsyncIterator[str]:
    """Стримит ответ от bridge, выдаёт SSE-строки в формате OpenAI."""
    headers = {
        "X-API-Key": api_key,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "messages": messages,
        "model": BRIDGE_MODEL,
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    payload.update({k: v for k, v in extra.items() if v is not None})

    async with aiohttp.ClientSession() as session:
        async with session.post(BRIDGE_COMPLETIONS_URL, headers=headers, json=payload) as resp:
            if resp.status != 200 and resp.status != 201:
                err_text = await resp.text()
                logger.error("Bridge stream error %s: %s", resp.status, err_text[:500])
                raise HTTPException(status_code=resp.status, detail=err_text or "Bridge error")

            chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
            created = int(datetime.now().timestamp())
            buffer = ""

            async for chunk in resp.content:
                if not chunk:
                    continue
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        yield "data: [DONE]\n\n"
                        return
                    try:
                        chunk_data = json.loads(data_str)
                        # Преобразуем chunk bridge в формат OpenAI
                        choices = chunk_data.get("choices", [{}])
                        delta = choices[0].get("delta", {}) if choices else {}
                        openai_chunk = {
                            "id": chunk_data.get("id", chunk_id),
                            "object": "chat.completion.chunk",
                            "created": chunk_data.get("created", created),
                            "model": request_model,
                            "choices": [
                                {"index": 0, "delta": delta, "finish_reason": chunk_data.get("finish_reason")}
                            ],
                        }
                        yield f"data: {json.dumps(openai_chunk)}\n\n"
                    except json.JSONDecodeError:
                        pass

            if buffer.strip().startswith("data: "):
                data_str = buffer.strip()[6:].strip()
                if data_str and data_str != "[DONE]":
                    try:
                        chunk_data = json.loads(data_str)
                        choices = chunk_data.get("choices", [{}])
                        delta = choices[0].get("delta", {}) if choices else {}
                        openai_chunk = {
                            "id": chunk_data.get("id", chunk_id),
                            "object": "chat.completion.chunk",
                            "created": chunk_data.get("created", created),
                            "model": request_model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(openai_chunk)}\n\n"
                    except json.JSONDecodeError:
                        pass
            yield "data: [DONE]\n\n"


def transform_response_to_openai(bridge_data: Dict[str, Any], request_model: str) -> Dict[str, Any]:
    """Преобразует JSON-ответ bridge в формат OpenAI."""
    choices = bridge_data.get("choices", [])
    message_content = ""
    if choices:
        message_content = choices[0].get("message", {}).get("content", "")
    usage = bridge_data.get("usage", {})

    return {
        "id": bridge_data.get("id", f"chatcmpl-{uuid.uuid4().hex}"),
        "object": "chat.completion",
        "created": bridge_data.get("created", int(datetime.now().timestamp())),
        "model": request_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": message_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


# --- Эндпоинты ---

@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    """Список моделей в формате OpenAI для n8n."""
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": "bridge",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """Чат-комплишены: проксирование на bridge с форматом OpenAI."""
    api_key = get_api_key(authorization, x_api_key)

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    try:
        if request.stream:
            stream_gen = bridge_request_stream(
                messages=messages,
                api_key=api_key,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                request_model=request.model,
            )
            return StreamingResponse(
                stream_gen,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            response = await bridge_request_json(
                messages=messages,
                api_key=api_key,
                stream=False,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            openai_response = transform_response_to_openai(response, request.model)
            return JSONResponse(content=openai_response)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error in chat/completions")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/health")
async def health() -> Dict[str, str]:
    """Healthcheck для Docker/оркестрации."""
    return {"status": "healthy", "service": "bridge-openai-gateway"}


@app.get("/")
async def root() -> Dict[str, str]:
    """Краткая информация о сервисе."""
    return {
        "service": "bridge-openai-gateway",
        "openai_compatible": "v1",
        "docs": "/docs",
        "health": "/health",
    }

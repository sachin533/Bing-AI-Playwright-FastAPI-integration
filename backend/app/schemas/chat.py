"""Pydantic schemas: OpenAI-compatible chat API."""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Role
    content: str = Field(..., description="Message text content.")

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("message content must not be empty")
        return v


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str = Field(default="bing-ai", description="Model identifier echoed back in the response.")
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = Field(default=False, description="Only non-streaming is supported for now.")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    user: str | None = None

    @field_validator("messages")
    @classmethod
    def _must_contain_user_message(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if not any(m.role == "user" for m in v):
            raise ValueError("at least one message with role 'user' is required")
        return v


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: Literal["stop", "length", "content_filter", "error"] = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-bing-{uuid.uuid4().hex[:24]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "bing-ai"
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage = Field(default_factory=ChatCompletionUsage)

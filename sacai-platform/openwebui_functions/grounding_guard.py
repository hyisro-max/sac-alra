"""
title: SACAI Numeric Grounding Guard
description: Append a warning when final-response numbers cannot be traced to tool output in the same turn.
author: SACAI
version: 1.0.0
"""

import asyncio
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class Filter:
    """Apply a deterministic numeric grounding check after model generation."""

    class Valves(BaseModel):
        """Configure warning behavior and linked audit-service access."""

        priority: int = Field(default=100, description="Run late, after normal response filters.")
        append_warning: bool = Field(default=True, description="Append a visible warning for unmatched numbers.")
        service_url: str = Field(default="http://sacai-api:8000", description="Internal SACAI audit API base URL.")
        service_token: str = Field(
            default="replace-with-at-least-16-characters",
            description="Shared internal audit API token.",
            json_schema_extra={"input": {"type": "password"}},
        )
        request_timeout_seconds: int = Field(default=10, ge=1, le=60)

    def __init__(self):
        """Initialize default guard Valves before OpenWebUI applies stored values."""

        self.valves = self.Valves()

    @staticmethod
    def _number_tokens(text: str) -> list[str]:
        """Extract standalone decimal/scientific numeric tokens from text.

        Text is the input. Tokens retain their source spelling so the warning
        can name exact claims while normalized comparison handles 1 versus 1.0.
        """

        pattern = r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])"
        return re.findall(pattern, text or "")

    @staticmethod
    def _normalize(token: str) -> str:
        """Normalize one number token for exact-value comparison.

        A token is the input. The canonical Decimal string is returned; invalid
        values fall back to their original spelling and remain ungrounded.
        """

        try:
            return str(Decimal(token.replace(",", "")).normalize())
        except InvalidOperation:
            return token

    @classmethod
    def _tool_texts(cls, messages: list[dict[str, Any]]) -> list[str]:
        """Collect only actual tool-call output text from outlet messages.

        The OpenWebUI message list is the input. Returned strings exclude normal
        assistant prose so a hallucinated value cannot ground itself.
        """

        texts: list[str] = []
        for message in messages:
            if message.get("role") == "tool":
                texts.append(str(message.get("content") or ""))
            for item in message.get("output") or []:
                if not isinstance(item, dict) or item.get("type") != "function_call_output":
                    continue
                output = item.get("output")
                if isinstance(output, str):
                    texts.append(output)
                else:
                    texts.append(json.dumps(output, sort_keys=True, default=str))
        return texts

    def _audit(self, correlation_id: str, user_id: str, payload: dict[str, Any]) -> None:
        """Append the final text and grounding result to linked service audit.

        Correlation, actor and payload are inputs. The method returns nothing;
        audit availability never changes the visible grounding decision.
        """

        path = f"{self.valves.service_url.rstrip('/')}/v1/audit/{correlation_id}"
        query = f"?event_type=grounding.checked&user_id={user_id}"
        request = Request(
            path + query,
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-SACAI-Token": self.valves.service_token},
        )
        try:
            with urlopen(request, timeout=self.valves.request_timeout_seconds):
                return
        except URLError:
            return

    @staticmethod
    def _job_correlation(tool_texts: list[str]) -> str | None:
        """Return a service correlation ID embedded in a tool result, if any.

        Raw tool-output strings are the input. The first JSON object containing
        ``correlation_id`` links later polling turns back to the original job.
        """

        for text in tool_texts:
            try:
                value = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict) and value.get("correlation_id"):
                return str(value["correlation_id"])
        return None

    async def outlet(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any] = {},
        __metadata__: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """Check every final-response number against same-turn tool results.

        OpenWebUI outlet data and injected user/turn metadata are inputs. The
        returned body preserves all messages and appends a warning to the last
        assistant message when one or more values lack a tool-result match.
        """

        messages = body.get("messages") or []
        assistant = next((message for message in reversed(messages) if message.get("role") == "assistant"), None)
        if not assistant:
            return body
        final_text = str(assistant.get("content") or "")
        tool_texts = self._tool_texts(messages)
        grounded = {
            self._normalize(token)
            for text in tool_texts
            for token in self._number_tokens(text)
        }
        response_tokens = self._number_tokens(final_text)
        unmatched = [token for token in response_tokens if self._normalize(token) not in grounded]
        if unmatched and self.valves.append_warning:
            unique = list(dict.fromkeys(unmatched))
            assistant["content"] = (
                final_text.rstrip()
                + "\n\n Numeric grounding warning: these values were not found in this turn's tool output: "
                + ", ".join(unique)
                + ". Verify them before scientific use."
            )
        correlation_id = str(
            self._job_correlation(tool_texts)
            or (__metadata__ or {}).get("message_id")
            or body.get("id")
            or (__metadata__ or {}).get("chat_id")
            or "unlinked"
        )
        await asyncio.to_thread(
            self._audit,
            correlation_id,
            str((__user__ or {}).get("id") or "unknown"),
            {
                "final_text": final_text,
                "raw_tool_outputs": tool_texts,
                "response_numbers": response_tokens,
                "grounded_numbers": sorted(grounded),
                "unmatched_numbers": unmatched,
                "passed": not unmatched,
            },
        )
        return body

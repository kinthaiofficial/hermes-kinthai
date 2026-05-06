"""KinthAI platform adapter for Hermes Agent.

This module is only ever imported inside the Hermes venv (via the
hermes_agent.plugins entry point), never by the CLI installer.
The gateway.* imports are therefore always available at import time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    SendResult,
)

logger = logging.getLogger(__name__)

VERSION = "1.0.0"


# ── Plugin entry point ────────────────────────────────────────────────────────

def check_requirements() -> bool:
    return bool(os.getenv("KINTHAI_TOKEN"))


def validate_config(config) -> bool:
    return bool(os.getenv("KINTHAI_TOKEN"))


def is_connected(config) -> bool:
    return validate_config(config)


def register(ctx) -> None:
    """Hermes plugin entry point — called at gateway startup."""
    ctx.register_platform(
        name="kinthai",
        label="KinthAI",
        adapter_factory=lambda cfg: KinthaiAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["KINTHAI_TOKEN"],
        install_hint="Run: pipx run hermes-kinthai <email>",
        emoji="🦀",
        allow_update_command=True,
        platform_hint=(
            "You are chatting via KinthAI. "
            "Supports markdown. Keep responses concise and helpful."
        ),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _derive_agent_id() -> str:
    """Derive agent ID from HERMES_HOME (set by `hermes -p <profile>`)."""
    home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    m = re.search(r"/profiles/([^/]+)$", home)
    return f"hermes-{m.group(1)}" if m else "hermes-lead"


# ── Adapter ───────────────────────────────────────────────────────────────────

class KinthaiAdapter(BasePlatformAdapter):
    """KinthAI WebSocket adapter with debounced message batching."""

    DEBOUNCE_S = 3.0
    MAX_BATCH = 20
    CHAR_LIMIT = 20000
    DEDUPE_TTL = 1200  # seconds

    def __init__(self, config: PlatformConfig) -> None:
        super().__init__(config, Platform("kinthai"))
        self.api_key: str = os.getenv("KINTHAI_TOKEN", "")
        self.api_base: str = os.getenv(
            "KINTHAI_API_BASE", "https://kinthai.ai"
        ).rstrip("/")
        self.agent_id: str = _derive_agent_id()
        self._kk_user_id: Optional[str] = None
        self._session = None
        self._ws_task: Optional[asyncio.Task] = None
        self._running: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        import aiohttp

        self._session = aiohttp.ClientSession()
        try:
            async with self._session.get(
                f"{self.api_base}/api/v1/me",
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as r:
                me = await r.json()
                self._kk_user_id = str(me.get("user_id") or me.get("id", ""))
        except Exception as e:
            logger.error("[kinthai] /me failed: %s", e)
            await self._session.close()
            self._session = None
            return False

        self._running = True
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._mark_connected()
        logger.info("[kinthai:%s] Connected (user_id=%s)", self.agent_id, self._kk_user_id)
        return True

    async def disconnect(self) -> None:
        self._running = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        if self._session:
            await self._session.close()
            self._session = None
        self._mark_disconnected()
        logger.info("[kinthai:%s] Disconnected", self.agent_id)

    # ── WebSocket loop ────────────────────────────────────────────────────────

    async def _ws_loop(self) -> None:
        import aiohttp

        backoff = 2.0
        ws_url = (
            self.api_base
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        ) + "/ws"

        while self._running:
            try:
                async with self._session.ws_connect(
                    ws_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    heartbeat=30,
                ) as ws:
                    backoff = 2.0
                    await self._receive_loop(ws)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                logger.warning(
                    "[kinthai:%s] WS error: %s — retry in %.0fs",
                    self.agent_id, e, backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _receive_loop(self, ws) -> None:
        import aiohttp

        pending: dict[str, list] = {}
        timers: dict[str, asyncio.Task] = {}
        seen: dict[str, float] = {}

        async for raw in ws:
            if raw.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                continue
            try:
                data = json.loads(raw.data)
            except Exception:
                continue

            ev = data.get("event")

            if ev == "hello":
                await ws.send_str(json.dumps({
                    "event": "identify",
                    "api_key": self.api_key,
                    "plugin_version": f"hermes-kinthai/{VERSION}",
                }))

            elif ev == "ping":
                await ws.send_str(json.dumps(
                    {"event": "pong", "ts": data.get("ts")}
                ))

            elif ev == "message.new" and data.get("trigger_agent"):
                await self._handle_new_message(data, ws, pending, timers, seen)

    async def _handle_new_message(
        self,
        data: dict,
        ws,
        pending: dict,
        timers: dict,
        seen: dict,
    ) -> None:
        msg_id = data.get("message_id")
        if not msg_id:
            return

        now = time.monotonic()
        seen = {k: v for k, v in seen.items() if now - v < self.DEDUPE_TTL}
        if msg_id in seen:
            return
        seen[msg_id] = now

        msg = await self._fetch_message(msg_id)
        if msg is None:
            return
        if str(msg.get("sender_id")) == self._kk_user_id:
            return  # self-message filter

        await ws.send_str(json.dumps(
            {"event": "message.received", "message_id": msg_id}
        ))

        conv_id = data["conversation_id"]
        pending.setdefault(conv_id, []).append(msg)

        existing = timers.get(conv_id)
        if existing and not existing.done():
            existing.cancel()

        chars = sum(len(m.get("content", "")) for m in pending[conv_id])
        if len(pending[conv_id]) >= self.MAX_BATCH or chars >= self.CHAR_LIMIT:
            asyncio.create_task(self._flush(conv_id, pending, timers))
        else:
            timers[conv_id] = asyncio.create_task(
                self._debounced_flush(conv_id, pending, timers)
            )

    async def _debounced_flush(
        self, conv_id: str, pending: dict, timers: dict
    ) -> None:
        await asyncio.sleep(self.DEBOUNCE_S)
        await self._flush(conv_id, pending, timers)

    async def _flush(
        self, conv_id: str, pending: dict, timers: dict
    ) -> None:
        msgs = pending.pop(conv_id, [])
        timers.pop(conv_id, None)
        if not msgs:
            return

        text = "\n\n".join(
            f"[{m.get('sender_name', 'User')}]: {m.get('content', '')}"
            for m in msgs
        )
        source = self.build_source(
            chat_id=conv_id,
            chat_name=f"kinthai:{conv_id}",
            chat_type="group",
            user_id=str(msgs[-1].get("sender_id", "")),
            user_name=msgs[-1].get("sender_name", ""),
        )
        event = MessageEvent(
            text=text,
            message_type=MessageType.TEXT,
            source=source,
            message_id=msgs[-1].get("message_id"),
        )
        await self.handle_message(event)

    async def _fetch_message(self, msg_id: str) -> Optional[dict]:
        try:
            async with self._session.get(
                f"{self.api_base}/api/v1/messages/{msg_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            ) as r:
                return await r.json() if r.status == 200 else None
        except Exception:
            return None

    # ── Sending ───────────────────────────────────────────────────────────────

    async def send(
        self,
        chat_id: str,
        content: str,
        **kwargs,
    ) -> SendResult:
        try:
            async with self._session.post(
                f"{self.api_base}/api/v1/conversations/{chat_id}/messages",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"content": content},
            ) as r:
                return SendResult(success=r.status in (200, 201))
        except Exception as e:
            logger.error("[kinthai:%s] send() failed: %s", self.agent_id, e)
            return SendResult(success=False, error=str(e))

    async def send_typing(self, chat_id: str, **kwargs) -> None:
        pass  # KinthAI has no typing indicator API yet

    async def get_chat_info(self, chat_id: str) -> dict:
        return {"name": chat_id, "type": "group"}

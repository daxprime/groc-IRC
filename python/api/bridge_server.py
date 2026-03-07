"""HTTP Bridge Server - Allows Tcl bot to call Grok API via HTTP."""

import logging
import json
from aiohttp import web

logger = logging.getLogger("groc-irc.bridge")


class BridgeServer:
    """Local HTTP bridge for Tcl -> Python Grok API communication."""

    def __init__(self, grok_client, host="127.0.0.1", port=5580):
        self.grok = grok_client
        self.host = host
        self.port = port
        self._app = web.Application()
        self._runner = None
        self._setup_routes()

    def _setup_routes(self):
        self._app.router.add_post("/api/chat", self._handle_chat)
        self._app.router.add_post("/api/mode", self._handle_mode)
        self._app.router.add_post("/api/header", self._handle_header)
        self._app.router.add_get("/api/status", self._handle_status)

    async def _check_localhost(self, request):
        peername = request.transport.get_extra_info("peername")
        if peername and peername[0] not in ("127.0.0.1", "::1", "localhost"):
            raise web.HTTPForbidden(text="Bridge only accepts localhost connections")

    async def _handle_chat(self, request):
        await self._check_localhost(request)
        try:
            data = await request.json()
            channel = data.get("channel", "#bridge")
            user = data.get("user", "tcl_bot")
            message = data.get("message", "")
            if not message:
                return web.json_response({"error": "No message provided"}, status=400)
            response = await self.grok.chat(channel, user, message)
            return web.json_response({
                "content": response.content,
                "model": response.model,
                "usage": response.usage,
                "latency_ms": response.latency_ms,
            })
        except Exception as e:
            logger.error(f"Bridge chat error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_mode(self, request):
        await self._check_localhost(request)
        try:
            data = await request.json()
            action = data.get("action", "get")
            channel = data.get("channel", "#bridge")
            if action == "set":
                mode_name = data.get("mode", "default")
                success = self.grok.set_channel_mode(channel, mode_name)
                return web.json_response({"success": success, "mode": mode_name})
            elif action == "list":
                return web.json_response({"modes": self.grok.list_modes()})
            else:
                current = self.grok.get_channel_mode(channel)
                return web.json_response({"mode": current})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_header(self, request):
        await self._check_localhost(request)
        try:
            data = await request.json()
            action = data.get("action", "list")
            if action == "set":
                key = data.get("key", "")
                value = data.get("value", "")
                if key:
                    self.grok.set_header(key, value)
                    return web.json_response({"success": True})
                return web.json_response({"error": "No key provided"}, status=400)
            elif action == "remove":
                key = data.get("key", "")
                success = self.grok.remove_header(key)
                return web.json_response({"success": success})
            else:
                return web.json_response({"headers": self.grok.list_headers()})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def _handle_status(self, request):
        await self._check_localhost(request)
        return web.json_response({
            "status": "running",
            "model": self.grok.model,
            "temperature": self.grok.temperature,
            "max_tokens": self.grok.max_tokens,
            "modes": self.grok.list_modes(),
        })

    async def start(self):
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(f"Bridge server started on {self.host}:{self.port}")

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            logger.info("Bridge server stopped")

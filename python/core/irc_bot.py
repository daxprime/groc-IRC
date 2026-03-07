"""Async IRC Bot core for groc-IRC - Connects to Undernet."""

import asyncio
import logging
import time
import re
from typing import Optional, Callable, Dict, List, Tuple, Any
from dataclasses import dataclass

logger = logging.getLogger("groc-irc.core")


@dataclass
class IRCMessage:
    raw: str
    prefix: str
    nick: str
    user: str
    host: str
    command: str
    params: List[str]
    channel: Optional[str]
    text: str
    timestamp: float

    @classmethod
    def parse(cls, raw_line: str) -> "IRCMessage":
        raw = raw_line.strip()
        prefix = nick = user = host = ""
        rest = raw
        if rest.startswith(':'):
            prefix, rest = rest[1:].split(' ', 1)
            if '!' in prefix:
                nick, userhost = prefix.split('!', 1)
                if '@' in userhost:
                    user, host = userhost.split('@', 1)
                else:
                    user = userhost
            else:
                nick = prefix
        parts = rest.split(' ')
        command = parts[0].upper()
        params = []
        i = 1
        while i < len(parts):
            if parts[i].startswith(':'):
                params.append(' '.join(parts[i:])[1:])
                break
            params.append(parts[i])
            i += 1
        channel = None
        text = ""
        if command == "PRIVMSG" and params:
            channel = params[0] if params[0].startswith('#') else None
            text = params[1] if len(params) > 1 else ""
        elif command == "JOIN" and params:
            channel = params[0].lstrip(':')
        return cls(raw=raw, prefix=prefix, nick=nick, user=user, host=host,
                   command=command, params=params, channel=channel, text=text,
                   timestamp=time.time())

    @property
    def hostmask(self) -> str:
        return f"{self.nick}!{self.user}@{self.host}"


class IRCBot:
    """Async IRC bot with Undernet support."""

    def __init__(self, server="us.undernet.org", port=6667, nickname="GrocBot",
                 username="grocbot", realname="Grok IRC Bot", channels=None,
                 password="", use_ssl=False, encoding="utf-8",
                 reconnect_delay=30, max_reconnect=10, message_delay=0.5,
                 undernet_user="", undernet_pass=""):
        self.server = server
        self.port = port
        self.nickname = nickname
        self.username = username
        self.realname = realname
        self.channels = channels or ["#grocbot"]
        self.password = password
        self.use_ssl = use_ssl
        self.encoding = encoding
        self.reconnect_delay = reconnect_delay
        self.max_reconnect = max_reconnect
        self.message_delay = message_delay
        self.undernet_user = undernet_user
        self.undernet_pass = undernet_pass
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._running = False
        self._handlers: Dict[str, List[Callable]] = {}
        self._last_message_time = 0.0
        self._reconnect_count = 0
        self._current_nick = nickname

    async def connect(self):
        logger.info(f"Connecting to {self.server}:{self.port}...")
        try:
            if self.use_ssl:
                import ssl as _ssl
                ctx = _ssl.create_default_context()
                self._reader, self._writer = await asyncio.open_connection(
                    self.server, self.port, ssl=ctx)
            else:
                self._reader, self._writer = await asyncio.open_connection(
                    self.server, self.port)
            self._connected = True
            self._reconnect_count = 0
            if self.password:
                await self.send_raw(f"PASS {self.password}")
            await self.send_raw(f"NICK {self.nickname}")
            await self.send_raw(f"USER {self.username} 0 * :{self.realname}")
            logger.info("Registration sent.")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            raise

    async def send_raw(self, message: str):
        if not self._writer:
            return
        now = time.time()
        delay = self.message_delay - (now - self._last_message_time)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            self._writer.write(f"{message}\r\n".encode(self.encoding))
            await self._writer.drain()
            self._last_message_time = time.time()
        except Exception as e:
            logger.error(f"Send failed: {e}")
            self._connected = False

    async def send_message(self, target: str, text: str):
        max_len = 400
        for i in range(0, len(text), max_len):
            chunk = text[i:i+max_len]
            await self.send_raw(f"PRIVMSG {target} :{chunk}")

    async def join_channel(self, channel: str, key: str = ""):
        cmd = f"JOIN {channel} {key}".strip() if key else f"JOIN {channel}"
        await self.send_raw(cmd)
        if channel not in self.channels:
            self.channels.append(channel)

    async def part_channel(self, channel: str, reason: str = ""):
        msg = f"PART {channel} :{reason}" if reason else f"PART {channel}"
        await self.send_raw(msg)
        if channel in self.channels:
            self.channels.remove(channel)

    async def quit(self, reason: str = "Goodbye!"):
        self._running = False
        await self.send_raw(f"QUIT :{reason}")
        if self._writer:
            self._writer.close()
        self._connected = False

    def on(self, command: str, handler: Callable):
        command = command.upper()
        if command not in self._handlers:
            self._handlers[command] = []
        self._handlers[command].append(handler)

    async def _dispatch(self, msg: IRCMessage):
        handlers = self._handlers.get(msg.command, [])
        for handler in handlers:
            try:
                result = handler(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Handler error for {msg.command}: {e}")
        all_handlers = self._handlers.get("*", [])
        for handler in all_handlers:
            try:
                result = handler(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Wildcard handler error: {e}")

    async def _handle_system(self, msg: IRCMessage):
        if msg.command == "PING":
            token = msg.params[0] if msg.params else ""
            await self.send_raw(f"PONG :{token}")
        elif msg.command == "001":
            logger.info(f"Connected as {self._current_nick}")
            if self.undernet_user and self.undernet_pass:
                await self.send_raw(
                    f"PRIVMSG X@channels.undernet.org :LOGIN {self.undernet_user} {self.undernet_pass}")
                logger.info("Sent Undernet X login")
                await asyncio.sleep(2)
            for channel in self.channels:
                await self.join_channel(channel)
        elif msg.command == "433":
            self._current_nick = self.nickname + "_"
            await self.send_raw(f"NICK {self._current_nick}")
        elif msg.command == "KICK":
            if len(msg.params) >= 2 and msg.params[1] == self._current_nick:
                channel = msg.params[0]
                logger.warning(f"Kicked from {channel}, rejoining...")
                await asyncio.sleep(3)
                await self.join_channel(channel)

    async def _read_loop(self):
        while self._running and self._connected:
            try:
                data = await asyncio.wait_for(self._reader.readline(), timeout=300)
                if not data:
                    logger.warning("Connection closed by server")
                    self._connected = False
                    break
                line = data.decode(self.encoding, errors='replace').strip()
                if not line:
                    continue
                msg = IRCMessage.parse(line)
                await self._handle_system(msg)
                await self._dispatch(msg)
            except asyncio.TimeoutError:
                await self.send_raw("PING :keepalive")
            except Exception as e:
                logger.error(f"Read error: {e}")
                self._connected = False
                break

    async def run(self):
        self._running = True
        while self._running:
            try:
                await self.connect()
                await self._read_loop()
            except Exception as e:
                logger.error(f"Bot error: {e}")
            if self._running:
                self._reconnect_count += 1
                if self._reconnect_count > self.max_reconnect:
                    logger.error("Max reconnects reached")
                    break
                wait = min(self.reconnect_delay * self._reconnect_count, 300)
                logger.info(f"Reconnecting in {wait}s (attempt {self._reconnect_count})...")
                await asyncio.sleep(wait)

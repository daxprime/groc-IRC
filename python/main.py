"""groc-IRC Main Orchestrator - Ties IRC bot, Grok API, and admin system together."""

import os
import sys
import asyncio
import logging
import signal
from dotenv import load_dotenv

from python.core.irc_bot import IRCBot, IRCMessage
from python.api.grok_client import GrokAPIClient, APIError
from python.api.bridge_server import BridgeServer
from python.auth.admin import AdminManager, Role
from python.utils.config import Config
from python.utils.security import RateLimiter, InputSanitizer

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("groc-irc")


class GrocIRCBot:
    """Main orchestrator for the groc-IRC bot."""

    def __init__(self, config_path="config/settings.json"):
        self.config = Config(config_path)
        irc_cfg = self.config.get("irc", {})
        grok_cfg = self.config.get("grok_api", {})
        admin_cfg = self.config.get("admin", {})
        sec_cfg = self.config.get("security", {})

        api_key = os.getenv("GROK_API_KEY", "")
        if not api_key:
            logger.error("GROK_API_KEY not set!")
            sys.exit(1)

        irc_servers = irc_cfg.get("servers", [
            os.getenv("IRC_SERVER", "budapest.hu.eu.undernet.org"),
            "bucharest.ro.eu.undernet.org",
        ])
        self.bot = IRCBot(
            server=irc_servers[0],
            servers=irc_servers,
            port=int(os.getenv("IRC_PORT", irc_cfg.get("port", 6667))),
            nickname=os.getenv("IRC_NICKNAME", irc_cfg.get("nickname", "GrocBot")),
            username=irc_cfg.get("username", "grocbot"),
            realname=irc_cfg.get("realname", "Grok IRC Bot"),
            channels=irc_cfg.get("channels", ["#grocbot"]),
            use_ssl=irc_cfg.get("use_ssl", False),
            reconnect_delay=irc_cfg.get("reconnect_delay", 30),
            max_reconnect=irc_cfg.get("max_reconnect", 10),
            message_delay=irc_cfg.get("message_delay", 0.5),
            undernet_user=os.getenv("UNDERNET_USER", ""),
            undernet_pass=os.getenv("UNDERNET_PASS", ""),
        )

        self.grok = GrokAPIClient(
            api_key=api_key,
            base_url=grok_cfg.get("base_url", "https://api.x.ai/v1"),
            model=grok_cfg.get("default_model", "grok-3"),
            max_tokens=grok_cfg.get("max_tokens", 1024),
            temperature=grok_cfg.get("temperature", 0.7),
            system_prompt=grok_cfg.get("system_prompt", "You are a helpful IRC assistant."),
            max_context_messages=grok_cfg.get("max_context_messages", 10),
            timeout=grok_cfg.get("timeout", 30),
        )

        for name, mode_cfg in grok_cfg.get("modes", {}).items():
            self.grok.register_mode(name, mode_cfg)

        self.admin = AdminManager(
            super_admin_hostmask=os.getenv("SUPER_ADMIN_HOSTMASK",
                                           admin_cfg.get("super_admin_hostmask", "")),
            super_admin_password=os.getenv("SUPER_ADMIN_PASSWORD",
                                           admin_cfg.get("super_admin_password", "")),
            session_timeout=admin_cfg.get("session_timeout", 3600),
        )

        self.rate_limiter = RateLimiter(
            max_requests=sec_cfg.get("rate_limit", {}).get("max_requests", 5),
            window_seconds=sec_cfg.get("rate_limit", {}).get("window_seconds", 60),
        )
        self.sanitizer = InputSanitizer(
            max_length=sec_cfg.get("max_message_length", 500)
        )

        self.bridge = BridgeServer(self.grok, port=5580)
        self._register_handlers()

    def _register_handlers(self):
        self.bot.on("PRIVMSG", self._handle_message)

    async def _handle_message(self, msg: IRCMessage):
        if not msg.text or not msg.channel:
            return
        text = msg.text.strip()
        hostmask = msg.hostmask

        # dynamic command: !<currentNick> (case-insensitive)
        bot_nick = self.bot._current_nick.lower()
        nick_cmd = f"!{bot_nick}"

        if text.startswith("!admin "):
            await self._handle_admin_command(msg, text[7:])
        elif text.lower().startswith(nick_cmd + " "):
            await self._handle_grok(msg, text[len(nick_cmd)+1:])
        elif text.lower() == nick_cmd:
            await self.bot.send_message(msg.channel,
                f"{msg.nick}: Usage: !{self.bot._current_nick} <question>")
        elif text == "!help":
            await self._handle_help(msg)
        elif text == "!status":
            await self._handle_status(msg)
        elif text == "!modes":
            modes = self.grok.list_modes()
            current = self.grok.get_channel_mode(msg.channel)
            await self.bot.send_message(msg.channel,
                f"Available modes: {', '.join(modes) if modes else 'none'} | Current: {current}")

    async def _handle_grok(self, msg: IRCMessage, question: str):
        hostmask = msg.hostmask
        if self.admin.check_blocked(hostmask):
            return
        if not self.rate_limiter.is_allowed(hostmask):
            await self.bot.send_message(msg.channel, f"{msg.nick}: Rate limit exceeded. Please wait.")
            return
        clean = self.sanitizer.sanitize(question)
        if not clean:
            await self.bot.send_message(msg.channel, f"{msg.nick}: Invalid or empty message.")
            return
        try:
            await self.bot.send_message(msg.channel, f"{msg.nick}: Thinking...")
            response = await self.grok.chat(msg.channel, msg.nick, clean)
            answer = response.content.replace("\n", " | ")
            if len(answer) > 450:
                chunks = [answer[i:i+450] for i in range(0, len(answer), 450)]
                for chunk in chunks[:3]:
                    await self.bot.send_message(msg.channel, f"{msg.nick}: {chunk}")
                if len(chunks) > 3:
                    await self.bot.send_message(msg.channel, f"{msg.nick}: [truncated, {len(chunks)-3} more parts]")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: {answer}")
        except APIError as e:
            logger.error(f"Grok API error: {e}")
            await self.bot.send_message(msg.channel, f"{msg.nick}: API error - {e}")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            await self.bot.send_message(msg.channel, f"{msg.nick}: An error occurred.")

    async def _handle_admin_command(self, msg: IRCMessage, cmd: str):
        hostmask = msg.hostmask
        parts = cmd.strip().split()
        if not parts:
            return
        action = parts[0].lower()

        if action == "login":
            password = parts[1] if len(parts) > 1 else ""
            session = self.admin.authenticate(msg.nick, hostmask, password)
            if session:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Authenticated as {session.role.name}")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Authentication failed.")
            return

        if not self.admin.check_permission(hostmask, Role.MANAGER):
            await self.bot.send_message(msg.channel, f"{msg.nick}: Permission denied.")
            return

        if action == "addmanager" and len(parts) >= 3:
            if not self.admin.check_permission(hostmask, Role.SUPER_ADMIN):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Only super admin can add managers.")
                return
            nick_to_add = parts[1]
            mask = parts[2]
            pw = parts[3] if len(parts) > 3 else ""
            if self.admin.add_manager(nick_to_add, mask, msg.nick, pw):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Manager {nick_to_add} added.")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Manager already exists.")

        elif action == "removemanager" and len(parts) >= 2:
            if not self.admin.check_permission(hostmask, Role.SUPER_ADMIN):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Only super admin can remove managers.")
                return
            if self.admin.remove_manager(parts[1]):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Manager {parts[1]} removed.")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Manager not found.")

        elif action == "listmanagers":
            managers = self.admin.list_managers()
            if managers:
                for m in managers:
                    await self.bot.send_message(msg.channel,
                        f"  {m['nick']} [{m['role']}] mask={m['hostmask']} by={m['added_by']}")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: No managers.")

        elif action == "setheader" and len(parts) >= 3:
            self.grok.set_header(parts[1], ' '.join(parts[2:]))
            await self.bot.send_message(msg.channel, f"{msg.nick}: Header {parts[1]} set.")

        elif action == "removeheader" and len(parts) >= 2:
            if self.grok.remove_header(parts[1]):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Header {parts[1]} removed.")

        elif action == "listheaders":
            headers = self.grok.list_headers()
            await self.bot.send_message(msg.channel, f"Headers: {headers}")

        elif action == "setcontext" and len(parts) >= 2:
            context = ' '.join(parts[1:])
            self.grok.set_channel_context(msg.channel, context)
            await self.bot.send_message(msg.channel, f"{msg.nick}: Channel context updated.")

        elif action == "clearcontext":
            self.grok.clear_channel_context(msg.channel)
            await self.bot.send_message(msg.channel, f"{msg.nick}: Channel context cleared.")

        elif action == "setmode" and len(parts) >= 2:
            if self.grok.set_channel_mode(msg.channel, parts[1]):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Mode set to {parts[1]}")
            else:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Unknown mode. Available: {', '.join(self.grok.list_modes())}")

        elif action == "setmodel" and len(parts) >= 2:
            self.grok.set_model(parts[1])
            await self.bot.send_message(msg.channel, f"{msg.nick}: Model changed to {parts[1]}")

        elif action == "settemp" and len(parts) >= 2:
            try:
                self.grok.set_temperature(float(parts[1]))
                await self.bot.send_message(msg.channel, f"{msg.nick}: Temperature set to {parts[1]}")
            except ValueError:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Invalid temperature value.")

        elif action == "setmaxtokens" and len(parts) >= 2:
            try:
                self.grok.set_max_tokens(int(parts[1]))
                await self.bot.send_message(msg.channel, f"{msg.nick}: Max tokens set to {parts[1]}")
            except ValueError:
                await self.bot.send_message(msg.channel, f"{msg.nick}: Invalid token count.")

        elif action == "clearhistory":
            channel = parts[1] if len(parts) > 1 else msg.channel
            self.grok.clear_history(channel)
            await self.bot.send_message(msg.channel, f"{msg.nick}: History cleared for {channel}")

        elif action == "join" and len(parts) >= 2:
            await self.bot.join_channel(parts[1])
            await self.bot.send_message(msg.channel, f"{msg.nick}: Joined {parts[1]}")

        elif action == "part" and len(parts) >= 2:
            await self.bot.part_channel(parts[1], "Requested by admin")
            await self.bot.send_message(msg.channel, f"{msg.nick}: Left {parts[1]}")

        elif action == "block" and len(parts) >= 2:
            if not self.admin.check_permission(hostmask, Role.SUPER_ADMIN):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Only super admin can block.")
                return
            self.admin.block_user(parts[1])
            await self.bot.send_message(msg.channel, f"{msg.nick}: Blocked {parts[1]}")

        elif action == "unblock" and len(parts) >= 2:
            if not self.admin.check_permission(hostmask, Role.SUPER_ADMIN):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Only super admin can unblock.")
                return
            self.admin.unblock_user(parts[1])
            await self.bot.send_message(msg.channel, f"{msg.nick}: Unblocked {parts[1]}")

        elif action == "chpasswd":
            is_sa = self.admin.check_permission(hostmask, Role.SUPER_ADMIN)
            if is_sa and len(parts) == 3:
                # super admin resetting a user's password
                target, newpw = parts[1], parts[2]
                if self.admin.change_password(target, newpw, by_admin=True):
                    await self.bot.send_message(msg.channel, f"{msg.nick}: Password updated for {target}.")
                else:
                    await self.bot.send_message(msg.channel, f"{msg.nick}: User not found (use nick or __super__).")
            elif len(parts) == 3:
                # any authed user changing their own password
                oldpw, newpw = parts[1], parts[2]
                if self.admin.change_password(msg.nick, newpw, old_password=oldpw):
                    await self.bot.send_message(msg.channel, f"{msg.nick}: Password changed.")
                else:
                    await self.bot.send_message(msg.channel, f"{msg.nick}: Failed - wrong current password.")
            else:
                await self.bot.send_message(msg.channel,
                    f"{msg.nick}: Usage: !admin chpasswd <oldpass> <newpass>  "
                    f"| (super admin) !admin chpasswd <nick|__super__> <newpass>")

        elif action == "shutdown":
            if not self.admin.check_permission(hostmask, Role.SUPER_ADMIN):
                await self.bot.send_message(msg.channel, f"{msg.nick}: Only super admin can shutdown.")
                return
            await self.bot.send_message(msg.channel, "Shutting down...")
            await self.bot.quit("Shutdown by admin")

        else:
            await self.bot.send_message(msg.channel,
                f"{msg.nick}: Unknown admin command. Use: login, addmanager, removemanager, "
                f"listmanagers, setheader, removeheader, listheaders, setcontext, clearcontext, "
                f"setmode, setmodel, settemp, setmaxtokens, clearhistory, join, part, block, unblock, "
                f"chpasswd, shutdown")

    async def _handle_help(self, msg: IRCMessage):
        help_lines = [
            "groc-IRC Bot Commands:",
            "  !grok <question> - Ask Grok AI a question",
            "  !modes - List available API modes",
            "  !status - Bot status",
            "  !help - This help message",
            "  !admin login [password] - Authenticate",
            "  !admin <command> - Admin commands (use !admin help for list)",
        ]
        for line in help_lines:
            await self.bot.send_message(msg.channel, line)

    async def _handle_status(self, msg: IRCMessage):
        mode = self.grok.get_channel_mode(msg.channel)
        history = self.grok.get_history_length(msg.channel)
        await self.bot.send_message(msg.channel,
            f"Model: {self.grok.model} | Mode: {mode} | "
            f"Temp: {self.grok.temperature} | MaxTokens: {self.grok.max_tokens} | "
            f"History: {history} msgs")

    async def run(self):
        logger.info("Starting groc-IRC bot...")
        bridge_task = asyncio.create_task(self.bridge.start())
        try:
            await self.bot.run()
        finally:
            await self.bridge.stop()
            await self.grok.close()
            bridge_task.cancel()


def main():
    bot = GrocIRCBot()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        loop.close()


if __name__ == "__main__":
    main()

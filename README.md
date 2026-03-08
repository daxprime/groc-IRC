# groc-IRC

**Multi-language IRC bot powered by Grok AI** — Python, Tcl & x86_64 Assembly

Connect to the Undernet IRC network, ask questions using `!<BotNick>`, and get AI-powered responses directly in your channels. Supports role-based admin system, per-channel customization, multiple API modes, and a local HTTP bridge for Tcl/Eggdrop integration.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                 IRC (Undernet)               │
│      budapest.hu.eu.undernet.org:6667        │
│   (failover: bucharest.ro.eu.undernet.org)   │
└──────────┬──────────────┬───────────────────┘
           │              │
    ┌──────▼──────┐ ┌─────▼──────┐
    │  Python Bot │ │  Tcl Bot   │
    │  (asyncio)  │ │(standalone │
    │             │ │ or eggdrop)│
    └──────┬──────┘ └─────┬──────┘
           │              │
           │         HTTP Bridge
           │        (localhost:5580)
           │              │
    ┌──────▼──────────────▼──────┐
    │      Grok API Client       │
    │   (modes, headers, context)│
    └──────────────┬─────────────┘
                   │
           ┌───────▼───────┐
           │  Grok API     │
           │ api.x.ai/v1   │
           └───────────────┘

    ┌──────────────────────┐
    │  x86_64 Assembly     │
    │  (fast IRC parser,   │
    │   sanitizer, crypto) │
    └──────────────────────┘
```

---

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/daxprime/groc-IRC.git
cd groc-IRC
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
nano .env   # or your editor of choice
```

Minimum required settings in `.env`:
```ini
GROK_API_KEY=xai-your-api-key-here
IRC_NICKNAME=YourBotNick
IRC_SERVER=budapest.hu.eu.undernet.org
IRC_CHANNELS=#yourchannel
SUPER_ADMIN_HOSTMASK=yournick!*@your.host.com
SUPER_ADMIN_PASSWORD=changeme
```

### 3. Run

```bash
# Python bot (recommended)
python3 -m python.main

# Or with venv explicitly
/path/to/venv/bin/python3 -m python.main

# Tcl standalone bot
tclsh tcl/grocbot.tcl

# Eggdrop — add to eggdrop.conf:
# source /path/to/groc-IRC/tcl/grocbot_eggdrop.tcl
```

### 4. Build Assembly (optional performance module)

```bash
cd assembly
./build.sh
# Produces grocbot_asm.so — auto-loaded by the Python bot if present
```

---

## Commands

> **Note:** The bot command prefix is `!<BotNick>` — it dynamically uses whatever nickname the bot currently has (including trailing `_` if the nick is taken).
> Example: if the bot connects as `MosIonGrok`, the command is `!MosIonGrok hello`.

### User Commands

| Command | Description |
|---------|-------------|
| `!<BotNick> <question>` | Ask Grok AI a question |
| `!<BotNick>` | Show usage hint |
| `!help` | Show help message |
| `!status` | Show current bot status (model, mode, temperature) |
| `!modes` | List available API modes and current channel mode |

### Admin Login

All admin commands require authentication first. The bot checks IRC hostmask automatically — if your hostmask matches the configured pattern you may login with just your password:

```
!admin login <password>
```

Session lasts **1 hour** by default (configurable via `admin.session_timeout` in `settings.json`).

---

### Manager Commands

> Requires `MANAGER` role or higher (login first).

| Command | Description |
|---------|-------------|
| `!admin login <password>` | Authenticate and start a session |
| `!admin setheader <key> <value>` | Add/update a custom HTTP header for API requests |
| `!admin removeheader <key>` | Remove a custom API header |
| `!admin listheaders` | List all active custom headers |
| `!admin setcontext <text>` | Set a channel-specific system prompt override |
| `!admin clearcontext` | Remove the channel system prompt override |
| `!admin setmode <mode>` | Switch the channel API mode (see modes below) |
| `!admin setmodel <model>` | Change the Grok model (e.g. `grok-3`, `grok-3-mini`) |
| `!admin settemp <0.0–2.0>` | Set response temperature (creativity vs precision) |
| `!admin setmaxtokens <n>` | Set maximum tokens per response |
| `!admin clearhistory [#channel]` | Clear conversation history for a channel |
| `!admin join <#channel>` | Make the bot join a channel |
| `!admin part <#channel>` | Make the bot leave a channel |
| `!admin chpasswd <oldpass> <newpass>` | Change your own manager password |

---

### Super Admin Commands

> Requires `SUPER_ADMIN` role. All manager commands are also available.

| Command | Description |
|---------|-------------|
| `!admin addmanager <nick> <hostmask> [password]` | Register a new manager |
| `!admin removemanager <nick>` | Remove a manager |
| `!admin listmanagers` | List all registered managers with their roles and hostmasks |
| `!admin chpasswd <nick\|__super__> <newpass>` | Reset any user's password (no old password needed) |
| `!admin block <hostmask>` | Block a hostmask pattern from using the bot |
| `!admin unblock <hostmask>` | Unblock a hostmask pattern |
| `!admin shutdown` | Gracefully disconnect and shut down the bot |

---

## Admin & Manager System

### Roles

| Role | Level | Capabilities |
|------|-------|-------------|
| `USER` | 0 | Ask questions, view status |
| `MANAGER` | 1 | All user commands + API tuning, header/context/mode management |
| `SUPER_ADMIN` | 2 | All manager commands + user management, block/unblock, shutdown |

### Registering a Manager (in IRC, as super admin)

```
!admin login yourpassword
!admin addmanager Dave *!dave@some.host.com davepass123
!admin addmanager Alice *!*@*.trusted-isp.net          ← hostmask-only, no password
!admin listmanagers
!admin removemanager Dave
```

- Hostmasks use IRC wildcards: `*` matches anything, `?` matches one character
- Example patterns: `Nick!*@*`, `*!user@specific.host`, `*!*@*.myisp.net`

### Logging In (as a manager, in IRC)

```
!admin login yourpassword
```

### Changing Passwords

```
# As a manager — change your own password (requires current password):
!admin chpasswd oldpassword newpassword

# As super admin — reset any manager's password:
!admin chpasswd Dave newpassword

# As super admin — change the super admin password (runtime only*):
!admin chpasswd __super__ newpassword
```

> ⚠️ Changing `__super__` via IRC is temporary — the bot re-reads `SUPER_ADMIN_PASSWORD` from `.env` on next restart. To make it permanent, update `.env`:
> ```ini
> SUPER_ADMIN_PASSWORD=yournewpassword
> ```

---

## API Modes

Modes are pre-configured personalities with different system prompts. Set per-channel or globally.

| Mode | Temperature | Description |
|------|-------------|-------------|
| `default` | 0.7 | Balanced helpful assistant |
| `creative` | 1.2 | Expressive and imaginative responses |
| `precise` | 0.2 | Factual, no-nonsense, shorter answers (512 tokens) |
| `code` | 0.3 | Programming-focused, optimized for code snippets (1500 tokens) |

```
!admin setmode creative          # switch current channel to creative mode
!admin setmode code              # switch to code mode
!modes                           # list modes and show current channel mode
```

### Adding Custom Modes

Edit `config/settings.json` under `grok_api.custom_modes`:

```json
"grok_api": {
  "custom_modes": {
    "pirate": {
      "system_prompt": "You are a helpful pirate. Respond in pirate speak, keep it short for IRC.",
      "temperature": 1.0,
      "max_tokens": 800
    },
    "eli5": {
      "system_prompt": "Explain everything like the user is 5 years old. Be very simple and brief.",
      "temperature": 0.8,
      "max_tokens": 600
    }
  }
}
```

Restart the bot to load new modes.

---

## API Customization

### Custom Headers

Add arbitrary HTTP headers to every Grok API request:

```
!admin setheader X-Custom-Tag myapp
!admin setheader Authorization-Extra extra-token
!admin listheaders
!admin removeheader X-Custom-Tag
```

### Per-Channel System Prompts (Context)

Override the system prompt for a specific channel:

```
!admin setcontext You are an expert Python developer. Only answer coding questions.
!admin setcontext You are a sarcastic assistant who answers in exactly one sentence.
!admin clearcontext
```

Context is combined with the active mode's system prompt.

### Model & Parameter Tuning

```
!admin setmodel grok-3           # switch model
!admin setmodel grok-3-mini      # faster/cheaper model
!admin settemp 0.9               # 0.0 = deterministic, 2.0 = very random
!admin setmaxtokens 2048         # max tokens per response
!admin clearhistory              # reset conversation memory for current channel
!admin clearhistory #otherchan   # reset for a specific channel
```

---

## Configuration Reference

### Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GROK_API_KEY` | *(required)* | Your xAI API key |
| `IRC_SERVER` | `budapest.hu.eu.undernet.org` | Primary IRC server |
| `IRC_PORT` | `6667` | IRC server port |
| `IRC_NICKNAME` | `GrocBot` | Bot nickname |
| `IRC_CHANNELS` | `#grocbot` | Comma-separated channels to join on start |
| `UNDERNET_USER` | — | Undernet X account username (for channel auth) |
| `UNDERNET_PASS` | — | Undernet X account password |
| `SUPER_ADMIN_HOSTMASK` | `*!*@*` | IRC hostmask pattern for super admin |
| `SUPER_ADMIN_PASSWORD` | — | Super admin login password |
| `BRIDGE_HOST` | `127.0.0.1` | HTTP bridge bind address |
| `BRIDGE_PORT` | `5580` | HTTP bridge port (used by Tcl bot) |

### `config/settings.json` — Key Sections

#### `irc`

```json
{
  "server": "budapest.hu.eu.undernet.org",
  "servers": [
    "budapest.hu.eu.undernet.org",
    "bucharest.ro.eu.undernet.org"
  ],
  "port": 6667,
  "ssl_port": 6697,
  "use_ssl": false,
  "nickname": "GrocBot",
  "channels": ["#grocbot"],
  "reconnect_delay": 30,
  "max_reconnect_attempts": 10,
  "message_throttle_seconds": 2,
  "max_message_length": 400
}
```

- `servers` — list cycled through on reconnect; add more Undernet servers here
- `reconnect_delay` — seconds between reconnect attempts (multiplied each try, max 300s)
- `message_throttle_seconds` — minimum delay between outgoing IRC messages (flood protection)

#### `grok_api`

```json
{
  "base_url": "https://api.x.ai/v1",
  "model": "grok-3",
  "max_tokens": 1024,
  "temperature": 0.7,
  "timeout": 30,
  "default_system_prompt": "You are a helpful IRC assistant...",
  "custom_headers": {},
  "custom_modes": { ... }
}
```

#### `security`

```json
{
  "rate_limit_per_user": 10,
  "rate_limit_window_seconds": 60,
  "max_input_length": 500,
  "max_context_messages": 10,
  "sanitize_input": true,
  "log_conversations": true
}
```

- `rate_limit_per_user` — max requests per user per window
- `max_context_messages` — how many past messages to send as conversation history
- `sanitize_input` — strips IRC control chars and detects prompt injection attempts

#### `admin`

```json
{
  "session_timeout": 3600,
  "require_hostmask_auth": true
}
```

#### `logging`

```json
{
  "level": "INFO",
  "file": "logs/grocbot.log",
  "max_size_mb": 10,
  "backup_count": 5,
  "log_to_console": true
}
```

---

## HTTP Bridge API

The bridge server runs on `http://127.0.0.1:5580` and allows Tcl/external scripts to interact with the bot.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | `GET` | Bot status, model, modes |
| `/api/chat` | `POST` | Send a message to Grok |
| `/api/mode` | `POST` | Change API mode |
| `/api/header` | `POST` | Set a custom header |

**Chat example:**
```bash
curl -X POST http://127.0.0.1:5580/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the capital of France?"}'
```

**Response:**
```json
{
  "content": "Paris.",
  "model": "grok-3",
  "usage": { "total_tokens": 15 },
  "latency_ms": 412.3
}
```

---

## Security

| Feature | Implementation |
|---------|---------------|
| API key encryption | Fernet (AES-256) for stored secrets |
| Password hashing | PBKDF2-HMAC-SHA256, random salt per user |
| Session tokens | `secrets.token_urlsafe(32)`, time-limited (1 hr) |
| Rate limiting | Per-user sliding window, configurable |
| Input sanitization | Strips IRC control chars (`\x00–\x1f`, `\x7f`), prompt injection detection |
| Hostmask auth | `fnmatch` pattern matching against IRC hostmask |
| Bridge isolation | HTTP bridge bound to `127.0.0.1` only |
| Conversation privacy | History stored in-memory only, cleared on restart |

---

## Server Failover

The bot cycles through the `servers` list on each reconnect attempt:

```json
"servers": [
  "budapest.hu.eu.undernet.org",
  "bucharest.ro.eu.undernet.org"
]
```

Add any number of Undernet servers here. Other Undernet servers: `us.undernet.org`, `eu.undernet.org`, `irc.undernet.org`.

---

## Assembly Module

The optional x86_64 NASM assembly module (`assembly/grocbot_asm.asm`) provides faster implementations of:

- `fast_irc_parse` — IRC message tokenizer
- `sanitize_buffer` — control character removal
- `xor_encrypt` — simple XOR cipher for lightweight obfuscation
- `hash_djb2` — fast DJB2 string hashing
- `rate_check` — atomic rate limit counter

The Python bot auto-detects `grocbot_asm.so` and falls back to pure Python if not present.

```bash
cd assembly && ./build.sh
# Requires: nasm, gcc
```

---

## Project Structure

```
groc-IRC/
├── python/
│   ├── main.py              # Main orchestrator (GrocIRCBot class)
│   ├── core/
│   │   └── irc_bot.py       # Async IRC client, server cycling, reconnect
│   ├── api/
│   │   ├── grok_client.py   # Grok API client (modes, headers, history)
│   │   └── bridge_server.py # HTTP bridge server (aiohttp, port 5580)
│   ├── auth/
│   │   └── admin.py         # Role-based access control (User/Manager/SuperAdmin)
│   └── utils/
│       ├── config.py        # Config loader (JSON + env overrides)
│       ├── security.py      # RateLimiter, InputSanitizer, SecureConfig, password utils
│       └── asm_bridge.py    # ctypes bridge to assembly .so
├── tcl/
│   ├── grocbot.tcl          # Standalone Tcl IRC bot
│   └── grocbot_eggdrop.tcl  # Eggdrop-compatible Tcl script
├── assembly/
│   ├── grocbot_asm.asm      # x86_64 NASM performance routines
│   └── build.sh             # Builds grocbot_asm.so
├── config/
│   └── settings.json        # Full bot configuration
├── .env                     # Your local secrets (never commit this)
├── .env.example             # Template with all available variables
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Requirements

- **Python** 3.8+
- **aiohttp** ≥ 3.9.0
- **python-dotenv** ≥ 1.0.0
- **cryptography** ≥ 41.0.0
- **Tcl** 8.6 *(for Tcl bot only)*
- **NASM** + **GCC** *(for assembly module, optional)*

```bash
pip install -r requirements.txt
```

---

## License

MIT License — see [LICENSE](LICENSE)

## Author

**daxprime / iamre00t00** — [iamre00t00@gmail.com](mailto:iamre00t00@gmail.com)

---

## Docker Deployment

> **Note — `sudo` requirement:** Docker commands require `sudo` until you log out and back in
> after installation (the `docker` group is only applied at next login).
> Alternatively, run `newgrp docker` once in your current terminal to activate it immediately.

### Essential Commands

```bash
# Start the bot (detached)
sudo docker compose up -d

# Follow live logs
sudo docker compose logs -f grocbot

# Stop the bot
sudo docker compose down
```

### Quick Start

```bash
# 1. Clone the repo (or use the already-cloned dockerized branch)
git clone -b dockerized https://github.com/daxprime/groc-IRC.git groc-irc-docker
cd groc-irc-docker

# 2. Create your .env file from the template
cp .env.example .env
# Edit .env and fill in:
#   GROK_API_KEY       — your xAI API key
#   IRC_NICKNAME       — bot nick (default: GrocBot)
#   IRC_CHANNELS       — comma-separated, e.g. #grocbot
#   SUPER_ADMIN_PASSWORD — admin console password

# 3. Build and start
sudo docker compose up -d
```

### Container Overview

| Component | Detail |
|-----------|--------|
| Base image | `python:3.12-slim` |
| Build stage | `python:3.12-slim` + nasm + gcc (compiles Assembly module) |
| Runtime stage | Slim image, no build tools, non-root user (`grocbot`, uid 1001) |
| Exposed port | `5580` (HTTP bridge API, bound to `127.0.0.1` only) |
| Volumes | `./config:/app/config` (persist settings), `./logs:/app/logs` |

### Environment Variables

All variables from `.env.example` are available inside the container. Key ones:

| Variable | Description | Default |
|----------|-------------|---------|
| `GROK_API_KEY` | xAI API key (**required**) | — |
| `IRC_SERVER` | Primary IRC server | `budapest.hu.eu.undernet.org` |
| `IRC_NICKNAME` | Bot nick | `GrocBot` |
| `IRC_CHANNELS` | Channel(s) to join | `#grocbot` |
| `GROK_MODEL` | Grok model name | `grok-3` |
| `BRIDGE_HOST` | Bridge server bind address | `0.0.0.0` |
| `BRIDGE_PORT` | Bridge server port | `5580` |
| `SUPER_ADMIN_PASSWORD` | `!admin` password | — |

### Makefile Commands

> If `docker` group is not yet active in your session, prefix with `sudo`: `sudo make up`

```bash
make build     # Build Docker image
make up        # Build + start in background
make run       # Start with live logs
make down      # Stop and remove containers
make logs      # Follow container logs
make restart   # Restart the bot
make shell     # Get a shell inside the container
make status    # Query bridge API health endpoint
make clean     # Remove containers, images, and volumes
```

### Manual docker compose Commands

```bash
sudo docker compose up -d                   # Start detached
sudo docker compose logs -f grocbot         # Follow logs
sudo docker compose restart grocbot         # Restart after config change
sudo docker compose down                    # Stop
sudo docker compose down --rmi all          # Stop + remove image
```

### Volumes and Persistence

The bot stores runtime state in `./config/settings.json`. Mount it as a volume so changes survive container restarts:

```yaml
volumes:
  - ./config:/app/config
```

Logs are written to `./logs/` and rotated by Docker's json-file driver (10 MB × 5 files by default).

### HTTP Bridge API (port 5580)

The bridge allows Tcl scripts or external tools to interact with the bot. By default it is only accessible from localhost (`127.0.0.1:5580`). To expose it on your network, edit `docker-compose.yml`:

```yaml
ports:
  - "5580:5580"   # expose to all interfaces (trusted networks only)
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Bot status (nick, server, channel, mode) |
| `/api/chat` | POST | Send a message, get Grok response |
| `/api/mode` | POST | Change response mode |
| `/api/header` | POST | Change system prompt header |

### Healthcheck

Docker automatically polls `/api/status` every 60 seconds. If the bridge is down the container is marked `unhealthy`. Check with:

```bash
docker inspect --format='{{.State.Health.Status}}' groc-irc-bot
```

### Multi-architecture Build (optional)

```bash
docker buildx create --use
docker buildx build --platform linux/amd64,linux/arm64 -t yourname/groc-irc:latest --push .
```

### Upgrading

```bash
git pull origin dockerized
sudo docker compose down
sudo docker compose build --no-cache
sudo docker compose up -d
```

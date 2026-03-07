# groc-IRC

**Multi-language IRC bot powered by Grok AI** — Python, Tcl & x86_64 Assembly

Connect to Undernet IRC network, ask questions via `!grok`, and get AI-powered responses directly in your channels.

## Architecture

```
┌─────────────────────────────────────────────┐
│                 IRC (Undernet)               │
│            us.undernet.org:6667              │
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
    │   (customizable modes,     │
    │    headers, contexts)      │
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

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/iamre00t00/groc-IRC.git
cd groc-IRC
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your settings:
#   GROK_API_KEY=your-xai-api-key
#   IRC_NICKNAME=YourBot
#   SUPER_ADMIN_HOSTMASK=yournick!*@your.host
#   SUPER_ADMIN_PASSWORD=secretpassword
```

### 3. Run

```bash
# Python bot (recommended)
python -m python.main

# Tcl standalone bot
tclsh tcl/grocbot.tcl

# Eggdrop (add to eggdrop.conf)
# source /path/to/groc-IRC/tcl/grocbot_eggdrop.tcl
```

### 4. Build Assembly (optional)

```bash
cd assembly
chmod +x build.sh
./build.sh
# Produces grocbot_asm.so - auto-detected by Python bot
```

## Commands

### User Commands
| Command | Description |
|---------|-------------|
| `!grok <question>` | Ask Grok AI a question |
| `!help` | Show help message |
| `!status` | Show bot status (model, mode, temp) |
| `!modes` | List available API modes |

### Admin Commands (Managers & Super Admin)
| Command | Description |
|---------|-------------|
| `!admin login [password]` | Authenticate |
| `!admin setheader <key> <value>` | Set custom API header |
| `!admin removeheader <key>` | Remove API header |
| `!admin listheaders` | List current headers |
| `!admin setcontext <text>` | Set channel system prompt |
| `!admin clearcontext` | Clear channel context |
| `!admin setmode <mode>` | Set channel API mode |
| `!admin setmodel <model>` | Change Grok model |
| `!admin settemp <0.0-2.0>` | Set temperature |
| `!admin setmaxtokens <n>` | Set max response tokens |
| `!admin clearhistory [channel]` | Clear conversation history |
| `!admin join <#channel>` | Join a channel |
| `!admin part <#channel>` | Leave a channel |

### Super Admin Only
| Command | Description |
|---------|-------------|
| `!admin addmanager <nick> <hostmask> [password]` | Add manager |
| `!admin removemanager <nick>` | Remove manager |
| `!admin listmanagers` | List all managers |
| `!admin block <hostmask>` | Block a user |
| `!admin unblock <hostmask>` | Unblock a user |
| `!admin shutdown` | Shutdown the bot |

## API Customization

### Modes

Pre-configured in `config/settings.json`:

- **default** — Balanced responses (temp 0.7)
- **creative** — More creative output (temp 1.2)
- **precise** — Factual, focused (temp 0.3)
- **code** — Code generation optimized (temp 0.2)

Set per-channel: `!admin setmode creative`

### Custom Headers

Add any HTTP header to API requests:
```
!admin setheader X-Custom-Header my-value
!admin listheaders
!admin removeheader X-Custom-Header
```

### Context / System Prompts

Override the system prompt per-channel:
```
!admin setcontext You are an expert Python developer. Only answer coding questions.
!admin clearcontext
```

### Model & Parameters

```
!admin setmodel grok-3
!admin settemp 0.5
!admin setmaxtokens 2048
```

## Security

- **API Key Encryption** — Fernet (AES-256) encryption for stored secrets
- **Password Hashing** — PBKDF2-HMAC-SHA256 with random salts
- **Rate Limiting** — Per-user sliding window (configurable)
- **Input Sanitization** — Strips control chars, detects prompt injection
- **Hostmask Auth** — fnmatch pattern matching for admin verification
- **Localhost Bridge** — HTTP bridge only accepts 127.0.0.1 connections
- **Session Tokens** — Time-limited authentication tokens

## Project Structure

```
groc-IRC/
├── python/
│   ├── __init__.py
│   ├── main.py              # Main orchestrator
│   ├── core/
│   │   ├── __init__.py
│   │   └── irc_bot.py       # Async IRC client
│   ├── api/
│   │   ├── __init__.py
│   │   ├── grok_client.py   # Grok API client
│   │   └── bridge_server.py # HTTP bridge for Tcl
│   ├── auth/
│   │   ├── __init__.py
│   │   └── admin.py         # Admin/Manager system
│   └── utils/
│       ├── __init__.py
│       ├── config.py         # Configuration manager
│       ├── security.py       # Rate limiter, sanitizer, crypto
│       └── asm_bridge.py     # Assembly ctypes bridge
├── tcl/
│   ├── grocbot.tcl           # Standalone Tcl bot
│   └── grocbot_eggdrop.tcl   # Eggdrop-compatible script
├── assembly/
│   ├── grocbot_asm.asm       # x86_64 NASM routines
│   └── build.sh              # Build script
├── config/
│   └── settings.json         # Bot configuration
├── .env.example              # Environment template
├── .gitignore
├── requirements.txt
├── LICENSE
└── README.md
```

## Configuration

Edit `config/settings.json` for IRC settings, API modes, security parameters, and logging.

Environment variables (`.env`) override config file settings:

| Variable | Description |
|----------|-------------|
| `GROK_API_KEY` | Your xAI API key (required) |
| `IRC_SERVER` | IRC server hostname |
| `IRC_PORT` | IRC server port |
| `IRC_NICKNAME` | Bot nickname |
| `UNDERNET_USER` | Undernet X username |
| `UNDERNET_PASS` | Undernet X password |
| `SUPER_ADMIN_HOSTMASK` | Super admin hostmask pattern |
| `SUPER_ADMIN_PASSWORD` | Super admin password |

## Requirements

- Python 3.8+
- aiohttp >= 3.9.0
- python-dotenv >= 1.0.0
- cryptography >= 41.0.0
- Tcl 8.6 (for Tcl bot)
- NASM + GCC (for assembly, optional)

## License

MIT License — see [LICENSE](LICENSE)

## Author

**iamre00t00** — [iamre00t00@gmail.com](mailto:iamre00t00@gmail.com)

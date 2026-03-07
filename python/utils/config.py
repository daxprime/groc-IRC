"""Configuration loader for groc-IRC."""
import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from copy import deepcopy

logger = logging.getLogger("groc-irc.config")

class Config:
    DEFAULT_CONFIG_PATH = "config/settings.json"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or self.DEFAULT_CONFIG_PATH)
        self._config: Dict[str, Any] = {}
        self._runtime_overrides: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")
        with open(self.config_path, 'r') as f:
            self._config = json.load(f)
        self._apply_env_overrides()
        logger.info(f"Config loaded from {self.config_path}")

    def reload(self):
        self._runtime_overrides.clear()
        self.load()

    def save(self):
        merged = self._get_merged_config()
        with open(self.config_path, 'w') as f:
            json.dump(merged, f, indent=4)

    def get(self, key_path: str, default: Any = None) -> Any:
        if key_path in self._runtime_overrides:
            return self._runtime_overrides[key_path]
        keys = key_path.split('.')
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, key_path: str, value: Any, persist: bool = False):
        self._runtime_overrides[key_path] = value
        if persist:
            keys = key_path.split('.')
            config = self._config
            for key in keys[:-1]:
                if key not in config:
                    config[key] = {}
                config = config[key]
            config[keys[-1]] = value
            self.save()

    def _get_merged_config(self) -> Dict[str, Any]:
        merged = deepcopy(self._config)
        for key_path, value in self._runtime_overrides.items():
            keys = key_path.split('.')
            config = merged
            for key in keys[:-1]:
                if key not in config:
                    config[key] = {}
                config = config[key]
            config[keys[-1]] = value
        return merged

    def _apply_env_overrides(self):
        env_mappings = {
            "IRC_NETWORK": "irc.network",
            "IRC_PORT": ("irc.port", int),
            "IRC_USE_SSL": ("irc.use_ssl", lambda x: x.lower() == 'true'),
            "IRC_NICKNAME": "irc.nickname",
            "IRC_CHANNELS": ("irc.channels", lambda x: x.split(',')),
            "GROK_API_BASE_URL": "grok_api.base_url",
            "RATE_LIMIT_PER_USER": ("security.rate_limit_per_user", int),
            "RATE_LIMIT_WINDOW": ("security.rate_limit_window_seconds", int),
            "SUPER_ADMIN_HOSTMASKS": ("admin.super_admins", lambda x: x.split(',')),
        }
        for env_var, mapping in env_mappings.items():
            env_value = os.environ.get(env_var)
            if env_value is not None:
                if isinstance(mapping, tuple):
                    key_path, converter = mapping
                    try:
                        self.set(key_path, converter(env_value))
                    except (ValueError, TypeError):
                        pass
                else:
                    self.set(mapping, env_value)

    @property
    def irc(self) -> Dict[str, Any]:
        return self.get("irc", {})

    @property
    def grok_api(self) -> Dict[str, Any]:
        return self.get("grok_api", {})

    @property
    def security(self) -> Dict[str, Any]:
        return self.get("security", {})

    @property
    def admin(self) -> Dict[str, Any]:
        return self.get("admin", {})

    def get_mode(self, mode_name: str) -> Optional[Dict[str, Any]]:
        modes = self.get("grok_api.custom_modes", {})
        return modes.get(mode_name)

    def set_mode(self, mode_name: str, mode_config: Dict[str, Any], persist: bool = False):
        modes = self.get("grok_api.custom_modes", {})
        modes[mode_name] = mode_config
        self.set("grok_api.custom_modes", modes, persist=persist)

    def get_custom_headers(self) -> Dict[str, str]:
        return self.get("grok_api.custom_headers", {})

    def set_custom_header(self, key: str, value: str, persist: bool = False):
        headers = self.get_custom_headers()
        headers[key] = value
        self.set("grok_api.custom_headers", headers, persist=persist)

    def remove_custom_header(self, key: str, persist: bool = False):
        headers = self.get_custom_headers()
        headers.pop(key, None)
        self.set("grok_api.custom_headers", headers, persist=persist)

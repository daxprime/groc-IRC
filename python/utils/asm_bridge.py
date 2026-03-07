"""Assembly bridge - Loads compiled .so and provides Python fallbacks."""

import os
import ctypes
import logging
import re
import time
from typing import Optional, Dict, Tuple

logger = logging.getLogger("groc-irc.asm")

ASM_LIB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             "assembly", "grocbot_asm.so")


class ASMBridge:
    """Bridge to x86_64 assembly routines with Python fallbacks."""

    def __init__(self, lib_path: str = ASM_LIB_PATH):
        self._lib = None
        self._available = False
        try:
            if os.path.exists(lib_path):
                self._lib = ctypes.CDLL(lib_path)
                self._setup_functions()
                self._available = True
                logger.info(f"Assembly library loaded from {lib_path}")
            else:
                logger.info("Assembly library not found, using Python fallbacks")
        except OSError as e:
            logger.warning(f"Could not load assembly library: {e}")

    def _setup_functions(self):
        if not self._lib:
            return
        self._lib.fast_irc_parse.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._lib.fast_irc_parse.restype = ctypes.c_int
        self._lib.sanitize_buffer.argtypes = [ctypes.c_char_p, ctypes.c_int]
        self._lib.sanitize_buffer.restype = ctypes.c_int
        self._lib.xor_encrypt.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                           ctypes.c_char_p, ctypes.c_int]
        self._lib.xor_encrypt.restype = None
        self._lib.hash_djb2.argtypes = [ctypes.c_char_p]
        self._lib.hash_djb2.restype = ctypes.c_uint64
        self._lib.rate_check.argtypes = [ctypes.c_uint64, ctypes.c_uint64,
                                          ctypes.c_uint64, ctypes.c_uint64]
        self._lib.rate_check.restype = ctypes.c_int

    @property
    def available(self) -> bool:
        return self._available

    def parse_irc_message(self, raw_line: str) -> Dict[str, str]:
        if self._available:
            try:
                input_buf = raw_line.encode('utf-8')
                output_buf = ctypes.create_string_buffer(512)
                result = self._lib.fast_irc_parse(input_buf, output_buf, len(input_buf))
                if result == 0:
                    raw_out = output_buf.raw
                    return {
                        "prefix": raw_out[0:128].split(b"\x00")[0].decode('utf-8', errors='replace'),
                        "command": raw_out[128:160].split(b"\x00")[0].decode('utf-8', errors='replace'),
                        "params": raw_out[160:416].split(b"\x00")[0].decode('utf-8', errors='replace'),
                        "trailing": raw_out[416:512].split(b"\x00")[0].decode('utf-8', errors='replace'),
                    }
            except Exception as e:
                logger.debug(f"ASM parse failed, using fallback: {e}")
        return self._parse_irc_fallback(raw_line)

    def _parse_irc_fallback(self, raw_line: str) -> Dict[str, str]:
        prefix = command = params_str = trailing = ""
        line = raw_line.strip()
        if line.startswith(':'):
            parts = line[1:].split(' ', 1)
            prefix = parts[0]
            line = parts[1] if len(parts) > 1 else ""
        if ' :' in line:
            before, trailing = line.split(' :', 1)
        else:
            before = line
        parts = before.split()
        if parts:
            command = parts[0]
            params_str = ' '.join(parts[1:])
        return {"prefix": prefix, "command": command, "params": params_str, "trailing": trailing}

    def sanitize(self, text: str) -> str:
        if self._available:
            try:
                buf = ctypes.create_string_buffer(text.encode('utf-8'), len(text) + 1)
                new_len = self._lib.sanitize_buffer(buf, len(text))
                return buf.value.decode('utf-8', errors='replace')[:new_len]
            except Exception as e:
                logger.debug(f"ASM sanitize failed, using fallback: {e}")
        return self._sanitize_fallback(text)

    def _sanitize_fallback(self, text: str) -> str:
        result = []
        for ch in text:
            code = ord(ch)
            if 32 <= code <= 126 or code in (9, 10):
                result.append(ch)
        return ''.join(result)

    def xor_encrypt(self, data: bytes, key: bytes) -> bytes:
        if self._available and len(data) > 0 and len(key) > 0:
            try:
                data_buf = ctypes.create_string_buffer(data, len(data))
                key_buf = ctypes.create_string_buffer(key, len(key))
                self._lib.xor_encrypt(data_buf, len(data), key_buf, len(key))
                return data_buf.raw[:len(data)]
            except Exception as e:
                logger.debug(f"ASM xor failed, using fallback: {e}")
        return self._xor_fallback(data, key)

    def _xor_fallback(self, data: bytes, key: bytes) -> bytes:
        if not key:
            return data
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def hash_djb2(self, text: str) -> int:
        if self._available:
            try:
                return self._lib.hash_djb2(text.encode('utf-8'))
            except Exception as e:
                logger.debug(f"ASM hash failed, using fallback: {e}")
        return self._hash_djb2_fallback(text)

    def _hash_djb2_fallback(self, text: str) -> int:
        h = 5381
        for ch in text.encode('utf-8'):
            h = ((h << 5) + h + ch) & 0xFFFFFFFFFFFFFFFF
        return h

    def check_rate(self, user_hash: int, current_time: int, max_req: int, window: int) -> bool:
        if self._available:
            try:
                return self._lib.rate_check(user_hash, current_time, max_req, window) == 1
            except Exception as e:
                logger.debug(f"ASM rate check failed, using fallback: {e}")
        return True


_bridge_instance: Optional[ASMBridge] = None


def get_asm_bridge() -> ASMBridge:
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = ASMBridge()
    return _bridge_instance

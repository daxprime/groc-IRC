"""Admin and Manager system for groc-IRC - Role-based access control."""

import time
import fnmatch
import logging
import secrets
from enum import IntEnum
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, field
from python.utils.security import hash_password, verify_password, generate_token

logger = logging.getLogger("groc-irc.auth")


class Role(IntEnum):
    USER = 0
    MANAGER = 1
    SUPER_ADMIN = 2


@dataclass
class AdminUser:
    nick: str
    hostmask_pattern: str
    role: Role
    password_hash: str = ""
    added_by: str = ""
    added_at: float = field(default_factory=time.time)
    last_seen: float = 0.0
    is_blocked: bool = False


@dataclass
class Session:
    nick: str
    hostmask: str
    role: Role
    token: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def is_valid(self) -> bool:
        if self.expires_at == 0:
            return True
        return time.time() < self.expires_at


class AdminManager:
    """Manages admin users, sessions, and role-based access."""

    def __init__(self, super_admin_hostmask="*!*@*", super_admin_password="",
                 session_timeout=3600):
        self._users: Dict[str, AdminUser] = {}
        self._sessions: Dict[str, Session] = {}
        self._blocked_masks: Set[str] = set()
        self.session_timeout = session_timeout

        if super_admin_hostmask:
            self._users["__super_admin__"] = AdminUser(
                nick="SuperAdmin",
                hostmask_pattern=super_admin_hostmask,
                role=Role.SUPER_ADMIN,
                password_hash=hash_password(super_admin_password) if super_admin_password else "",
                added_by="SYSTEM"
            )

    def _match_hostmask(self, hostmask: str, pattern: str) -> bool:
        return fnmatch.fnmatch(hostmask.lower(), pattern.lower())

    def check_blocked(self, hostmask: str) -> bool:
        for mask in self._blocked_masks:
            if self._match_hostmask(hostmask, mask):
                return True
        return False

    def get_role(self, hostmask: str) -> Role:
        if self.check_blocked(hostmask):
            return Role.USER
        best_role = Role.USER
        for user in self._users.values():
            if user.is_blocked:
                continue
            if self._match_hostmask(hostmask, user.hostmask_pattern):
                if user.role > best_role:
                    best_role = user.role
        return best_role

    def is_admin(self, hostmask: str) -> bool:
        return self.get_role(hostmask) >= Role.SUPER_ADMIN

    def is_manager(self, hostmask: str) -> bool:
        return self.get_role(hostmask) >= Role.MANAGER

    def authenticate(self, nick: str, hostmask: str, password: str = "") -> Optional[Session]:
        if self.check_blocked(hostmask):
            logger.warning(f"Blocked user attempted auth: {hostmask}")
            return None
        role = self.get_role(hostmask)
        if role == Role.USER:
            if password:
                for user in self._users.values():
                    if user.password_hash and verify_password(password, user.password_hash):
                        if not user.is_blocked:
                            role = user.role
                            break
            if role == Role.USER:
                return None
        token = generate_token()
        session = Session(
            nick=nick, hostmask=hostmask, role=role, token=token,
            expires_at=time.time() + self.session_timeout if self.session_timeout else 0
        )
        self._sessions[hostmask] = session
        logger.info(f"Authenticated {nick} ({hostmask}) as {role.name}")
        return session

    def get_session(self, hostmask: str) -> Optional[Session]:
        session = self._sessions.get(hostmask)
        if session and session.is_valid():
            return session
        if session:
            del self._sessions[hostmask]
        return None

    def check_permission(self, hostmask: str, required_role: Role) -> bool:
        session = self.get_session(hostmask)
        if session:
            return session.role >= required_role
        return self.get_role(hostmask) >= required_role

    def add_manager(self, nick: str, hostmask_pattern: str, added_by: str,
                    password: str = "") -> bool:
        key = f"manager_{nick.lower()}"
        if key in self._users:
            return False
        self._users[key] = AdminUser(
            nick=nick, hostmask_pattern=hostmask_pattern, role=Role.MANAGER,
            password_hash=hash_password(password) if password else "",
            added_by=added_by
        )
        logger.info(f"Manager added: {nick} ({hostmask_pattern}) by {added_by}")
        return True

    def remove_manager(self, nick: str) -> bool:
        key = f"manager_{nick.lower()}"
        if key in self._users:
            del self._users[key]
            logger.info(f"Manager removed: {nick}")
            return True
        return False

    def list_managers(self) -> List[Dict[str, str]]:
        managers = []
        for key, user in self._users.items():
            if key == "__super_admin__":
                continue
            managers.append({
                "nick": user.nick,
                "hostmask": user.hostmask_pattern,
                "role": user.role.name,
                "added_by": user.added_by,
                "blocked": str(user.is_blocked),
            })
        return managers

    def block_user(self, hostmask_pattern: str) -> bool:
        self._blocked_masks.add(hostmask_pattern.lower())
        for key, user in self._users.items():
            if self._match_hostmask(user.hostmask_pattern, hostmask_pattern):
                user.is_blocked = True
        sessions_to_remove = [
            hm for hm, s in self._sessions.items()
            if self._match_hostmask(hm, hostmask_pattern)
        ]
        for hm in sessions_to_remove:
            del self._sessions[hm]
        logger.info(f"Blocked: {hostmask_pattern}")
        return True

    def unblock_user(self, hostmask_pattern: str) -> bool:
        self._blocked_masks.discard(hostmask_pattern.lower())
        for user in self._users.values():
            if self._match_hostmask(user.hostmask_pattern, hostmask_pattern):
                user.is_blocked = False
        logger.info(f"Unblocked: {hostmask_pattern}")
        return True

    def list_blocked(self) -> List[str]:
        return list(self._blocked_masks)

    def cleanup_sessions(self):
        expired = [hm for hm, s in self._sessions.items() if not s.is_valid()]
        for hm in expired:
            del self._sessions[hm]

    def revoke_session(self, hostmask: str) -> bool:
        if hostmask in self._sessions:
            del self._sessions[hostmask]
            return True
        return False

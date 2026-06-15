from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    user_id: str
    display_name: str
    locale: str = "en-US"
    timezone: str = "UTC"
    storage_key: str = "local"

    @classmethod
    def local_default(cls) -> "UserContext":
        return cls(
            user_id="local-user",
            display_name="Local User",
            storage_key="local-user",
        )

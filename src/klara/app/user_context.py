"""User partition context assembled by the Klara app layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserContext:
    """Local user identity contract for Klara runs.

    This is not production auth. It gives traces, sessions, memory, and skills a
    future partition key while keeping the current runtime focused on loop
    mechanics.
    """

    # Internal user id is stable but not necessarily prompt-visible.
    user_id: str
    # Display name may enter prompts as a friendly user label.
    display_name: str
    # Locale is a prompt/runtime hint, not an authorization boundary.
    locale: str = "en-US"
    # Timezone lets later prompts describe local time consistently.
    timezone: str = "UTC"
    # Storage key is the filesystem/database partition handle for local adapters.
    storage_key: str = "local"

    @classmethod
    def local_default(cls) -> "UserContext":
        """Create the single-user local context used by local runs.

        Returns:
            A deterministic local user context for tests and examples.
        """

        return cls(
            user_id="local-user",
            display_name="Local User",
            storage_key="local-user",
        )

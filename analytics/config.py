"""Validated runtime settings. No production default credentials."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    admin_token: str
    hash_secret: str
    database: str

    @classmethod
    def from_env(cls) -> "Settings":
        admin = os.getenv("GC_ANALYTICS_ADMIN_TOKEN", "")
        secret = os.getenv("GC_ANALYTICS_HASH_SECRET", "")
        if len(admin) < 32 or len(secret) < 32 or admin == secret:
            raise RuntimeError(
                "Set distinct random GC_ANALYTICS_ADMIN_TOKEN and "
                "GC_ANALYTICS_HASH_SECRET (at least 32 characters each)."
            )
        return cls(admin_token=admin, hash_secret=secret,
                   database=os.getenv("GC_ANALYTICS_DATABASE", "./analytics.sqlite3"))

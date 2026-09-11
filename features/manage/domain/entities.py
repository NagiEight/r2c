from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class R2Object:
    key: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class R2HttpConfig:
    account_id: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str

@dataclass(frozen=True)
class FileTask:
    local_path: Path
    remote_key: str
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class BulkOperationResult:
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (key_or_path, error_reason)

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.failed)
@dataclass(frozen=True)
class R2ObjectSummary:
    key: str
    size_bytes: int
    last_modified: datetime | None = None
class OverwriteOption(str, Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"
    OVERWRITE_ALL = "overwrite_all"
    SKIP_ALL = "skip_all"
    RENAME_ALL = "rename_all"

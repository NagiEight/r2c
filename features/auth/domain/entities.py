from dataclasses import dataclass


@dataclass(frozen=True)
class R2Credentials:
    account_id: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str

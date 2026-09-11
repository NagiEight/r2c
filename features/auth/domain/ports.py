

from typing import Protocol

from features.auth.domain.entities import R2Credentials


class AccountRepositoryPort(Protocol):
    def save_account(self, name: str, credentials: R2Credentials) -> None:
        ...

    def set_active_account(self, name: str) -> None:
        ...

    def get_active_account_name(self) -> str:
        ...

    def get_account(self, name: str) -> R2Credentials:
        ...

    def list_account_names(self) -> list[str]:
        ...

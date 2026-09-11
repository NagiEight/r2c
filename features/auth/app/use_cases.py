from dataclasses import dataclass

from features.auth.domain.entities import R2Credentials
from features.auth.domain.ports import AccountRepositoryPort


@dataclass(frozen=True)
class SaveAccountUseCase:
    account_repo: AccountRepositoryPort

    def execute(
        self,
        name: str,
        account_id: str,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        set_active: bool = True,
    ) -> None:
        creds = R2Credentials(
            account_id=account_id,
            bucket_name=bucket_name,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        self.account_repo.save_account(name, creds)
        if set_active:
            self.account_repo.set_active_account(name)


@dataclass(frozen=True)
class SelectActiveAccountUseCase:
    account_repo: AccountRepositoryPort

    def execute(self, name: str) -> None:
        available = self.account_repo.list_account_names()
        if name not in available:
            raise ValueError(f"Account '{name}' does not exist. Available accounts: {', '.join(available)}")
        self.account_repo.set_active_account(name)


@dataclass(frozen=True)
class GetActiveCredentialsUseCase:
    account_repo: AccountRepositoryPort

    def execute(self, override_account: str | None = None) -> R2Credentials:
        target_name = override_account or self.account_repo.get_active_account_name()
        return self.account_repo.get_account(target_name)

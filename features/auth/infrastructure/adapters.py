import json
from pathlib import Path

import keyring

from features.auth.domain.entities import R2Credentials


class KeyringAccountRepository:
    _SERVICE_NAME = "r2c"

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = (
            config_path or Path.home() / ".config" / "r2c" / "config.json"
        )

    def _load_data(self) -> dict:
        if not self._config_path.exists():
            return {"active_account": "default", "accounts": {}}
        return json.loads(self._config_path.read_text())

    def _save_data(self, data: dict) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(data, indent=2))

    def save_account(self, name: str, credentials: R2Credentials) -> None:
        data = self._load_data()
        data["accounts"][name] = {
            "account_id": credentials.account_id,
            "bucket_name": credentials.bucket_name,
            "access_key_id": credentials.access_key_id,
        }
        self._save_data(data)
        keyring.set_password(
            self._SERVICE_NAME, f"secret_key:{name}", credentials.secret_access_key
        )

    def set_active_account(self, name: str) -> None:
        data = self._load_data()
        data["active_account"] = name
        self._save_data(data)

    def get_active_account_name(self) -> str:
        data = self._load_data()
        return data.get("active_account", "default")

    def get_account(self, name: str) -> R2Credentials:
        data = self._load_data()
        account_data = data.get("accounts", {}).get(name)
        if not account_data:
            raise KeyError(f"Account '{name}' is not configured.")

        secret_key = keyring.get_password(self._SERVICE_NAME, f"secret_key:{name}")
        if not secret_key:
            raise ValueError(f"Secret key for account '{name}' not found in keyring.")

        return R2Credentials(
            account_id=account_data["account_id"],
            bucket_name=account_data["bucket_name"],
            access_key_id=account_data["access_key_id"],
            secret_access_key=secret_key,
        )

    def list_account_names(self) -> list[str]:
        data = self._load_data()
        return list(data.get("accounts", {}).keys())

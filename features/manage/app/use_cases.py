import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from ..domain.entities import BulkOperationResult, FileTask
from ..domain.ports import R2AdapterPort


@dataclass(frozen=True)
class ManageAssetUseCase:
    r2_adapter: R2AdapterPort

    async def upload_directory(
        self,
        source_dir: Path,
        remote_prefix: str = "",
        max_concurrent: int = 5,
    ) -> BulkOperationResult:
        if not source_dir.is_dir():
            raise ValueError(f"Path '{source_dir}' is not a valid directory.")

        tasks: list[FileTask] = []
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                relative_path = file_path.relative_to(source_dir).as_posix()
                remote_key = f"{remote_prefix.strip('/')}/{relative_path}".lstrip("/")

                content_type, _ = mimetypes.guess_type(file_path)
                tasks.append(
                    FileTask(
                        local_path=file_path,
                        remote_key=remote_key,
                        content_type=content_type or "application/octet-stream",
                    )
                )

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _upload_single(task: FileTask) -> None:
            target_key = task.remote_key

            async with semaphore:
                data = task.local_path.read_bytes()
                max_retries = 2

                for attempt in range(1, max_retries + 1):
                    try:
                        await self.r2_adapter.upload(
                            key=target_key,
                            data=data,
                            content_type=task.content_type,
                        )
                        succeeded.append(target_key)
                        break
                    except Exception as err:
                        if attempt == max_retries:
                            failed.append((str(task.local_path), str(err)))
                        else:
                            await asyncio.sleep(1)

        await asyncio.gather(*[_upload_single(t) for t in tasks])
        return BulkOperationResult(succeeded=succeeded, failed=failed)

    async def sync_remote_prefix_to_dir(
        self,
        prefix: str,
        target_dir: Path,
        max_concurrent: int = 5,
    ) -> BulkOperationResult:
        target_dir.mkdir(parents=True, exist_ok=True)
        keys = await self.r2_adapter.list_keys(prefix=prefix)

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch_single(key: str) -> None:
            async with semaphore:
                try:
                    content = await self.r2_adapter.fetch(key)
                    relative_key = key.removeprefix(prefix).lstrip("/")
                    local_file = target_dir / relative_key
                    local_file.parent.mkdir(parents=True, exist_ok=True)
                    local_file.write_bytes(content)
                    succeeded.append(key)
                except Exception as err:
                    failed.append((key, str(err)))

        await asyncio.gather(*[_fetch_single(k) for k in keys])
        return BulkOperationResult(succeeded=succeeded, failed=failed)

    async def delete_prefix(self, prefix: str) -> BulkOperationResult:
        keys = await self.r2_adapter.list_keys(prefix=prefix)
        if not keys:
            return BulkOperationResult()

        try:
            await self.r2_adapter.delete_many(keys)
            return BulkOperationResult(succeeded=keys)
        except Exception as err:
            return BulkOperationResult(failed=[(prefix, str(err))])

    async def delete_by_pattern(
        self,
        pattern: str,
        prefix: str = "",
        case_sensitive: bool = False,
    ) -> BulkOperationResult:
        """Finds all keys matching a substring pattern and bulk deletes them."""
        all_keys = await self.r2_adapter.list_keys(prefix=prefix)

        if case_sensitive:
            matching_keys = [k for k in all_keys if pattern in k]
        else:
            target = pattern.lower()
            matching_keys = [k for k in all_keys if target in k.lower()]

        if not matching_keys:
            return BulkOperationResult()

        try:
            await self.r2_adapter.delete_many(matching_keys)
            return BulkOperationResult(succeeded=matching_keys)
        except Exception as err:
            return BulkOperationResult(
                failed=[(k, str(err)) for k in matching_keys]
            )

    async def delete_keys(self, keys: list[str]) -> BulkOperationResult:
        """Deletes specific keys after verifying their existence on R2."""
        if not keys:
            return BulkOperationResult()

        try:
            existing_keys = set(await self.r2_adapter.list_keys())
        except Exception as err:
            return BulkOperationResult(failed=[(k, str(err)) for k in keys])

        valid_keys = [k for k in keys if k in existing_keys]
        missing_keys = [k for k in keys if k not in existing_keys]

        failed: list[tuple[str, str]] = [
            (k, "Key does not exist on R2") for k in missing_keys
        ]

        if not valid_keys:
            return BulkOperationResult(failed=failed)

        try:
            await self.r2_adapter.delete_many(valid_keys)
            return BulkOperationResult(succeeded=valid_keys, failed=failed)
        except Exception as err:
            failed.extend((k, str(err)) for k in valid_keys)
            return BulkOperationResult(failed=failed)

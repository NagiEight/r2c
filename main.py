import mimetypes
from pathlib import Path
from socket import timeout
from typing import Annotated

import httpx
import typer
from async_typer import AsyncTyper
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from features.auth.app.use_cases import (
    GetActiveCredentialsUseCase,
    SaveAccountUseCase,
    SelectActiveAccountUseCase,
)
from features.auth.infrastructure.adapters import KeyringAccountRepository
from features.manage.app.use_cases import ManageAssetUseCase
from features.manage.domain.entities import R2HttpConfig
from features.manage.infrastructure.adapter import HTTPR2Adapter

app = AsyncTyper(name="r2c", help="Streamlined Cloudflare R2 CLI")
account_app = AsyncTyper(help="Manage R2 account profiles")
app.add_typer(account_app, name="account")

account_repo = KeyringAccountRepository()
console = Console()


def get_adapter() -> HTTPR2Adapter:
    use_case = GetActiveCredentialsUseCase(account_repo)
    try:
        creds = use_case.execute()
    except (FileNotFoundError, KeyError, ValueError) as err:
        typer.secho(
            f"Configuration Error: {err}\n"
            "Please configure an account using: r2c account add -n <name> -a <id> -b <bucket> -k <key_id> -s <secret_key>",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    config = R2HttpConfig(
        account_id=creds.account_id,
        bucket_name=creds.bucket_name,
        access_key_id=creds.access_key_id,
        secret_access_key=creds.secret_access_key,
    )
    _timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=60.0)
    client = httpx.AsyncClient(timeout=_timeout)
    return HTTPR2Adapter(config, client)


def _format_http_error(err: httpx.HTTPStatusError) -> str:
    body = err.response.text.strip()
    return f"HTTP {err.response.status_code}: {body}" if body else str(err)


@app.command()
async def upload(
    path: Annotated[
        Path, typer.Option("--path", "-p", help="Local file or directory path")
    ],
    prefix: Annotated[
        str, typer.Option("--prefix", "-k", help="Remote R2 destination prefix/key")
    ] = "",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview files to upload without sending them")
    ] = False,
) -> None:
    """Upload a single file or an entire directory recursively."""
    if not path.exists():
        typer.secho(f"Error: Path '{path}' does not exist.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    if dry_run:
        if path.is_dir():
            files = [p for p in path.rglob("*") if p.is_file()]
            typer.secho(
                f"[DRY RUN] Would upload {len(files)} file(s) from directory '{path}':",
                fg=typer.colors.YELLOW,
            )
            for f in files:
                rel_path = f.relative_to(path).as_posix()
                dest_key = f"{prefix.strip('/')}/{rel_path}" if prefix else rel_path
                typer.echo(f"  - {f} -> {dest_key}")
        else:
            remote_key = prefix or path.name
            typer.secho(f"[DRY RUN] Would upload file: {path} -> {remote_key}", fg=typer.colors.YELLOW)
        return

    async with get_adapter() as adapter:
        if path.is_dir():
            files = [p for p in path.rglob("*") if p.is_file()]
            succeeded, failed = 0, 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("[cyan]Uploading files...", total=len(files))

                for file in files:
                    rel_path = file.relative_to(path).as_posix()
                    dest_key = f"{prefix.strip('/')}/{rel_path}" if prefix else rel_path
                    content_type, _ = mimetypes.guess_type(file)

                    try:
                        await adapter.upload(
                            dest_key, file.read_bytes(), content_type or "application/octet-stream"
                        )
                        succeeded += 1
                    except httpx.HTTPStatusError as err:
                        failed += 1
                        progress.console.print(
                            f"[red]Failed to upload {file}: {_format_http_error(err)}[/red]"
                        )
                    except Exception as err:
                        failed += 1
                        progress.console.print(
                            f"[red]Failed to upload {file}: {type(err).__name__} - {err}[/red]"
                        )
                    finally:
                        progress.advance(task)

            typer.secho(
                f"Uploaded directory '{path}': {succeeded} succeeded, {failed} failed.",
                fg=typer.colors.GREEN if not failed else typer.colors.YELLOW,
            )
        else:
            remote_key = prefix or path.name
            content_type, _ = mimetypes.guess_type(path)
            try:
                await adapter.upload(
                    remote_key, path.read_bytes(), content_type or "application/octet-stream"
                )
                typer.secho(f"Successfully uploaded {path} -> {remote_key}", fg=typer.colors.GREEN)
            except httpx.HTTPStatusError as err:
                typer.secho(f"Upload failed: {_format_http_error(err)}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)


@app.command()
async def fetch(
    key: Annotated[
        str, typer.Option("--key", "-k", help="Remote R2 object key")
    ],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Local output file path")
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview fetch without downloading content")
    ] = False,
) -> None:
    """Fetch an object from R2 and write to a file."""
    if dry_run:
        typer.secho(
            f"[DRY RUN] Would fetch key '{key}' and write to target path '{output}'",
            fg=typer.colors.YELLOW,
        )
        return

    async with get_adapter() as adapter:
        try:
            obj = await adapter.fetch(key)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(obj.content)
            typer.secho(f"Successfully saved {key} -> {output}", fg=typer.colors.GREEN)
        except httpx.HTTPStatusError as err:
            typer.secho(f"Fetch failed: {_format_http_error(err)}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)


@app.command()
async def delete(
    keys: Annotated[
        list[str] | None,
        typer.Argument(help="Specific keys to delete from R2"),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option("--contains", "-c", help="Delete all keys containing this keyword"),
    ] = None,
    prefix: Annotated[
        str,
        typer.Option("--prefix", "-p", help="Optional prefix filter when using --contains"),
    ] = "",
    case_sensitive: Annotated[
        bool,
        typer.Option("--case-sensitive", help="Enable strict case sensitivity for pattern matching"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List matching keys without deleting them"),
    ] = False,
) -> None:
    """Delete objects from R2 by explicit key or keyword pattern."""
    if not keys and not contains:
        typer.secho(
            "Error: Provide at least one key argument or use --contains to filter by pattern.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)

    async with get_adapter() as adapter:
        use_case = ManageAssetUseCase(r2_adapter=adapter)

        if contains:
            result = await use_case.delete_by_pattern(
                pattern=contains,
                prefix=prefix,
                case_sensitive=case_sensitive,
            )
        else:
            result = await use_case.delete_keys(keys or [])

        if not result.succeeded and not result.failed:
            typer.secho("No matching objects found.", fg=typer.colors.YELLOW)
            return

        target_keys = result.succeeded + [item[0] for item in result.failed]

        if dry_run:
            typer.secho(
                f"[DRY RUN] The following {len(target_keys)} key(s) would be processed:",
                fg=typer.colors.YELLOW,
            )
            for key in target_keys:
                typer.echo(f"  - {key}")
            return

        for failed_key, reason in result.failed:
            typer.secho(f"Failed to delete '{failed_key}': {reason}", fg=typer.colors.RED, err=True)

        if result.succeeded:
            typer.secho(
                f"Successfully deleted {len(result.succeeded)} object(s).",
                fg=typer.colors.GREEN,
            )

        if result.failed and not result.succeeded:
            raise typer.Exit(code=1)


@account_app.command("add")
def add_account(
    name: Annotated[
        str, typer.Option("--name", "-n", help="Account alias (e.g. prod, dev)")
    ],
    account_id: Annotated[
        str, typer.Option("--account-id", "-a", help="Cloudflare Account ID")
    ],
    bucket: Annotated[
        str, typer.Option("--bucket", "-b", help="R2 Bucket Name")
    ],
    key_id: Annotated[
        str, typer.Option("--key-id", "-k", help="R2 Access Key ID")
    ],
    secret_key: Annotated[
        str, typer.Option("--secret-key", "-s", help="R2 Secret Access Key")
    ],
    set_active: Annotated[bool, typer.Option("--use/--no-use")] = True,
) -> None:
    """Save a new R2 account and set it active."""
    use_case = SaveAccountUseCase(account_repo)
    use_case.execute(
        name=name,
        account_id=account_id,
        bucket_name=bucket,
        access_key_id=key_id,
        secret_access_key=secret_key,
        set_active=set_active,
    )
    typer.secho(f"Account '{name}' saved successfully.", fg=typer.colors.GREEN)


@account_app.command("use")
def switch_account(
    name: Annotated[str, typer.Argument(help="Account alias to activate")],
) -> None:
    """Switch the active R2 account."""
    use_case = SelectActiveAccountUseCase(account_repo)
    try:
        use_case.execute(name)
        typer.secho(
            f"Switched active account to '{name}'.", fg=typer.colors.GREEN
        )
    except ValueError as err:
        typer.secho(f"Error: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@account_app.command("list")
def list_accounts() -> None:
    """List all saved account profiles."""
    names = account_repo.list_account_names()
    if not names:
        typer.secho(
            "No accounts configured yet. Use 'r2c account add' to create one.",
            fg=typer.colors.YELLOW,
        )
        return

    active = account_repo.get_active_account_name()
    for name in names:
        if name == active:
            typer.secho(f"* {name} (active)", fg=typer.colors.GREEN)
        else:
            typer.echo(f"  {name}")


@account_app.command("current")
def current_account() -> None:
    """Display current active account details."""
    try:
        active_name = account_repo.get_active_account_name()
        creds = account_repo.get_account(active_name)
        typer.echo(f"Active Profile : {active_name}")
        typer.echo(f"Account ID     : {creds.account_id}")
        typer.echo(f"Bucket Name    : {creds.bucket_name}")
    except (KeyError, FileNotFoundError, ValueError):
        typer.secho(
            "No active account set. Run 'r2c account add' to configure one.",
            fg=typer.colors.YELLOW,
        )


def _format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size_bytes)} B"
        size /= 1024.0
    return f"{size:.1f} TB"


@app.command("ls")
@app.command("list-objects")
async def list_objects(
    prefix: Annotated[
        str,
        typer.Option("--prefix", "-p", help="Filter keys starting with a specific prefix/folder"),
    ] = "",
) -> None:
    """List objects in the active R2 bucket."""
    async with get_adapter() as adapter:
        try:
            objects = await adapter.list_objects(prefix=prefix)
        except httpx.HTTPStatusError as err:
            typer.secho(f"Listing failed: {_format_http_error(err)}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)

        if not objects:
            typer.secho("No objects found.", fg=typer.colors.YELLOW)
            return

        typer.secho(f"{'SIZE':<12} {'LAST MODIFIED':<22} KEY", fg=typer.colors.CYAN, bold=True)
        typer.echo("-" * 65)

        for obj in objects:
            size_str = _format_size(obj.size_bytes)
            date_str = (
                obj.last_modified.strftime("%Y-%m-%d %H:%M:%S")
                if obj.last_modified
                else "N/A"
            )
            typer.echo(f"{size_str:<12} {date_str:<22} {obj.key}")

        typer.echo("-" * 65)
        typer.secho(f"Total: {len(objects)} object(s)", fg=typer.colors.GREEN)


@app.command()
async def rename(
    source: Annotated[str, typer.Argument(help="Current remote R2 object key")],
    destination: Annotated[str, typer.Argument(help="New remote R2 object key")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview copy and delete sequence without executing")
    ] = False,
) -> None:
    """Rename (copy + delete) an object in R2."""
    if dry_run:
        typer.secho(
            f"[DRY RUN] Would copy '{source}' -> '{destination}' and delete source key '{source}'",
            fg=typer.colors.YELLOW,
        )
        return

    async with get_adapter() as adapter:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"[cyan]Renaming '{source}'...", total=2)
            try:
                await adapter.copy(source_key=source, destination_key=destination)
                progress.advance(task)
                await adapter.delete(source)
                progress.advance(task)
                typer.secho(f"Successfully renamed {source} -> {destination}", fg=typer.colors.GREEN)
            except httpx.HTTPStatusError as err:
                typer.secho(f"\nRename failed: {_format_http_error(err)}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

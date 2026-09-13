# R2C

A lightweight, CLI tool for Cloudflare R2, built for speed and simplicity.

## Features

- Save and use your r2 credentials.
- Manage files on your bucket (bulk uploading, deleting, listing, renaming, fetching).

## Installation

Clone the repository and install dependencies using `uv`:

```bash
git clone https://github.com/NagiEight/r2c.git
cd r2c
uv sync

```
## Usage

Run the CLI using `uv run main.py` for now._I will setup packaging later in CICD when I'm free._

open help menu with this:
```bash
uv run main.py --help
```

## License
Use as your will as this is published under MIT LICENSE.


## detailed features

Upload: Upload single files or entire directories recursively.
Fetch: Download objects from R2 straight to a local file.
Delete: Remove objects by explicit key or keyword pattern.
List: View bucket contents via list-objects or ls.
Rename: Quick remote object renaming (copy + delete).
Account: Manage multi-account/profile configurations easily.

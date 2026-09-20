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

## Experimental warning
This project is an early-stage prototype provided strictly "as is." It is experimental code that may break, or behave unpredictably. Use it at your own risk and please do not use it on production storage or critical buckets

## Roadmap
I'm planning on adding race conditions, rate limits, caching, CI/CD, test suite. After that, I will remove the experimental warning.
Note: I'm in a middle of moving out, and I'll be busy for a while. Don't expect production readiness anytime soon.

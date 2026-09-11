# R2C

A lightweight, hexagonal clean-architecture CLI tool for Cloudflare R2, built for speed and simplicity.

## Features

* Secure credential management utilizing your OS native keyring alongside standard local config.
* Clean separation of concerns via Hexagonal Clean Architecture patterns.
* Fast dependency management and packaging powered by `uv`.

## Installation

Clone the repository and install dependencies using `uv`:

```bash
git clone https://github.com/NagiEight/r2c.git
cd r2c
uv sync

```

## Configuration

R2C stores your non-sensitive metadata (such as account names, account IDs, bucket names, and public access keys) in a plaintext JSON configuration file at `~/.config/r2c/config.json`.

Sensitive secrets (like your secret access keys) are safely isolated within your operating system's native secure keyring service under the service name `r2c`.

## Usage

Run the CLI using `uv run`:

```bash
uv run r2c --help

```

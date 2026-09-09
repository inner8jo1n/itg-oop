# itg-oop

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Checks

Run everything (linter + formatter check + tests) in one go:

```bash
make check
```

Each step prints a green `✔` on success, or a red `✘` with the failure output and stops there.

Individual commands:

```bash
make lint     # ruff check .
make format   # ruff format . (auto-fixes formatting)
make test     # pytest
```

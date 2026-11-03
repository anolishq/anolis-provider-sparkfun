# anolis-provider-sparkfun dev commands. `check` + `test` are what CI runs.

# List available recipes
default:
    @just --list

# Install the locked dev environment
setup:
    uv sync --locked --extra dev

# Format the code
fmt:
    uv run ruff format .

# Lint
lint:
    uv run ruff check .

# CI-equivalent static checks: format, lint, strict typecheck
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy

# Unit tests, and the conformance harness against the provider in mock mode
test:
    uv run pytest

# Build the frozen single-file binary into dist/ (PyInstaller; for the host architecture)
freeze:
    uv sync --locked --extra dev --extra freeze
    uv run pyinstaller --clean --noconfirm packaging/anolis-provider-sparkfun.spec

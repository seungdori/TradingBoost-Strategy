# Repository Guidelines

## Project Structure & Module Organization
The repo contains two independent strategy stacks plus shared infrastructure. `HYPERRSI/src` houses FastAPI routers, Celery tasks, and trading flows for the Hyper RSI engine. `GRID` mirrors that layout for the grid bot, with exchange handlers, services, and schedulers in sibling folders. Cross-strategy utilities (configuration, exchange clients, indicators, error handling) reside under `shared`. Root-level scripts such as `run_hyperrsi.sh`, `run_grid.sh`, and `install.sh` provide entry points and setup automation.

## Build & Runtime Commands
Create a Python 3.11+ virtualenv, then install dependencies with `pip install -e .[dev]` or run `./install.sh`. Launch the RSI strategy via `./run_hyperrsi.sh` and the grid engine via `./run_grid.sh --port 8012`. When developing new functionality, prefer running the service module directly (`python HYPERRSI/main.py`) so environment variables are loaded consistently.

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation and keep lines ≤120 characters (Ruff default). Module names stay snake_case; classes use PascalCase; asynchronous workers and Celery tasks use descriptive snake_case verbs. Leverage type hints for public interfaces, reuse the shared logging helpers, and keep configuration in Pydantic models under `shared/config`.

## Quality Assurance & Manual Verification
Automated tests are currently unavailable; prioritize deterministic manual checks. Exercise core trade flows against mocked exchanges, confirm FastAPI endpoints respond with expected schemas, and inspect logs for structured context IDs. Before opening a PR, restart both strategies locally to ensure no runtime regressions and capture command output for reviewers.

## Commit & Pull Request Guidelines
Adopt the existing Conventional Commit prefix style (`feat:`, `refactor:`, `fix:`) with an optional scope (e.g., `feat: hyperrsi position rebalance`). Summaries should explain motivation and impact in 72 characters or fewer, with thorough details in the body. Pull requests must describe strategy impacts, configuration changes, and manual verification evidence. Link issues or task IDs and attach API responses or screenshots when behavior changes.

## Agent Communication Policy
Codex와 다른 자동화 에이전트는 팀 대화 시 기본적으로 한국어로 응답해야 하며, 예외가 필요하면 PR 설명에 명시하세요. 사용자 메세지에 영어가 포함되어도 안내 요청이 없는 한 한국어 답변을 유지합니다.

## Environment & Security Notes
Secrets live in `.env`; copy from `.env.example` and keep credentials out of Git. Local development defaults to SQLite and Redis, while production expects PostgreSQL plus hardened Redis access. Scrub API keys, Telegram IDs, and exchange secrets from logs before sharing artifacts.

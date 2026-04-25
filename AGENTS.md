# FBV1 Agent Instructions

## Project Root

Treat this directory as the project root:

`C:\Users\Sophanaroth Lem\Documents\Word\Lesson\FBV1`

When editing this project, read and modify files inside `FBV1` only unless the user explicitly asks for another folder.

Do not use files from `GSMEDIACUT` as context for FBV1 work.

## Project Layout

- `Fbv1.py`: primary desktop launcher.
- `Fbv2.py`: compatibility launcher that forwards to `Fbv1.py`.
- `fbv1_app/`: Tk desktop application package.
- `backend/`: FastAPI backend package.
- `backend/api/`: REST routes and WebSocket events.
- `backend/core/`: settings, logging, executor, and event broker.
- `backend/modules/`: job handlers.
- `backend/data/`: SQLAlchemy models, repository helpers, and SQLite storage.
- `backend/workers/`: queue submission and threaded execution.
- `run_backend.py`: backend-only entry point.

## Run Commands

Desktop app:

```bash
python Fbv1.py
```

Backend only:

```bash
python run_backend.py
```

## Editing Rules

- Keep changes scoped to the requested task.
- Follow the existing Python style in the nearby files.
- Do not commit secrets from `.env`, cookies, sessions, account folders, backups, logs, or generated images.
- Do not modify generated/cache folders such as `__pycache__`.
- If a change touches backend behavior, check the related route, worker, and data model before editing.
- If a change touches the desktop UI, check `fbv1_app/` before changing launcher files.

## Continue/Ollama

Use the local Ollama models configured in Continue:

- Chat/edit/apply: `llama3.1:8b`
- Autocomplete: `qwen2.5-coder:1.5b-base`
- Embeddings: `nomic-embed-text:latest`

If asked to confirm that this file was read, answer `yes`.

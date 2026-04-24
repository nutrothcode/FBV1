from __future__ import annotations

import uvicorn

from backend.core.config import get_settings


def run_server(*, reload: bool | None = None) -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development" if reload is None else reload,
    )


def main() -> None:
    run_server()


if __name__ == "__main__":
    main()

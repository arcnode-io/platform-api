"""Uvicorn entry point. Loads config, sets up logging, mounts the app."""

import logging

import uvicorn

from src import config
from src.app_module import AppModule

app_module = AppModule()
app = app_module.create_app()
app_module.register_database(app)


def main() -> None:
    """Boot the platform-api uvicorn server."""
    cfg = config.load_config()
    config.setup_logger(cfg)
    logging.info("Running with: Config( %s )", cfg)
    uvicorn.run(
        "src.main:app",
        host=str(cfg.host),
        port=cfg.port,
        log_level=cfg.log_level.value.lower(),
        reload=cfg.reload,
    )


if __name__ == "__main__":
    main()

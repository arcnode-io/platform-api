"""Setup wizard HTTP controller — the wizard UI + its apply route.

Standalone app (see main.py), not mounted into platform-api's own router.
Plain FastAPI APIRouter, not classy_fastapi: the appliance runs this
natively from apt (python3-fastapi), and classy_fastapi has no Debian
package.
"""

from pathlib import Path
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse

from src.wizard.wizard_record import ApplyRequest, ApplyResult, SetupInfo
from src.wizard.wizard_service import (
    InvalidSshKeyError,
    SshStepNotAvailableError,
    WizardAlreadyAppliedError,
    WizardService,
)

_STATIC_DIR: Final[Path] = Path(__file__).parent / "static"


class WizardController:
    """GET / (+ its static assets), GET /api/config, POST /api/ssh
    (on-prem only). The wizard has its own port (8080), so it lives at the
    root — no path prefix."""

    def __init__(self, *, service: WizardService) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/",
            self.index,
            methods=["GET"],
            summary="Serve the wizard UI, or 404 once applied",
        )
        self.router.add_api_route(
            "/{filename}",
            self.static_asset,
            methods=["GET"],
            summary="Serve a static JSX/JS asset the UI references",
        )
        self.router.add_api_route(
            "/api/config",
            self.config,
            methods=["GET"],
            response_model=SetupInfo,
            summary="Cloud or on-prem, and whose login SSH is for",
        )
        self.router.add_api_route(
            "/api/ssh",
            self.ssh,
            methods=["POST"],
            response_model=ApplyResult,
            summary="On-prem SSH step: authorize your public key, verify SSH works",
        )

    async def index(self) -> HTMLResponse:
        """Entry point the person's browser loads."""
        self._refuse_if_applied()
        return HTMLResponse((_STATIC_DIR / "index.html").read_text())

    async def static_asset(self, filename: str) -> FileResponse:
        """tokens.jsx / setup-wizard.jsx — whatever index.html's script tags need.

        FastAPI path params can't contain "/", so this only ever matches
        single-segment filenames — safe against path traversal.
        """
        self._refuse_if_applied()
        path = _STATIC_DIR / filename
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return FileResponse(path)

    async def config(self) -> SetupInfo:
        """What the UI needs to render the SSH step before apply."""
        self._refuse_if_applied()
        return self._service.setup_info()

    async def ssh(self, request: ApplyRequest) -> ApplyResult:
        """The one irreversible action — see WizardService.apply."""
        try:
            return self._service.apply(request)
        except (WizardAlreadyAppliedError, SshStepNotAvailableError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidSshKeyError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def _refuse_if_applied(self) -> None:
        if self._service.is_applied():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="setup already applied"
            )

"""POST /api/https/request, /api/https and /api/https/skip — the optional HTTPS
certificate page, on its own router beside the wizard's."""

from fastapi import APIRouter, HTTPException, status

from src.wizard.https_service import HttpsService
from src.wizard.wizard_record import (
    HttpsCertificate,
    SigningRequest,
    SigningRequestResult,
    StepResult,
)
from src.wizard.wizard_steps import StepAlreadyDoneError


class HttpsController:
    """Signing request, certificate install, skip."""

    def __init__(self, *, https: HttpsService) -> None:
        self._https = https
        self.router = APIRouter()
        routes = [
            ("/api/https/request", self.request_signing),
            ("/api/https", self.install),
            ("/api/https/skip", self.skip),
        ]
        for path, handler in routes:
            self.router.add_api_route(path, handler, methods=["POST"])

    def request_signing(self, request: SigningRequest) -> SigningRequestResult:
        """Make the box's key and a signing request for its name — see HttpsService."""
        return self._https.request_signing(request)

    def install(self, request: HttpsCertificate) -> StepResult:
        """Install the signed certificate and verify — see HttpsService.apply."""
        try:
            return self._https.apply(request)
        except StepAlreadyDoneError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    def skip(self) -> StepResult:
        """Keep plain http://<ip>/ for now."""
        return self._https.skip()

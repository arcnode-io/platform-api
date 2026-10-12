"""Bundle module — DI assembly for the download redirect."""

from src.aws.s3_service import S3Service
from src.bundle.bundle_controller import BundleController


class BundleModule:
    """Single point of DI for the bundle download route."""

    def __init__(self, *, s3: S3Service) -> None:
        self.router = BundleController(s3=s3).router

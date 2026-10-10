"""ISO module — DI assembly for `IsoService`."""

from src.aws.aws_module import AwsModule
from src.iso.iso_service import IsoService


class IsoModule:
    """Single point of DI for the per-order ISO bake."""

    def __init__(self, *, aws: AwsModule, base_iso_url: str) -> None:
        self.service = IsoService(base_iso_url=base_iso_url, s3=aws.s3)

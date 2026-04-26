"""CFN module — DI assembly for `CfnService`."""

from src.cfn.cfn_service import CfnService


class CfnModule:
    """Single point of DI for CFN deep-link construction."""

    def __init__(
        self,
        *,
        template_url_standard: str,
        template_url_govcloud: str,
        region: str,
    ) -> None:
        self.service = CfnService(
            template_url_standard=template_url_standard,
            template_url_govcloud=template_url_govcloud,
            region=region,
        )

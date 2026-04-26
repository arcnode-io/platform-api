"""Orchestrator module — DI assembly.

Imports `EdpClientModule`, `AwsModule`, `CfnModule`, and `PortalModule` and wires
their services into `OrchestratorService`. `OrdersModule` consumes `module.service`.
"""

from src.aws.aws_module import AwsModule
from src.cfn.cfn_module import CfnModule
from src.edp_client.edp_client_module import EdpClientModule
from src.orchestrator.orchestrator_service import OrchestratorService
from src.portal.portal_module import PortalModule


class OrchestratorModule:
    """Single point of DI for the order orchestrator."""

    def __init__(
        self,
        *,
        edp: EdpClientModule,
        aws: AwsModule,
        cfn: CfnModule,
        portal: PortalModule,
    ) -> None:
        self.service = OrchestratorService(
            edp_client=edp.service,
            s3=aws.s3,
            ses=aws.ses,
            cfn=cfn.service,
            portal=portal.service,
        )

"""Orchestrator module — DI assembly.

Imports `EdpClientModule` + `AwsModule` and wires their services into
`OrchestratorService`. `OrdersModule` imports this and consumes
`module.service`.
"""

from src.aws.aws_module import AwsModule
from src.edp_client.edp_client_module import EdpClientModule
from src.orchestrator.orchestrator_service import OrchestratorService


class OrchestratorModule:
    """Single point of DI for the order orchestrator."""

    def __init__(
        self,
        *,
        edp: EdpClientModule,
        aws: AwsModule,
        ems_hmi_apk_url: str,
    ) -> None:
        self.service = OrchestratorService(
            edp_client=edp.service,
            s3=aws.s3,
            ses=aws.ses,
            ems_hmi_apk_url=ems_hmi_apk_url,
        )

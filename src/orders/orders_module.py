"""Orders module — DI assembly. Imports OrchestratorModule for the work."""

from src.orchestrator.orchestrator_module import OrchestratorModule
from src.orders.orders_controller import OrdersController
from src.orders.orders_service import OrdersService


class OrdersModule:
    """Single point of DI for the orders feature."""

    def __init__(self, *, orchestrator: OrchestratorModule) -> None:
        self.service = OrdersService(orchestrator=orchestrator.service)
        self.router = OrdersController(service=self.service).router

"""Orders module — DI assembly. Imports OrchestratorModule for the work."""

from src.orchestrator.orchestrator_module import OrchestratorModule
from src.orders.order_rate_limit import OrderRateLimiter
from src.orders.orders_controller import OrdersController
from src.orders.orders_service import OrdersService


class OrdersModule:
    """Single point of DI for the orders feature."""

    def __init__(
        self,
        *,
        orchestrator: OrchestratorModule,
        rate_limit_count: int,
        rate_limit_window_s: int,
    ) -> None:
        self.service = OrdersService(orchestrator=orchestrator.service)
        self.limiter = OrderRateLimiter(
            count=rate_limit_count, window_s=rate_limit_window_s
        )
        self.router = OrdersController(
            service=self.service, limiter=self.limiter
        ).router

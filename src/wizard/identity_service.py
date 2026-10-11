"""The identity page: the first page after the hardware check. Read-only facts from
the order the configurator baked into this ISO (customer, site, market, order id),
and a Confirm that marks the page done. The customer stops here if it's the wrong ISO.
"""

from pathlib import Path

import yaml

from src.wizard.order_record import SITE_FILE, OrderSite
from src.wizard.wizard_record import Deployment, IdentityInfo, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker


class IdentityStepNotAvailableError(Exception):
    """No identity page in the cloud — the stack's own parameters name the site there."""


class IdentityService:
    """Reads the order's identity and records the customer's confirmation."""

    def __init__(
        self, *, deployment: Deployment, tracker: StepTracker, order_dir: Path
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._order_dir = order_dir

    def info(self) -> IdentityInfo:
        """What this ISO was built for, from /etc/arcnode/order/site.yml."""
        if self._deployment == Deployment.CLOUD:
            raise IdentityStepNotAvailableError("no identity page in the cloud")
        site = OrderSite.model_validate(
            yaml.safe_load((self._order_dir / SITE_FILE).read_text())
        )
        market = " · ".join(filter(None, (site.market_region, site.settlement_point)))
        return IdentityInfo(
            customer=site.customer,
            site=site.site_name or site.site_id,
            market=market or None,
            order_id=site.order_id,
        )

    def confirm(self) -> StepResult:
        """The customer says this is their site; mark the page done."""
        if self._deployment == Deployment.CLOUD:
            raise IdentityStepNotAvailableError("no identity page in the cloud")
        if self._tracker.is_done("identity"):
            raise StepAlreadyDoneError("the identity is already confirmed")
        info = self.info()
        self._tracker.mark_done("identity")
        return StepResult(
            verified=True,
            checks=[
                VerifyCheck(
                    name="Site identity confirmed",
                    ok=True,
                    detail=info.site,
                    hint="",
                )
            ],
        )

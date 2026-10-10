"""The on-prem Site page: the per-order ISO carried the order's site and
device topology to /etc/arcnode/order; this page hands them to the EMS
containers as the same files the cloud's UserData writes."""

import shutil
from collections import Counter
from pathlib import Path

import yaml

from src.wizard.ems_cfg import (
    GATEWAY_CFG_FILE,
    HMI_CFG_FILE,
    AnalystCfg,
    AnalystMarket,
    GatewayCfg,
    HmiCfg,
    read_analyst_cfg,
    update_analyst_cfg,
    write_yaml,
)
from src.wizard.order_record import DTM_FILE, SITE_FILE, OrderDtm, OrderSite
from src.wizard.wizard_record import Deployment, StepResult, VerifyCheck
from src.wizard.wizard_steps import StepAlreadyDoneError, StepTracker


class SiteStepNotAvailableError(Exception):
    """No Site page in the cloud — UserData writes these files from the order."""


class SiteService:
    """Order → dtm.json + gateway/HMI/analyst cfg files in /opt/arcnode."""

    def __init__(
        self,
        *,
        deployment: Deployment,
        tracker: StepTracker,
        order_dir: Path,
        ems_dir: Path,
        analyst_cfg_path: Path,
    ) -> None:
        self._deployment = deployment
        self._tracker = tracker
        self._order_dir = order_dir
        self._ems_dir = ems_dir
        self._analyst_cfg_path = analyst_cfg_path

    def apply(self) -> StepResult:
        """Save the order's site for every container, then verify. Rewrites
        the same files on a retry, so it's safe to repeat."""
        if self._deployment == Deployment.CLOUD:
            raise SiteStepNotAvailableError("no Site step in the cloud")
        if self._tracker.is_done("site"):
            raise StepAlreadyDoneError("the site is already set up")
        site_path = self._order_dir / SITE_FILE
        dtm_path = self._order_dir / DTM_FILE
        if not (site_path.exists() and dtm_path.exists()):
            return StepResult(verified=False, checks=[self._no_order()])
        site = OrderSite.model_validate(yaml.safe_load(site_path.read_text()))
        self._save(site, dtm_path)
        checks = [
            self._order_check(site),
            self._topology_check(dtm_path),
            self._saved_check(site, dtm_path),
        ]
        verified = all(check.ok for check in checks)
        if verified:
            self._tracker.mark_done("site")
        return StepResult(verified=verified, checks=checks)

    def _save(self, site: OrderSite, dtm_path: Path) -> None:
        self._ems_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dtm_path, self._ems_dir / DTM_FILE)
        write_yaml(self._ems_dir / GATEWAY_CFG_FILE, GatewayCfg(site_id=site.site_id))
        write_yaml(self._ems_dir / HMI_CFG_FILE, _hmi_cfg(site))
        # Reason: the Ollama page already wrote this file's settings: block.
        update_analyst_cfg(self._analyst_cfg_path, _analyst_cfg(site))

    def _no_order(self) -> VerifyCheck:
        return VerifyCheck(
            name="Order on this box",
            ok=False,
            detail="This ISO has no order — download your site's ISO from "
            "the delivery portal",
            hint=f"ls {self._order_dir}",
        )

    def _order_check(self, site: OrderSite) -> VerifyCheck:
        market = (
            f"{site.market_region} · {site.settlement_point}"
            if site.market_region is not None and site.settlement_point is not None
            else "no wholesale market"
        )
        return VerifyCheck(
            name="Order on this box",
            ok=True,
            detail=f"site {site.site_id} · {market}",
            hint=f"cat {self._order_dir / SITE_FILE}",
        )

    def _topology_check(self, dtm_path: Path) -> VerifyCheck:
        dtm = OrderDtm.model_validate_json(dtm_path.read_text())
        modules = Counter(d.template for d in dtm.devices.values() if d.parent is None)
        summary = ", ".join(f"{n} {template}" for template, n in modules.items())
        return VerifyCheck(
            name="Device topology",
            ok=bool(dtm.devices),
            detail=(
                f"{len(dtm.devices)} devices — {summary}"
                if dtm.devices
                else "the order has no devices"
            ),
            hint=f"cat {dtm_path}",
        )

    def _saved_check(self, site: OrderSite, dtm_path: Path) -> VerifyCheck:
        """Read every file back — what the containers will actually mount."""
        ems = self._ems_dir
        saved = {
            DTM_FILE: (ems / DTM_FILE).read_bytes() == dtm_path.read_bytes(),
            GATEWAY_CFG_FILE: _read(ems / GATEWAY_CFG_FILE)
            == GatewayCfg(site_id=site.site_id).model_dump(),
            HMI_CFG_FILE: _read(ems / HMI_CFG_FILE)
            == _hmi_cfg(site).model_dump(by_alias=True),
            self._analyst_cfg_path.name: read_analyst_cfg(
                self._analyst_cfg_path
            ).model_copy(update={"settings": None})
            == _analyst_cfg(site),
        }
        wrong = [name for name, ok in saved.items() if not ok]
        return VerifyCheck(
            name="Saved for the EMS containers",
            ok=not wrong,
            detail=(
                f"{ems}: {', '.join(saved)}"
                if not wrong
                else f"missing or different: {', '.join(wrong)}"
            ),
            hint=f"sudo ls -l {ems}",
        )


def _hmi_cfg(site: OrderSite) -> HmiCfg:
    return HmiCfg(site_id=site.site_id, deployment_name=site.site_id)


def _analyst_cfg(site: OrderSite) -> AnalystCfg:
    """Market only with a settlement point — same rule as the cloud's: without
    one the analyst has no pricing node to query."""
    market = (
        AnalystMarket(
            wholesale_market=site.market_region,
            settlement_point=site.settlement_point,
        )
        if site.market_region is not None and site.settlement_point is not None
        else None
    )
    return AnalystCfg(site_id=site.site_id, market=market)


def _read(path: Path) -> object:
    return yaml.safe_load(path.read_text()) if path.exists() else None

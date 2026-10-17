"""Wizard module — DI assembly for the standalone setup-wizard app."""

from pathlib import Path
from typing import Final

from src.wizard.device_api_service import DeviceApiService
from src.wizard.docker_service import DockerService
from src.wizard.grafana_service import GrafanaService
from src.wizard.ssh_lockdown_service import SshLockdownService
from src.wizard.hmi_service import HmiService
from src.wizard.industrial_gateway_service import IndustrialGatewayService
from src.wizard.hivemq_service import HivemqService
from src.wizard.neo4j_service import Neo4jService
from src.wizard.ollama_service import OllamaService
from src.wizard.postgres_service import PostgresService
from src.wizard.analyst_model_service import AnalystModelService
from src.wizard.der_control_service import DerControlService
from src.wizard.analyst_server_service import AnalystServerService
from src.wizard.mlflow_service import MlflowService
from src.wizard.preflight_service import PreflightService
from src.wizard.prometheus_service import PrometheusService
from src.wizard.site_service import SiteService
from src.wizard.telemetry_writer_service import TelemetryWriterService
from src.wizard.ssh_service import SshService
from src.wizard.system_runner import LineStream, Runner
from src.wizard.wizard_controller import WizardController
from src.wizard.wizard_record import SshAccount, WizardConfig
from src.wizard.wizard_steps import StepTracker

# Debian's sshd includes this directory; the lockdown page drops its file there.
SSHD_CONFIG_DIR: Final[Path] = Path("/etc/ssh/sshd_config.d")


class WizardModule:
    """Single point of DI for the wizard feature.

    ``base_dir`` is ``/etc/arcnode`` in production (injectable for tests);
    ``secrets_env_path`` is the env file the EMS containers load (the same
    ``/opt/arcnode/secrets.env`` as the cloud);
    ``analyst_cfg_path`` is ems-analyst's cfg.customer.yml (same path as the
    cloud's); ``ems_dir`` is where every other file the containers mount
    goes (``/opt/arcnode``, as in the cloud); ``account`` is whose authorized_keys the SSH key goes into;
    ``config`` is wizard-cfg.yml (hardware minimums + Ollama models); ``run`` runs the install and
    verification commands and ``stream`` the long downloads (fakes in tests).
    """

    def __init__(
        self,
        *,
        base_dir: Path,
        secrets_env_path: Path,
        analyst_cfg_path: Path,
        ems_dir: Path,
        account: SshAccount,
        config: WizardConfig,
        run: Runner,
        stream: LineStream,
        sshd_config_dir: Path = SSHD_CONFIG_DIR,
    ) -> None:
        tracker = StepTracker(steps_dir=base_dir / "steps")
        self.preflight = PreflightService(
            tracker=tracker,
            minimums=config.hardware,
            run=run,
        )
        self.ssh = SshService(account=account, tracker=tracker, run=run)
        self.docker = DockerService(tracker=tracker, account=account, run=run)
        self.postgres = PostgresService(
            tracker=tracker,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.neo4j = Neo4jService(
            tracker=tracker,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.ollama = OllamaService(
            config=config,
            tracker=tracker,
            analyst_cfg_path=analyst_cfg_path,
            run=run,
            stream=stream,
        )
        # The per-order ISO's /order, copied there at install.
        self.site = SiteService(
            tracker=tracker,
            order_dir=base_dir / "order",
            ems_dir=ems_dir,
            analyst_cfg_path=analyst_cfg_path,
        )
        self.hivemq = HivemqService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.telemetry = TelemetryWriterService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.prometheus = PrometheusService(tracker=tracker, ems_dir=ems_dir, run=run)
        self.mlflow = MlflowService(tracker=tracker, ems_dir=ems_dir, run=run)
        self.analyst_model = AnalystModelService(
            tracker=tracker,
            order_dir=base_dir / "order",
            ems_dir=ems_dir,
            run=run,
        )
        self.device_api = DeviceApiService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.industrial_gateway = IndustrialGatewayService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.hmi = HmiService(tracker=tracker, ems_dir=ems_dir, run=run)
        self.grafana = GrafanaService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.analyst_server = AnalystServerService(
            tracker=tracker,
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.der_control = DerControlService(
            tracker=tracker,
            order_dir=base_dir / "order",
            ems_dir=ems_dir,
            secrets_env_path=secrets_env_path,
            run=run,
        )
        self.ssh_lockdown = SshLockdownService(
            tracker=tracker,
            account=account,
            sshd_config_dir=sshd_config_dir,
            run=run,
        )
        self.router = WizardController(
            preflight=self.preflight,
            ssh=self.ssh,
            docker=self.docker,
            postgres=self.postgres,
            neo4j=self.neo4j,
            ollama=self.ollama,
            site=self.site,
            hivemq=self.hivemq,
            telemetry=self.telemetry,
            prometheus=self.prometheus,
            mlflow=self.mlflow,
            analyst_model=self.analyst_model,
            analyst_server=self.analyst_server,
            der_control=self.der_control,
            device_api=self.device_api,
            industrial_gateway=self.industrial_gateway,
            hmi=self.hmi,
            grafana=self.grafana,
            ssh_lockdown=self.ssh_lockdown,
            tracker=tracker,
            account=account,
        ).router

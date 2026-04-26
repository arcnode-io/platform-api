"""CfnService — renders per-order CFN templates + builds the console deep link.

Each order gets its own `ems-stack.yaml` with deployment_uuid / dtm_url / ems_mode
baked in (no CFN `Parameters:` block needed — values are known at render time).
The orchestrator uploads it to S3 and passes the resulting URL into `build_link`.

The link itself opens the AWS Console "Create stack (review)" page in the
operator's *own* AWS account; ARCNODE never holds AWS credentials. ISO path
returns None.
"""

from typing import Final
from urllib.parse import urlencode

import yaml

from src.edp_client.edp_artifacts import EdpDeliveryPath

CONSOLE_HOST: Final[dict[EdpDeliveryPath, str]] = {
    EdpDeliveryPath.CFN_STANDARD: "https://console.aws.amazon.com",
    EdpDeliveryPath.CFN_GOVCLOUD: "https://console.amazonaws-us-gov.com",
}

STUB_NOTE: Final[str] = (
    "Stub template — real EMS provisioning lands in a future iteration."
)


class CfnService:
    """Per-order template renderer + console deep-link builder."""

    def __init__(self, *, region: str) -> None:
        self._region = region

    def render_template(
        self, *, deployment_uuid: str, dtm_url: str, ems_mode: str
    ) -> str:
        """Return a stub CFN template (yaml) with the order's params baked in."""
        short = deployment_uuid.split("-", 1)[0]
        template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": (
                f"ARCNODE EMS deployment marker (stub) — {deployment_uuid}"
            ),
            "Resources": {
                "DeploymentMarker": {
                    "Type": "AWS::SNS::Topic",
                    "Properties": {
                        "TopicName": f"arcnode-{short}",
                        "DisplayName": "ARCNODE EMS deployment marker",
                    },
                },
            },
            "Outputs": {
                "DeploymentUuid": {"Value": deployment_uuid},
                "DtmUrl": {"Value": dtm_url},
                "EmsMode": {"Value": ems_mode},
                "Note": {"Value": STUB_NOTE},
            },
        }
        return yaml.safe_dump(template, sort_keys=False)

    def build_link(
        self,
        *,
        path: EdpDeliveryPath,
        template_url: str,
        deployment_uuid: str,
    ) -> str | None:
        """Return the CFN deep link, or None for ISO path (handled elsewhere)."""
        if path == EdpDeliveryPath.ISO:
            return None
        host = CONSOLE_HOST[path]
        params = urlencode(
            {
                "templateURL": template_url,
                "stackName": f"arcnode-{deployment_uuid[:8]}",
            }
        )
        return (
            f"{host}/cloudformation/home"
            f"?region={self._region}#/stacks/create/review?{params}"
        )

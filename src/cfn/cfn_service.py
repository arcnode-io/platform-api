"""CfnService — builds CloudFormation create-stack deep links.

The operator clicks the link in their email, lands on AWS Console with the
template + parameters pre-filled, and confirms the stack launch from their own
AWS account. ARCNODE never touches their AWS — we only construct the URL.

Standard partition vs GovCloud is a different console host. ISO path returns
None; the orchestrator emits a stub URL for that case (pending v1 ISO build).
"""

from typing import Final
from urllib.parse import urlencode

from src.edp_client.edp_artifacts import EdpDeliveryPath

CONSOLE_HOST: Final[dict[EdpDeliveryPath, str]] = {
    EdpDeliveryPath.CFN_STANDARD: "https://console.aws.amazon.com",
    EdpDeliveryPath.CFN_GOVCLOUD: "https://console.amazonaws-us-gov.com",
}


class CfnService:
    """Pure URL builder. No I/O, no AWS calls — operators do the launch themselves."""

    def __init__(
        self,
        *,
        template_url_standard: str,
        template_url_govcloud: str,
        region: str,
    ) -> None:
        self._template_urls = {
            EdpDeliveryPath.CFN_STANDARD: template_url_standard,
            EdpDeliveryPath.CFN_GOVCLOUD: template_url_govcloud,
        }
        self._region = region

    def build_link(
        self,
        *,
        path: EdpDeliveryPath,
        deployment_uuid: str,
        dtm_url: str,
        ems_mode: str,
    ) -> str | None:
        """Return the CFN deep link, or None for ISO path (handled elsewhere)."""
        if path == EdpDeliveryPath.ISO:
            return None
        host = CONSOLE_HOST[path]
        template_url = self._template_urls[path]
        params = urlencode(
            {
                "templateURL": template_url,
                "stackName": f"arcnode-{deployment_uuid[:8]}",
                "param_DeploymentUuid": deployment_uuid,
                "param_DtmUrl": dtm_url,
                "param_EmsMode": ems_mode,
            }
        )
        return (
            f"{host}/cloudformation/home"
            f"?region={self._region}#/stacks/create/review?{params}"
        )

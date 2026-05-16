"""Bedrock preflight custom resource — runs at stack-create.

Calls Bedrock from inside the customer's account to verify they've
granted model access for the IDs the analyst needs. If access is
missing, the stack creation FAILS FAST with a Reason that names the
exact model + the AWS console link to grant it — far better than the
stack deploying green and the chat endpoint then 500'ing on first call
with an opaque AccessDeniedException.

We can't probe Bedrock from our account — customers don't and shouldn't
give us cross-account access. Running the check from a Lambda inside
their stack solves the trust gap: customer's own role, no shared creds.

Model IDs come from event.ResourceProperties — the CFN customer-resource
passes the canonical values from `platform-api/src/cfn/bedrock_models.py`
so the Lambda stays generic and there's exactly ONE place to bump on
model deprecation.

Delete is a no-op — nothing to clean up (Bedrock model access is an
account-level setting, not a stack resource).
"""

# Reason: PEP 563 lazy annotations — keeps TYPE_CHECKING-only stub
# imports working without runtime quotes.
from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING

import boto3  # type: ignore[import-untyped]

if TYPE_CHECKING:
    # Type stubs only — Lambda runtime has boto3 but no stubs; the if
    # block stays out of the runtime path entirely.
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

# Tiny probe input — Bedrock charges per-token; "ok" is enough to
# exercise auth + permission resolution without burning tokens.
PROBE_TEXT = "ok"


def handler(event: dict, context: object) -> None:
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", "bedrock-preflight")
    try:
        if request_type == "Create":
            props = event["ResourceProperties"]
            _probe(
                chat_model_id=props["ChatModelId"],
                embed_model_id=props["EmbedModelId"],
            )
            _respond(event, "SUCCESS", physical_id, {})
        else:
            # Update + Delete: no-op. Re-running the probe on every stack
            # update would burn tokens without value.
            _respond(event, "SUCCESS", physical_id, {})
    except Exception as e:
        _respond(event, "FAILED", physical_id, {"Reason": str(e)})


def _probe(*, chat_model_id: str, embed_model_id: str) -> None:
    """Invoke both models once. AccessDeniedException -> raise with link."""
    client = boto3.client("bedrock-runtime")
    _probe_titan(client, embed_model_id)
    _probe_claude(client, chat_model_id)


def _probe_titan(client: BedrockRuntimeClient, model_id: str) -> None:
    try:
        client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": PROBE_TEXT}),
        )
    except client.exceptions.AccessDeniedException as e:
        raise RuntimeError(_access_denied_message(model_id)) from e


def _probe_claude(client: BedrockRuntimeClient, model_id: str) -> None:
    try:
        client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": PROBE_TEXT}],
                }
            ),
        )
    except client.exceptions.AccessDeniedException as e:
        raise RuntimeError(_access_denied_message(model_id)) from e


def _access_denied_message(model_id: str) -> str:
    return (
        f"Bedrock model access not granted for {model_id}. "
        "Open AWS console > Bedrock > Model access > Manage model access > "
        "request + accept terms for the model above, then re-run the stack. "
        "Account-level setting; only needed once per AWS account."
    )


def _respond(event: dict, status: str, physical_id: str, data: dict) -> None:
    body = json.dumps(
        {
            "Status": status,
            "Reason": data.get("Reason", "see CloudWatch logs"),
            "PhysicalResourceId": physical_id,
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": {k: v for k, v in data.items() if k != "Reason"},
        }
    ).encode()
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"content-type": "", "content-length": str(len(body))},
    )
    urllib.request.urlopen(req)

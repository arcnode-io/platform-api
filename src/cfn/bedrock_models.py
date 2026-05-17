"""Single source of truth for the Bedrock model IDs we provision against.

Per ADR-024:
  - Chat: Sonnet 4.6 (Anthropic) via CRIS — direct anthropic.* IDs need
    provisioned throughput, so the runtime ALWAYS calls the inference
    profile (us.* prefix). IAM must permit BOTH the inference-profile
    arn AND each underlying foundation-model arn the profile spans.
  - Embed: Titan Text Embeddings v2 (Amazon, native 1024d).

These IDs are referenced in 4 places that must stay in lockstep:
  1. EC2 instance role (cfn_resources.iam_resources)
  2. Bedrock preflight Lambda IAM (bedrock_preflight_resources)
  3. Bedrock preflight Lambda probe targets (passed in via
     ResourceProperties so the lambda source stays generic)
  4. CFN top-level Description (cfn_service.render_template)

When AWS deprecates a model, bump here ONLY.
"""

from typing import Final

# Foundation model IDs (no inference-profile prefix).
BEDROCK_CHAT_FOUNDATION_MODEL: Final[str] = "anthropic.claude-sonnet-4-6"
BEDROCK_EMBED_FOUNDATION_MODEL: Final[str] = "amazon.titan-embed-text-v2:0"

# CRIS inference profile ID. Runtime invoke targets THIS, not the
# foundation model directly.
BEDROCK_CHAT_INFERENCE_PROFILE: Final[str] = "us.anthropic.claude-sonnet-4-6"

# Regions the us.* CRIS profile spans. IAM must permit invoke on the
# foundation model in each.
BEDROCK_CHAT_CRIS_REGIONS: Final[tuple[str, ...]] = (
    "us-east-1",
    "us-east-2",
    "us-west-2",
)

# Region the embed model lives in (Titan has no CRIS — single region).
BEDROCK_EMBED_REGION: Final[str] = "us-east-1"


def chat_inference_profile_arn_sub() -> dict[str, str]:
    """CFN Fn::Sub for the CRIS inference-profile arn (account-scoped)."""
    return {
        "Fn::Sub": (
            f"arn:${{AWS::Partition}}:bedrock:{BEDROCK_EMBED_REGION}:${{AWS::AccountId}}"
            f":inference-profile/{BEDROCK_CHAT_INFERENCE_PROFILE}"
        ),
    }


def chat_foundation_model_arns() -> list[dict[str, str]]:
    """Foundation-model arns for each CRIS-spanned region. ${AWS::Partition} = aws | aws-us-gov."""
    return [
        {
            "Fn::Sub": (
                f"arn:${{AWS::Partition}}:bedrock:{region}::"
                f"foundation-model/{BEDROCK_CHAT_FOUNDATION_MODEL}"
            ),
        }
        for region in BEDROCK_CHAT_CRIS_REGIONS
    ]


def embed_foundation_model_arn() -> dict[str, str]:
    """Foundation-model arn for the embed model (single-region; no CRIS)."""
    return {
        "Fn::Sub": (
            f"arn:${{AWS::Partition}}:bedrock:{BEDROCK_EMBED_REGION}::"
            f"foundation-model/{BEDROCK_EMBED_FOUNDATION_MODEL}"
        ),
    }


def all_invoke_resources() -> list[object]:
    """Full Resource list for bedrock:InvokeModel — used by EC2 role + preflight Lambda role."""
    return [
        chat_inference_profile_arn_sub(),
        *chat_foundation_model_arns(),
        embed_foundation_model_arn(),
    ]


def description_prereq_clause() -> str:
    """Operator-facing prereq sentence for the CFN Description field.

    Stays under the 1024-char Description limit when concatenated with
    the deployment_uuid prefix.
    """
    return (
        f" | Requires Bedrock model access (us-east-1) for: "
        f"{BEDROCK_EMBED_FOUNDATION_MODEL}, {BEDROCK_CHAT_FOUNDATION_MODEL} (CRIS). "
        "Grant via console > Bedrock > Model access BEFORE deploy."
    )

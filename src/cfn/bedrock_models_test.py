"""Pure-function tests for bedrock_models — the single source of truth.

If these break it means someone bumped a model ID; review the matching
cfg.yml in mcp-server + analyst-agent at the same time.
"""

from src.cfn.bedrock_models import (
    BEDROCK_CHAT_CRIS_REGIONS,
    BEDROCK_CHAT_FOUNDATION_MODEL,
    BEDROCK_CHAT_INFERENCE_PROFILE,
    BEDROCK_EMBED_FOUNDATION_MODEL,
    all_invoke_resources,
    chat_foundation_model_arns,
    description_prereq_clause,
    embed_foundation_model_arn,
)


def test_chat_inference_profile_uses_cris_prefix() -> None:
    """us.* prefix is mandatory per ADR-024 — direct anthropic.* needs PT."""
    # Assert
    assert BEDROCK_CHAT_INFERENCE_PROFILE.startswith("us.")
    assert BEDROCK_CHAT_INFERENCE_PROFILE.endswith(BEDROCK_CHAT_FOUNDATION_MODEL)


def test_chat_arns_cover_all_cris_spanned_regions() -> None:
    """CRIS IAM requires a FM arn per spanned region."""
    # Arrange + Act
    arns = chat_foundation_model_arns()

    # Assert
    assert len(arns) == len(BEDROCK_CHAT_CRIS_REGIONS)
    for region in BEDROCK_CHAT_CRIS_REGIONS:
        assert any(f":{region}:" in arn for arn in arns), f"missing arn for {region}"


def test_all_invoke_resources_combines_chat_profile_chat_fms_embed_fm() -> None:
    """The full Resource list for any bedrock:InvokeModel policy."""
    # Arrange + Act
    resources = all_invoke_resources()

    # Assert: 1 CRIS profile (Fn::Sub) + N chat foundation arns + 1 embed arn
    assert len(resources) == 1 + len(BEDROCK_CHAT_CRIS_REGIONS) + 1
    assert resources[-1] == embed_foundation_model_arn()


def test_description_prereq_clause_under_cfn_description_limit() -> None:
    """CFN Description caps at 1024 chars — leave headroom for deployment_uuid prefix."""
    # Arrange + Act
    clause = description_prereq_clause()

    # Assert
    assert len(clause) < 512, f"clause too long: {len(clause)} chars"
    assert BEDROCK_EMBED_FOUNDATION_MODEL in clause
    assert BEDROCK_CHAT_FOUNDATION_MODEL in clause

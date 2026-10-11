"""Upload an e2e stack's template to S3 so CreateStack takes a TemplateURL.

CreateStack rejects an inline TemplateBody over 51,200 bytes; the defense
template is ~53 KB. Real orders already deliver the template by S3 URL, so this
is also the closer match to production.
"""

from typing import Final, Protocol

# Private bucket the CI role already writes to; CloudFormation reads the object
# with the caller's own credentials.
TEMPLATE_BUCKET: Final[str] = "arcnode-artifacts"
TEMPLATE_PREFIX: Final[str] = "e2e-templates"
REGION: Final[str] = "us-east-1"


class S3Writer(Protocol):
    """The two boto3 S3 calls this module makes (keyword-only, like boto3)."""

    def put_object(self, **kwargs: object) -> object: ...

    def delete_object(self, **kwargs: object) -> object: ...


def template_key(stack_name: str) -> str:
    """Where a stack's template lives in the bucket."""
    return f"{TEMPLATE_PREFIX}/{stack_name}.yaml"


def upload_template(s3: S3Writer, *, stack_name: str, template: str) -> str:
    """Put the rendered template in S3 and return its URL for CreateStack."""
    key = template_key(stack_name)
    s3.put_object(
        Bucket=TEMPLATE_BUCKET,
        Key=key,
        Body=template.encode(),
        ContentType="application/yaml",
    )
    return f"https://{TEMPLATE_BUCKET}.s3.{REGION}.amazonaws.com/{key}"


def delete_template(s3: S3Writer, *, stack_name: str) -> None:
    """Remove the uploaded template once CloudFormation has read it."""
    s3.delete_object(Bucket=TEMPLATE_BUCKET, Key=template_key(stack_name))

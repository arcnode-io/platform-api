"""The e2e stacks pass their template to CloudFormation by S3 URL, not inline:
CreateStack rejects an inline TemplateBody over 51,200 bytes and the defense
template renders at ~53 KB (found running e2e_defense, 2026-10-11)."""

from tests.e2e.template_url import TEMPLATE_BUCKET, upload_template


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []

    def put_object(self, **kwargs: object) -> None:
        self.puts.append(kwargs)

    def delete_object(self, **kwargs: object) -> None:
        self.deletes.append(kwargs)


def test_upload_puts_the_template_under_the_stack_name_and_returns_its_url() -> None:
    # Arrange
    s3 = FakeS3()
    template = "AWSTemplateFormatVersion: '2010-09-09'\n" + "x" * 60_000

    # Act
    actual = upload_template(s3, stack_name="smoke-defense-abc123", template=template)

    # Assert
    assert s3.puts == [
        {
            "Bucket": TEMPLATE_BUCKET,
            "Key": "e2e-templates/smoke-defense-abc123.yaml",
            "Body": template.encode(),
            "ContentType": "application/yaml",
        }
    ]
    assert actual == (
        f"https://{TEMPLATE_BUCKET}.s3.us-east-1.amazonaws.com"
        "/e2e-templates/smoke-defense-abc123.yaml"
    )

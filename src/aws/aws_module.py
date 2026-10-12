"""AWS module — DI assembly for `S3Service` + `SesService`.

Both services share the LocalStack endpoint in tests; in production each points
at the real AWS endpoint (`endpoint_url=None`).
"""

from src.aws.s3_service import S3Service
from src.aws.ses_service import SesService


class AwsModule:
    """Single point of DI for AWS clients."""

    def __init__(
        self,
        *,
        s3_endpoint_url: str | None,
        s3_bucket: str,
        ses_endpoint_url: str | None,
        ses_sender_email: str,
        presign_access_key_id: str | None = None,
        presign_secret_access_key: str | None = None,
    ) -> None:
        self.s3 = S3Service(
            endpoint_url=s3_endpoint_url,
            bucket=s3_bucket,
            presign_access_key_id=presign_access_key_id,
            presign_secret_access_key=presign_secret_access_key,
        )
        self.ses = SesService(
            endpoint_url=ses_endpoint_url, sender_email=ses_sender_email
        )

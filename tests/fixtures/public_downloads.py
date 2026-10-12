"""Seed the APK and gateway download files into LocalStack.

The bundle build downloads every manifest file, so the integration test can't point those
URLs at unreachable hosts. Tiny stand-in bytes are enough: the test checks the zip, not the payload.
"""

import boto3

APK_KEY: str = "public/ems-hmi.apk"
GATEWAY_KEY: str = "public/gateway/latest.tar.gz"


def seed_public_downloads(localstack_url: str, bucket: str) -> tuple[str, str]:
    """Upload the APK, gateway tarball and its .sha256; return (APK URL, tarball URL).

    Reason: the bucket must already exist (seed_base_iso creates it).
    """
    s3 = boto3.client(
        "s3",
        endpoint_url=localstack_url,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    s3.put_object(Bucket=bucket, Key=APK_KEY, Body=b"apk-bytes")
    s3.put_object(Bucket=bucket, Key=GATEWAY_KEY, Body=b"gateway-bytes")
    s3.put_object(Bucket=bucket, Key=f"{GATEWAY_KEY}.sha256", Body=b"deadbeef")
    return (
        f"{localstack_url}/{bucket}/{APK_KEY}",
        f"{localstack_url}/{bucket}/{GATEWAY_KEY}",
    )

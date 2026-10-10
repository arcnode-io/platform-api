"""Keep the newest base AMIs and delete the rest, with their snapshots, so
storage and cost stay flat across frequent builds."""

import argparse
from typing import Final, Protocol

import boto3

NAME_PREFIX: Final[str] = "arcnode-ems-base-"


class Ec2Client(Protocol):
    """The part of boto3's EC2 client this module uses."""

    def describe_images(self, **kwargs: object) -> dict[str, list[dict[str, object]]]:
        """Images matching the filters."""
        ...

    def deregister_image(self, ImageId: str) -> None:  # noqa: N803  # boto3's own name
        """Remove an image's registration."""
        ...

    def delete_snapshot(self, SnapshotId: str) -> None:  # noqa: N803  # boto3's own name
        """Delete a snapshot."""
        ...


def images_to_delete(images: list[dict[str, object]], keep: int) -> list[dict[str, object]]:
    """Every base AMI older than the newest `keep`. ISO-8601 CreationDate sorts as text."""
    newest_first = sorted(images, key=lambda image: str(image["CreationDate"]), reverse=True)
    return newest_first[keep:]


def prune(ec2: Ec2Client, keep: int) -> list[str]:
    """Deregister the old base AMIs and delete their snapshots. Returns the deleted image IDs."""
    response = ec2.describe_images(Owners=["self"], Filters=[{"Name": "name", "Values": [f"{NAME_PREFIX}*"]}])
    doomed = images_to_delete(response["Images"], keep)
    for image in doomed:
        ec2.deregister_image(ImageId=str(image["ImageId"]))
        for mapping in image.get("BlockDeviceMappings", []):
            ebs = mapping.get("Ebs")
            if isinstance(ebs, dict):
                ec2.delete_snapshot(SnapshotId=str(ebs["SnapshotId"]))
    return [str(image["ImageId"]) for image in doomed]


def main() -> None:
    """Parse the flags and prune base AMIs in the chosen region."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    deleted = prune(boto3.client("ec2", region_name=args.region), keep=args.keep)
    print(f"deleted {len(deleted)} base AMI(s): {', '.join(deleted) or 'none'}")


if __name__ == "__main__":
    main()

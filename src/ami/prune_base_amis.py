"""Keep the newest base AMIs and delete the rest, with their snapshots, so
storage and cost stay flat across frequent builds."""

import argparse
from typing import Final, Protocol, cast

import boto3

NAME_PREFIX: Final[str] = "arcnode-ems-base-"


class Ec2Client(Protocol):
    """The part of boto3's EC2 client this module uses; the calls take boto3's keyword arguments."""

    def describe_images(self, **kwargs: object) -> dict[str, list[dict[str, object]]]:
        """Images matching the filters."""
        ...

    def deregister_image(self, **kwargs: object) -> None:
        """Remove an image's registration (ImageId=...)."""
        ...

    def delete_snapshot(self, **kwargs: object) -> None:
        """Delete a snapshot (SnapshotId=...)."""
        ...


def images_to_delete(
    images: list[dict[str, object]], keep: int
) -> list[dict[str, object]]:
    """Every base AMI older than the newest `keep`. ISO-8601 CreationDate sorts as text."""
    newest_first = sorted(
        images, key=lambda image: str(image["CreationDate"]), reverse=True
    )
    return newest_first[keep:]


def prune(ec2: Ec2Client, keep: int) -> list[str]:
    """Deregister the old base AMIs and delete their snapshots. Returns the deleted image IDs."""
    response = ec2.describe_images(
        Owners=["self"], Filters=[{"Name": "name", "Values": [f"{NAME_PREFIX}*"]}]
    )
    doomed = images_to_delete(response["Images"], keep)
    for image in doomed:
        ec2.deregister_image(ImageId=str(image["ImageId"]))
        # Reason: describe_images returns EBS mappings for our AMIs; the cast gives the checker that shape.
        mappings = cast(
            list[dict[str, dict[str, object]]], image.get("BlockDeviceMappings", [])
        )
        for mapping in mappings:
            ec2.delete_snapshot(SnapshotId=str(mapping["Ebs"]["SnapshotId"]))
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

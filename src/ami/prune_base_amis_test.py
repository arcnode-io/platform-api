"""Unit tests for pruning old base AMIs — the newest ones survive, and each
deleted image's snapshots go with it."""

from src.ami.prune_base_amis import images_to_delete, prune


def image(image_id: str, created: str, snapshot: str) -> dict[str, object]:
    return {
        "ImageId": image_id,
        "CreationDate": created,
        "BlockDeviceMappings": [{"Ebs": {"SnapshotId": snapshot}}],
    }


class FakeEc2:
    def __init__(self, images: list[dict[str, object]]) -> None:
        self._images = images
        self.deregistered: list[str] = []
        self.deleted_snapshots: list[str] = []

    def describe_images(self, **kwargs: object) -> dict[str, list[dict[str, object]]]:  # noqa: ARG002  # filters are fixed in the module
        return {"Images": self._images}

    def deregister_image(self, ImageId: str) -> None:  # noqa: N803  # boto3's own name
        self.deregistered.append(ImageId)

    def delete_snapshot(self, SnapshotId: str) -> None:  # noqa: N803  # boto3's own name
        self.deleted_snapshots.append(SnapshotId)


def test_keeps_the_newest_three_and_deletes_the_rest_with_their_snapshots() -> None:
    # Arrange
    ec2 = FakeEc2(
        [
            image("ami-1", "2026-10-01T00:00:00Z", "snap-1"),
            image("ami-2", "2026-10-02T00:00:00Z", "snap-2"),
            image("ami-3", "2026-10-03T00:00:00Z", "snap-3"),
            image("ami-4", "2026-10-04T00:00:00Z", "snap-4"),
            image("ami-5", "2026-10-05T00:00:00Z", "snap-5"),
        ]
    )

    # Act
    deleted = prune(ec2, keep=3)

    # Assert
    assert deleted == ["ami-2", "ami-1"]
    assert ec2.deregistered == ["ami-2", "ami-1"]
    assert ec2.deleted_snapshots == ["snap-2", "snap-1"]


def test_nothing_is_deleted_when_there_are_only_three() -> None:
    # Arrange
    ec2 = FakeEc2([image("ami-1", "2026-10-01T00:00:00Z", "snap-1")])

    # Act
    deleted = prune(ec2, keep=3)

    # Assert
    assert deleted == []
    assert ec2.deregistered == []


def test_images_to_delete_sorts_by_creation_date_not_list_order() -> None:
    # Arrange
    images = [
        image("ami-new", "2026-10-09T00:00:00Z", "snap-new"),
        image("ami-old", "2026-10-01T00:00:00Z", "snap-old"),
    ]

    # Act
    doomed = images_to_delete(images, keep=1)

    # Assert
    assert [i["ImageId"] for i in doomed] == ["ami-old"]

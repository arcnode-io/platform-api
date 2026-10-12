"""One file inside the order's arcnode.zip."""

from typing import Final

from pydantic import BaseModel


class BundleFile(BaseModel):
    """A zip entry: `path` is the in-zip name, `url` is where the bytes live."""

    path: str  # "D1/dtm.json" — artifact code folder + file name
    url: str  # s3:// or https:// source of the bytes


# Reason: SigV4 caps a presigned link at 7 days, the most the signing key allows.
BUNDLE_LINK_EXPIRY_S: Final[int] = 604800

"""One file inside the order's arcnode.zip."""

from pydantic import BaseModel


class BundleFile(BaseModel):
    """A zip entry: `path` is the in-zip name, `url` is where the bytes live."""

    path: str  # "D1/dtm.json" — artifact code folder + file name
    url: str  # s3:// or https:// source of the bytes

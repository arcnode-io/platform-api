"""One file inside the order's arcnode.zip."""

from pydantic import BaseModel


class BundleFile(BaseModel):
    """A zip entry: `path` is the in-zip name, `url` is where the bytes live."""

    path: str  # "D1/dtm.json" — artifact code folder + file name
    url: str  # s3:// or https:// source of the bytes


ORDER_PREFIX_LENGTH: int = 6


def bundle_path_slug(site_slug: str, order_id: str) -> str:
    """URL segment for one order's bundle: `<site-slug>-<order6>`.

    Reason: the site name alone can collide across customers, so the order prefix keeps
    each zip's link unique. Same order prefix the site hostnames use.
    """
    return f"{site_slug}-{order_id.replace('-', '')[:ORDER_PREFIX_LENGTH]}"

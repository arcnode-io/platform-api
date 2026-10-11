"""What a cloud stack's UserData needs to get its site a DNS name and real certificate."""

from pydantic import BaseModel


class SiteCallback(BaseModel):
    """The address callback for one order: where to POST, the order's token, and the
    DNS name platform-api will point at the box once it reports its address."""

    url: str
    token: str
    hostname: str

"""TLS settings for the e2e checks: the box serves HTTPS with its own self-signed
certificate (until the site name gets a real one), so the checks accept it."""

import ssl

import urllib3


def insecure_pool() -> urllib3.PoolManager:
    """A urllib3 pool that talks HTTPS to a box with a self-signed certificate."""
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return urllib3.PoolManager(cert_reqs=ssl.CERT_NONE)

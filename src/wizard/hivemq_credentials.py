"""Fills the broker's credentials.xml template for an on-prem box. The cloud
fills the same template with sed; passwords there never contain XML
special characters, here the customer chooses them, so they're escaped."""

from xml.sax.saxutils import escape


def render_credentials(template: str, passwords: dict[str, str]) -> str:
    """The template with each __NAME__ replaced by its XML-escaped password."""
    rendered = template
    for name, password in passwords.items():
        rendered = rendered.replace(f"__{name}__", escape(password))
    return rendered

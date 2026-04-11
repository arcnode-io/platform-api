from tortoise import fields
from tortoise.models import Model


class Example(Model):
    """
    Example entity representing data stored in the example table.
    Contains a name field for storing string values.
    """

    id = fields.BigIntField(primary_key=True)
    name = fields.CharField(max_length=100)

    class Meta:
        table = "example"

    def __repr__(self) -> str:
        return f"Example(id={self.id!r}, name={self.name!r})"

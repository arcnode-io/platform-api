from .example_controller import ExampleController
from .example_service import ExampleService


class ExampleModule:
    """Example module."""

    def __init__(self) -> None:
        # Create controller without session factory
        example_service = ExampleService()
        controller = ExampleController(example_service)
        self.router = controller.router

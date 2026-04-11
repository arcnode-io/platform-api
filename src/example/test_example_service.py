import pytest
from unittest.mock import AsyncMock, Mock, patch

from .example_service import ExampleService
from .entities.example_entity import Example
from .dto.create_example_dto import CreateExampleDto
from .dto.update_example_dto import UpdateExampleDto


class TestExampleService:
    """Unit tests for ExampleService."""

    @pytest.fixture
    def service(self) -> ExampleService:
        """Create ExampleService instance."""
        return ExampleService()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.create", new_callable=AsyncMock)
    async def test_create_should_create_and_save_example_entity(
        self, mock_create: AsyncMock, service: ExampleService
    ) -> None:
        """Test creating and saving an example entity."""
        # Arrange
        create_example_dto = CreateExampleDto(name="bar")
        expected_example = Example(id=1, name="bar")
        mock_create.return_value = expected_example

        # Act
        result = await service.create_example(create_example_dto)

        # Assert
        assert result.id == 1
        assert result.name == "bar"
        mock_create.assert_called_once_with(name="bar")

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.all", new_callable=AsyncMock)
    async def test_find_all_should_return_all_example_entities(
        self, mock_all: AsyncMock, service: ExampleService
    ) -> None:
        """Test returning all example entities."""
        # Arrange
        expected_examples = [
            Example(id=1, name="example1"),
            Example(id=2, name="example2"),
        ]
        mock_all.return_value = expected_examples

        # Act
        result = await service.find_all()

        # Assert
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].name == "example1"
        assert result[1].name == "example2"
        mock_all.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.filter")
    async def test_find_one_should_find_example_by_id(
        self, mock_filter: Mock, service: ExampleService
    ) -> None:
        """Test finding one example by id."""
        # Arrange
        expected_example = Example(id=1, name="example1")
        mock_queryset = Mock()
        mock_queryset.first = AsyncMock(return_value=expected_example)
        mock_filter.return_value = mock_queryset

        # Act
        result = await service.find_one(1)

        # Assert
        assert result is not None
        assert result.id == 1
        assert result.name == "example1"
        mock_filter.assert_called_once_with(id=1)
        mock_queryset.first.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.filter")
    async def test_find_one_should_return_none_when_example_not_found(
        self, mock_filter: Mock, service: ExampleService
    ) -> None:
        """Test returning None when example not found."""
        # Arrange
        mock_queryset = Mock()
        mock_queryset.first = AsyncMock(return_value=None)
        mock_filter.return_value = mock_queryset

        # Act
        result = await service.find_one(999)

        # Assert
        assert result is None
        mock_filter.assert_called_once_with(id=999)
        mock_queryset.first.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.filter")
    async def test_update_should_update_example_and_return_updated_entity(
        self, mock_filter: Mock, service: ExampleService
    ) -> None:
        """Test updating example and returning updated entity."""
        # Arrange
        update_example_dto = UpdateExampleDto(name="updated example")
        mock_example = Mock()
        mock_example.update_from_dict = AsyncMock()
        mock_example.save = AsyncMock()
        mock_example.id = 1
        mock_example.name = "updated example"

        mock_queryset = Mock()
        mock_queryset.first = AsyncMock(return_value=mock_example)
        mock_filter.return_value = mock_queryset

        # Act
        result = await service.update_example(1, update_example_dto)

        # Assert
        assert result is not None
        assert result.id == 1
        mock_filter.assert_called_once_with(id=1)
        mock_queryset.first.assert_called_once()
        mock_example.update_from_dict.assert_called_once_with(
            {"name": "updated example"}
        )
        mock_example.save.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.filter")
    async def test_remove_should_remove_example_and_return_true_when_successful(
        self, mock_filter: Mock, service: ExampleService
    ) -> None:
        """Test removing example and returning True when successful."""
        # Arrange
        mock_queryset = Mock()
        mock_queryset.delete = AsyncMock(return_value=1)  # 1 row deleted
        mock_filter.return_value = mock_queryset

        # Act
        result = await service.remove(1)

        # Assert
        assert result is True
        mock_filter.assert_called_once_with(id=1)
        mock_queryset.delete.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.example.entities.example_entity.Example.filter")
    async def test_remove_should_return_false_when_example_not_found(
        self, mock_filter: Mock, service: ExampleService
    ) -> None:
        """Test returning False when example to remove not found."""
        # Arrange
        mock_queryset = Mock()
        mock_queryset.delete = AsyncMock(return_value=0)  # 0 rows deleted
        mock_filter.return_value = mock_queryset

        # Act
        result = await service.remove(999)

        # Assert
        assert result is False
        mock_filter.assert_called_once_with(id=999)
        mock_queryset.delete.assert_called_once()

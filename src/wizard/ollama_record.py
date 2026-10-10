"""Pydantic DTOs for the Ollama page: what Ollama's API answers, and the
NDJSON events the page streams to the browser while models download."""

from pydantic import BaseModel

from src.wizard.wizard_record import StepResult


class PullLine(BaseModel):
    """One NDJSON line of POST /api/pull. Errors arrive as a line too
    (HTTP 200), so every line is checked."""

    status: str = ""
    completed: int | None = None
    total: int | None = None
    error: str | None = None


class PullProgress(BaseModel):
    """A download progress event for the browser; byte counts are for the
    layer being pulled (the weights layer is nearly all of a model)."""

    model: str
    status: str
    completed: int | None = None
    total: int | None = None


class OllamaPageEvent(BaseModel):
    """One NDJSON line of POST /api/ollama: progress while pulling, then
    exactly one result as the last line."""

    progress: PullProgress | None = None
    result: StepResult | None = None


class OllamaTag(BaseModel):
    """A downloaded model, from GET /api/tags."""

    name: str


class OllamaTags(BaseModel):
    """GET /api/tags."""

    models: list[OllamaTag]


class LoadedModel(BaseModel):
    """A model in memory, from GET /api/ps — size_vram == size means fully
    on the GPU."""

    name: str
    size: int
    size_vram: int
    context_length: int


class LoadedModels(BaseModel):
    """GET /api/ps."""

    models: list[LoadedModel]


class Embeddings(BaseModel):
    """POST /api/embed."""

    embeddings: list[list[float]]


class Generated(BaseModel):
    """POST /api/generate, stream false — eval_count is tokens produced."""

    eval_count: int = 0

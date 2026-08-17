"""Content parts carried inside protocol message items.

Input and output parts are separate families, exactly as in OpenResponses:
a request supplies ``input_*`` parts and a model returns ``output_text`` or a
``refusal``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, model_validator

from bothesis.agent.protocol import ProtocolModel


class InputText(ProtocolModel):
    """Plain text supplied to the model."""

    type: Literal["input_text"] = "input_text"
    text: str


class InputImage(ProtocolModel):
    """An image supplied by URL, data URL, or provider file reference."""

    type: Literal["input_image"] = "input_image"
    image_url: str | None = None
    file_id: str | None = None
    detail: Literal["auto", "low", "high"] = "auto"

    @model_validator(mode="after")
    def _require_a_source(self) -> InputImage:
        if not self.image_url and not self.file_id:
            raise ValueError("input_image requires image_url or file_id")
        return self


class InputFile(ProtocolModel):
    """A document supplied by provider file reference, URL, or inline data."""

    type: Literal["input_file"] = "input_file"
    file_id: str | None = None
    file_url: str | None = None
    filename: str | None = None
    file_data: str | None = None

    @model_validator(mode="after")
    def _require_a_source(self) -> InputFile:
        if not self.file_id and not self.file_url and not self.file_data:
            raise ValueError("input_file requires file_id, file_url, or file_data")
        return self


class OutputText(ProtocolModel):
    """Text produced by the model.

    ``annotations`` stays an opaque payload because its members are provider
    and tool specific (citations, file paths, container references). Keeping it
    untyped avoids pulling provider vocabulary into the common contract.
    """

    type: Literal["output_text"] = "output_text"
    text: str
    annotations: tuple[dict[str, Any], ...] = ()


class Refusal(ProtocolModel):
    """A model refusal returned in place of output text."""

    type: Literal["refusal"] = "refusal"
    refusal: str


InputContent: TypeAlias = Annotated[
    InputText | InputImage | InputFile,
    Field(discriminator="type"),
]

OutputContent: TypeAlias = Annotated[
    OutputText | Refusal,
    Field(discriminator="type"),
]

ContentPart: TypeAlias = Annotated[
    InputText | InputImage | InputFile | OutputText | Refusal,
    Field(discriminator="type"),
]

__all__ = [
    "ContentPart",
    "InputContent",
    "InputFile",
    "InputImage",
    "InputText",
    "OutputContent",
    "OutputText",
    "Refusal",
]

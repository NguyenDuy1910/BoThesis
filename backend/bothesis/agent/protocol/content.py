"""Content parts, exactly as OpenResponses defines them.

Three families share one ``type``-discriminated union:

* input parts (``input_text``, ``input_image``, ``input_file``) are supplied by
  a client inside a ``message`` item;
* message output parts (``output_text``, ``refusal``) are produced by a model
  inside a ``message`` item;
* reasoning parts (``reasoning_text``, ``summary_text``) live inside a
  ``reasoning`` item.

``input_video`` is specified but never authored by BoThesis, so it is not
modelled. Nothing here knows about a provider.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, model_validator

from bothesis.agent.protocol import ProtocolModel

Annotation: TypeAlias = dict[str, Any]
"""One annotation attached to an ``output_text`` part.

Kept opaque because members are provider and tool specific: OpenAI emits
``url_citation``, ``file_citation``, ``file_path`` and container references,
OpenRouter emits file-cache descriptors, and BoThesis adds
:data:`DOCUMENT_CITATION_TYPE`. Typing the union would pull every provider's
vocabulary into the common contract for no gain.
"""

DOCUMENT_CITATION_TYPE = "bothesis:document_citation"
"""The one BoThesis annotation type.

OpenResponses only specifies ``url_citation``, which cannot carry enterprise
document lineage (document id, page, section, access source). The spec requires
implementer-specific types to be slug-prefixed, hence ``bothesis:``.
"""


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
    """Text produced by the model, with its span annotations."""

    type: Literal["output_text"] = "output_text"
    text: str
    annotations: tuple[Annotation, ...] = ()


class Refusal(ProtocolModel):
    """A model refusal returned in place of output text."""

    type: Literal["refusal"] = "refusal"
    refusal: str


class ReasoningText(ProtocolModel):
    """Raw reasoning text inside a ``reasoning`` item."""

    type: Literal["reasoning_text"] = "reasoning_text"
    text: str


class SummaryText(ProtocolModel):
    """One provider-authored reasoning summary fragment."""

    type: Literal["summary_text"] = "summary_text"
    text: str


InputContent: TypeAlias = Annotated[
    InputText | InputImage | InputFile,
    Field(discriminator="type"),
]

MessageOutputContent: TypeAlias = Annotated[
    OutputText | Refusal,
    Field(discriminator="type"),
]

ReasoningContent: TypeAlias = Annotated[
    ReasoningText | SummaryText,
    Field(discriminator="type"),
]

ContentPart: TypeAlias = Annotated[
    InputText
    | InputImage
    | InputFile
    | OutputText
    | Refusal
    | ReasoningText
    | SummaryText,
    Field(discriminator="type"),
]

TEXT_PART_TYPES = (InputText, OutputText, ReasoningText, SummaryText)
"""Every part exposing a plain ``text`` attribute."""

__all__ = [
    "DOCUMENT_CITATION_TYPE",
    "TEXT_PART_TYPES",
    "Annotation",
    "ContentPart",
    "InputContent",
    "InputFile",
    "InputImage",
    "InputText",
    "MessageOutputContent",
    "OutputText",
    "ReasoningContent",
    "ReasoningText",
    "Refusal",
    "SummaryText",
]

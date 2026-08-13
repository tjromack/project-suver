"""The Read-an-image tool — Suver's 14th tool and its first IMAGE input (DEC 041).

Drop an image (a receipt, form, screenshot, scanned page) → a faithful transcription of its visible text, with an
**honest trust note**. This is the one modality where sanitize-before-egress can't hold — you can't tokenize PII
*inside* pixels before reading them — so Suver is transparent about it rather than pretending: the image is sent to
the model as-is (the trust note says so plainly), the model is told to transcribe only what's visible and never guess
(the vision analog of abstention), and the data boundary is applied to the **output** transcription (detect + flag
sensitive content + offer a sanitized copy for downstream). Same principle — *never a confident fabrication* — adapted
to a modality where the pre-egress guarantee can't apply.
"""

from __future__ import annotations

from app.pipeline import image_media_type, read_image_document
from app.tools import Tool, ToolError, ToolInput, ToolOutput, register


def run(inp: ToolInput) -> ToolOutput:
    if inp.data is None or not inp.filename:
        raise ToolError("Upload an image (PNG, JPG, GIF, or WEBP) to read.")
    media_type = image_media_type(inp.filename)
    if media_type is None:
        raise ToolError("That doesn't look like a supported image. Upload a PNG, JPG, GIF, or WEBP.")
    result = read_image_document(inp.data, media_type)
    return ToolOutput(result=result, template="_vision_result.html")


VISION = register(
    Tool(
        slug="read-image",
        name="Read an image",
        blurb="Drop an image — get a faithful transcription of its visible text, with an honest trust note.",
        icon="🖼️",
        accepts="PNG · JPG · GIF · WEBP",
        action_label="Read",
        run=run,
        status="live",
        platform="Documents",
        lane="Read",
        tags=("Documents", "Vision", "Honest about limits"),
        accept_ext=".png,.jpg,.jpeg,.gif,.webp",
        no_paste=True,
        upload_note="the image itself is sent to the AI to be read — see the trust note with your result",
    )
)

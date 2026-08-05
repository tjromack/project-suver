"""The rest of the Documents platform — registered as 'coming soon' so the hub shows where Suver is going.

These are the other engines the suite already has (Copilot/Converse, Draft, Extractor); once the shell + contract
+ hub exist (this pilot), each becomes a small add on the same rails. No `run` yet → the hub shows them as cards,
not openable. See ../../../_PLATFORM/VISION.md (the Documents platform is the flagship).
"""

from __future__ import annotations

from app.tools import Tool, register

register(Tool(
    slug="extractor",
    name="Extract fields",
    blurb="Pull the fields you need into a clean table — typed, validated, with the uncertain ones flagged.",
    icon="🧾",
    accepts="PDF · DOCX · TXT",
    action_label="Extract",
    status="soon",
    tags=("Documents", "Typed extraction"),
))

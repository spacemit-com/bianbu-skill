"""Resolve VPU benchmark tools supplied by the operating system."""

from __future__ import annotations

import shutil


MVX_TOOLS = (
    "mvx_encoder",
    "mvx_decoder",
    "mvx_encoder_multi",
    "mvx_decoder_multi",
)


def tool_path(name: str) -> str | None:
    """Return a system-installed executable from PATH."""
    return shutil.which(name)


def missing_mvx_tools() -> list[str]:
    return [name for name in MVX_TOOLS if tool_path(name) is None]

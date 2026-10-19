"""Participant stop requests, independent of caption punctuation."""

import re


def stop_requested(text: str) -> bool:
    return re.fullmatch(r"tilo\s*,?\s+leave[.!?]*", text.strip(), flags=re.I) is not None

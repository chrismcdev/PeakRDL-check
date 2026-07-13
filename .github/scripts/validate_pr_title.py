"""Validate a pull-request title against this repository's commit convention."""

from __future__ import annotations

import os
import re


ALLOWED_TYPES = ("feat", "fix", "docs", "test", "perf", "build", "ci", "style", "revert")
TITLE_PATTERN = re.compile(
    rf"^(?:{'|'.join(ALLOWED_TYPES)})(?:\([a-z0-9][a-z0-9._/-]*\))?!?: [^\s].+$"
)


def validate(title: str) -> None:
    """Raise ValueError when *title* cannot become an allowed squash commit."""
    if len(title) > 72:
        raise ValueError(f"PR title is {len(title)} characters; the maximum is 72")
    if not TITLE_PATTERN.fullmatch(title):
        allowed = ", ".join(ALLOWED_TYPES)
        raise ValueError(
            "PR title must use 'type(scope): summary' or 'type: summary'; "
            f"allowed types are: {allowed}. chore and refactor are intentionally blocked."
        )


if __name__ == "__main__":
    try:
        validate(os.environ["PR_TITLE"])
    except (KeyError, ValueError) as error:
        print(f"::error title=Invalid PR title::{error}")
        raise SystemExit(1) from error

    print(f"Accepted Conventional Commit title: {os.environ['PR_TITLE']}")

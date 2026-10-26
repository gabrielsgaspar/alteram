"""Load cases and prompts from Markdown files."""

import hashlib
import re
from pathlib import Path

from pydantic import ValidationError

from alteram.models import Case, Prompt

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_FIELDS = ("id", "title", "kind", "expected")
_PARAGRAPH = re.compile(r"^\[(\d+)\] (.+)$")
_VERSION = re.compile(r"^version: (\d+)$")


class CaseFormatError(ValueError):
    pass


def load_case(path: Path) -> Case:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise CaseFormatError(f"{path.name}: missing --- frontmatter block")
    end = lines.index("---", 1)

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if not sep:
            raise CaseFormatError(f"{path.name}: bad frontmatter line {line!r}")
        meta[key.strip()] = value.strip()
    missing = [f for f in _FIELDS if not meta.get(f)]
    if missing:
        raise CaseFormatError(f"{path.name}: missing frontmatter field(s) {missing}")

    paragraphs: dict[int, str] = {}
    for line in lines[end + 1 :]:
        if not line.strip():
            continue
        match = _PARAGRAPH.match(line)
        if not match:
            raise CaseFormatError(f"{path.name}: not a [n] paragraph: {line!r}")
        n = int(match[1])
        if n in paragraphs:
            raise CaseFormatError(f"{path.name}: paragraph [{n}] appears twice")
        paragraphs[n] = match[2]

    try:
        return Case(**{f: meta[f] for f in _FIELDS}, paragraphs=paragraphs)
    except ValidationError as e:
        raise CaseFormatError(f"{path.name}: {e}") from e


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    raw = (prompts_dir / f"{name}.md").read_bytes().decode("utf-8")
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    first, _, rest = text.partition("\n")
    match = _VERSION.match(first)
    if not match:
        raise ValueError(f"{name}.md must start with 'version: N', got {first!r}")
    return Prompt(
        name=name,
        version=int(match[1]),
        text=rest.lstrip("\n"),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )

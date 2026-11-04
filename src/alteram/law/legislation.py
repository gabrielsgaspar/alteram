"""Parse one legislation.gov.uk CLML document into provisions (M3.md 4.2).

The parser reads the `/data.xml` form of a section or Act. It returns clean
text, a heading path, validity dates, status and the unapplied effects that
affect each provision, so the chunker never sees XML. Standard library only.

Validity: `RestrictStartDate` and `RestrictEndDate` are read from the *same*
element, the nearest one (the provision or an ancestor) that has a start date.
Ancestors such as `Body` and `Part` carry end dates that belong to other
versions, so mixing elements would give wrong spans. `RestrictEndDate` is
already exclusive: it equals the next version's start date, so it is used as
`in_force_to` unchanged (see the CCA s.88 tests).
"""

import re
import xml.etree.ElementTree as ET
from datetime import date

from pydantic import BaseModel

from alteram.law.models import Provision, Status

_CLML = "http://www.legislation.gov.uk/namespaces/legislation"
_UKM = "http://www.legislation.gov.uk/namespaces/metadata"
_DC = "http://purl.org/dc/elements/1.1/"
_DCT = "http://purl.org/dc/terms/"
_ATOM = "http://www.w3.org/2005/Atom"

_HAS_VERSION = "http://purl.org/dc/terms/hasVersion"
_ID_PREFIX = "http://www.legislation.gov.uk/id/"

# Elements removed from text together with everything inside them.
_DROP = frozenset(
    {"CommentaryRef", "FootnoteRef", "Commentaries", "Footnotes", "Footnote"}
)
# Sub-levels of a subsection: each goes on its own line as "(n) text".
_SUBLEVELS = frozenset({"P3", "P4", "P5", "P6", "P7"})
# Provision levels; a provision nested inside one of these is quoted text.
_PROVISION_LEVELS = frozenset({"P1", "P2"}) | _SUBLEVELS
# Ancestors whose titles go into the heading path.
_HEADING_LEVELS = frozenset({"Part", "Chapter", "Pblock"})

_TRAILING_DATE = re.compile(r"/\d{4}-\d{2}-\d{2}$")


class ParsedDocument(BaseModel):
    """One parsed CLML document."""

    uri_path: str
    valid_from: date
    restrict_start: date | None
    restrict_end: date | None
    version_dates: list[date]
    provisions: list[Provision]
    skipped: int = 0


def _local(elem: ET.Element) -> str:
    return elem.tag.rpartition("}")[2]


def _clml(name: str) -> str:
    return f"{{{_CLML}}}{name}"


def _inline(elem: ET.Element) -> str:
    """Text of an element without dropped elements (tails kept), whitespace tidied."""

    def collect(e: ET.Element) -> list[str]:
        parts = [e.text or ""]
        for child in e:
            if _local(child) not in _DROP:
                parts.extend(collect(child))
            parts.append(child.tail or "")
        return parts

    return " ".join("".join(collect(elem)).split())


def _lines(elem: ET.Element) -> list[str]:
    """Text lines below a provision: its text, then each sub-level as "(n) ..."."""
    result: list[str] = []
    for child in elem:
        name = _local(child)
        if name in _DROP or name == "Pnumber":
            continue
        if name == "Text":
            result.append(_inline(child))
        elif name in _SUBLEVELS:
            number = child.find(_clml("Pnumber"))
            body = _lines(child)
            label = f"({_inline(number)})" if number is not None else ""
            if body and label:
                body[0] = f"{label} {body[0]}"
            result.extend(body)
        else:
            result.extend(_lines(child))
    return [line for line in result if line]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _uri_path(uri: str) -> str:
    """`http://www.legislation.gov.uk/id/ukpga/1974/39` -> `ukpga/1974/39`."""
    path = uri.removeprefix(_ID_PREFIX)
    return _TRAILING_DATE.sub("", path)


def _metadata_text(root: ET.Element, namespace: str, name: str) -> str | None:
    found = root.find(f"{{{_UKM}}}Metadata/{{{namespace}}}{name}")
    return found.text.strip() if found is not None and found.text else None


def _version_dates(root: ET.Element) -> list[date]:
    dates: set[date] = set()
    for link in root.iterfind(f"{{{_UKM}}}Metadata/{{{_ATOM}}}link"):
        if link.get("rel") == _HAS_VERSION:
            parsed = _parse_date(link.get("title"))
            if parsed is not None:
                dates.add(parsed)
    return sorted(dates)


def _chain(elem: ET.Element, parents: dict[ET.Element, ET.Element]) -> list[ET.Element]:
    """The element and its ancestors, nearest first."""
    result = [elem]
    while result[-1] in parents:
        result.append(parents[result[-1]])
    return result


def _validity(
    chain: list[ET.Element], fallback_start: date
) -> tuple[date, date | None]:
    """Start and end from the same element: the nearest with a start date."""
    for elem in chain:
        start = _parse_date(elem.get("RestrictStartDate"))
        if start is not None:
            return start, _parse_date(elem.get("RestrictEndDate"))
    return fallback_start, None


def _first_attr(chain: list[ET.Element], name: str) -> str | None:
    for elem in chain:
        value = elem.get(name)
        if value is not None:
            return value
    return None


def _status(chain: list[ET.Element]) -> Status:
    value = _first_attr(chain, "Status")
    if value == "Prospective":
        return "prospective"
    if value == "Repealed":
        return "repealed"
    return "in_force"


def _heading_path(
    act_title: str, chain: list[ET.Element], section_number: str
) -> list[str]:
    path = [act_title] if act_title else []
    section_title = ""
    for elem in reversed(chain):
        name = _local(elem)
        title = elem.find(_clml("Title"))
        if title is None:
            continue
        if name in _HEADING_LEVELS:
            path.append(_inline(title))
        elif name == "P1group":
            section_title = _inline(title)
    path.append(f"s.{section_number} {section_title}".strip())
    return path


def _subtree_ids(elem: ET.Element, chain: list[ET.Element]) -> set[str]:
    """`id`s of the provision, its ancestors and everything inside it."""
    ids = {e.get("id") for e in chain} | {e.get("id") for e in elem.iter()}
    ids.discard(None)
    return {i for i in ids if i}


class _Effect:
    """One unapplied effect: the element ids it targets and a short description."""

    def __init__(self, targets: set[str], text: str) -> None:
        self.targets = targets
        self.text = text


def _effects(root: ET.Element, known_ids: set[str]) -> list[_Effect]:
    effects: list[_Effect] = []
    path = f"{{{_UKM}}}Metadata/{{{_UKM}}}PrimaryMetadata/{{{_UKM}}}UnappliedEffects"
    for effect in root.iterfind(f"{path}/{{{_UKM}}}UnappliedEffect"):
        targets: set[str] = set()
        affected = effect.find(f"{{{_UKM}}}AffectedProvisions")
        for ref_elem in affected.iter() if affected is not None else []:
            ref = ref_elem.get("Ref")
            found = ref_elem.get("FoundRef")
            if ref in known_ids:
                targets.add(ref)
            elif found:
                targets.add(found)
        kind = effect.get("Type", "changed")
        affected_text = effect.get("AffectedProvisions", "")
        affecting_text = effect.get("AffectingProvisions", "")
        title_elem = effect.find(f"{{{_UKM}}}AffectingTitle")
        title = (
            " ".join("".join(title_elem.itertext()).split())
            if title_elem is not None
            else ""
        )
        by = ", ".join(part for part in (title, affecting_text) if part)
        text = f"{kind}: {affected_text}" + (f" (by {by})" if by else "")
        effects.append(_Effect(targets, text.strip()))
    return effects


def parse_document(xml: bytes, source: str) -> ParsedDocument:
    """Parse one CLML `data.xml` document. Raises ValueError on unusable input."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not valid XML: {exc}") from exc
    if _local(root) != "Legislation":
        raise ValueError(f"not a CLML Legislation document: <{_local(root)}>")

    identity = root.get("IdURI") or root.get("DocumentURI")
    if not identity:
        raise ValueError("document has no IdURI")
    valid_from = _parse_date(_metadata_text(root, _DCT, "valid"))
    if valid_from is None:
        raise ValueError("document has no dct:valid date")
    restrict_start = _parse_date(root.get("RestrictStartDate"))
    restrict_end = _parse_date(root.get("RestrictEndDate"))
    act_title = _metadata_text(root, _DC, "title") or ""

    parents = {child: parent for parent in root.iter() for child in parent}
    known_ids = {i for e in root.iter() if (i := e.get("id"))}
    effects = _effects(root, known_ids)

    provisions: list[Provision] = []
    skipped = 0
    for p1 in root.iter(_clml("P1")):
        p1_chain = _chain(p1, parents)
        if any(_local(e) in _PROVISION_LEVELS for e in p1_chain[1:]):
            continue  # quoted text inside an amendment, not a provision
        number_elem = p1.find(_clml("Pnumber"))
        section_number = _inline(number_elem) if number_elem is not None else ""
        units = p1.findall(f"{_clml('P1para')}/{_clml('P2')}") or [p1]
        for unit in units:
            chain = _chain(unit, parents)
            if (
                _first_attr(chain, "Match") == "false"
                and _status(chain) != "prospective"
            ):
                skipped += 1
                continue
            start, end = _validity(chain, restrict_start or valid_from)
            ids = _subtree_ids(unit, chain)
            unit_number = unit.find(_clml("Pnumber"))
            provisions.append(
                Provision(
                    source=source,
                    uri_path=_uri_path(unit.get("IdURI") or ""),
                    heading_path=_heading_path(act_title, p1_chain, section_number),
                    number=_inline(unit_number) if unit_number is not None else "",
                    text="\n".join(_lines(unit)),
                    extent=_first_attr(chain, "RestrictExtent"),
                    in_force_from=start,
                    in_force_to=end,
                    status=_status(chain),
                    unapplied_effects=[e.text for e in effects if e.targets & ids],
                )
            )

    return ParsedDocument(
        uri_path=_uri_path(identity),
        valid_from=valid_from,
        restrict_start=restrict_start,
        restrict_end=restrict_end,
        version_dates=_version_dates(root),
        provisions=provisions,
        skipped=skipped,
    )

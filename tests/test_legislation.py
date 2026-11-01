"""Tests for the CLML parser, run on the fixtures in tests/fixtures/law/legislation."""

import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from alteram.law.legislation import ParsedDocument, parse_document
from alteram.law.models import in_force_on

FIXTURES = Path(__file__).parent / "fixtures" / "law" / "legislation"
ALL_FIXTURES = sorted(FIXTURES.glob("*.xml"))
SOURCE = "legislation.gov.uk"


def load(name: str) -> ParsedDocument:
    return parse_document((FIXTURES / name).read_bytes(), SOURCE)


def by_number(doc: ParsedDocument, number: str):
    matches = [p for p in doc.provisions if p.number == number]
    assert len(matches) == 1, f"expected one provision numbered {number}"
    return matches[0]


def test_fixtures_are_present() -> None:
    assert len(ALL_FIXTURES) == 8


def test_cra_s9_one_provision_per_subsection() -> None:
    doc = load("ukpga-2015-15-section-9@2015-10-01.xml")
    assert doc.uri_path == "ukpga/2015/15"
    assert [p.number for p in doc.provisions] == [str(n) for n in range(1, 10)]
    first = by_number(doc, "1")
    assert first.text == (
        "Every contract to supply goods is to be treated as including a term "
        "that the quality of the goods is satisfactory."
    )
    assert first.heading_path[0] == "Consumer Rights Act 2015"
    assert first.heading_path[-1] == "s.9 Goods to be of satisfactory quality"
    assert first.heading_path[1:-1] == [
        "Consumer contracts for goods, digital content and services",
        "Goods",
        "What statutory rights are there under a goods contract?",
    ]
    assert first.uri_path == "ukpga/2015/15/section/9/1"
    assert first.source == SOURCE
    assert first.status == "in_force"
    assert first.extent == "E+W+S+N.I."


def test_cra_s9_sublevels_stay_in_subsection_text() -> None:
    doc = load("ukpga-2015-15-section-9@2015-10-01.xml")
    lines = by_number(doc, "2").text.split("\n")
    assert lines[0].endswith("taking account of—")
    assert lines[1] == "(a) any description of the goods,"
    assert lines[3] == "(c) all the other relevant circumstances (see subsection (5))."


def test_cra_s9_validity_pairs_start_and_end_from_one_element() -> None:
    # Body, Part and Chapter carry unrelated end dates; the section's own span
    # is open-ended.
    doc = load("ukpga-2015-15-section-9@2015-10-01.xml")
    for provision in doc.provisions:
        assert provision.in_force_from == date(2015, 10, 1)
        assert provision.in_force_to is None


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.name)
def test_provision_text_is_clean(path: Path) -> None:
    data = path.read_bytes()
    doc = parse_document(data, SOURCE)
    commentaries = [
        " ".join("".join(c.itertext()).split())
        for c in ET.fromstring(data).iter()
        if c.tag.endswith("}Commentary")
    ]
    for provision in doc.provisions:
        assert "<" not in provision.text
        assert ">" not in provision.text
        assert not re.search(r"\bF\d+\b", provision.text)
        for commentary in commentaries:
            assert commentary[:40] not in provision.text
        assert provision.text == provision.text.strip()
        assert "  " not in provision.text


def test_substitution_and_addition_text_is_kept() -> None:
    doc = load("ukpga-1974-39-section-88@current.xml")
    assert "not be less than 14 days after" in by_number(doc, "2").text
    assert by_number(doc, "4").text.endswith(
        "consequences of failure to comply with it and any other prescribed "
        "matters relating to the agreement."
    )
    assert by_number(doc, "4A").text == (
        "The default notice must also include a copy of the current default "
        "information sheet under section 86A."
    )


def test_s88_current_version_dates_are_ascending_and_dated_only() -> None:
    doc = load("ukpga-1974-39-section-88@current.xml")
    assert doc.version_dates == [
        date(1991, 2, 1),
        date(2006, 6, 16),
        date(2006, 10, 1),
        date(2008, 10, 1),
    ]
    assert doc.valid_from == date(2026, 9, 30)
    assert doc.uri_path == "ukpga/1974/39"


def test_s88_current_provision_is_open_ended_from_2008() -> None:
    doc = load("ukpga-1974-39-section-88@current.xml")
    for provision in doc.provisions:
        assert provision.in_force_from == date(2008, 10, 1)
        assert provision.in_force_to is None
    assert by_number(doc, "1").heading_path[1:-1] == [
        "Default and Termination",
        "Default notices",
    ]
    assert by_number(doc, "1").heading_path[-1] == (
        "s.88 Contents and effect of default notice."
    )


def adjacent_versions() -> list[ParsedDocument]:
    return [
        load(f"ukpga-1974-39-section-88@{stamp}.xml")
        for stamp in ("2006-06-16", "2006-10-01", "2008-10-01")
    ]


def test_s88_adjacent_versions_meet_without_gap_or_overlap() -> None:
    docs = adjacent_versions()
    for earlier, later in zip(docs, docs[1:], strict=False):
        for a, b in zip(earlier.provisions[:1], later.provisions[:1], strict=True):
            assert a.in_force_to == b.in_force_from
    assert docs[0].provisions[0].in_force_from == date(2006, 6, 16)
    assert docs[0].provisions[0].in_force_to == date(2006, 10, 1)
    assert docs[1].provisions[0].in_force_to == date(2008, 10, 1)
    assert docs[2].provisions[0].in_force_to is None


def test_restrict_end_date_is_already_exclusive() -> None:
    """The 2006-06-16 version ends on 2006-10-01, the day the next one starts.

    So RestrictEndDate is the first day the version no longer applies, and it
    is used as `in_force_to` unchanged.
    """
    earlier, later, _ = adjacent_versions()
    boundary = date(2006, 10, 1)
    assert not in_force_on(earlier.provisions[0], boundary)
    assert in_force_on(later.provisions[0], boundary)
    assert in_force_on(earlier.provisions[0], date(2006, 9, 30))


def test_s88_4a_absent_in_2006_10_01_and_present_in_2008_10_01() -> None:
    _, middle, latest = adjacent_versions()
    assert "4A" not in [p.number for p in middle.provisions]
    assert "4A" in [p.number for p in latest.provisions]


def test_s88_changed_text_between_versions() -> None:
    first, second, _ = adjacent_versions()
    assert "seven days" in by_number(first, "2").text
    assert "14 days" in by_number(second, "2").text


def test_cra_s12_has_unapplied_effects_for_its_own_subsections() -> None:
    doc = load("ukpga-2015-15-section-12@current.xml")
    subsection_3 = by_number(doc, "3")
    own = [e for e in subsection_3.unapplied_effects if "s. 12(3)" in e]
    assert len(own) == 2
    assert any("words substituted" in e for e in own)
    # s.12(2A) does not exist yet; its effect attaches to the section.
    assert any("12(2A)" in e for e in by_number(doc, "1").unapplied_effects)
    # An effect on s.37 is not listed on s.12.
    for provision in doc.provisions:
        assert not any("37(2A)" in e for e in provision.unapplied_effects)
    # An effect on "specified provision(s)" has no target and is not attached.
    for provision in doc.provisions:
        assert not any("specified provision" in e for e in provision.unapplied_effects)


def test_effect_text_names_the_affecting_act() -> None:
    doc = load("ukpga-2015-15-section-12@current.xml")
    effect = next(e for e in by_number(doc, "3").unapplied_effects if "s. 12(3)" in e)
    assert "Digital Markets, Competition and Consumers Act 2024" in effect
    assert "s. 278(3)(b)(i)" in effect


def test_s88_lists_no_effects_aimed_at_other_sections() -> None:
    doc = load("ukpga-1974-39-section-88@current.xml")
    assert doc.provisions
    assert all(p.unapplied_effects == [] for p in doc.provisions)


def test_s140a_base_date_case() -> None:
    """Requested at 1990-01-01, s.140A did not exist until 2007.

    The document's `dct:valid` is 1991-02-01. Every part of s.140A is
    `Match="false"` and not marked prospective, so none is returned and all
    five subsections are counted in `skipped`.
    """
    doc = load("ukpga-1974-39-section-140A@1990-01-01.xml")
    assert doc.valid_from == date(1991, 2, 1)
    assert doc.provisions == []
    assert doc.skipped == 5


def synthetic(body: str, section_attrs: str = "") -> bytes:
    return f"""<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
 IdURI="http://www.legislation.gov.uk/id/ukpga/2000/1/2001-01-01"
 RestrictStartDate="2001-01-01" RestrictExtent="E+W">
<ukm:Metadata xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dct="http://purl.org/dc/terms/">
<dc:title>Test Act 2000</dc:title><dct:valid>2001-01-01</dct:valid></ukm:Metadata>
<Primary><Body><P1group {section_attrs}><Title>A title</Title>
{body}</P1group></Body></Primary>
</Legislation>""".encode()


def test_section_without_subsections_is_one_provision() -> None:
    xml = synthetic(
        '<P1 IdURI="http://www.legislation.gov.uk/id/ukpga/2000/1/section/1" '
        'id="section-1"><Pnumber>1</Pnumber><P1para><Text>Plain<CommentaryRef '
        'Ref="c1"/> text.</Text></P1para></P1>'
    )
    doc = parse_document(xml, SOURCE)
    assert doc.uri_path == "ukpga/2000/1"
    assert len(doc.provisions) == 1
    provision = doc.provisions[0]
    assert provision.text == "Plain text."
    assert provision.number == "1"
    assert provision.uri_path == "ukpga/2000/1/section/1"
    assert provision.heading_path == ["Test Act 2000", "s.1 A title"]
    assert provision.in_force_from == date(2001, 1, 1)


def test_prospective_and_repealed_status() -> None:
    p1 = (
        '<P1 IdURI="http://www.legislation.gov.uk/id/ukpga/2000/1/section/1" '
        'id="section-1"><Pnumber>1</Pnumber><P1para><Text>Words.</Text></P1para></P1>'
    )
    prospective = parse_document(synthetic(p1, 'Status="Prospective"'), SOURCE)
    assert prospective.provisions[0].status == "prospective"
    repealed = parse_document(synthetic(p1, 'Status="Repealed"'), SOURCE)
    assert repealed.provisions[0].status == "repealed"


def test_non_matching_provisions_are_skipped_unless_prospective() -> None:
    p1 = (
        '<P1 IdURI="http://www.legislation.gov.uk/id/ukpga/2000/1/section/1" '
        'id="section-1"><Pnumber>1</Pnumber><P1para><Text>Words.</Text></P1para></P1>'
    )
    skipped = parse_document(synthetic(p1, 'Match="false"'), SOURCE)
    assert skipped.provisions == []
    assert skipped.skipped == 1
    kept = parse_document(synthetic(p1, 'Match="false" Status="Prospective"'), SOURCE)
    assert [p.status for p in kept.provisions] == ["prospective"]
    assert kept.skipped == 0


def test_invalid_input_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not valid XML"):
        parse_document(b"<Legislation", SOURCE)
    with pytest.raises(ValueError, match="not a CLML"):
        parse_document(b"<html/>", SOURCE)

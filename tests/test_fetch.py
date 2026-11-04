import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from alteram.law.fetch import (
    FetchError,
    Source,
    fetch_source,
    load_sources,
    section_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "law" / "legislation"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
CONTACT = "mailto:test@example.com"
BASE = "ukpga/1974/39"

# s.88 lists a 1991-02-01 version, but no fixture exists for that date. The mock
# serves the 2006-06-16 fixture for it: only the request matters here, not the text.
URL_TO_FILE = {
    section_url(BASE, "88"): "ukpga-1974-39-section-88@current.xml",
    section_url(
        BASE, "88", date(1991, 2, 1)
    ): "ukpga-1974-39-section-88@2006-06-16.xml",
    section_url(
        BASE, "88", date(2006, 6, 16)
    ): "ukpga-1974-39-section-88@2006-06-16.xml",
    section_url(
        BASE, "88", date(2006, 10, 1)
    ): "ukpga-1974-39-section-88@2006-10-01.xml",
    section_url(
        BASE, "88", date(2008, 10, 1)
    ): "ukpga-1974-39-section-88@2008-10-01.xml",
}
EXPECTED_FILES = [
    "88@1991-02-01.xml",
    "88@2006-06-16.xml",
    "88@2006-10-01.xml",
    "88@2008-10-01.xml",
    "88@current.xml",
]


def make_source() -> Source:
    return Source(
        kind="legislation",
        base=BASE,
        title="Consumer Credit Act 1974",
        sections=["88"],
        doc_type="statute",
        authority_tier="statute",
        licence="OGL-3.0",
        attribution="x",
    )


class Mock:
    def __init__(self, status: int = 200, fail_url: str | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.fail_url = fail_url
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == self.fail_url:
            return httpx.Response(self.status)
        return httpx.Response(200, content=(FIXTURES / URL_TO_FILE[url]).read_bytes())


def run(mock: Mock, raw: Path, sleeps: list[float], **kwargs):
    return fetch_source(
        make_source(),
        raw,
        mock.client,
        sleeps.append,
        NOW,
        kwargs.pop("contact", CONTACT),
        name="cca-1974",
        **kwargs,
    )


def test_real_sources_file_loads() -> None:
    sources = load_sources(Path(__file__).parents[1] / "law" / "sources.toml")
    assert set(sources) == {"cra-2015", "cca-1974", "limitation-1980"}
    assert "75" not in sources["cca-1974"].sections
    assert "75A" not in sources["cca-1974"].sections
    assert sources["cra-2015"].topics["24"] == [
        "price_reduction",
        "final_right_to_reject",
    ]


BASE_TOML = (
    'kind = "legislation"\nbase = "a/b"\ntitle = "T"\nsections = ["1"]\n'
    'doc_type = "statute"\nauthority_tier = "statute"\n'
    'licence = "L"\nattribution = "A"\n'
)


@pytest.mark.parametrize(
    "toml_text",
    [
        BASE_TOML + "surprise = 1\n",
        BASE_TOML.replace('licence = "L"\n', ""),
        BASE_TOML.replace('"legislation"', '"book"'),
    ],
)
def test_config_errors_name_the_source(tmp_path: Path, toml_text: str) -> None:
    path = tmp_path / "sources.toml"
    path.write_text("[my-source]\n" + toml_text)
    with pytest.raises(ValueError, match="^my-source:"):
        load_sources(path)


def test_section_url() -> None:
    assert section_url("ukpga/1974/39", "140A") == (
        "https://www.legislation.gov.uk/ukpga/1974/39/section/140A/data.xml"
    )
    assert section_url("ukpga/1974/39", "88", date(2006, 10, 1)) == (
        "https://www.legislation.gov.uk/ukpga/1974/39/section/88/2006-10-01/data.xml"
    )


def test_fetch_writes_current_and_dated_versions(tmp_path: Path) -> None:
    mock, sleeps = Mock(), []
    report = run(mock, tmp_path, sleeps)
    out = tmp_path / "cca-1974"
    assert sorted(p.name for p in out.glob("*.xml")) == EXPECTED_FILES
    assert report.fetched == 5
    assert report.skipped == 0
    assert len(mock.requests) == 5
    assert sleeps == [1.0] * 4
    for request in mock.requests:
        assert CONTACT in request.headers["user-agent"]
        assert request.headers["user-agent"].startswith("alteram/")


def test_second_run_makes_no_requests_and_refresh_refetches(tmp_path: Path) -> None:
    run(Mock(), tmp_path, [])
    again, sleeps = Mock(), []
    report = run(again, tmp_path, sleeps)
    assert again.requests == []
    assert sleeps == []
    assert report.fetched == 0
    assert report.skipped == 5
    forced = Mock()
    report = run(forced, tmp_path, [], refresh=True)
    assert len(forced.requests) == 5
    assert report.fetched == 5


def test_fetch_json_hashes_sorted_and_reproducible(tmp_path: Path) -> None:
    run(Mock(), tmp_path, [])
    manifest = tmp_path / "cca-1974" / "fetch.json"
    first = manifest.read_bytes()
    entries = json.loads(first)
    assert [e["file"] for e in entries] == EXPECTED_FILES
    for entry in entries:
        data = (tmp_path / "cca-1974" / entry["file"]).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["fetched_at"] == NOW.isoformat()
        assert entry["url"].startswith("https://www.legislation.gov.uk/" + BASE)
    run(Mock(), tmp_path, [])
    assert manifest.read_bytes() == first
    run(Mock(), tmp_path, [], refresh=True)
    assert manifest.read_bytes() == first


@pytest.mark.parametrize("status", [404, 503])
def test_http_error_names_url_and_leaves_no_partial_file(
    tmp_path: Path, status: int
) -> None:
    bad = section_url(BASE, "88", date(2006, 10, 1))
    mock = Mock(status=status, fail_url=bad)
    with pytest.raises(FetchError, match=bad):
        run(mock, tmp_path, [])
    out = tmp_path / "cca-1974"
    names = sorted(p.name for p in out.iterdir() if p.name != "fetch.json")
    assert "88@2006-10-01.xml" not in names
    assert all(n.endswith(".xml") for n in names)


def test_empty_contact_is_rejected(tmp_path: Path) -> None:
    mock = Mock()
    with pytest.raises(ValueError, match="contact"):
        run(mock, tmp_path, [], contact="  ")
    assert mock.requests == []

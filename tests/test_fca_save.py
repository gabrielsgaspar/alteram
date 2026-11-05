"""Tests for the pure parts of scripts/fca_save.py: no browser, no network, and
never the real .env."""

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fca_save.py"
DISP_TITLE = "FCA Handbook - DISP 2.8 Was the complaint referred in time?"
CONC_TITLE = "FCA Handbook - CONC 5.2A Creditworthiness assessment"


@pytest.fixture(scope="module")
def fca_save() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fca_save", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loading_the_script_does_not_import_playwright(fca_save: ModuleType) -> None:
    assert "playwright" not in sys.modules


# --- paths -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "cleaned", "chapter", "is_chapter"),
    [
        ("disp2/disp2s8", "disp2/disp2s8", "disp2", False),
        ("/conc5/conc5s6/", "conc5/conc5s6", "conc5", False),
        ("conc5", "conc5", "conc5", True),
        ("CONC2A", "conc2a", "conc2a", True),
    ],
)
def test_targets(
    fca_save: ModuleType, path: str, cleaned: str, chapter: str, is_chapter: bool
) -> None:
    assert fca_save.check_target(path) == cleaned
    assert fca_save.chapter_of(path) == chapter
    assert fca_save.is_chapter_path(path) is is_chapter


@pytest.mark.parametrize(
    "path", ["disp2/conc2s8", "disp2/disp3s1", "../etc/passwd", "conc", "", "a/b/c"]
)
def test_bad_paths_are_rejected(fca_save: ModuleType, path: str) -> None:
    with pytest.raises(ValueError, match="Not a Handbook chapter or section path"):
        fca_save.check_target(path)


def test_page_url(fca_save: ModuleType) -> None:
    assert fca_save.page_url("conc5") == "https://handbook.fca.org.uk/handbook/conc5"
    assert (
        fca_save.page_url("disp2/disp2s8")
        == "https://handbook.fca.org.uk/handbook/disp2/disp2s8"
    )


def test_chapter_label(fca_save: ModuleType) -> None:
    assert fca_save.chapter_label("conc5") == ("CONC", "5")
    assert fca_save.chapter_label("prin2a") == ("PRIN", "2A")


# --- discovery ---------------------------------------------------------------


def test_section_links_keeps_this_chapters_sections_in_order(
    fca_save: ModuleType,
) -> None:
    hrefs = [
        "/handbook/conc5/conc5s6#p37760",
        None,
        "/handbook/conc5",
        "/handbook/conc1/conc1s3",
        "/handbook/conc5/conc5s4",
        "https://handbook.fca.org.uk/handbook/conc5/conc5s7/",
        "/handbook/conc5/conc5s6",
        "https://example.org/handbook/conc5/conc5s9",
        "/handbook/conc50/conc50s1",
        "/glossary",
        "",
    ]
    assert fca_save.section_links("conc5", hrefs) == [
        "conc5/conc5s6",
        "conc5/conc5s4",
        "conc5/conc5s7",
    ]


def test_sections_from_api(fca_save: ModuleType) -> None:
    data = {
        "Result": {
            "chapterId": "conc5",
            "sectionId": None,
            "provisions": [
                {"sectionId": "conc5s6", "sectionName": "CONC 5.2A  Creditworthiness"},
                {"sectionId": "conc5s6", "sectionName": "ignored repeat"},
                {"sectionId": "conc5s4", "sectionName": None},
                {"sectionId": "conc5s4", "sectionName": "CONC 5.4 Credit brokers"},
                {"sectionId": "conc1s3", "sectionName": "another chapter"},
                {"nested": [{"sectionId": "CONC5S7", "sectionName": "CONC 5.5A P2P"}]},
            ],
        }
    }
    assert fca_save.sections_from_api("conc5", data) == [
        ("conc5/conc5s6", "CONC 5.2A Creditworthiness"),
        ("conc5/conc5s4", "CONC 5.4 Credit brokers"),
        ("conc5/conc5s7", "CONC 5.5A P2P"),
    ]
    assert fca_save.sections_from_api("conc5", {"Result": None}) == []


API = "https://api.prod.handbook.fca.org.uk/Handbook/"
PROVISIONS = API + "GetAllHandBookProvisionsSortedOrderByChapter/"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (PROVISIONS + "conc5?IsDeleted=false", True),
        (PROVISIONS + "conc5?sectionId=conc5s6&IsDeleted=false", False),
        (PROVISIONS + "conc50?IsDeleted=false", False),
        ("https://api.prod.handbook.fca.org.uk/TitleNote/GetTitleNote", False),
    ],
)
def test_is_chapter_provisions_url(
    fca_save: ModuleType, url: str, expected: bool
) -> None:
    assert fca_save.is_chapter_provisions_url("conc5", url) is expected


# --- page facts --------------------------------------------------------------


def test_section_number_and_file_stem(fca_save: ModuleType) -> None:
    assert fca_save.section_number(CONC_TITLE) == ("CONC", "5.2A")
    assert fca_save.section_number(DISP_TITLE) == ("DISP", "2.8")
    assert fca_save.section_number("FCA Handbook - CONC 5 Responsible lending") is None
    assert fca_save.file_stem("CONC", "5.2A") == "CONC-5.2A"


def test_annex_names(fca_save: ModuleType) -> None:
    title = "FCA Handbook - DISP 1 Annex 3 Appropriate wording for a final response"
    assert fca_save.section_number(title) == ("DISP", "1 Annex 3")
    title = "FCA Handbook - DISP 1 Annex 1AA Notes on completing the form"
    assert fca_save.section_number(title) == ("DISP", "1 Annex 1AA")
    assert fca_save.file_stem("DISP", "1 Annex 1AA") == "DISP-1-Annex-1AA"


@pytest.mark.parametrize(
    ("number", "chapter", "expected"),
    [("5.2A", "5", True), ("5 Annex 1", "5", True), ("50.1", "5", False)],
)
def test_in_chapter(
    fca_save: ModuleType, number: str, chapter: str, expected: bool
) -> None:
    assert fca_save.in_chapter(number, chapter) is expected


@pytest.mark.parametrize(
    ("header", "number", "expected"),
    [
        ("CONC 5.2A.1 01/11/2018 R", "5.2A", True),
        ("CONC 5.2.1 01/11/2018 R", "5.2A", False),
        ("CONC 5.2A.1 01/11/2018 R", "5.2", False),
        ("CONC 5.21.1 01/11/2018 R", "5.2", False),
        ("DISP 1 Annex 3.1 01/01/2020 R", "1 Annex 3", True),
        ("DISP 1 Annex 3 01/01/2020 R", "1 Annex 3", True),
        ("DISP 1 Annex 3A 01/01/2020 R", "1 Annex 3", False),
    ],
)
def test_header_in_section(
    fca_save: ModuleType, header: str, number: str, expected: bool
) -> None:
    book = header.split()[0]
    assert fca_save.header_in_section(header, book, number) is expected


def test_shown_dates_from_the_page_banner(fca_save: ModuleType) -> None:
    text = (
        "You are viewing DISP 2.8 Was the complaint referred in time? as of "
        "04/11/2026. DISP 2.8 Was the complaint referred in time? was last "
        "updated on 13/01/2018.\nDISP 2.8.2\n30/06/2016\nR"
    )
    assert fca_save.shown_dates(text) == {
        "as_of": "04/11/2026",
        "last_updated": "13/01/2018",
    }
    assert fca_save.shown_dates("DISP 2.8.2 30/06/2016 R") == {
        "as_of": None,
        "last_updated": None,
    }


def test_header_text(fca_save: ModuleType) -> None:
    raw = "DISP 2.8.2\n30/06/2016\nR"
    assert fca_save.header_text(raw) == "DISP 2.8.2 30/06/2016 R"
    assert fca_save.header_text("  \n ") is None
    assert fca_save.header_text(None) is None


@pytest.mark.parametrize(
    ("status", "text"),
    [
        (403, "DISP 2.8.2"),
        (429, ""),
        (200, "Please complete the reCAPTCHA to continue"),
        (None, "Verify you are human"),
    ],
)
def test_check_stop_raises(fca_save: ModuleType, status: int | None, text: str) -> None:
    with pytest.raises(fca_save.StopError):
        fca_save.check_stop(status, text)


@pytest.mark.parametrize(("status", "text"), [(200, "DISP 2.8.2"), (404, "")])
def test_check_stop_passes(fca_save: ModuleType, status: int, text: str) -> None:
    fca_save.check_stop(status, text)


CONC_5_TITLE = "FCA Handbook - CONC 5 Responsible lending"


@pytest.mark.parametrize(
    ("path", "status", "text", "title", "header", "reason"),
    [
        ("disp2/disp2s8", 200, "rules", DISP_TITLE, "DISP 2.8.1 13/01/2018 R", None),
        ("conc5/conc5s6", None, "rules", CONC_TITLE, "CONC 5.2A.1 01/11/2018 R", None),
        ("disp2/disp2s8", 404, "", DISP_TITLE, None, "HTTP 404"),
        ("disp2/disp2s8", 200, " \n", DISP_TITLE, None, "empty render"),
        ("disp2/disp2s99", 200, "Page not found", "FCA Handbook", None, "not found"),
        ("disp2/disp2s8", 200, "Loading...", DISP_TITLE, None, "no rule headers"),
        ("conc7/conc7s3", 200, "rules", CONC_TITLE, "CONC 5.2A.1 x R", "CONC 7"),
        ("conc5/conc5s6", 200, "rules", CONC_TITLE, "CONC 5.4.1 x R", "not in"),
        ("conc5/conc5s6", 200, "rules", CONC_5_TITLE, "CONC 5.2A.1 x R", "not name"),
    ],
)
def test_skip_reason(
    fca_save: ModuleType,
    path: str,
    status: int | None,
    text: str,
    title: str,
    header: str | None,
    reason: str | None,
) -> None:
    result = fca_save.skip_reason(path, status, text, title, header)
    if reason is None:
        assert result is None
    else:
        assert result is not None and reason in result


# --- files -------------------------------------------------------------------


def test_sidecar(fca_save: ModuleType) -> None:
    saved_at = datetime(2026, 11, 4, 12, 0, 5, tzinfo=timezone(timedelta(hours=1)))
    dates = {"as_of": "04/11/2026", "last_updated": "13/01/2018"}
    url = "https://handbook.fca.org.uk/handbook/disp2/disp2s8"
    sidecar = fca_save.build_sidecar(
        url,
        saved_at,
        dates,
        {"DISP-2.8.html": b"<html></html>"},
        final_url=url,
        title=DISP_TITLE,
        seconds_to_rules=2.345,
        first_header="DISP 2.8.1 13/01/2018 R",
    )
    assert sidecar == {
        "url": url,
        "final_url": url,
        "title": DISP_TITLE,
        "saved_at": "2026-11-04T11:00:05Z",
        "dates_shown": dates,
        "first_header": "DISP 2.8.1 13/01/2018 R",
        "seconds_to_rules": 2.3,
        "files": {"DISP-2.8.html": hashlib.sha256(b"<html></html>").hexdigest()},
        "saved_by": fca_save.SAVED_BY,
    }


def test_to_json_is_stable(fca_save: ModuleType) -> None:
    sidecar = fca_save.build_sidecar(
        "u", datetime(2026, 11, 4, tzinfo=UTC), {}, {"b": b"2", "a": b"1"}
    )
    text = fca_save.to_json(sidecar)
    assert text.endswith("\n")
    assert text == fca_save.to_json(json.loads(text))
    assert list(json.loads(text)["files"]) == ["a", "b"]


def write_save(
    fca_save: ModuleType, folder: Path, stem: str, url: str, html: bytes
) -> None:
    """A complete save as the script writes it: HTML file plus sidecar."""
    files = {f"{stem}.html": html}
    (folder / f"{stem}.html").write_bytes(html)
    sidecar = fca_save.build_sidecar(url, datetime.now(UTC), {}, files)
    (folder / f"{stem}.json").write_text(fca_save.to_json(sidecar))


def test_completed_saves_needs_sidecar_and_matching_file(
    fca_save: ModuleType, tmp_path: Path
) -> None:
    assert fca_save.completed_saves(tmp_path / "missing") == {}
    write_save(fca_save, tmp_path, "CONC-5.2A", "https://h/conc5/conc5s6", b"<a>")
    write_save(fca_save, tmp_path, "CONC-5.4", "https://h/conc5/conc5s4", b"<b>")
    write_save(fca_save, tmp_path, "CONC-5.5A", "https://h/conc5/conc5s7", b"<c>")
    (tmp_path / "CONC-5.4.html").write_bytes(b"<changed>")  # sha256 no longer matches
    (tmp_path / "CONC-5.5A.html").unlink()  # file gone
    (tmp_path / "CONC-6.1.html").write_bytes(b"<d>")  # interrupted: no sidecar
    (tmp_path / "report.json").write_text(json.dumps({"url": "https://h/report"}))
    (tmp_path / "other.json").write_text(json.dumps({"url": "https://h/other"}))
    (tmp_path / "broken.json").write_text("{")
    assert fca_save.completed_saves(tmp_path) == {
        "https://h/conc5/conc5s6": "CONC-5.2A"
    }


def test_fixtures_are_complete_saves_listed_in_sources(fca_save: ModuleType) -> None:
    fixtures = Path(__file__).parent / "fixtures" / "law" / "fca"
    assert fca_save.completed_saves(fixtures) == {
        "https://handbook.fca.org.uk/handbook/disp2/disp2s8": "DISP-2.8",
        "https://handbook.fca.org.uk/handbook/conc7/conc7s3": "CONC-7.3",
        "https://handbook.fca.org.uk/handbook/conc5/conc5s6": "CONC-5.2A",
    }
    sources = (fixtures / "SOURCES.md").read_text(encoding="utf-8")
    for path in sorted(fixtures.glob("*.htm*")) + sorted(fixtures.glob("*.json")):
        assert hashlib.sha256(path.read_bytes()).hexdigest() in sources, path.name


def test_rerun_skips_complete_saves_without_any_request(
    fca_save: ModuleType, tmp_path: Path
) -> None:
    url = fca_save.page_url("conc5/conc5s6")
    write_save(fca_save, tmp_path, "CONC-5.2A", url, b"<a>")

    class NoPage:
        def __getattr__(self, name: str) -> None:
            raise AssertionError(f"page.{name} used for an already saved section")

    report = fca_save.Report()
    pacer = fca_save.Pacer(sleep=lambda s: pytest.fail("paced without a request"))
    sections = fca_save.collect_sections(NoPage(), ["conc5/conc5s6"], pacer, report)
    fca_save.save_all(NoPage(), sections, tmp_path, pacer, report)
    entry = report.chapters["conc5"].as_dict()
    assert entry["already_present"] == ["conc5/conc5s6"]
    assert entry["missing"] == []
    assert report.problems() == 0


# --- report ------------------------------------------------------------------


def test_report_records_outcomes_per_chapter(fca_save: ModuleType) -> None:
    report = fca_save.Report()
    chapter = report.chapter("conc5")
    chapter.url, chapter.source = "https://h/conc5", "provisions data"
    chapter.found = [{"path": "conc5/conc5s4", "name": "CONC 5.4"}]
    chapter.requested = ["conc5/conc5s4", "conc5/conc5s6", "conc5/conc5s7"]
    report.chapter("disp2").requested = ["disp2/disp2s8"]
    report.record("conc5/conc5s4", "saved", "CONC-5.4")
    report.record("conc5/conc5s6", "already_present")
    report.record("disp2/disp2s8", "skipped", "HTTP 404")
    conc5 = report.chapters["conc5"].as_dict()
    assert conc5["discovered_from"] == "provisions data"
    assert conc5["saved"] == [{"path": "conc5/conc5s4", "file": "CONC-5.4"}]
    assert conc5["already_present"] == ["conc5/conc5s6"]
    assert conc5["missing"] == ["conc5/conc5s7"]  # never tried: the run stopped
    assert conc5["counts"] == {
        "found": 1,
        "saved": 1,
        "already_present": 1,
        "skipped": 0,
        "missing": 1,
    }
    disp2 = report.chapters["disp2"].as_dict()
    assert disp2["sections_found"] is None
    assert disp2["skipped"] == [{"path": "disp2/disp2s8", "reason": "HTTP 404"}]
    assert disp2["missing"] == ["disp2/disp2s8"]
    assert report.problems() == 2
    with pytest.raises(ValueError, match="Unknown outcome"):
        report.record("conc5/conc5s4", "lost")


def test_unreached_chapter_has_unknown_missing(fca_save: ModuleType) -> None:
    report = fca_save.Report()
    report.chapter("disp3").error = fca_save.NOT_REACHED
    entry = report.chapters["disp3"].as_dict()
    assert entry["missing"] is None
    assert entry["counts"]["missing"] is None
    assert report.problems() == 1


def test_collect_sections_queues_given_sections(fca_save: ModuleType) -> None:
    report = fca_save.Report()
    sections = fca_save.collect_sections(
        None,
        ["disp2/disp2s8", "conc7/conc7s3", "disp2/disp2s8"],
        fca_save.Pacer(),
        report,
    )
    assert sections == ["disp2/disp2s8", "conc7/conc7s3"]
    assert report.chapters["disp2"].requested == ["disp2/disp2s8"]
    assert report.chapters["conc7"].requested == ["conc7/conc7s3"]


def test_discovery_error_counts_as_a_problem(fca_save: ModuleType) -> None:
    report = fca_save.Report()
    entry = report.chapter("conc9")
    entry.found, entry.error = [], "navigation failed: Timeout 60000ms exceeded"
    # No sections known, so "missing" must not read as "nothing missing".
    assert entry.as_dict()["missing"] is None
    assert report.problems() == 1


def test_merge_report_replaces_only_this_runs_chapters(fca_save: ModuleType) -> None:
    previous = {
        "chapters": {
            "conc1": {"saved": ["old"]},
            "conc5": {"saved": ["x"]},
            "disp3": {"saved": ["earlier run"]},
        }
    }
    report = fca_save.Report(stopped="https://h/x: HTTP 403")
    report.record("conc5/conc5s4", "saved", "CONC-5.4")
    report.chapter("disp3").error = fca_save.NOT_REACHED
    report.chapter("disp1").error = fca_save.NOT_REACHED
    merged = fca_save.merge_report(previous, report, datetime(2026, 11, 5, tzinfo=UTC))
    assert merged["updated_at"] == "2026-11-05T00:00:00Z"
    assert merged["stopped"] == "https://h/x: HTTP 403"
    assert list(merged["chapters"]) == ["conc1", "conc5", "disp1", "disp3"]
    assert merged["chapters"]["conc1"] == {"saved": ["old"]}
    assert merged["chapters"]["conc5"]["saved"] == [
        {"path": "conc5/conc5s4", "file": "CONC-5.4"}
    ]
    assert merged["chapters"]["disp3"] == {"saved": ["earlier run"]}  # kept
    assert merged["chapters"]["disp1"]["discovery_error"] == fca_save.NOT_REACHED
    empty = fca_save.merge_report(None, fca_save.Report(), datetime.now(UTC))
    assert empty["chapters"] == {}


# --- environment and pacing --------------------------------------------------


def test_user_agent(fca_save: ModuleType) -> None:
    ua = fca_save.user_agent("0.1.0", "https://example.org/alteram")
    assert ua == "alteram/0.1.0 (+https://example.org/alteram)"


def test_contact_from_environment_does_not_load_env_file(fca_save: ModuleType) -> None:
    def load_env() -> None:
        raise AssertionError(".env must not be read when the variable is set")

    environ = {"ALTERAM_HTTP_CONTACT": " https://example.org "}
    assert fca_save.get_contact(environ, load_env) == "https://example.org"


def test_contact_falls_back_to_env_file(fca_save: ModuleType) -> None:
    environ: dict[str, str] = {}

    def load_env() -> None:
        environ["ALTERAM_HTTP_CONTACT"] = "someone@example.org"

    assert fca_save.get_contact(environ, load_env) == "someone@example.org"


def test_missing_contact_refuses_to_run(fca_save: ModuleType) -> None:
    with pytest.raises(fca_save.StopError, match="ALTERAM_HTTP_CONTACT"):
        fca_save.get_contact({"ALTERAM_HTTP_CONTACT": "  "}, lambda: None)


def test_proxy_settings(fca_save: ModuleType) -> None:
    assert fca_save.proxy_settings({}) is None
    assert fca_save.proxy_settings({"https_proxy": "http://127.0.0.1:3128"}) == {
        "server": "http://127.0.0.1:3128"
    }
    with_auth = {"HTTPS_PROXY": "http://us%40er:p%3Ass@proxy.local:8080"}
    assert fca_save.proxy_settings(with_auth) == {
        "server": "http://proxy.local:8080",
        "username": "us@er",
        "password": "p:ss",
    }


def test_pacer_keeps_three_seconds_between_requests(fca_save: ModuleType) -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    pacer = fca_save.Pacer(delay=3.0, clock=lambda: now[0], sleep=sleep)
    pacer.wait()  # first request: no wait
    now[0] += 1.0
    pacer.wait()  # 1 s later: waits 2 s
    now[0] += 5.0
    pacer.wait()  # 5 s later: no wait
    assert slept == [pytest.approx(2.0)]


def test_bad_path_stops_before_any_browser_or_env(
    fca_save: ModuleType, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert fca_save.main([str(tmp_path), "disp2/disp2s8", "nonsense/x"]) == 1
    assert "Not a Handbook chapter or section path" in capsys.readouterr().err
    assert "playwright" not in sys.modules


def test_stop_message_includes_retry_after(fca_save: ModuleType) -> None:
    with pytest.raises(fca_save.StopError, match=r"HTTP 429.*Retry-After: 120"):
        fca_save.check_stop(429, "", "120")


@pytest.mark.parametrize(
    ("resource_type", "aborted"),
    [
        ("image", True),
        ("font", True),
        ("media", True),
        ("document", False),
        ("script", False),
        ("xhr", False),
        ("fetch", False),
    ],
)
def test_skip_resource(fca_save: ModuleType, resource_type: str, aborted: bool) -> None:
    calls: list[str] = []

    class Request:
        pass

    class Route:
        request = Request()

        def abort(self) -> None:
            calls.append("abort")

        def continue_(self) -> None:
            calls.append("continue")

    Route.request.resource_type = resource_type  # type: ignore[attr-defined]
    fca_save.skip_resource(Route())
    assert calls == ["abort" if aborted else "continue"]

"""Save FCA Handbook section pages with a headless browser, politely.

Usage (in the repo):
    uv run --with playwright playwright install --with-deps chromium   # once
    uv run --with playwright python scripts/fca_save.py OUT_DIR PATH ... [--list]

PATH is a section (disp2/disp2s8) or a whole chapter (conc5). Section slugs are
the site's own IDs, not section numbers: conc5/conc5s6 is CONC 5.2A. For a
chapter the script opens the chapter page and reads its live sections from the
provisions data the page itself loads (no extra request); if that is not seen,
from the section links on the rendered page. Then it saves each section.
--list prints the section paths and names without saving anything.

Runs under the FCA's written consent recorded in docs/SETUP_LOG.md (2026-11-04).
One page at a time, at least --delay seconds apart (default and minimum 3), with
ALTERAM_HTTP_CONTACT in the User-Agent. Images, fonts and media are not
downloaded, since only the text is needed. A section that is not found, fails
to load, renders empty or shows another section's rules is recorded in
OUT_DIR/report.json and skipped. The whole run stops, without retrying, on a
CAPTCHA or access check, a 403 or a 429.
A section already saved completely in OUT_DIR (its sidecar and every file it
lists, with matching sha256) is not requested again; report.json lists the
sections still missing per chapter.
Exit status: 0 all saved, 1 stopped or bad arguments, 2 something was skipped.

Per section it writes, named from the section number the page shows:
    CONC-5.2A.html   rendered HTML (page.content()), the format the parser reads
    CONC-5.2A.json   sidecar: URLs, title, time saved, dates shown, first rule
                     header, seconds until the rules appeared, sha256 of the HTML
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

BASE_URL = "https://handbook.fca.org.uk/handbook/"
PROVISIONS_API = "/Handbook/GetAllHandBookProvisionsSortedOrderByChapter/"
DELAY_SECONDS = 3.0
SKIPPED_RESOURCES = {"image", "font", "media"}
TIMEOUT_MS = 60_000
CONTACT_ENV = "ALTERAM_HTTP_CONTACT"
REPORT_NAME = "report.json"
SAVED_BY = "scripts/fca_save.py (headless Chromium via Playwright)"

CHAPTER_PATH = re.compile(r"^([a-z]+)(\d+[a-z]?)$")
SECTION_PATH = re.compile(r"^([a-z]+)(\d+[a-z]?)/\1\2s(\d+[a-z]?)$")
SECTION_NAME = re.compile(
    r"\b([A-Z]{2,}) (\d+[A-Z]?\.\d+[A-Z]?|\d+[A-Z]? Annex \d+[A-Z]*)(?![\w.])"
)
AS_OF = re.compile(r"\bas of (\d{2}/\d{2}/\d{4})")
LAST_UPDATED = re.compile(r"\bwas last updated on (\d{2}/\d{2}/\d{4})")
CAPTCHA_TEXT = re.compile(
    r"captcha|verify you are (a )?human|not a robot|unusual traffic|access denied",
    re.IGNORECASE,
)
NOT_FOUND_TEXT = re.compile(r"page not found|\b404\b|no longer exists", re.IGNORECASE)

# A page is ready once a rule header's status letter is rendered (the site's
# class name is spelled "provison-type").
RULES_READY_JS = "() => document.querySelector('.provison-type') !== null"
FIRST_HEADER_JS = """() => {
  const el = document.querySelector('.provison-type');
  return el && el.parentElement ? el.parentElement.innerText : null;
}"""
HREFS_JS = "els => els.map(e => e.getAttribute('href'))"


class StopError(Exception):
    """A condition that must stop the whole run: never retried."""


# --- paths -----------------------------------------------------------------


def _clean(path: str) -> str:
    return path.strip().strip("/").lower()


def check_target(path: str) -> str:
    """A cleaned chapter or section path; ValueError for anything else."""
    cleaned = _clean(path)
    if CHAPTER_PATH.match(cleaned) or SECTION_PATH.match(cleaned):
        return cleaned
    raise ValueError(
        f"Not a Handbook chapter or section path: {path!r} "
        "(expected e.g. conc5 or disp2/disp2s8)"
    )


def is_chapter_path(path: str) -> bool:
    return CHAPTER_PATH.match(_clean(path)) is not None


def chapter_of(path: str) -> str:
    """'conc5/conc5s6' -> 'conc5'; 'conc5' -> 'conc5'."""
    return check_target(path).split("/")[0]


def page_url(path: str) -> str:
    return BASE_URL + check_target(path)


def chapter_label(chapter: str) -> tuple[str, str]:
    """'conc5' -> ('CONC', '5'); 'conc2a' -> ('CONC', '2A')."""
    match = CHAPTER_PATH.match(_clean(chapter))
    if not match:
        raise ValueError(f"Not a Handbook chapter path: {chapter!r}")
    return match.group(1).upper(), match.group(2).upper()


def section_links(chapter: str, hrefs: Iterable[str | None]) -> list[str]:
    """Section paths of `chapter` among the page's link targets, in page order,
    without duplicates. Other chapters and non-section links are dropped."""
    chapter = _clean(chapter)
    wanted = re.compile(
        rf"^/handbook/({re.escape(chapter)}/{re.escape(chapter)}s\d+[a-z]?)/?$"
    )
    found: list[str] = []
    for href in hrefs:
        if not href:
            continue
        parts = urlsplit(href.strip())
        if parts.netloc and parts.netloc != "handbook.fca.org.uk":
            continue
        match = wanted.match(parts.path.lower())
        if match and match.group(1) not in found:
            found.append(match.group(1))
    return found


def sections_from_api(chapter: str, data: Any) -> list[tuple[str, str]]:
    """(section path, section name) pairs in the chapter's provisions data, in
    order of first appearance. Only IDs of this chapter count."""
    chapter = _clean(chapter)
    wanted = re.compile(rf"^{re.escape(chapter)}s\d+[a-z]?$")
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            sid = node.get("sectionId")
            if isinstance(sid, str) and wanted.match(sid.lower()):
                path = f"{chapter}/{sid.lower()}"
                name = " ".join(str(node.get("sectionName") or "").split())
                if not found.get(path):
                    found[path] = name
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return list(found.items())


def is_chapter_provisions_url(chapter: str, url: str) -> bool:
    """The chapter page's own provisions request (not a single section's)."""
    parts = urlsplit(url)
    return (
        parts.path.lower().endswith((PROVISIONS_API + _clean(chapter)).lower())
        and "sectionid=" not in parts.query.lower()
    )


# --- page facts -------------------------------------------------------------


def section_number(title: str) -> tuple[str, str] | None:
    """'FCA Handbook - CONC 5.2A Creditworthiness assessment' -> ('CONC', '5.2A');
    'FCA Handbook - DISP 1 Annex 3 Appropriate wording' -> ('DISP', '1 Annex 3')."""
    match = SECTION_NAME.search(title)
    return (match.group(1), match.group(2)) if match else None


def file_stem(book: str, number: str) -> str:
    """('CONC', '5.2A') -> 'CONC-5.2A'; ('DISP', '1 Annex 3') -> 'DISP-1-Annex-3'."""
    return f"{book}-{number}".replace(" ", "-")


def in_chapter(number: str, chapter: str) -> bool:
    """'5.2A' and '5 Annex 1' are in chapter '5'; '50.1' is not."""
    return number.startswith((f"{chapter}.", f"{chapter} Annex "))


def header_in_section(header: str, book: str, number: str) -> bool:
    """'CONC 5.2A.1 01/11/2018 R' is in CONC 5.2A; 'CONC 5.2.1 ...' is not."""
    return (
        re.match(rf"{re.escape(book)} {re.escape(number)}(?![\w])", header) is not None
    )


def shown_dates(text: str) -> dict[str, str | None]:
    """The page's 'as of DD/MM/YYYY' view date and 'was last updated on
    DD/MM/YYYY' date, as shown (DD/MM/YYYY). None where missing."""
    as_of, updated = AS_OF.search(text), LAST_UPDATED.search(text)
    return {
        "as_of": as_of.group(1) if as_of else None,
        "last_updated": updated.group(1) if updated else None,
    }


def header_text(raw: str | None) -> str | None:
    """'DISP 2.8.1\\n13/01/2018\\nR' -> 'DISP 2.8.1 13/01/2018 R'."""
    if raw is None:
        return None
    return " ".join(raw.split()) or None


def status_reason(status: int | None) -> str | None:
    """Why an HTTP status means the page can't be saved, or None."""
    if status is not None and status >= 400:
        return f"HTTP {status}"
    return None


def check_stop(status: int | None, text: str, retry_after: str | None = None) -> None:
    """Raise StopError for the conditions that end the whole run."""
    if status in (403, 429):
        wait = f" (Retry-After: {retry_after})" if retry_after else ""
        raise StopError(f"HTTP {status}: the site refused the request{wait}")
    if CAPTCHA_TEXT.search(text):
        raise StopError("the page shows a CAPTCHA or an access check")


def skip_reason(
    path: str, status: int | None, text: str, title: str, first_header: str | None
) -> str | None:
    """Why a section page is skipped (not saved), or None if it can be saved.
    The page must name a section of the path's chapter, and its first rule
    header must belong to that section. Call check_stop first."""
    if reason := status_reason(status):
        return reason
    if not text.strip():
        return "empty render: the page has no text"
    if first_header is None:
        if NOT_FOUND_TEXT.search(text):
            return "page not found"
        return f"no rule headers appeared within {TIMEOUT_MS // 1000} s"
    shown = section_number(title)
    book, chapter = chapter_label(chapter_of(path))
    if shown is None or shown[0] != book or not in_chapter(shown[1], chapter):
        return f"title {title!r} does not name a section of {book} {chapter}"
    if not header_in_section(first_header, *shown):
        return f"first rule header {first_header!r} is not in {shown[0]} {shown[1]}"
    return None


# --- files ------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_sidecar(
    url: str,
    saved_at: datetime,
    dates: Mapping[str, str | None],
    files: Mapping[str, bytes],
    *,
    final_url: str | None = None,
    title: str | None = None,
    seconds_to_rules: float | None = None,
    first_header: str | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "final_url": final_url,
        "title": title,
        "saved_at": saved_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dates_shown": dict(dates),
        "first_header": first_header,
        "seconds_to_rules": (
            None if seconds_to_rules is None else round(seconds_to_rules, 1)
        ),
        "files": {name: sha256(data) for name, data in sorted(files.items())},
        "saved_by": SAVED_BY,
    }


def to_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def completed_saves(out_dir: Path) -> dict[str, str]:
    """URL -> file stem of every section saved completely in out_dir: a sidecar
    written by this script whose listed files all exist with the recorded sha256.
    A section with a missing or changed file, or no sidecar, is not complete."""
    done: dict[str, str] = {}
    if not out_dir.is_dir():
        return done
    for path in sorted(out_dir.glob("*.json")):
        if path.name == REPORT_NAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        files = data.get("files") or {}
        if data.get("saved_by") != SAVED_BY or not data.get("url") or not files:
            continue
        if all(
            (out_dir / name).is_file()
            and sha256((out_dir / name).read_bytes()) == digest
            for name, digest in files.items()
        ):
            done[data["url"]] = path.stem
    return done


# --- report -----------------------------------------------------------------


NOT_REACHED = "not reached: the run stopped first"


@dataclass
class ChapterReport:
    """What happened to one chapter's sections in one run."""

    url: str | None = None  # the chapter page, if the chapter was discovered
    source: str | None = None  # "provisions data", "page links"; None if given
    found: list[dict[str, str]] | None = None  # None: sections were given
    error: str | None = None  # why discovery failed, or NOT_REACHED
    requested: list[str] = field(default_factory=list)  # queued for saving
    saved: list[dict[str, str]] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def missing(self) -> list[str] | None:
        """Sections queued but not saved in this or an earlier run: skipped, or
        never tried because the run stopped. None if the chapter's sections
        are unknown: discovery failed or was never reached."""
        if self.error is not None:
            return None
        have = {s["path"] for s in self.saved} | set(self.already_present)
        return [s for s in self.requested if s not in have]

    def as_dict(self) -> dict[str, Any]:
        missing = self.missing()
        return {
            "url": self.url,
            "discovered_from": self.source,
            "sections_found": self.found,
            "discovery_error": self.error,
            "saved": self.saved,
            "already_present": self.already_present,
            "skipped": self.skipped,
            "missing": missing,
            "counts": {
                "found": None if self.found is None else len(self.found),
                "saved": len(self.saved),
                "already_present": len(self.already_present),
                "skipped": len(self.skipped),
                "missing": None if missing is None else len(missing),
            },
        }


@dataclass
class Report:
    chapters: dict[str, ChapterReport] = field(default_factory=dict)
    stopped: str | None = None

    def chapter(self, name: str) -> ChapterReport:
        return self.chapters.setdefault(name, ChapterReport())

    def record(self, section: str, outcome: str, detail: str = "") -> None:
        """outcome: 'saved' (detail: file stem), 'already_present', or
        'skipped' (detail: reason)."""
        entry = self.chapter(chapter_of(section))
        if outcome == "saved":
            entry.saved.append({"path": section, "file": detail})
        elif outcome == "already_present":
            entry.already_present.append(section)
        elif outcome == "skipped":
            entry.skipped.append({"path": section, "reason": detail or "unknown"})
        else:
            raise ValueError(f"Unknown outcome: {outcome!r}")

    def problems(self) -> int:
        """Missing sections plus chapters whose discovery failed."""
        return sum(
            len(c.missing() or []) + (c.error is not None)
            for c in self.chapters.values()
        )


def merge_report(
    previous: Mapping[str, Any] | None, report: Report, now: datetime
) -> dict[str, Any]:
    """The report file's new content: chapters from this run replace the same
    chapters from earlier runs; other chapters are kept, and so is an earlier
    entry for a chapter this run never reached."""
    chapters = dict((previous or {}).get("chapters", {}))
    for name, entry in report.chapters.items():
        if entry.error == NOT_REACHED and name in chapters:
            continue
        chapters[name] = entry.as_dict()
    return {
        "updated_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stopped": report.stopped,
        "chapters": dict(sorted(chapters.items())),
    }


def write_report(out_dir: Path, report: Report) -> None:
    path = out_dir / REPORT_NAME
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    new = merge_report(previous, report, datetime.now(UTC))
    path.write_text(to_json(new), encoding="utf-8")


# --- environment ------------------------------------------------------------


def user_agent(package_version: str, contact: str) -> str:
    return f"alteram/{package_version} (+{contact})"


def get_contact(environ: Mapping[str, str], load_env: Callable[[], Any]) -> str:
    """ALTERAM_HTTP_CONTACT from the environment, else from .env (load_env), as
    the app does. Raises StopError if it is still empty."""
    contact = environ.get(CONTACT_ENV, "").strip()
    if not contact:
        load_env()
        contact = environ.get(CONTACT_ENV, "").strip()
    if not contact:
        raise StopError(
            f"{CONTACT_ENV} is not set. Put a contact (URL or email) in .env or the "
            "environment; the FCA should be able to reach whoever runs this."
        )
    return contact


def proxy_settings(environ: Mapping[str, str]) -> dict[str, str] | None:
    """Playwright's proxy option from HTTPS_PROXY (or https_proxy), with any
    user:password moved out of the URL, since Chromium won't read them from it.
    None if no proxy is set."""
    raw = environ.get("HTTPS_PROXY") or environ.get("https_proxy")
    if not raw:
        return None
    parts = urlsplit(raw)
    if not parts.hostname:
        raise ValueError("HTTPS_PROXY is set but has no host")
    port = f":{parts.port}" if parts.port else ""
    settings = {"server": f"{parts.scheme or 'http'}://{parts.hostname}{port}"}
    if parts.username:
        settings["username"] = unquote(parts.username)
        settings["password"] = unquote(parts.password or "")
    return settings


class Pacer:
    """Keeps at least `delay` seconds between the starts of page requests."""

    def __init__(
        self,
        delay: float = DELAY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.delay, self.clock, self.sleep = delay, clock, sleep
        self.last: float | None = None

    def wait(self) -> None:
        if self.last is not None:
            remaining = self.delay - (self.clock() - self.last)
            if remaining > 0:
                self.sleep(remaining)
        self.last = self.clock()


# --- browser ----------------------------------------------------------------


def first_line(exc: Exception) -> str:
    return (str(exc).strip().splitlines() or [type(exc).__name__])[0][:200]


def open_page(page: Any, url: str, pacer: Pacer) -> int | None:
    """Go to url (paced). Returns the HTTP status, None if unknown. Stops the
    run at once on a 403 or 429."""
    pacer.wait()
    response = page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    if response is None:
        return None
    if response.status in (403, 429):
        check_stop(response.status, "", response.headers.get("retry-after"))
    return response.status


def skip_resource(route: Any) -> None:
    """Abort requests for images, fonts and media; let the rest through."""
    if route.request.resource_type in SKIPPED_RESOURCES:
        route.abort()
    else:
        route.continue_()


def wait_for_rules(page: Any) -> float | None:
    """Seconds until the first rule header rendered, None if it never did."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    started = time.monotonic()
    try:
        page.wait_for_function(RULES_READY_JS, timeout=TIMEOUT_MS)
    except PlaywrightTimeout:
        return None
    return time.monotonic() - started


def body_text(page: Any) -> str:
    return page.inner_text("body") if page.query_selector("body") else ""


def discover(page: Any, chapter: str, pacer: Pacer, report: Report) -> list[str]:
    """Live section paths of a chapter; recorded in the report."""
    from playwright.sync_api import Error as PlaywrightError

    url = page_url(chapter)
    entry = report.chapter(chapter)
    entry.url, entry.error = url, None

    def is_provisions(response: Any) -> bool:
        return response.status == 200 and is_chapter_provisions_url(
            chapter, response.url
        )

    data: Any = None
    status: int | None = None
    try:
        with page.expect_response(is_provisions, timeout=TIMEOUT_MS) as info:
            status = open_page(page, url, pacer)
        data = info.value.json()
    except PlaywrightError as exc:  # includes the timeout: fall back to links
        if not page.url.startswith(url):
            entry.found, entry.error = [], f"navigation failed: {first_line(exc)}"
            return []
    check_stop(status, body_text(page))
    pairs = sections_from_api(chapter, data) if data is not None else []
    if pairs:
        entry.source = "provisions data"
        unique = dict(pairs)
    else:
        entry.source = "page links"
        wait_for_rules(page)
        hrefs = page.eval_on_selector_all("a[href]", HREFS_JS)
        unique = dict.fromkeys(section_links(chapter, hrefs), "")
    entry.found = [{"path": p, "name": n} for p, n in unique.items()]
    if not entry.found:
        entry.error = status_reason(status) or "no sections found on the page"
    return list(unique)


def save_section(
    page: Any, path: str, out_dir: Path, pacer: Pacer, owners: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """Save one section. Returns (file stem, None) if saved, else (None, reason).
    owners maps file stems of complete saves to their URLs: a complete save
    from another URL is never overwritten; leftovers of an interrupted run are."""
    from playwright.sync_api import Error as PlaywrightError

    url = page_url(path)
    try:
        status = open_page(page, url, pacer)
    except PlaywrightError as exc:
        return None, f"navigation failed: {first_line(exc)}"
    seconds = wait_for_rules(page) if status_reason(status) is None else None
    text = body_text(page)
    check_stop(status, text)
    title = page.title()
    header = header_text(page.evaluate(FIRST_HEADER_JS)) if seconds else None
    if reason := skip_reason(path, status, text, title, header):
        return None, reason
    shown = section_number(title)
    assert shown is not None  # skip_reason checked it
    stem = file_stem(*shown)
    if owners.get(stem, url) != url:
        return None, f"{stem}.html is already saved from {owners[stem]}"

    files = {f"{stem}.html": page.content().encode("utf-8")}
    sidecar = build_sidecar(
        url,
        datetime.now(UTC),
        shown_dates(text),
        files,
        final_url=page.url,
        title=title,
        seconds_to_rules=seconds,
        first_header=header,
    )
    for name, data in files.items():
        (out_dir / name).write_bytes(data)
    (out_dir / f"{stem}.json").write_text(to_json(sidecar), encoding="utf-8")
    print(f"saved {path} -> {stem}: {header} ({sidecar['seconds_to_rules']} s)")
    return stem, None


def collect_sections(
    page: Any, targets: list[str], pacer: Pacer, report: Report
) -> list[str]:
    for target in targets:  # until discovered, a chapter counts as not reached
        if is_chapter_path(target):
            report.chapter(target).error = NOT_REACHED
    sections: list[str] = []
    for target in targets:
        if is_chapter_path(target):
            found = discover(page, target, pacer, report)
            print(f"{target}: {len(found)} sections", file=sys.stderr)
            new = [s for s in found if s not in sections]
        else:
            new = [target] if target not in sections else []
        for section in new:
            report.chapter(chapter_of(section)).requested.append(section)
        sections += new
    return sections


def print_sections(sections: list[str], report: Report) -> None:
    names = {
        f["path"]: f["name"] for c in report.chapters.values() for f in c.found or []
    }
    for section in sections:
        print(f"{section}\t{names.get(section, '')}".rstrip())


def save_all(
    page: Any, sections: list[str], out_dir: Path, pacer: Pacer, report: Report
) -> None:
    """Save each section not already saved completely; skip the rest with no
    request."""
    out_dir.mkdir(parents=True, exist_ok=True)
    done = completed_saves(out_dir)
    owners = {stem: url for url, stem in done.items()}
    for section in sections:
        if page_url(section) in done:
            report.record(section, "already_present")
            continue
        stem, reason = save_section(page, section, out_dir, pacer, owners)
        if stem:
            report.record(section, "saved", stem)
        else:
            print(f"skipped {section}: {reason}", file=sys.stderr)
            report.record(section, "skipped", reason or "")


def run(
    out_dir: Path, targets: list[str], contact: str, list_only: bool, delay: float
) -> Report:
    from playwright.sync_api import sync_playwright

    report, pacer = Report(), Pacer(delay=max(delay, DELAY_SECONDS))
    ua = user_agent(version("alteram"), contact)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, proxy=proxy_settings(os.environ))
        context = browser.new_context(user_agent=ua, locale="en-GB")
        context.route("**/*", skip_resource)
        page = context.new_page()
        try:
            sections = collect_sections(page, targets, pacer, report)
            if list_only:
                print_sections(sections, report)
            else:
                save_all(page, sections, out_dir, pacer, report)
        except StopError as exc:
            report.stopped = f"{page.url}: {exc}"
            raise
        finally:
            browser.close()
            if not list_only and report.chapters:
                out_dir.mkdir(parents=True, exist_ok=True)
                write_report(out_dir, report)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path, help="folder to save into")
    parser.add_argument(
        "paths", nargs="+", help="chapters (conc5) or sections (disp2/disp2s8)"
    )
    parser.add_argument(
        "--list", action="store_true", help="print section paths, save nothing"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAY_SECONDS,
        help=f"seconds between pages (at least {DELAY_SECONDS:g})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        targets = [check_target(p) for p in args.paths]
        from dotenv import load_dotenv

        contact = get_contact(os.environ, load_dotenv)
        report = run(args.out_dir, targets, contact, args.list, args.delay)
    except (StopError, ValueError) as exc:
        print(f"fca_save: stopped: {exc}", file=sys.stderr)
        return 1
    return 2 if report.problems() else 0


if __name__ == "__main__":
    sys.exit(main())

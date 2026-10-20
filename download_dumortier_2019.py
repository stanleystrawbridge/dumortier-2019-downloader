#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stanley E. Strawbridge
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, version 3 of the License.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See LICENSE.
# A copy of the licence should accompany this program.
# Otherwise, see https://www.gnu.org/licenses/gpl-3.0.html.
"""Download the publicly linked data accompanying Dumortier et al., Science (2019).

Run without options to choose a destination, check the inventory, and confirm
before downloading. Use --inventory-only to inspect without downloading data.
All download logic is in this file. Python 3.10+ and requests are required.
There is no default destination and no machine-specific configuration.

    python download_dumortier_2019.py
    python download_dumortier_2019.py --inventory-only
    python download_dumortier_2019.py --refresh-inventory
    python download_dumortier_2019.py --destination "./data" --yes

Source: https://ressources.curie.fr/frackening/
Paper: https://doi.org/10.1126/science.aaw7709
Original team: https://institut-curie.org/team/maitre

Independent downloader, not an official Institut Curie tool. The software
licence does not relicense the downloaded data. See README.md and DATA_SOURCE.md.
"""
from __future__ import annotations

import argparse
import csv
import copy
import hashlib
import json
import io
import os
import posixpath
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urldefrag, urljoin, urlsplit, urlunsplit

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required. See README.md.")

try:
    import requests
except ImportError:
    raise SystemExit("Run the launcher, or install dependencies: python -m pip install -r requirements.txt")

VERSION = "0.2.0"
SCHEMA_VERSION = 1
SOURCE = "https://ressources.curie.fr/frackening/"
REQUEST_DELAY = 0.5  # One request at a time, with a pause between requests.
TIMEOUT = (20, 120)  # Connection and per-read timeout, in seconds.
ATTEMPTS = 4
CHUNK = 1024 * 1024
MAX_HTML = 10 * 1024 * 1024
META = "_download_metadata"
ASSETS = {".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".map"}
IMAGING = {".tif", ".tiff", ".czi", ".lsm", ".lif", ".nd2", ".ims",
           ".avi", ".mp4", ".mov", ".mkv", ".h5", ".hdf5", ".ndpi"}
SORT_QUERY = re.compile(r"(?:(?:C=[NMSD]|O=[AD]|F=[012]|V=[01])(?:[;&]|$))+$", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def human(size: int | None) -> str:
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{value:,.2f} {unit}"
        value /= 1024
    return str(size)


def integer(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def canonical(url: str) -> str:
    url = urldefrag(url)[0]
    p = urlsplit(url)
    query = "" if SORT_QUERY.fullmatch(p.query) else p.query
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", query, ""))


def within(url: str, source: str) -> bool:
    p, root = urlsplit(url), urlsplit(source)
    if p.username or p.password or p.scheme not in {"http", "https"} or p.netloc != root.netloc:
        return False
    if root.scheme == "https" and p.scheme != "https":
        return False
    # Decode before checking the boundary so encoded traversal is not followed.
    decoded = unquote(p.path)
    if "\\" in decoded or "\x00" in decoded:
        return False
    normalized = posixpath.normpath(decoded)
    boundary = posixpath.normpath(unquote(root.path))
    return normalized == boundary or normalized.startswith(boundary.rstrip("/") + "/")


def safe_component(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    reserved = re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", cleaned.split(".")[0], re.I)
    if not cleaned or cleaned in {".", ".."} or reserved:
        cleaned = "_" + cleaned.replace(".", "_")
    if cleaned != name or len(cleaned) > 150:
        cleaned = cleaned[:120] + "__" + hashlib.sha256(name.encode()).hexdigest()[:12]
    return cleaned


def local_name(url: str, source: str) -> str:
    path = unquote(urlsplit(url).path)
    base = unquote(urlsplit(source).path).rstrip("/") + "/"
    if not path.startswith(base):
        raise ValueError("A file URL is outside the source directory")
    parts = path[len(base):].split("/")
    if any(p in {".", ".."} for p in parts):
        raise ValueError("Unsafe path component")
    parts = [safe_component(p) for p in parts if p]
    if not parts:
        parts = ["download"]
    if urlsplit(url).query:
        leaf = Path(parts[-1])
        digest = hashlib.sha256(urlsplit(url).query.encode()).hexdigest()[:12]
        parts[-1] = leaf.stem + "__query_" + digest + leaf.suffix
    # Keep administrative filenames and temporary suffixes out of the source tree.
    if parts[0].casefold() in {META.casefold(), ".git", ".venv"} or parts[-1].lower().endswith(".part"):
        raise ValueError("Source filename conflicts with downloader bookkeeping")
    return "/".join(parts)


def assert_no_symlinks(path: Path, root: Path) -> None:
    """Reject pre-existing symlinks/junctions beneath the selected output root."""
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("Output would escape the selected destination") from exc
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise RuntimeError(f"Refusing a symlink or junction in the output tree: {current}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError("Output resolves outside the selected destination")


def target_path(destination: Path, entry: dict, source: str) -> Path:
    if entry.get("relative_path") != local_name(entry["url"], source):
        raise ValueError("Inventory path does not match its source URL")
    target = destination.joinpath(*entry["relative_path"].split("/"))
    assert_no_symlinks(target, destination)
    return target


def atomic_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Replace a metadata file using a unique temporary file in the same folder."""
    if path.is_symlink():
        raise RuntimeError(f"Refusing metadata symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding=encoding, newline="",
                                         dir=path.parent, prefix=".metadata-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, data: object) -> None:
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path.name}")
    return value


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(path, buffer.getvalue(), "utf-8-sig")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.base = ""
        self.scripts = 0
        self.forms = 0
        self.password = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "base" and a.get("href") and not self.base:
            self.base = a["href"] or ""
        if tag == "script":
            self.scripts += 1
        if tag == "form":
            self.forms += 1
        if tag == "input" and (a.get("type") or "").lower() == "password":
            self.password = True
        attribute = {"a": "href", "area": "href", "link": "href", "img": "src",
                     "video": "src", "audio": "src", "source": "src", "iframe": "src",
                     "object": "data", "script": "src", "embed": "src"}.get(tag)
        if attribute and a.get(attribute):
            self.links.append(a[attribute] or "")


class OutsideScope(RuntimeError):
    pass


class Client:
    def __init__(self, source: str, delay: float = REQUEST_DELAY) -> None:
        self.source = source
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Dumortier2019Downloader/0.2.0 (single-connection; static-links)",
            "Accept-Encoding": "identity",
        })

    def request(self, method: str, url: str, headers: dict | None = None) -> requests.Response:
        for _ in range(10):
            if not within(url, self.source):
                raise OutsideScope(f"Not followed (outside dataset prefix): {url}")
            response = None
            for attempt in range(ATTEMPTS):
                time.sleep(self.delay)
                try:
                    response = self.session.request(method, url, headers=headers,
                        timeout=TIMEOUT, stream=True, allow_redirects=False)
                except requests.RequestException:
                    if attempt + 1 == ATTEMPTS:
                        raise
                    time.sleep(2 ** attempt)
                    continue
                if response.status_code not in {429, 500, 502, 503, 504} or attempt + 1 == ATTEMPTS:
                    break
                wait = integer(response.headers.get("Retry-After"))
                response.close()
                time.sleep(min(wait if wait is not None else 2 ** attempt, 300))
            assert response is not None
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise RuntimeError("Redirect without a Location header")
                url = canonical(urljoin(url, location))
                continue
            return response
        raise RuntimeError(f"Too many redirects: {url}")

    def close(self) -> None:
        self.session.close()


def is_html(response: requests.Response) -> bool:
    mime = response.headers.get("Content-Type", "").lower().split(";")[0]
    return mime in {"text/html", "application/xhtml+xml"} or (
        not mime and (urlsplit(response.url).path.endswith("/") or
                      Path(urlsplit(response.url).path).suffix.lower() in {".html", ".htm"}))


def describe(response: requests.Response, source: str) -> dict:
    url = canonical(response.url)
    name = local_name(url, source)
    suffix = Path(urlsplit(url).path).suffix.lower()
    encoding = response.headers.get("Content-Encoding", "identity").lower()
    size = integer(response.headers.get("Content-Length")) if encoding in {"", "identity"} else None
    return {"url": url, "relative_path": name, "bytes": size,
            "content_type": response.headers.get("Content-Type", ""),
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "category": "website_asset" if suffix in ASSETS else "file",
            "imaging_extension": suffix in IMAGING}



# ---- Portable inventories and lightweight directory checks ------------------

FILE_FIELDS = ["relative_path", "url", "bytes", "content_type", "category",
               "imaging_extension", "etag", "last_modified"]


def page_links(parser: Links, resolved: str, source: str) -> tuple[list[str], list[str]]:
    inside, outside = set(), set()
    base = urljoin(resolved, parser.base) if parser.base else resolved
    for raw in parser.links:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        link = canonical(urljoin(base, raw.strip()))
        p, root = urlsplit(link), urlsplit(source)
        if p.scheme not in {"http", "https"}:
            continue
        if p.scheme == "http" and root.scheme == "https" and p.netloc == root.netloc:
            link = urlunsplit(("https", p.netloc, p.path, p.query, ""))
        if link == resolved:  # Ignore directory sort links pointing to this page.
            continue
        (inside if within(link, source) else outside).add(link)
    return sorted(inside), sorted(outside)


def fetch_page(client: Client, url: str, metadata: Path) -> dict:
    """Read a small HTML page, never an imaging body, and store its fingerprint."""
    with client.request("GET", url) as page:
        page.raise_for_status()
        if page.status_code != 200 or not is_html(page):
            raise RuntimeError("Expected a directory/HTML page, not a data file")
        resolved = canonical(page.url)
        content = bytearray()
        for block in page.iter_content(65536):
            content.extend(block)
            if len(content) > MAX_HTML:
                raise RuntimeError("HTML page exceeds the 10 MiB safety limit")
        parser = Links()
        parser.feed(bytes(content).decode(page.encoding or "utf-8", errors="replace"))
        if parser.password:
            raise RuntimeError("A password form was returned; browser login is not supported")
        inside, outside = page_links(parser, resolved, client.source)
        result = {"url": resolved, "in_scope_links": inside,
                  "outside_scope_links": outside,
                  "html_sha256": hashlib.sha256(content).hexdigest(),
                  "etag": page.headers.get("ETag", ""),
                  "last_modified": page.headers.get("Last-Modified", ""),
                  "scripts": parser.scripts, "forms": parser.forms}
    snapshots = metadata / "pages"
    assert_no_symlinks(snapshots, metadata.parent)
    snapshots.mkdir(parents=True, exist_ok=True)
    path = snapshots / (hashlib.sha256(resolved.encode()).hexdigest()[:20] + ".html")
    assert_no_symlinks(path, metadata.parent)
    # Snapshot HTML is metadata only. It is never executed by this program.
    with path.open("wb") as handle:
        handle.write(content)
    return result


def validate_inventory(snapshot: dict, source: str) -> dict:
    """Treat a downloaded or locally edited manifest as untrusted input."""
    if snapshot.get("schema_version") != SCHEMA_VERSION or snapshot.get("source") != source:
        raise ValueError("Inventory schema/source mismatch. Use --refresh-inventory.")
    rows, pages = snapshot.get("files"), snapshot.get("pages")
    if not isinstance(rows, list) or not isinstance(pages, list) or not rows or not pages:
        raise ValueError("Inventory must contain nonempty file and page lists")
    urls, paths, component_spellings = set(), set(), {}
    for entry in rows:
        if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
            raise ValueError("Invalid inventory file record")
        url = entry["url"]
        if url != canonical(url) or not within(url, source):
            raise ValueError("Unsafe or noncanonical URL in inventory")
        relative = local_name(url, source)
        if entry.get("relative_path") != relative or url in urls:
            raise ValueError("Duplicate URL or invalid local path in inventory")
        size = entry.get("bytes")
        if size is not None and (type(size) is not int or size < 0):
            raise ValueError("Invalid file size in inventory")
        for key in ("etag", "last_modified", "content_type"):
            if not isinstance(entry.get(key, ""), str):
                raise ValueError(f"Invalid {key} in inventory")
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in paths:
            raise ValueError("File paths collide on a case-insensitive filesystem")
        parts = relative.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            folded = unicodedata.normalize("NFC", prefix).casefold()
            if folded in component_spellings and component_spellings[folded] != prefix:
                raise ValueError("Directory/file names differ only by case or Unicode normalization")
            component_spellings[folded] = prefix
        paths.add(key)
        urls.add(url)
    for path in paths:
        if any(str(parent) in paths for parent in PurePosixPath(path).parents if str(parent) != "."):
            raise ValueError("A file path also acts as a directory")
    page_urls = set()
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("url"), str):
            raise ValueError("Invalid page record")
        url = page["url"]
        if not within(url, source) or canonical(url) != url or url in page_urls or url in urls:
            raise ValueError("Unsafe, duplicate, or conflicting page URL")
        links = page.get("in_scope_links")
        if not isinstance(links, list) or any(not isinstance(x, str) or not within(x, source) for x in links):
            raise ValueError("Unsafe page links in inventory")
        digest = page.get("html_sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("Invalid page checksum")
        page_urls.add(url)
    if source not in page_urls:
        raise ValueError("Inventory is missing the root listing")
    if any(link not in urls | page_urls for page in pages for link in page["in_scope_links"]):
        raise ValueError("Inventory has in-scope links without file/page records")
    if len(rows) + len(pages) > 50000:
        raise ValueError("Inventory exceeds the 50,000 URL safety limit")
    return snapshot


def report_for(snapshot: dict) -> dict:
    rows, pages = snapshot["files"], snapshot["pages"]
    return {"source": snapshot["source"], "scanned_at_utc": snapshot["scanned_at_utc"],
            "checked_at_utc": snapshot.get("checked_at_utc"), "files": len(rows),
            "html_pages": len(pages), "known_bytes": sum(r["bytes"] or 0 for r in rows),
            "unknown_sizes": sum(r["bytes"] is None for r in rows),
            "outside_scope_links": len(snapshot.get("outside_scope", [])),
            "discovery_errors": 0,
            "imaging_extensions": sum(bool(r.get("imaging_extension")) for r in rows),
            "completeness": "Static-link inventory, not proof of repository completeness."}


def save_inventory(snapshot: dict, metadata: Path) -> None:
    write_json(metadata / "inventory_cache.json", snapshot)
    write_csv(metadata / "inventory.csv", snapshot["files"], FILE_FIELDS)
    write_json(metadata / "scan_summary.json", report_for(snapshot))
    write_csv(metadata / "outside_scope.csv", snapshot.get("outside_scope", []), ["url", "linked_from"])
    write_csv(metadata / "discovery_errors.csv", [], ["url", "error"])
    page_rows = []
    for page in snapshot["pages"]:
        key = hashlib.sha256(page["url"].encode()).hexdigest()[:20]
        page_rows.append({"url": page["url"], "snapshot": f"pages/{key}.html",
                          "links": len(page["in_scope_links"]),
                          "scripts": page.get("scripts", 0), "forms": page.get("forms", 0)})
    write_csv(metadata / "pages.csv", page_rows, ["url", "snapshot", "links", "scripts", "forms"])


def infer_page_records(page_urls: list[str], file_urls: list[str], source: str) -> list[dict]:
    """Bootstrap a directory-link baseline when original HTML bytes are absent."""
    all_urls = set(page_urls + file_urls)
    pages = []
    for url in page_urls:
        children = [u for u in all_urls if u != url and u.rstrip("/").rsplit("/", 1)[0] + "/" == url]
        parent = url.rstrip("/").rsplit("/", 1)[0] + "/"
        if within(parent, source) and parent != url:
            children.append(parent)
        pages.append({"url": url, "in_scope_links": sorted(set(children)),
                      "outside_scope_links": [], "html_sha256": None,
                      "etag": "", "last_modified": "", "scripts": 0, "forms": 0})
    return pages


def import_legacy_inventory(metadata: Path, source: str) -> dict | None:
    """Reuse metadata from the earlier inventory-only downloader where present."""
    needed = [metadata / x for x in ("inventory.csv", "pages.csv", "scan_summary.json")]
    if not all(p.exists() for p in needed):
        return None
    summary = read_json(needed[2])
    if summary.get("source") != source or summary.get("discovery_errors") or summary.get("url_limit_reached"):
        return None
    with needed[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["bytes"] = int(row["bytes"]) if row.get("bytes") else None
        row["imaging_extension"] = row.get("imaging_extension", "").lower() == "true"
    with needed[1].open(encoding="utf-8-sig", newline="") as handle:
        page_urls = [p["url"] for p in csv.DictReader(handle)]
    pages = infer_page_records(page_urls, [r["url"] for r in rows], source)
    for page in pages:
        path = metadata / "pages" / (hashlib.sha256(page["url"].encode()).hexdigest()[:20] + ".html")
        assert_no_symlinks(path, metadata.parent)
        if path.exists() and path.stat().st_size <= MAX_HTML:
            content = path.read_bytes()
            parser = Links()
            parser.feed(content.decode("utf-8", errors="replace"))
            page["in_scope_links"], page["outside_scope_links"] = page_links(parser, page["url"], source)
            page["html_sha256"] = hashlib.sha256(content).hexdigest()
            page["scripts"], page["forms"] = parser.scripts, parser.forms
    outside = metadata / "outside_scope.csv"
    outside_rows = []
    if outside.exists():
        with outside.open(encoding="utf-8-sig", newline="") as handle:
            outside_rows = list(csv.DictReader(handle))
    snapshot = {"schema_version": SCHEMA_VERSION, "source": source,
                "scanned_at_utc": summary["scanned_at_utc"], "checked_at_utc": None,
                "files": rows, "pages": pages, "outside_scope": outside_rows,
                "provenance": "Imported earlier downloader metadata; missing HTML hashes use inferred link sets."}
    return validate_inventory(snapshot, source)


def discover(client: Client, metadata: Path, max_urls: int) -> dict:
    """Full static-link crawl, only when needed or explicitly requested."""
    print("Building a fresh inventory. Data files are inspected by headers only.", flush=True)
    queue, scheduled, visited = deque([client.source]), {client.source}, set()
    entries, pages, outside, errors = {}, {}, {}, []
    while queue:
        url = queue.popleft()
        if url in visited:
            continue
        if len(visited) >= max_urls:
            errors.append({"url": url, "error": "URL safety limit reached"})
            break
        visited.add(url)
        try:
            if urlsplit(url).path.endswith("/"):
                page = fetch_page(client, url, metadata)
            else:
                response = client.request("HEAD", url)
                if response.status_code in {400, 403, 405, 501}:
                    response.close()
                    response = client.request("GET", url)
                with response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise RuntimeError(f"Unexpected inventory HTTP status {response.status_code}")
                    if not is_html(response):
                        entry = describe(response, client.source)
                        entries[entry["url"]] = entry
                        print(f"  FILE {entry['relative_path']} [{human(entry['bytes'])}]", flush=True)
                        continue
                    resolved = canonical(response.url)
                page = fetch_page(client, resolved, metadata)
            pages[page["url"]] = page
            visited.add(page["url"])
            print(f"  PAGE {page['url']}", flush=True)
            for link in page["outside_scope_links"]:
                outside.setdefault(link, page["url"])
            for link in page["in_scope_links"]:
                if link not in scheduled:
                    if len(scheduled) >= max_urls:
                        raise RuntimeError("URL safety limit reached")
                    scheduled.add(link)
                    queue.append(link)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append({"url": url, "error": str(exc)})
            print(f"  NOT READ {url}: {exc}", flush=True)
    write_csv(metadata / "discovery_errors.csv", errors, ["url", "error"])
    if errors:
        raise RuntimeError("Discovery is incomplete. Review discovery_errors.csv. The previous cache is retained.")
    snapshot = {"schema_version": SCHEMA_VERSION, "source": client.source,
                "scanned_at_utc": now(), "checked_at_utc": now(),
                "files": sorted(entries.values(), key=lambda r: r["relative_path"].casefold()),
                "pages": sorted(pages.values(), key=lambda p: p["url"]),
                "outside_scope": [{"url": u, "linked_from": p} for u, p in sorted(outside.items())],
                "provenance": "Full HTTP static-link crawl and file-header inspection."}
    return validate_inventory(snapshot, client.source)


def check_pages(client: Client, snapshot: dict, metadata: Path) -> tuple[bool, dict]:
    """Compare all known nested listings without issuing file-header requests."""
    updated = copy.deepcopy(snapshot)
    checked = []
    bootstrap = any(not p.get("html_sha256") for p in snapshot["pages"])
    print(f"Checking {len(snapshot['pages'])} directory pages; reusing cached file headers.", flush=True)
    if bootstrap:
        print("First check uses recorded link sets and establishes local HTML fingerprints.")
    for index, old_page in enumerate(snapshot["pages"], 1):
        print(f"  Listing {index}/{len(snapshot['pages'])}", flush=True)
        try:
            fresh = fetch_page(client, old_page["url"], metadata)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in {404, 410}:
                print("A recorded listing was removed. A full inventory refresh is required.")
                return True, updated
            raise RuntimeError("Could not check all listings. No claim of 'unchanged' is made. Retry later.") from exc
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            raise RuntimeError("Could not check all listings. Previous inventory retained; retry later.") from exc
        changed = (fresh["url"] != old_page["url"] or
                   set(fresh["in_scope_links"]) != set(old_page["in_scope_links"]) or
                   bool(old_page.get("html_sha256") and fresh["html_sha256"] != old_page["html_sha256"]))
        if changed:
            print("A directory listing changed. Refreshing the full inventory.")
            return True, updated
        checked.append(fresh)
    updated["pages"] = checked
    updated["checked_at_utc"] = now()
    updated["outside_scope"] = [{"url": u, "linked_from": p["url"]} for p in checked
                               for u in p["outside_scope_links"]]
    print("No link changes detected." if bootstrap else "No directory-listing changes detected.")
    print("This does not independently verify the contents of every remote file.")
    return False, updated


def obtain_inventory(client: Client, metadata: Path, reference: Path,
                     refresh: bool = False, use_cached: bool = False, max_urls: int = 50000) -> dict:
    if refresh:
        snapshot = discover(client, metadata, max_urls)
    else:
        local = metadata / "inventory_cache.json"
        if local.exists():
            snapshot = validate_inventory(read_json(local), client.source)
            print("Using the saved inventory from the selected destination.")
        else:
            snapshot = import_legacy_inventory(metadata, client.source)
            if snapshot is not None:
                print("Reusing the inventory from the earlier downloader.")
            elif reference.exists():
                candidate = read_json(reference)
                snapshot = validate_inventory(candidate, client.source) if candidate.get("source") == client.source else None
                if snapshot is not None:
                    print("Using the bundled reference inventory.")
        if snapshot is None:
            if use_cached:
                raise RuntimeError("No suitable cached inventory exists. Run without --use-cached-inventory.")
            snapshot = discover(client, metadata, max_urls)
        elif use_cached:
            print("WARNING: directory change checking was explicitly disabled for this run.")
        else:
            changed, checked = check_pages(client, snapshot, metadata)
            if changed:
                fresh = discover(client, metadata, max_urls)
                removed = {r["url"] for r in snapshot["files"]} - {r["url"] for r in fresh["files"]}
                if removed:
                    print(f"{len(removed)} URLs disappeared from the inventory. Local copies will not be deleted.")
                snapshot = fresh
            else:
                snapshot = checked
    save_inventory(snapshot, metadata)
    return snapshot


# ---- Resumable transfers ----------------------------------------------------

def publish_partial(partial: Path, target: Path) -> None:
    """Publish a complete file without replacing a pre-existing destination.

    Hard links give no-replace publication on normal POSIX filesystems. Windows
    rename already refuses an existing target. For other filesystems use an
    exclusive copy, leaving the completed partial available until it finishes.
    """
    if target.exists() or target.is_symlink():
        raise RuntimeError(f"Target already exists; left untouched: {target}")
    if os.name == "nt":
        partial.rename(target)
        return
    try:
        os.link(partial, target)
    except FileExistsError:
        raise RuntimeError(f"Target already exists; left untouched: {target}")
    except OSError as exc:
        import errno
        if exc.errno not in {errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS}:
            raise
        # Rare fallback for filesystems that do not support hard links.
        created = False
        try:
            with target.open("xb") as out:
                created = True
                with partial.open("rb") as src:
                    shutil.copyfileobj(src, out, CHUNK)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise
        partial.unlink()
    else:
        partial.unlink()


def validator(entry: dict) -> str:
    tag = entry.get("etag", "")
    return tag if tag and not tag.startswith("W/") else entry.get("last_modified", "")


def compatible(saved: dict, entry: dict) -> bool:
    if saved.get("url") != entry["url"]:
        return False
    for key in ("etag", "last_modified"):
        if entry.get(key) and saved.get(key) != entry[key]:
            return False
    return entry["bytes"] is None or saved.get("bytes") == entry["bytes"]


def download_one(client: Client, entry: dict, destination: Path, state: dict,
                 state_path: Path, verify: bool = False) -> str:
    target = target_path(destination, entry, client.source)
    target.parent.mkdir(parents=True, exist_ok=True)
    saved = state.get(entry["url"], {})
    if target.exists():
        if not (saved.get("status") == "complete" and compatible(saved, entry)
                and saved.get("relative_path") == entry["relative_path"]
                and target.stat().st_size == saved.get("local_bytes")):
            raise RuntimeError(f"Existing file not verified against this inventory; left untouched: {target}")
        if verify:
            hasher = hashlib.sha256()
            with target.open("rb") as handle:
                for block in iter(lambda: handle.read(CHUNK), b""):
                    hasher.update(block)
            if hasher.hexdigest() != saved.get("sha256"):
                raise RuntimeError(f"Local SHA-256 mismatch; file left untouched: {target}")
        return "skipped"
    partial = Path(str(target) + ".part")
    assert_no_symlinks(partial, destination)
    token = hashlib.sha256(entry["url"].encode()).hexdigest()
    partial_meta = destination / META / "partial" / f"{token}.json"
    assert_no_symlinks(partial_meta, destination)
    partial_meta.parent.mkdir(parents=True, exist_ok=True)
    if partial.exists() and not partial_meta.exists():
        raise RuntimeError(f"Unrecognised partial file left untouched: {partial}")
    # If the previous run stopped after hashing but before the final rename,
    # verify and publish that completed partial without another network transfer.
    if (partial.exists() and saved.get("status") == "complete" and
            compatible(saved, entry) and saved.get("relative_path") == entry["relative_path"] and
            partial.stat().st_size == saved.get("local_bytes") and
            hash_file(partial) == saved.get("sha256")):
        publish_partial(partial, target)
        partial_meta.unlink(missing_ok=True)
        return "downloaded"
    for attempt in range(ATTEMPTS):
        try:
            prior = read_json(partial_meta)
            if partial.exists() and (prior.get("url") != entry["url"] or prior.get("relative_path") != entry["relative_path"]):
                raise RuntimeError("Partial file metadata does not identify this file; left untouched")
            offset = partial.stat().st_size if partial.exists() else 0
            # Without a validator, restarting is safer than joining different versions.
            if offset and (not compatible(prior, entry) or not validator(prior)):
                offset = 0
            headers = {"Range": f"bytes={offset}-", "If-Range": validator(prior)} if offset else {}
            with client.request("GET", entry["url"], headers=headers) as response:
                if response.status_code == 416 and offset:
                    partial.unlink()
                    continue
                response.raise_for_status()
                if canonical(response.url) != entry["url"]:
                    raise RuntimeError("File URL changed since inventory; run with --refresh-inventory")
                if is_html(response):
                    raise RuntimeError("Server returned HTML rather than the inventoried file")
                if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                    raise RuntimeError("Server ignored identity encoding; byte-safe resume is not possible")
                current = describe(response, client.source)
                for key in ("etag", "last_modified"):
                    if entry.get(key) and current.get(key) != entry[key]:
                        raise RuntimeError("Remote validator changed since inventory; run with --refresh-inventory")
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or int(match[1]) != offset or int(match[2]) != int(match[3]) - 1:
                        raise RuntimeError("Unexpected partial-response byte range")
                    expected = int(match[3])
                    length = integer(response.headers.get("Content-Length"))
                    if length is not None and length != expected - offset:
                        raise RuntimeError("Partial response length does not match Content-Range")
                elif response.status_code == 200:
                    # A server may ignore Range. Never append a full response to a partial.
                    offset = 0
                    expected = integer(response.headers.get("Content-Length"))
                else:
                    raise RuntimeError(f"Unexpected download status {response.status_code}")
                if entry["bytes"] is not None and expected is not None and expected != entry["bytes"]:
                    raise RuntimeError("Remote size changed since inventory; run with --refresh-inventory")
                if expected is None:
                    expected = entry["bytes"]
                hasher = hashlib.sha256()
                if offset:
                    with partial.open("rb") as handle:
                        for block in iter(lambda: handle.read(CHUNK), b""):
                            hasher.update(block)
                partial_record = dict(current)
                partial_record["bytes"] = expected
                downloaded = offset
                last_update = time.monotonic()
                # Truncate before publishing fresh resume metadata, preventing old/new mixing.
                with partial.open("ab" if offset else "wb") as handle:
                    write_json(partial_meta, partial_record)
                    for block in response.iter_content(CHUNK):
                        if not block:
                            continue
                        if expected is not None and downloaded + len(block) > expected:
                            raise RuntimeError("Server sent more bytes than expected; partial retained")
                        handle.write(block)
                        hasher.update(block)
                        downloaded += len(block)
                        if time.monotonic() - last_update >= 5:
                            percent = f" ({100 * downloaded / expected:.1f}%)" if expected else ""
                            print(f"    {human(downloaded)} / {human(expected)}{percent}", flush=True)
                            last_update = time.monotonic()
                    handle.flush()
                    os.fsync(handle.fileno())
                if expected is not None and downloaded != expected:
                    raise requests.ConnectionError(f"Incomplete transfer: {downloaded} / {expected} bytes")
                # Persist the completion record before rename, allowing recovery after interruption.
                record = dict(partial_record, local_bytes=downloaded, status="complete",
                              sha256=hasher.hexdigest(), completed_at_utc=now())
                state[entry["url"]] = record
                write_json(state_path, state)
                if target.exists():
                    raise RuntimeError("Target appeared during download; not overwriting it")
                publish_partial(partial, target)
                partial_meta.unlink(missing_ok=True)
                return "downloaded"
        except requests.RequestException:
            if attempt + 1 == ATTEMPTS:
                raise
            print(f"    Connection problem. Retrying ({attempt + 2}/{ATTEMPTS})...")
            time.sleep(2 ** attempt)
    raise RuntimeError("Could not complete the transfer after repeated range errors")


def prepare_destination(value: str) -> Path:
    """Validate a user-supplied directory and test that a small file can be written."""
    value = value.strip()
    # A copied path may include surrounding quotes, especially on Windows.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        raise ValueError("Enter a destination folder. There is no default location.")
    if any(ord(character) < 32 for character in value):
        raise ValueError("The destination contains an invalid control character.")

    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        raise ValueError("Enter a local or mounted folder path, not a URL.")
    value = os.path.expandvars(value)
    if not value.strip():
        raise ValueError("The expanded destination is empty. There is no default location.")
    # Do not turn a Windows drive/UNC path into a misleading POSIX directory.
    if os.name != "nt" and (re.match(r"^[A-Za-z]:", value) or value.startswith("\\\\")):
        raise ValueError("That is a Windows path. Use a path valid on this computer.")
    destination = Path(value).expanduser()
    if os.name == "nt":
        if destination.drive and not destination.root:
            raise ValueError("Use a full drive path, not a drive-relative path such as D:data.")
        if destination.anchor and not Path(destination.anchor).exists():
            raise ValueError(
                f"Drive or share not accessible: {destination.anchor}. Connect it first."
            )

    if str(destination) == destination.anchor and destination.anchor:
        raise ValueError("Choose a dataset subfolder rather than a drive/filesystem root.")
    destination = destination.resolve()
    if destination == Path(destination.anchor):
        raise ValueError("Choose a dataset subfolder rather than a drive/filesystem root.")
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"The destination is a file, not a folder: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    # A real write test is more useful than checking permission flags on a share.
    # This temporary file is removed on close. It does not alter existing data.
    with tempfile.TemporaryFile(prefix=".downloader-write-test-", dir=destination) as probe:
        probe.write(b"write test")
        probe.flush()
    return destination


def choose_destination(value: str | None) -> Path:
    """Use --destination when provided; otherwise request it interactively."""
    if value is not None:
        return prepare_destination(value)
    print("Choose a folder for the dataset and its download metadata.")
    print("To continue a previous download, choose the same folder as before.")
    while True:
        try:
            value = input("Destination folder: ")
        except EOFError as exc:
            raise ValueError(
                'No destination received. For unattended runs, supply --destination "PATH".'
            ) from exc
        try:
            return prepare_destination(value)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Invalid destination: {exc}")
            print("Enter another folder, or press Ctrl+C to cancel.")



def preflight(rows: list[dict], destination: Path, state: dict, source: str) -> tuple[int, int]:
    """Estimate required free space conservatively and identify existing conflicts."""
    outstanding, unknown = 0, 0
    conflicts = []
    for row in rows:
        target = target_path(destination, row, source)
        if target.exists():
            saved = state.get(row["url"], {})
            if not (target.is_file() and saved.get("status") == "complete" and
                    compatible(saved, row) and saved.get("relative_path") == row["relative_path"] and
                    target.stat().st_size == saved.get("local_bytes")):
                conflicts.append(row["relative_path"])
            continue
        partial = Path(str(target) + ".part")
        assert_no_symlinks(partial, destination)
        available = 0
        if partial.exists():
            token = hashlib.sha256(row["url"].encode()).hexdigest()
            meta_path = destination / META / "partial" / f"{token}.json"
            assert_no_symlinks(meta_path, destination)
            prior = read_json(meta_path)
            if prior.get("url") != row["url"] or prior.get("relative_path") != row["relative_path"]:
                conflicts.append(row["relative_path"] + ".part")
                continue
            if compatible(prior, row) and validator(prior):
                available = partial.stat().st_size
        if row["bytes"] is None:
            unknown += 1
        else:
            outstanding += max(0, row["bytes"] - available)
    if conflicts:
        preview = "\n  ".join(conflicts[:10])
        raise RuntimeError(f"Existing files cannot be matched to this inventory; nothing will be overwritten.\n  {preview}\n"
                           "Keep those files and choose a new destination, or resolve the conflict before retrying.")
    return outstanding, unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inventory-only", action="store_true", help="Check/build inventory, without downloading data")
    mode.add_argument("--download", action="store_true", help="Offer to download (the default; retained for compatibility)")
    parser.add_argument("--destination", metavar="PATH", help="Output folder; otherwise ask at startup. No default path.")
    parser.add_argument("--yes", action="store_true", help="Skip the download confirmation; requires --destination")
    cache = parser.add_mutually_exclusive_group()
    cache.add_argument("--refresh-inventory", action="store_true", help="Force full discovery and file-header inspection")
    cache.add_argument("--use-cached-inventory", action="store_true", help="Explicitly skip the directory change check")
    parser.add_argument("--verify", action="store_true", help="Rehash completed local files before skipping them")
    parser.add_argument("--source", default=SOURCE, help="Advanced: alternative static directory URL ending in /")
    parser.add_argument("--max-urls", type=int, default=50000, help="Full scan URL safety limit (maximum 50,000)")
    args = parser.parse_args(argv)
    if not 1 <= args.max_urls <= 50000:
        parser.error("--max-urls must be between 1 and 50,000")
    if args.yes and not args.destination:
        parser.error("--yes requires --destination")
    if args.inventory_only and args.verify:
        parser.error("--verify checks completed downloads; do not combine it with --inventory-only")
    source = canonical(args.source)
    p = urlsplit(source)
    if (p.scheme not in {"http", "https"} or not p.netloc or p.username or p.password or
            not source.endswith("/") or p.query):
        parser.error("--source must be a public HTTP(S) directory URL ending in /, without credentials or query")
    destination = choose_destination(args.destination)
    metadata = destination / META
    assert_no_symlinks(metadata, destination)
    metadata.mkdir(exist_ok=True)
    # One process per destination, also compatible with the original script's lock.
    lock = metadata / "download.lock"
    assert_no_symlinks(lock, destination)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another run may be active in this destination. Close it first. "
                           "After a crash, remove _download_metadata/download.lock only after confirming no run is active.")
    client = None
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(f"PID {os.getpid()}\nStarted {now()}\n")
        for folder in (metadata / "pages", metadata / "partial"):
            assert_no_symlinks(folder, destination)
        print(f"\nDumortier 2019 downloader {VERSION}\nSource: {source}\nDestination: {destination}\n", flush=True)
        print("Copyright (C) 2026 Stanley E. Strawbridge. GPL-3.0-only; no warranty.")
        print("Redistribution/modification permitted under GNU GPL version 3. See LICENSE.\n")
        client = Client(source)
        reference = Path(__file__).resolve().with_name("reference_inventory.json")
        snapshot = obtain_inventory(client, metadata, reference, args.refresh_inventory,
                                    args.use_cached_inventory, args.max_urls)
        rows = snapshot["files"]
        report = report_for(snapshot)
        print(f"\nInventory: {len(rows)} files, {human(report['known_bytes'])} in known sizes.")
        if report["unknown_sizes"]:
            print(f"WARNING: {report['unknown_sizes']} file sizes are unknown.")
        outside = snapshot.get("outside_scope", [])
        if outside:
            print(f"{len(outside)} outside-scope links reported in _download_metadata/outside_scope.csv.")
        if any(p.get("scripts") or p.get("forms") for p in snapshot["pages"]):
            print("WARNING: some pages contain scripts/forms; browser-only downloads may not be discovered.")
        print("Only publicly linked files beneath the selected source directory are included.")
        if args.inventory_only:
            print("Inventory-only run complete. No data files downloaded.")
            return 0
        state_path = metadata / "download_state.json"
        state = read_json(state_path)
        if any(not isinstance(record, dict) for record in state.values()):
            raise ValueError("Invalid download_state.json. Retain it and resolve the metadata error before retrying.")
        outstanding, unknown = preflight(rows, destination, state, source)
        free = shutil.disk_usage(destination).free
        print(f"Known remaining data: {human(outstanding)}; reported free space: {human(free)}.")
        reserve = 1024**3 if outstanding or unknown else 0
        if outstanding + reserve > free:
            raise RuntimeError("Insufficient reported free space for known remaining data plus a 1 GiB reserve.")
        if unknown:
            print("Space required by unknown-size files is additional; a full space guarantee is not possible.")
        print("Downloaded archives and shortcuts are saved, never automatically opened or extracted.")
        if not args.yes:
            try:
                answer = input("Download/continue in this destination? [y/N]: ").strip().lower()
            except EOFError:
                raise ValueError("Confirmation needed. For unattended runs, provide --destination and --yes.")
            if answer not in {"y", "yes"}:
                print("Cancelled. Inventory retained; no data files downloaded.")
                return 0
        failures, counts = [], {"downloaded": 0, "skipped": 0}
        started = now()
        write_csv(metadata / "download_errors.csv", [], ["url", "error"])
        try:
            for index, row in enumerate(rows, 1):
                print(f"[{index}/{len(rows)}] {row['relative_path']} ({human(row['bytes'])})", flush=True)
                try:
                    result = download_one(client, row, destination, state, state_path, args.verify)
                    counts[result] += 1
                    print(f"    {result}", flush=True)
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    failures.append({"url": row["url"], "error": str(exc)})
                    print(f"    FAILED: {exc}", flush=True)
                    write_csv(metadata / "download_errors.csv", failures, ["url", "error"])
                # Filesystem failures intentionally stop the run rather than filling the drive.
        finally:
            write_csv(metadata / "checksums.csv", list(state.values()),
                      ["relative_path", "url", "local_bytes", "sha256", "etag", "last_modified", "completed_at_utc"])
        write_csv(metadata / "download_errors.csv", failures, ["url", "error"])
        write_json(metadata / "download_summary.json", {"source": source, "version": VERSION,
                   "started_at_utc": started, "finished_at_utc": now(), **counts,
                   "failed": len(failures), "inventory_files": len(rows), "verify": args.verify})
        print(f"\nDownloaded {counts['downloaded']}; skipped {counts['skipped']}; failed {len(failures)}.")
        print("Retain _download_metadata with the data. Checksums are local records, not author-supplied digests.")
        if failures:
            print("Review download_errors.csv. Rerun in the same destination to retry failed transfers.")
        return 2 if failures else 0
    finally:
        if client is not None:
            client.close()
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Partial files are retained. Run again with the same destination to continue.")
        sys.exit(130)
    except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

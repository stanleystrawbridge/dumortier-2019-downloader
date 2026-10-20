# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stanley E. Strawbridge
"""Local tests only. No requests to Institut Curie and no imaging downloads."""
from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import html
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("downloader", ROOT / "download_dumortier_2019.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.respond(False)

    def do_GET(self):
        self.respond(True)

    def respond(self, body):
        server = self.server
        path = unquote(urlsplit(self.path).path)
        server.seen.append((self.command, path, dict(self.headers)))
        if path in server.fail_pages:
            self.send_error(403)
            return
        if path in server.redirects:
            self.send_response(302)
            self.send_header("Location", server.redirects[path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.endswith("/"):
            if not any(k.startswith(path) for k in server.payloads):
                self.send_error(404)
                return
            links = set()
            for key in server.payloads:
                if key.startswith(path):
                    tail = key[len(path):]
                    links.add(tail.split("/")[0] + ("/" if "/" in tail else ""))
            text = '<html><body><a href="../">Parent directory</a>'
            for link in sorted(links):
                text += f'<a href="{quote(link)}">{html.escape(link)}</a>'
                key = path + link
                if key in server.payloads:
                    text += str(len(server.payloads[key]))
            text += server.page_extra.get(path, "") + "</body></html>"
            data = text.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)
            return
        if path not in server.payloads:
            self.send_error(404)
            return
        if self.command == "HEAD" and path in server.no_head:
            self.send_error(405)
            return
        data = server.payloads[path]
        tag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
        if body and path in server.changed_tags:
            tag = '"changed-after-inventory"'
        status, offset, content_range = 200, 0, None
        if body and "Range" in self.headers and path not in server.ignore_range:
            offset = int(self.headers["Range"].split("=")[1].split("-")[0])
            if offset >= len(data):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            status = 206
            start = offset + 1 if path in server.bad_range else offset
            content_range = f"bytes {start}-{len(data)-1}/{len(data)}"
        response = data[offset:]
        if body and path in server.as_html:
            response = b"<html>Login page</html>"
        self.send_response(status)
        self.send_header("Content-Type", "text/html" if body and path in server.as_html else "application/octet-stream")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("ETag", tag)
        self.send_header("Last-Modified", "Mon, 08 Apr 2019 08:35:52 GMT")
        if content_range:
            self.send_header("Content-Range", content_range)
        self.end_headers()
        if body:
            if path in server.drop_once:
                server.drop_once.remove(path)
                self.wfile.write(response[:len(response)//2])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.wfile.write(response)


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name) / "data"
        self.meta = self.dest / d.META
        self.meta.mkdir(parents=True)
        self.source = f"http://127.0.0.1:{self.server.server_port}/data/"
        self.server.payloads = {"/data/a.tif": bytes(range(128)), "/data/nested/b.zip": b"abcdef" * 8}
        self.server.seen = []
        for attribute in ("fail_pages", "no_head", "changed_tags", "ignore_range", "bad_range", "drop_once", "as_html"):
            setattr(self.server, attribute, set())
        self.server.redirects, self.server.page_extra = {}, {}
        self.client = d.Client(self.source, delay=0)
        self.addCleanup(self.client.close)
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        for name, value in (("CHUNK", 16), ("ATTEMPTS", 2)):
            mock = patch.object(d, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        mock = patch.object(d.time, "sleep", lambda seconds: None)
        mock.start()
        self.addCleanup(mock.stop)
        self.reference = Path(self.temp.name) / "absent_reference.json"

    def scan(self):
        return d.obtain_inventory(self.client, self.meta, self.reference)

    def entry(self):
        with self.client.request("HEAD", self.source + "a.tif") as response:
            return d.describe(response, self.source)

    def seed_partial(self, entry, data=None, validator=True):
        part = self.dest / "a.tif.part"
        part.write_bytes(bytes(range(32)) if data is None else data)
        prior = dict(entry)
        if not validator:
            prior["etag"] = prior["last_modified"] = ""
        token = hashlib.sha256(entry["url"].encode()).hexdigest()
        metadata = self.meta / "partial" / f"{token}.json"
        d.write_json(metadata, prior)
        return part, metadata

    def download(self, entry, state=None, verify=False):
        return d.download_one(self.client, entry, self.dest, {} if state is None else state,
                              self.meta / "download_state.json", verify)

    def test_full_scan_counts_and_sizes(self):
        snap = self.scan()
        self.assertEqual(len(snap["files"]), 2)
        self.assertEqual(len(snap["pages"]), 2)
        self.assertEqual(d.report_for(snap)["known_bytes"], 176)
        self.assertEqual(len(snap["outside_scope"]), 1)

    def test_reuse_does_not_request_file_headers_or_bodies(self):
        first = self.scan()
        self.server.seen.clear()
        second = self.scan()
        self.assertEqual(first["scanned_at_utc"], second["scanned_at_utc"])
        self.assertEqual([(m, p) for m, p, _ in self.server.seen], [("GET", "/data/"), ("GET", "/data/nested/")])

    def test_reference_bootstrap_needs_no_file_headers(self):
        snap = self.scan()
        snap["pages"] = d.infer_page_records([p["url"] for p in snap["pages"]], [r["url"] for r in snap["files"]], self.source)
        other = Path(self.temp.name) / "new" / d.META
        other.mkdir(parents=True)
        d.write_json(self.reference, snap)
        self.server.seen.clear()
        result = d.obtain_inventory(self.client, other, self.reference)
        self.assertEqual(len(self.server.seen), 2)
        self.assertTrue(all(p["html_sha256"] for p in result["pages"]))
        self.assertTrue(all(m == "GET" and p.endswith("/") for m, p, _ in self.server.seen))

    def test_nested_addition_refreshes_inventory(self):
        self.scan()
        self.server.payloads["/data/nested/new.tif"] = b"new"
        snap = self.scan()
        self.assertEqual(len(snap["files"]), 3)
        self.assertTrue(any(m == "HEAD" and p.endswith("new.tif") for m, p, _ in self.server.seen))

    def test_new_directory_is_discovered(self):
        self.scan()
        self.server.payloads["/data/newdir/new.tif"] = b"new"
        snap = self.scan()
        self.assertEqual(len(snap["pages"]), 3)

    def test_same_links_changed_html_refreshes_headers(self):
        self.scan()
        self.server.page_extra["/data/nested/"] = "updated timestamp"
        self.server.seen.clear()
        self.scan()
        self.assertTrue(any(m == "HEAD" for m, _, _ in self.server.seen))

    def test_removed_remote_file_does_not_delete_local_copy(self):
        snap = self.scan()
        local = self.dest / "a.tif"
        local.write_bytes(b"keep")
        del self.server.payloads["/data/a.tif"]
        result = self.scan()
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(local.read_bytes(), b"keep")

    def test_check_failure_retains_previous_cache(self):
        self.scan()
        before = (self.meta / "inventory_cache.json").read_bytes()
        self.server.fail_pages.add("/data/nested/")
        with self.assertRaises(RuntimeError):
            self.scan()
        self.assertEqual(before, (self.meta / "inventory_cache.json").read_bytes())

    def test_incomplete_full_scan_does_not_replace_cache(self):
        self.scan()
        before = (self.meta / "inventory_cache.json").read_bytes()
        self.server.fail_pages.add("/data/nested/")
        with self.assertRaises(RuntimeError):
            d.obtain_inventory(self.client, self.meta, self.reference, refresh=True)
        self.assertEqual(before, (self.meta / "inventory_cache.json").read_bytes())

    def test_force_refresh_reads_file_headers(self):
        self.scan()
        self.server.seen.clear()
        d.obtain_inventory(self.client, self.meta, self.reference, refresh=True)
        self.assertEqual(sum(m == "HEAD" for m, _, _ in self.server.seen), 2)

    def test_explicit_cache_skip_uses_no_network(self):
        self.scan()
        self.server.seen.clear()
        d.obtain_inventory(self.client, self.meta, self.reference, use_cached=True)
        self.assertEqual(self.server.seen, [])

    def test_cache_skip_without_inventory_fails(self):
        with self.assertRaises(RuntimeError):
            d.obtain_inventory(self.client, self.meta, self.reference, use_cached=True)

    def test_legacy_inventory_import(self):
        first = self.scan()
        (self.meta / "inventory_cache.json").unlink()
        self.server.seen.clear()
        second = self.scan()
        self.assertEqual(first["files"], second["files"])
        self.assertTrue(all(m == "GET" and p.endswith("/") for m, p, _ in self.server.seen))

    def test_head_not_supported_uses_streamed_get(self):
        self.server.no_head.add("/data/a.tif")
        snap = self.scan()
        self.assertEqual(len(snap["files"]), 2)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_successful_download_records_sha256(self):
        entry = self.entry()
        self.assertEqual(self.download(entry), "downloaded")
        self.assertEqual((self.dest / "a.tif").read_bytes(), bytes(range(128)))
        state = d.read_json(self.meta / "download_state.json")
        self.assertEqual(state[entry["url"]]["sha256"], hashlib.sha256(bytes(range(128))).hexdigest())

    def test_completed_file_skipped_without_get(self):
        entry = self.entry()
        self.download(entry)
        self.server.seen.clear()
        state = d.read_json(self.meta / "download_state.json")
        self.assertEqual(self.download(entry, state), "skipped")
        self.assertEqual(self.server.seen, [])

    def test_verified_completed_file_skipped(self):
        entry = self.entry()
        self.download(entry)
        state = d.read_json(self.meta / "download_state.json")
        self.assertEqual(self.download(entry, state, True), "skipped")

    def test_checksum_mismatch_preserves_modified_file(self):
        entry = self.entry()
        self.download(entry)
        state = d.read_json(self.meta / "download_state.json")
        (self.dest / "a.tif").write_bytes(b"z" * 128)
        with self.assertRaises(RuntimeError):
            self.download(entry, state, True)
        self.assertEqual((self.dest / "a.tif").read_bytes(), b"z" * 128)

    def test_untracked_file_not_overwritten(self):
        (self.dest / "a.tif").write_bytes(b"personal")
        with self.assertRaises(RuntimeError):
            self.download(self.entry())
        self.assertEqual((self.dest / "a.tif").read_bytes(), b"personal")

    def test_partial_resumes_using_range(self):
        entry = self.entry()
        self.seed_partial(entry)
        self.download(entry)
        self.assertTrue(any(h.get("Range") == "bytes=32-" for _, _, h in self.server.seen))
        self.assertEqual((self.dest / "a.tif").read_bytes(), bytes(range(128)))

    def test_ignored_range_restarts_not_appends(self):
        entry = self.entry()
        self.seed_partial(entry)
        self.server.ignore_range.add("/data/a.tif")
        self.download(entry)
        self.assertEqual((self.dest / "a.tif").read_bytes(), bytes(range(128)))

    def test_no_validator_restarts_partial(self):
        entry = self.entry()
        self.seed_partial(entry, validator=False)
        self.server.seen.clear()
        self.download(entry)
        self.assertFalse(any("Range" in h for _, _, h in self.server.seen))

    def test_unrecognised_partial_is_preserved(self):
        (self.dest / "a.tif.part").write_bytes(b"keep")
        with self.assertRaises(RuntimeError):
            self.download(self.entry())
        self.assertEqual((self.dest / "a.tif.part").read_bytes(), b"keep")

    def test_wrong_partial_metadata_is_preserved(self):
        entry = self.entry()
        part, meta = self.seed_partial(entry)
        record = d.read_json(meta)
        record["url"] = self.source + "other.tif"
        d.write_json(meta, record)
        with self.assertRaises(RuntimeError):
            self.download(entry)
        self.assertEqual(part.read_bytes(), bytes(range(32)))

    def test_malformed_range_not_published(self):
        entry = self.entry()
        self.seed_partial(entry)
        self.server.bad_range.add("/data/a.tif")
        with self.assertRaises(RuntimeError):
            self.download(entry)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_changed_remote_validator_not_published(self):
        entry = self.entry()
        self.server.changed_tags.add("/data/a.tif")
        with self.assertRaises(RuntimeError):
            self.download(entry)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_html_instead_of_data_rejected(self):
        entry = self.entry()
        self.server.as_html.add("/data/a.tif")
        with self.assertRaises(RuntimeError):
            self.download(entry)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_interrupted_transfer_retries_with_range(self):
        entry = self.entry()
        self.server.drop_once.add("/data/a.tif")
        self.download(entry)
        self.assertEqual((self.dest / "a.tif").read_bytes(), bytes(range(128)))
        self.assertTrue(any("Range" in h for _, _, h in self.server.seen))

    def test_complete_partial_recovers_without_network(self):
        entry = self.entry()
        self.seed_partial(entry, bytes(range(128)))
        state = {entry["url"]: dict(entry, status="complete", local_bytes=128,
                                   sha256=hashlib.sha256(bytes(range(128))).hexdigest())}
        self.server.seen.clear()
        self.download(entry, state)
        self.assertEqual(self.server.seen, [])
        self.assertEqual((self.dest / "a.tif").read_bytes(), bytes(range(128)))

    def test_outside_redirect_not_followed(self):
        self.server.redirects["/data/a.tif"] = "/elsewhere/private"
        with self.assertRaises(d.OutsideScope):
            self.client.request("GET", self.source + "a.tif")
        self.assertEqual(len(self.server.seen), 1)

    def test_path_traversal_rejected(self):
        self.assertFalse(d.within(self.source + "%2e%2e/secret", self.source))
        with self.assertRaises(ValueError):
            d.local_name(self.source + "../secret", self.source)

    def test_modified_inventory_local_path_rejected(self):
        snap = self.scan()
        snap["files"][0]["relative_path"] = "../secret"
        with self.assertRaises(ValueError):
            d.validate_inventory(snap, self.source)

    def test_case_collision_rejected(self):
        self.server.payloads["/data/A.tif"] = b"collision"
        with self.assertRaises(ValueError):
            self.scan()

    def test_invalid_negative_size_rejected(self):
        snap = self.scan()
        snap["files"][0]["bytes"] = -1
        with self.assertRaises(ValueError):
            d.validate_inventory(snap, self.source)

    @unittest.skipIf(os.name == "nt", "Symlink creation on Windows may require additional privileges")
    def test_symlink_target_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(b"safe")
        (self.dest / "a.tif").symlink_to(outside)
        with self.assertRaises(RuntimeError):
            self.download(self.entry())
        self.assertEqual(outside.read_bytes(), b"safe")

    def test_quoted_destination_with_spaces(self):
        chosen = Path(self.temp.name) / "folder with spaces"
        self.assertEqual(d.prepare_destination('"' + str(chosen) + '"'), chosen.resolve())

    def test_blank_destination_rejected(self):
        with self.assertRaises(ValueError):
            d.prepare_destination("  ")

    def test_url_destination_rejected(self):
        with self.assertRaises(ValueError):
            d.prepare_destination("https://example.org/data")

    def test_file_destination_rejected(self):
        path = Path(self.temp.name) / "file"
        path.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            d.prepare_destination(str(path))

    def test_filesystem_root_rejected(self):
        with self.assertRaises(ValueError):
            d.prepare_destination(self.dest.anchor)

    def test_destination_eof_explains_required_argument(self):
        with patch("builtins.input", side_effect=EOFError):
            with self.assertRaises(ValueError):
                d.choose_destination(None)

    def test_preflight_detects_conflicts(self):
        row = self.entry()
        (self.dest / "a.tif").write_bytes(b"keep")
        with self.assertRaises(RuntimeError):
            d.preflight([row], self.dest, {}, self.source)

    def test_preflight_subtracts_resumable_partial(self):
        row = self.entry()
        self.seed_partial(row)
        self.assertEqual(d.preflight([row], self.dest, {}, self.source), (96, 0))

    def test_inventory_only_cli_does_not_download(self):
        rc = d.main(["--source", self.source, "--destination", str(self.dest), "--inventory-only"])
        self.assertEqual(rc, 0)
        self.assertFalse((self.dest / "a.tif").exists())
        self.assertFalse((self.meta / "download.lock").exists())

    def test_default_cli_requires_confirmation(self):
        with patch("builtins.input", return_value="n"):
            rc = d.main(["--source", self.source, "--destination", str(self.dest)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_cli_download_yes_and_rerun(self):
        argv = ["--source", self.source, "--destination", str(self.dest), "--yes"]
        self.assertEqual(d.main(argv), 0)
        self.server.seen.clear()
        self.assertEqual(d.main(argv + ["--verify"]), 0)
        self.assertTrue(all(p.endswith("/") for _, p, _ in self.server.seen))
        summary = d.read_json(self.meta / "download_summary.json")
        self.assertEqual(summary["skipped"], 2)
        self.assertEqual(summary["failed"], 0)

    def test_active_lock_preserved(self):
        lock = self.meta / "download.lock"
        lock.write_text("another process")
        with self.assertRaises(RuntimeError):
            d.main(["--source", self.source, "--destination", str(self.dest), "--inventory-only"])
        self.assertEqual(lock.read_text(), "another process")

    def test_packaged_reference_is_valid_and_complete_as_recorded(self):
        snap = d.read_json(ROOT / "reference_inventory.json")
        d.validate_inventory(snap, d.SOURCE)
        self.assertEqual(len(snap["files"]), 801)
        self.assertEqual(len(snap["pages"]), 95)
        self.assertEqual(sum(r["bytes"] for r in snap["files"]), 144451717255)
        self.assertTrue(all(p["html_sha256"] is None for p in snap["pages"]))

    def test_reference_output_names_are_portable_relative_paths(self):
        snapshot = d.read_json(ROOT / "reference_inventory.json")
        self.assertNotIn("destination", snapshot)
        for row in snapshot["files"]:
            self.assertFalse(Path(row["relative_path"]).is_absolute())
            self.assertNotIn("\\", row["relative_path"])
            self.assertEqual(row["relative_path"], d.local_name(row["url"], d.SOURCE))

    def test_changed_remote_size_is_not_published(self):
        entry = self.entry()
        entry["etag"] = entry["last_modified"] = ""
        self.server.payloads["/data/a.tif"] = b"shorter"
        with self.assertRaises(RuntimeError):
            self.download(entry)
        self.assertFalse((self.dest / "a.tif").exists())

    def test_destination_prompt_retries_invalid_input(self):
        chosen = Path(self.temp.name) / "valid"
        with patch("builtins.input", side_effect=["", str(chosen)]):
            self.assertEqual(d.choose_destination(None), chosen.resolve())

    def test_publishing_never_replaces_an_existing_target(self):
        part, target = self.dest / "complete.part", self.dest / "complete"
        part.write_bytes(b"new")
        target.write_bytes(b"old")
        with self.assertRaises(RuntimeError):
            d.publish_partial(part, target)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(part.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()

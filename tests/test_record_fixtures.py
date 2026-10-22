"""Tests for scripts/record_fixtures.py (re-records tests/fixtures/pages
when the drift job's live scraper check fails): ENDPOINTS matches the
recorded fixtures, and record()/main() write and filter as documented, with
the network, output directory and clock injected.

Run with: python -m unittest discover -s tests
"""

import contextlib
import glob
import io
import json
import os
import unittest
import unittest.mock
from datetime import UTC, datetime

import helpers
import requests

record_fixtures = helpers.load_script("record_fixtures")

NOW = datetime(2026, 10, 21, 12, 30, 45, 123456, tzinfo=UTC)


def setUpModule():
    helpers.isolate_module()


class EndpointsTests(unittest.TestCase):
    """Without a live failure only this keeps ENDPOINTS and the fixtures
    RecordedPages serves in step."""

    def recorded(self):
        """(distro, slug) -> (url, extension) for every fixture on disk."""
        fixtures = {}
        for meta_path in glob.glob(os.path.join(helpers.PAGES_DIR, "*", "*.meta.json")):
            distro = os.path.basename(os.path.dirname(meta_path))
            stem = meta_path[: -len(".meta.json")]
            with open(meta_path, encoding="utf-8") as f:
                url = json.load(f)["url"]
            (body,) = (path for path in glob.glob(stem + ".*") if path != meta_path)
            fixtures[(distro, os.path.basename(stem))] = (
                url,
                os.path.splitext(body)[1][1:],
            )
        return fixtures

    def test_every_endpoint_has_a_fixture_recorded_from_its_url(self):
        endpoints = {
            (distro, slug): (url, ext)
            for distro, slug, url, ext in record_fixtures.ENDPOINTS
        }

        self.assertEqual(len(endpoints), len(record_fixtures.ENDPOINTS))
        self.assertEqual(endpoints, self.recorded())

    def test_fixtures_dir_is_where_recorded_pages_reads_from(self):
        self.assertEqual(
            os.path.normcase(record_fixtures.FIXTURES_DIR),
            os.path.normcase(helpers.PAGES_DIR),
        )


class RecordTests(unittest.TestCase):
    URL = "https://example.org/releases/"

    def setUp(self):
        self.out_dir = helpers.make_temp_dir(self, "record-fixtures-")

    def record(self, response):
        http = helpers.FakeHttp({self.URL: response})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            record_fixtures.record(
                "distro",
                "releases",
                self.URL,
                "html",
                NOW,
                get=http.get,
                out_dir=self.out_dir,
            )
        return http, out.getvalue()

    def test_writes_the_body_and_its_meta_under_distro_slug(self):
        body = b"<html>\xe2\x80\x94 not decoded</html>"
        http, out = self.record(
            helpers.fake_response(
                body, url=self.URL, headers={"Content-Type": "text/html"}
            )
        )

        self.assertEqual(http.requests, [(self.URL, 30)])
        directory = os.path.join(self.out_dir, "distro")
        self.assertEqual(
            sorted(os.listdir(directory)), ["releases.html", "releases.meta.json"]
        )
        with open(os.path.join(directory, "releases.html"), "rb") as f:
            self.assertEqual(f.read(), body)
        with open(os.path.join(directory, "releases.meta.json"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(
            json.loads(text),
            {
                "url": self.URL,
                "captured": "2026-10-21T12:30:45+00:00",
                "content_type": "text/html",
            },
        )
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(
            out, f"distro/releases.html: {len(body)} bytes from {self.URL}\n"
        )

    def test_overwrites_an_earlier_recording(self):
        self.record(helpers.fake_response(b"old", url=self.URL))
        self.record(helpers.fake_response(b"new", url=self.URL))

        with open(os.path.join(self.out_dir, "distro", "releases.html"), "rb") as f:
            self.assertEqual(f.read(), b"new")

    def test_http_errors_pass_through_and_nothing_is_written(self):
        with self.assertRaises(requests.HTTPError):
            self.record(helpers.fake_response(b"gone", status=500, url=self.URL))
        with self.assertRaises(requests.ConnectionError):
            self.record(requests.ConnectionError("refused"))

        self.assertEqual(os.listdir(self.out_dir), [])


class MainTests(unittest.TestCase):
    def run_main(self, argv):
        with unittest.mock.patch.object(record_fixtures, "record") as record:
            record_fixtures.main(argv, now=NOW)
        return record

    def recorded(self, record):
        return {(call.args[0], call.args[1]) for call in record.call_args_list}

    def test_no_arguments_records_every_endpoint(self):
        record = self.run_main([])

        self.assertEqual(
            record.call_args_list,
            [
                unittest.mock.call(distro, slug, url, ext, NOW)
                for distro, slug, url, ext in record_fixtures.ENDPOINTS
            ],
        )

    def test_distro_arguments_record_only_those_distros(self):
        record = self.run_main(["debian", "kali"])

        self.assertEqual(
            self.recorded(record),
            {
                ("debian", "amd64-bt-dvd"),
                ("debian", "arm64-bt-dvd"),
                ("debian", "amd64-bt-cd"),
                ("debian", "arm64-bt-cd"),
                ("kali", "get-kali"),
                ("kali", "cdimage"),
            },
        )

    def test_an_unknown_distro_records_nothing(self):
        record = self.run_main(["gentoo"])

        self.assertEqual(record.call_args_list, [])

    def test_now_defaults_to_the_current_utc_time(self):
        before = datetime.now(UTC)
        with unittest.mock.patch.object(record_fixtures, "record") as record:
            record_fixtures.main(["arch"])
        after = datetime.now(UTC)

        (now,) = {call.args[4] for call in record.call_args_list}
        self.assertEqual(now.tzinfo, UTC)
        self.assertTrue(before <= now <= after)


if __name__ == "__main__":
    unittest.main()

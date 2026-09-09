"""
Summary: Tests for the heuristic check for likely protected health
information. Every rule in the pattern table is exercised with a synthetic
example, every label-anchored rule is checked against ordinary prose that
must not fire, and the reports are pinned on the two properties that matter
most: they never quote what they found, and they never state that content
is free of protected health information.

This file is part of Extractium™
tests/test_phi_lint.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-09-09"

import inspect
import json
import pathlib

import pytest
from bs4 import BeautifulSoup

from extractium.core import phi_lint
from extractium.core.models import Document

# Every value below is invented for this test file. None of it refers to a
# real person, account, device, or address.
POSITIVE_EXAMPLES = {
    "email_address": "Write to ada.lovelace@example.org for access.",
    "phone_number": "Call (734) 555-0143 to reschedule.",
    "us_ssn": "Form shows 123-45-6789 in the identity box.",
    "gps_coordinates": "Recorded at 42.278600, -83.738200 on the map.",
    "postal_code": "Delivered to 48109-1340 last week.",
    "credit_card": "Charged card 4111 1111 1111 1111 in error.",
    "iban": "Transfer to GB82WEST12345698765432 was returned.",
    "npi": "Billed under provider 1234567893 that quarter.",
    "dea_number": "Prescriber registration BB1234563 expired.",
    "vehicle_identification_number": "Vehicle 1HGCM82633A004352 was logged.",
    "imei": "Handset 490154203237518 was replaced.",
    "mac_address": "Wearable 3C:22:FB:8A:1D:4E joined the network.",
    "device_udi": "Barcode reads (01)00819320080651 on the box.",
    "uuid": "Row key 123e4567-e89b-12d3-a456-426614174000 was reused.",
    "ip_address": "Request arrived from 192.168.10.42 overnight.",
    "url_with_query": "Opened https://example.org/record?id=7 from the email.",
    "person_name": "Patient: Ada Lovelace",
    "street_address": "Address: 1234 Maple Street",
    "birth_date": "Date of birth: 03/14/1954",
    "birth_year": "Year of birth: 1954",
    "clinical_event_date": "Admitted 2024-03-14 for observation.",
    "age_over_89": "Age 94 at the first visit.",
    "medical_record_number": "MRN: AB123456",
    "health_plan_id": "Member number: XY9988776",
    "device_identifier": "Dexcom sensor id G7X44219 was paired.",
    "other_identifier": "Study number ST0099421 was assigned.",
}

# Ordinary documentation that must not be flagged. Each line holds
# something an anchored rule would match if it fired without its label.
INNOCENT_LINES = (
    "Released on 2024-03-14 with new icons.",
    "Version 1.2.3 shipped March 14, 2024 to everyone.",
    "The all-hands meeting is on 03/14/2024 in room B.",
    "Ada Lovelace wrote the first published algorithm.",
    "Our office is near the Main Street parking structure.",
    "Copyright 1954 by the original publisher.",
    "Build number 12345678 finished without errors.",
    "Our team of 94 people met the deadline.",
    "Set the request timeout to 90 seconds.",
    "Take Highway 23 north for two miles.",
    "The catalogue number ABC12345 is printed on the spine.",
)


def local_document(text, url="local:notes/intake.md"):
    """A document that came from a folder on this machine."""
    return Document(url=url, title="Intake", content=text,
                    source_type="local", content_type="text", local=True)


def web_document(text, url="https://example.org/page"):
    """A document that came from a public web page."""
    return Document(url=url, title="Page", content=text,
                    source_type="web", content_type="page")


def fired(text):
    """The names of every rule that fires on one line."""
    return {pattern.name for pattern in phi_lint.PATTERNS if phi_lint.count_matches(pattern, text)}


# ---------------------------------------------------------------------------
# Every rule fires on its own example
# ---------------------------------------------------------------------------

def test_every_pattern_in_the_table_has_an_example_in_this_file():
    """A rule added without a test would otherwise ship unexercised."""
    assert set(POSITIVE_EXAMPLES) == set(phi_lint.PATTERNS_BY_NAME)


@pytest.mark.parametrize("name", sorted(POSITIVE_EXAMPLES))
def test_each_pattern_fires_on_its_own_example(name):
    assert name in fired(POSITIVE_EXAMPLES[name])


@pytest.mark.parametrize("name", sorted(phi_lint.PATTERNS_BY_NAME))
def test_each_pattern_names_a_safe_harbor_category_and_explains_itself(name):
    pattern = phi_lint.PATTERNS_BY_NAME[name]
    assert pattern.category[0].isdigit()
    assert pattern.description.endswith(".")
    assert pattern.tier in (phi_lint.TIER_STRUCTURAL, phi_lint.TIER_ANCHORED)


# ---------------------------------------------------------------------------
# Ordinary documentation is left alone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", INNOCENT_LINES)
def test_ordinary_documentation_is_not_flagged(line):
    assert fired(line) == set()


def test_a_date_with_no_personal_label_is_never_flagged():
    """
    Release notes, changelogs, and minutes are full of dates. A date rule
    that fired on all of them would bury every finding that matters.
    """
    notes = "\n".join([
        "# Release notes",
        "2024-03-14: search got faster.",
        "March 14, 2024 -- the first public build.",
        "Next review 06/01/2025.",
    ])
    assert phi_lint.scan_text(notes, "local:notes.md") == []


def test_a_bare_year_is_only_flagged_next_to_a_birth_label():
    assert "birth_year" not in fired("The study began in 1954 at three sites.")
    assert "birth_year" in fired("YOB 1954")


def test_an_age_below_ninety_is_not_flagged():
    assert "age_over_89" not in fired("Age 64 at enrollment.")
    assert "age_over_89" in fired("Age 91 at enrollment.")


def test_a_label_too_far_from_a_value_does_not_claim_it():
    far = "Patient records are held for seven years. " + " " * phi_lint.ANCHOR_WINDOW + "Ada Lovelace"
    assert "person_name" not in fired(far)


# ---------------------------------------------------------------------------
# Check digits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,wrong", [
    ("credit_card", "Charged card 4111 1111 1111 1112 in error."),
    ("imei", "Handset 490154203237519 was replaced."),
    ("npi", "Billed under provider 1234567890 that quarter."),
    ("dea_number", "Prescriber registration BB1234564 expired."),
    ("vehicle_identification_number", "Vehicle 1HGCM82633A004353 was logged."),
    ("iban", "Transfer to GB82WEST12345698765433 was returned."),
])
def test_a_wrong_check_digit_is_not_flagged(name, wrong):
    assert name not in fired(wrong)


def test_an_invalid_ipv4_octet_is_not_flagged():
    assert "ip_address" not in fired("Version 999.168.10.42 does not exist.")


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def test_the_default_mode_scans_local_content_only():
    report = phi_lint.scan(
        [local_document("MRN: AB123456"), web_document("MRN: AB123456")],
        mode=phi_lint.MODE_LOCAL,
    )

    assert report.documents_scanned == 1
    assert report.documents_skipped == 1
    assert {finding.url for finding in report.findings} == {"local:notes/intake.md"}


def test_mode_all_scans_web_content_too():
    report = phi_lint.scan(
        [local_document("MRN: AB123456"), web_document("MRN: CD654321")],
        mode=phi_lint.MODE_ALL,
    )

    assert report.documents_scanned == 2
    assert {finding.url for finding in report.findings} == {
        "local:notes/intake.md", "https://example.org/page",
    }


def test_mode_off_scans_nothing():
    report = phi_lint.scan([local_document("MRN: AB123456")], mode=phi_lint.MODE_OFF)

    assert report.documents_scanned == 0
    assert report.findings == ()


def test_a_parsed_html_document_is_scanned_as_text():
    soup = BeautifulSoup("<body><p>Patient: Ada Lovelace</p></body>", "html.parser")
    document = Document(url="local:page.html", title="Page", content=soup,
                        source_type="local", content_type="page", local=True)

    report = phi_lint.scan([document])

    assert [finding.pattern for finding in report.findings] == ["person_name"]


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

def test_a_finding_names_the_line_it_was_found_on():
    text = "Intro line.\nSecond line.\nMRN: AB123456"

    findings = phi_lint.scan_text(text, "local:notes.md")

    assert [(finding.line, finding.pattern) for finding in findings] == [
        (3, "medical_record_number"),
    ]


def test_repeated_matches_on_one_line_are_counted_once_with_a_total():
    findings = phi_lint.scan_text(
        "Contact ada@example.org or grace@example.org for access.", "local:notes.md"
    )

    assert len(findings) == 1
    assert findings[0].matches == 2


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def test_both_reports_are_written_to_the_folder_given(tmp_path):
    report = phi_lint.scan([local_document("MRN: AB123456")])

    paths = phi_lint.write_reports(report, tmp_path)

    assert [path.name for path in paths] == [phi_lint.JSON_REPORT_NAME, phi_lint.TEXT_REPORT_NAME]
    assert all(path.parent == tmp_path for path in paths)


def test_the_reports_default_to_the_working_directory_and_not_the_output_folder(tmp_path, monkeypatch):
    """
    Everything under the output folder is written in order to be published.
    A report of suspected identifiers is written in order to be read once.
    """
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    report = phi_lint.scan([local_document("MRN: AB123456")])

    paths = phi_lint.write_reports(report)

    assert all(path.parent == pathlib.Path.cwd() for path in paths)
    assert list(out_dir.iterdir()) == []


@pytest.mark.parametrize("name", sorted(POSITIVE_EXAMPLES))
def test_no_report_ever_quotes_what_it_found(tmp_path, name):
    """
    A report that copied the identifier out of the file would be a second
    copy of it, written somewhere nobody guards.
    """
    line = POSITIVE_EXAMPLES[name]
    report = phi_lint.scan([local_document(line)])
    value = line.split(maxsplit=1)[1]

    json_path, text_path = phi_lint.write_reports(report, tmp_path)

    for path in (json_path, text_path):
        contents = path.read_text(encoding="utf-8")
        assert value not in contents
        assert line not in contents


def test_the_json_report_holds_the_counts_and_the_findings(tmp_path):
    report = phi_lint.scan([local_document("MRN: AB123456\nMember number: XY9988776")])

    json_path, _ = phi_lint.write_reports(report, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert data["mode"] == phi_lint.MODE_LOCAL
    assert data["matchCount"] == 2
    assert data["countsByPattern"] == {"health_plan_id": 1, "medical_record_number": 1}
    assert data["countsByTier"] == {phi_lint.TIER_STRUCTURAL: 0, phi_lint.TIER_ANCHORED: 2}
    assert [finding["line"] for finding in data["findings"]] == [1, 2]


def test_the_text_report_tells_a_reader_where_to_look_and_what_to_do(tmp_path):
    report = phi_lint.scan([local_document("MRN: AB123456")])

    _, text_path = phi_lint.write_reports(report, tmp_path)
    contents = text_path.read_text(encoding="utf-8")

    assert "local:notes/intake.md" in contents
    assert "line 1: medical_record_number" in contents
    assert "What to do next" in contents
    assert "What this check cannot tell you" in contents


# ---------------------------------------------------------------------------
# What the check must never claim
# ---------------------------------------------------------------------------

def test_a_clean_scan_reports_the_exact_sentence(tmp_path):
    report = phi_lint.scan([local_document("Nothing here but ordinary prose.")])

    _, text_path = phi_lint.write_reports(report, tmp_path)

    assert report.findings == ()
    assert phi_lint.ZERO_MATCH_SENTENCE in phi_lint.summary_line(report)
    assert phi_lint.ZERO_MATCH_SENTENCE in text_path.read_text(encoding="utf-8")


def test_the_forbidden_phrase_is_absent_from_every_report_and_summary(tmp_path):
    clean = phi_lint.scan([local_document("Nothing here but ordinary prose.")])
    flagged = phi_lint.scan([local_document("MRN: AB123456")])

    for report in (clean, flagged):
        json_path, text_path = phi_lint.write_reports(report, tmp_path)
        for text in (json_path.read_text(encoding="utf-8"),
                     text_path.read_text(encoding="utf-8"),
                     phi_lint.summary_line(report)):
            assert "no phi" not in text.lower()


def test_the_forbidden_phrase_is_absent_from_the_module_itself():
    """
    Pinned against the source, not only the output, so a comment or a
    docstring cannot introduce the claim the reports are written to avoid.
    """
    assert "no phi" not in inspect.getsource(phi_lint).lower()


def test_the_summary_line_says_nothing_was_scanned_when_the_check_is_off():
    report = phi_lint.scan([local_document("MRN: AB123456")], mode=phi_lint.MODE_OFF)

    assert phi_lint.summary_line(report) == "PHI lint: off. No content was scanned."

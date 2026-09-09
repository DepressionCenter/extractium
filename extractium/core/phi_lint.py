"""
Summary: The heuristic check for likely protected health information (PHI).
Scans the text a build's sources produced for the identifier shapes HIPAA's
Safe Harbor rule names, and writes two reports for review: one JSON file for
a program, one plain-text file for a person. The check is flag-only. It
reports what looks like an identifier so a person can decide, and it can
never establish that content is free of protected health information.
See docs/extractium-spec.md section 7.

This file is part of Extractium™
extractium/core/phi_lint.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
Last Modified: 2026-09-09
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
__date__ = "2026-08-17"

import json
import pathlib
import re
import textwrap
from dataclasses import dataclass, field

### Constants ###

# The sentence a clean scan reports, word for word. A pattern check can show
# that something looks like an identifier; it can never show that nothing in
# a document is one. Reporting a clean scan as proof of anything would invite
# exactly that mistake, so the wording refuses to.
ZERO_MATCH_SENTENCE = "0 pattern matches (this does not confirm absence of PHI)"

# Report file names. Both are written to the working directory and never to
# the output folder, so a scheduled build cannot publish them by accident.
JSON_REPORT_NAME = "phi-lint-report.json"
TEXT_REPORT_NAME = "phi-lint-report.txt"

# How far apart, in characters on one line, a label word and a value may sit
# and still count as one finding. Wide enough for "Date of birth ....: value"
# in a form, narrow enough that a label at the start of a long paragraph does
# not claim a value at its end.
ANCHOR_WINDOW = 100

# Width the human report wraps to. Short lines are easier to track across,
# which matters most for the readers this report is hardest on.
REPORT_WIDTH = 78

# A rule whose shape or check digit settles the matter fires wherever it
# appears. A rule that needs a nearby label word to mean anything fires only
# next to one; on its own, a capitalised pair of words is a heading and a
# long number is a version string.
TIER_STRUCTURAL = "structural"
TIER_ANCHORED = "anchored"

# Which content a scan covers, matching the phi_lint setting.
MODE_LOCAL = "local"
MODE_ALL = "all"
MODE_OFF = "off"


### Shared Expressions ###

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"

# Written dates in the forms documents actually use: 03/14/1954, 1954-03-14,
# March 14, 1954, and 14 March 1954. Never applied on its own; every date
# rule below pairs it with a label that ties the date to one person's life or
# care, because ordinary documentation is full of dates that identify nobody.
DATE_VALUE = (
    r"(?:"
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}\b"
    r")"
)

# A record number, member number, serial, or any other assigned code: five or
# more characters with at least one digit, so an ordinary capitalised word
# sitting next to the label is not mistaken for one.
CODE_VALUE = r"(?<![A-Za-z0-9-])(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,24}(?![A-Za-z0-9-])"

# A personal name as documents write one: "Ada Lovelace", "Ada B. Lovelace",
# or "Lovelace, Ada".
NAME_VALUE = (
    r"(?:"
    r"\b[A-Z][a-z]{1,20},\s+[A-Z][a-z]{1,20}\b"
    r"|\b[A-Z][a-z]{1,20}(?:\s+[A-Z]\.)?\s+[A-Z][a-z]{1,20}\b"
    r")"
)


### Check Digits ###

def luhn_ok(digits):
    """
    True when a string of digits satisfies the Luhn check, the check digit
    used by payment cards, IMEI device numbers, and, over a fixed prefix,
    National Provider Identifiers.

    Args:
        digits (str): digits only, check digit last.

    Returns:
        bool: whether the sequence checks out.
    """
    if not digits.isdigit() or len(digits) < 2:
        return False
    total = 0
    for position, character in enumerate(reversed(digits)):
        value = int(character)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def is_credit_card(text):
    """True when text is a 13 to 19 digit number, separators aside, that passes the Luhn check."""
    digits = re.sub(r"[ -]", "", text)
    return 13 <= len(digits) <= 19 and luhn_ok(digits)


def is_imei(text):
    """True when text is a 15-digit mobile device number that passes the Luhn check."""
    return len(text) == 15 and luhn_ok(text)


def is_npi(text):
    """
    True when text is a National Provider Identifier: ten digits whose check
    digit satisfies Luhn over the number prefixed with the health-industry
    issuer code 80840, which is how that identifier is defined.
    """
    return len(text) == 10 and luhn_ok("80840" + text)


# Each character of a vehicle number is transliterated to a digit and
# multiplied by the weight published for its position; the ninth character is
# the check digit the weighted sum has to reproduce.
_VIN_TRANSLITERATION = {
    **{str(digit): digit for digit in range(10)},
    **dict(zip("ABCDEFGHJKLMNPRSTUVWXYZ",
               [1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 7, 9, 2, 3, 4, 5, 6, 7, 8, 9])),
}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def is_vin(text):
    """True when text is a 17-character vehicle identification number with a valid check digit."""
    if len(text) != 17:
        return False
    total = 0
    for character, weight in zip(text.upper(), _VIN_WEIGHTS):
        if character not in _VIN_TRANSLITERATION:
            return False
        total += _VIN_TRANSLITERATION[character] * weight
    expected = total % 11
    return text[8].upper() == ("X" if expected == 10 else str(expected))


def is_dea_number(text):
    """
    True when text is a Drug Enforcement Administration registration number:
    two letters and seven digits, where the last digit checks the first six.
    """
    body = text[2:]
    if len(body) != 7 or not body.isdigit():
        return False
    odd = int(body[0]) + int(body[2]) + int(body[4])
    even = int(body[1]) + int(body[3]) + int(body[5])
    return (odd + 2 * even) % 10 == int(body[6])


def is_iban(text):
    """True when text is an international bank account number passing the mod-97 check."""
    compact = text.replace(" ", "").upper()
    if len(compact) < 15:
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(character, 36)) for character in rearranged if character.isalnum())
    return bool(digits) and int(digits) % 97 == 1


def is_ipv4(text):
    """True when every dotted part of text is a number from 0 to 255."""
    parts = text.split(".")
    return len(parts) == 4 and all(part.isdigit() and int(part) <= 255 for part in parts)


def is_age_over_89(text):
    """
    True when text is an age of 90 or more. Safe Harbor lets a lower age
    stay; above it, an age describes so few people that it identifies them.
    """
    return text.isdigit() and int(text) >= 90


def is_birth_year(text):
    """
    True when a bare four-digit number could be a year of birth. A year is
    confidential when a label ties it to a birth, even where the day and the
    month were dropped, which is the reason it is checked at all.
    """
    return len(text) == 4 and text.isdigit() and 1900 <= int(text) <= 2099


### Pattern Table ###

@dataclass(frozen=True)
class Pattern:
    """
    One rule the linter applies. Adding a rule means adding an entry to
    PATTERNS below; both reports and the tests read their wording from here,
    so nothing else has to change.

    Attributes:
        name (str): identifier used in both reports and in the tests.
        category (str): the HIPAA Safe Harbor identifier it aims at, worded
            the way a privacy reviewer would recognise it.
        description (str): plain-language explanation for the human report.
        value (str): regular expression for the value itself.
        labels (tuple[str, ...]): expressions for the words that must appear
            near the value. Empty for a structural rule.
        validate (Callable[[str], bool] | None): extra check on the matched
            text, such as a check digit. None accepts every match.
        flags (int): regular-expression flags for the value expression.
    """

    name: str
    category: str
    description: str
    value: str
    labels: tuple = ()
    validate: object = None
    flags: int = 0
    value_re: object = field(default=None, compare=False, repr=False)
    label_re: object = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "value_re", re.compile(self.value, self.flags))
        if self.labels:
            object.__setattr__(self, "label_re", re.compile("|".join(self.labels), re.IGNORECASE))

    @property
    def tier(self):
        """Which tier this rule belongs to, decided by whether it needs a label."""
        return TIER_ANCHORED if self.labels else TIER_STRUCTURAL


# The rules, ordered by the Safe Harbor identifier each one aims at. The
# structural rules come first: their shape or their check digit settles the
# matter, so they fire wherever they appear. The anchored rules follow, and
# each fires only within ANCHOR_WINDOW characters of one of its label words
# on the same line.
PATTERNS = (
    ### Structural ###
    Pattern(
        name="email_address",
        category="6. Email addresses",
        description="An email address.",
        value=r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    ),
    Pattern(
        name="phone_number",
        category="4, 5. Telephone and fax numbers",
        description="A telephone or fax number, written in a North American or international form.",
        value=(
            r"(?<![\d-])(?:\+\d{1,3}[\s.-]?)?"
            r"(?:\(\d{3}\)\s*|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\d-])"
            r"|(?<![\d-])\+\d{1,3}[\s.-]?\d{2,4}(?:[\s.-]\d{2,4}){2,3}(?![\d-])"
        ),
    ),
    Pattern(
        name="us_ssn",
        category="7. Social Security numbers",
        description="A United States Social Security number, written with separators.",
        value=r"(?<!\d)(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}(?!\d)",
    ),
    Pattern(
        name="gps_coordinates",
        category="2. Geographic subdivisions",
        description="A latitude and longitude pair, in decimal degrees or degrees, minutes and seconds.",
        value=(
            r"(?<![\d.])[-+]?\d{1,2}\.\d{4,}\s*,\s*[-+]?\d{1,3}\.\d{4,}(?![\d.])"
            r"|\d{1,3}°\s*\d{1,2}['′]\s*[\d.]+[\"″]?\s*[NSEW]"
        ),
    ),
    Pattern(
        name="postal_code",
        category="2. Geographic subdivisions",
        description=(
            "A postal code precise enough to name a neighbourhood: a United States "
            "ZIP+4, or a United Kingdom or Canadian postcode."
        ),
        value=(
            r"(?<!\d)\d{5}-\d{4}(?!\d)"
            r"|(?<![A-Z0-9])[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}(?![A-Z0-9])"
            r"|(?<![A-Z0-9])[A-Z]\d[A-Z]\s?\d[A-Z]\d(?![A-Z0-9])"
        ),
    ),
    Pattern(
        name="credit_card",
        category="10. Account numbers",
        description="A payment card number that passes its check digit.",
        value=r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])",
        validate=is_credit_card,
    ),
    Pattern(
        name="iban",
        category="10. Account numbers",
        description="An international bank account number that passes its check digits.",
        value=r"(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]{11,30}(?![A-Z0-9])",
        validate=is_iban,
    ),
    Pattern(
        name="npi",
        category="11. Certificate and licence numbers",
        description="A National Provider Identifier that passes its check digit.",
        value=r"(?<!\d)\d{10}(?!\d)",
        validate=is_npi,
    ),
    Pattern(
        name="dea_number",
        category="11. Certificate and licence numbers",
        description="A Drug Enforcement Administration registration number that passes its check digit.",
        value=r"(?<![A-Z0-9])[ABCDEFGHJKLMPRSTUX][A-Z9]\d{7}(?![A-Z0-9])",
        validate=is_dea_number,
    ),
    Pattern(
        name="vehicle_identification_number",
        category="12. Vehicle identifiers and serial numbers",
        description="A vehicle identification number that passes its check digit.",
        value=r"(?<![A-HJ-NPR-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-HJ-NPR-Z0-9])",
        validate=is_vin,
    ),
    Pattern(
        name="imei",
        category="13. Device identifiers and serial numbers",
        description="A mobile device IMEI number that passes its check digit.",
        value=r"(?<!\d)\d{15}(?!\d)",
        validate=is_imei,
    ),
    Pattern(
        name="mac_address",
        category="13. Device identifiers and serial numbers",
        description=(
            "A network or Bluetooth hardware address, which identifies one physical "
            "device such as a fitness tracker, watch, or monitor."
        ),
        value=r"(?<![0-9A-Fa-f:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])",
    ),
    Pattern(
        name="device_udi",
        category="13. Device identifiers and serial numbers",
        description="A unique device identifier in its regulated barcode form, as printed on medical devices.",
        value=r"\(01\)\d{14}",
    ),
    Pattern(
        name="uuid",
        category="18. Any other unique identifying code",
        description="A universally unique identifier, often the key that links a record back to one person.",
        value=r"(?<![0-9A-Fa-f-])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f-])",
    ),
    Pattern(
        name="ip_address",
        category="15. Internet protocol addresses",
        description="An IPv4 or IPv6 address.",
        value=(
            r"(?<![\d.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])"
            r"|(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){3,7}[0-9A-Fa-f]{1,4}(?![0-9A-Fa-f:])"
        ),
        validate=lambda text: ":" in text or is_ipv4(text),
    ),
    Pattern(
        name="url_with_query",
        category="14. Web addresses",
        description="A web address carrying a query string, which is where tracking and record keys travel.",
        value=r"https?://[^\s<>\"]+\?[^\s<>\"]+",
    ),

    ### Anchored ###
    Pattern(
        name="person_name",
        category="1. Names",
        description="A personal name next to a word that ties it to one individual.",
        value=NAME_VALUE,
        labels=(
            r"\bpatients?\b", r"\bparticipants?\b", r"\bsubjects?\b", r"\brespondents?\b",
            r"\bname\b", r"\bfull name\b", r"\bcontact\b", r"\bguardian\b",
            r"\bcaregivers?\b", r"\bphysicians?\b", r"\bclinicians?\b", r"\bprovider\b",
        ),
    ),
    Pattern(
        name="street_address",
        category="2. Geographic subdivisions",
        description=(
            "A street address or post office box next to an address label. Covers United "
            "States street forms and the common international thoroughfare words."
        ),
        value=(
            r"\bP\.?\s?O\.?\s+Box\s+\d+\b"
            r"|\b\d{1,6}\s+(?:[A-Za-z0-9.'-]+\s+){0,4}"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
            r"Way|Terrace|Ter|Place|Pl|Circle|Cir|Highway|Hwy|Parkway|Pkwy|"
            r"Stra(?:ss|ß)e|Rue|Via|Calle|Avenida|Laan|Weg|Gata|Gade)\b\.?"
            r"|\b(?:Stra(?:ss|ß)e|Rue|Via|Calle|Avenida)\s+[A-Za-zÀ-ÿ.'-]+\s+\d{1,4}\b"
        ),
        labels=(
            r"\baddress\b", r"\bstreet\b", r"\bmailing\b", r"\bresidence\b",
            r"\bresides?\b", r"\bhome\b", r"\bcity\b", r"\bcounty\b", r"\bpostal\b",
        ),
        flags=re.IGNORECASE,
    ),
    Pattern(
        name="birth_date",
        category="3. Dates related to an individual",
        description="A full date next to a birth label.",
        value=DATE_VALUE,
        labels=(
            r"\bd\.?o\.?b\.?\b", r"\bdate of birth\b", r"\bbirth ?date\b",
            r"\bbirthday\b", r"\bborn\b", r"\bbirth\b",
        ),
    ),
    Pattern(
        name="birth_year",
        category="3. Dates related to an individual",
        description=(
            "A bare four-digit year next to a birth label. A year of birth stays "
            "confidential even where the day and the month were dropped."
        ),
        value=r"(?<![\d/-])\d{4}(?![\d/-])",
        labels=(
            r"\by\.?o\.?b\.?\b", r"\byear of birth\b", r"\bbirth year\b",
            r"\bd\.?o\.?b\.?\b", r"\bdate of birth\b", r"\bborn\b", r"\bbirth\b",
        ),
        validate=is_birth_year,
    ),
    Pattern(
        name="clinical_event_date",
        category="3. Dates related to an individual",
        description="A full date next to a word that ties it to one person's care.",
        value=DATE_VALUE,
        labels=(
            r"\badmitted\b", r"\badmission\b", r"\bdischarged?\b", r"\bvisits?\b",
            r"\bencounters?\b", r"\bappointment\b", r"\bseen on\b", r"\bseen\b",
            r"\bdate of service\b", r"\bservice date\b", r"\bprocedure\b",
            r"\bsurgery\b", r"\bcollected\b", r"\bspecimen\b", r"\bfollow[- ]?up\b",
            r"\blast seen\b", r"\bdeceased\b", r"\bdeath\b",
        ),
    ),
    Pattern(
        name="age_over_89",
        category="3. Dates related to an individual",
        description="An age of 90 or more, which Safe Harbor treats as identifying.",
        value=r"(?<!\d)\d{2,3}(?!\d)",
        labels=(r"\bages?d?\b", r"\byears old\b", r"\by/?o\b"),
        validate=is_age_over_89,
    ),
    Pattern(
        name="medical_record_number",
        category="8. Medical record numbers",
        description="An assigned code next to a medical record label.",
        value=CODE_VALUE,
        labels=(
            r"\bm\.?r\.?n\.?\b", r"\bmedical record\b", r"\bchart\b",
            r"\bpatient (?:id|no|number)\b", r"\brecord (?:id|no|number)\b",
            r"\baccession\b",
        ),
    ),
    Pattern(
        name="health_plan_id",
        category="9. Health plan beneficiary numbers",
        description="An assigned code next to an insurance or health plan label.",
        value=CODE_VALUE,
        labels=(
            r"\bmember (?:id|no|number)\b", r"\bsubscriber\b", r"\bbeneficiary\b",
            r"\bpolicy\b", r"\bgroup number\b", r"\binsurance\b",
            r"\bmedicare\b", r"\bmedicaid\b", r"\bhealth plan\b",
        ),
    ),
    Pattern(
        name="device_identifier",
        category="13. Device identifiers and serial numbers",
        description=(
            "A serial number next to a device label. Covers consumer wearables and "
            "nearables as well as insulin pumps, glucose monitors, and implants."
        ),
        value=CODE_VALUE,
        labels=(
            r"\bserial (?:no|number)\b", r"\bs/n\b", r"\bdevice (?:id|serial)\b",
            r"\bsensor (?:id|serial)\b", r"\btransmitter (?:id|serial)\b",
            r"\bpump (?:id|serial)\b", r"\bimei\b", r"\btrackers?\b", r"\bwatch\b",
            r"\bwearables?\b", r"\bmonitor\b", r"\bc\.?g\.?m\.?\b",
            r"\bcontinuous glucose\b", r"\binsulin pump\b", r"\bpacemaker\b",
            r"\bimplant\b", r"\bfitbit\b", r"\bgarmin\b", r"\bdexcom\b",
            r"\bomnipod\b", r"\bmedtronic\b", r"\boura\b", r"\bwhoop\b",
        ),
    ),
    Pattern(
        name="other_identifier",
        category="18. Any other unique identifying code",
        description="An assigned code next to a label that says it identifies a record or a person.",
        value=CODE_VALUE,
        labels=(
            r"\bidentifiers?\b", r"\b(?:study|case|account|enrol(?:l)?ment) (?:id|no|number)\b",
            r"\bspecimen (?:id|no|number)\b", r"\bsample (?:id|no|number)\b",
            r"\bvisit (?:id|no|number)\b", r"\bcertificate (?:no|number)\b",
            r"\blicen[cs]e (?:no|number)\b", r"\bpassport\b", r"\blicen[cs]e plate\b",
        ),
    ),
)

# A rule is looked up by name in the reports and in the tests.
PATTERNS_BY_NAME = {pattern.name: pattern for pattern in PATTERNS}


### Findings ###

@dataclass(frozen=True)
class Finding:
    """
    One rule firing on one line of one document.

    The matched text is deliberately absent. A report that quoted what it
    found would be a second copy of the identifiers, written to a folder
    nobody guards, and its whole purpose is to have fewer of those. The
    document and the line number are enough to find it.

    Attributes:
        url (str): the document the line belongs to.
        line (int): 1-based line number within the text that was scanned.
            For a web page, lines are the blocks the page was read as, not
            lines of its HTML source.
        pattern (str): the rule that fired.
        category (str): the Safe Harbor identifier that rule aims at.
        tier (str): TIER_STRUCTURAL or TIER_ANCHORED.
        matches (int): how many times the rule fired on that line.
    """

    url: str
    line: int
    pattern: str
    category: str
    tier: str
    matches: int


@dataclass(frozen=True)
class Report:
    """
    The result of one scan, and the record both report files are written from.

    Attributes:
        mode (str): the phi_lint mode the scan ran under.
        documents_scanned (int): how many documents were read.
        documents_skipped (int): how many were left out by the mode.
        findings (tuple[Finding, ...]): every firing, in document order.
    """

    mode: str
    documents_scanned: int
    documents_skipped: int
    findings: tuple

    def __post_init__(self):
        object.__setattr__(self, "findings", tuple(self.findings))

    @property
    def match_count(self):
        """Total number of times any rule fired."""
        return sum(finding.matches for finding in self.findings)

    @property
    def document_count(self):
        """Number of distinct documents holding at least one finding."""
        return len({finding.url for finding in self.findings})

    def counts_by_pattern(self):
        """Match totals per rule, largest first, then by name."""
        totals = {}
        for finding in self.findings:
            totals[finding.pattern] = totals.get(finding.pattern, 0) + finding.matches
        return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))

    def counts_by_tier(self):
        """Match totals per tier, so a reader can weigh certain shapes against likely ones."""
        totals = {TIER_STRUCTURAL: 0, TIER_ANCHORED: 0}
        for finding in self.findings:
            totals[finding.tier] += finding.matches
        return totals

    def findings_by_document(self):
        """Findings grouped by document URL, in first-seen order."""
        grouped = {}
        for finding in self.findings:
            grouped.setdefault(finding.url, []).append(finding)
        return grouped


### Scan ###

def document_text(document):
    """
    The plain text of one document, however its source produced it.

    Args:
        document (extractium.core.models.Document): what a source yielded.

    Returns:
        str: the text to scan. A parsed HTML node is flattened with one line
        per block, so line numbers point at something a reader can find.
    """
    content = document.content
    if isinstance(content, str):
        return content
    return content.get_text("\n")


def _label_spans(pattern, line):
    """Where each of a rule's label words sits on one line."""
    return [match.span() for match in pattern.label_re.finditer(line)]


def _near_a_label(span, label_spans):
    """True when a value's span is within ANCHOR_WINDOW characters of any label on the line."""
    start, end = span
    for label_start, label_end in label_spans:
        if start < label_end and label_start < end:
            return True
        gap = label_start - end if label_start >= end else start - label_end
        if gap <= ANCHOR_WINDOW:
            return True
    return False


def count_matches(pattern, line):
    """
    How many times one rule fires on one line.

    An anchored rule needs one of its label words nearby; a rule with a
    validate function keeps only the matches that pass it, which is what
    keeps a check-digit rule from flagging every number of the right length.

    Args:
        pattern (Pattern): the rule to apply.
        line (str): one line of text.

    Returns:
        int: the number of matches that survived every check.
    """
    label_spans = _label_spans(pattern, line) if pattern.labels else None
    if label_spans is not None and not label_spans:
        return 0
    hits = 0
    for match in pattern.value_re.finditer(line):
        text = match.group(0)
        if pattern.validate is not None and not pattern.validate(text):
            continue
        if label_spans is not None and not _near_a_label(match.span(), label_spans):
            continue
        hits += 1
    return hits


def scan_text(text, url, patterns=PATTERNS):
    """
    Applies every rule to one document's text.

    Args:
        text (str): the text to scan.
        url (str): the document URL, recorded on every finding.
        patterns (Iterable[Pattern]): the rules to apply.

    Returns:
        list[Finding]: one record per rule that fired on a line, in line order.
    """
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        for pattern in patterns:
            hits = count_matches(pattern, line)
            if hits:
                findings.append(Finding(
                    url=url,
                    line=number,
                    pattern=pattern.name,
                    category=pattern.category,
                    tier=pattern.tier,
                    matches=hits,
                ))
    return findings


def scan(documents, mode=MODE_LOCAL, patterns=PATTERNS):
    """
    Scans the documents a build produced for likely identifiers.

    Args:
        documents (Iterable[extractium.core.models.Document]): what the
            sources produced.
        mode (str): MODE_LOCAL scans only content read from a local folder,
            which is the content that was never published; MODE_ALL scans
            everything; MODE_OFF scans nothing.
        patterns (Iterable[Pattern]): the rules to apply.

    Returns:
        Report: what was scanned and what fired. Never a judgement about
        whether the content is safe to publish; that is a person's decision.
    """
    documents = list(documents)
    if mode == MODE_OFF:
        return Report(mode=mode, documents_scanned=0,
                      documents_skipped=len(documents), findings=())

    findings = []
    scanned = skipped = 0
    for document in documents:
        if mode == MODE_LOCAL and not document.local:
            skipped += 1
            continue
        scanned += 1
        findings.extend(scan_text(document_text(document), document.url, patterns))
    return Report(mode=mode, documents_scanned=scanned,
                  documents_skipped=skipped, findings=tuple(findings))


### Reports ###

def summary_line(report, paths=()):
    """
    The one line the command line shows an operator.

    Args:
        report (Report): the scan result.
        paths (Sequence[pathlib.Path]): the report files that were written.

    Returns:
        str: a line safe to print anywhere. It states what was found, and it
        never states what was not.
    """
    if report.mode == MODE_OFF:
        return "PHI lint: off. No content was scanned."
    where = f" Reports: {', '.join(str(path) for path in paths)}." if paths else ""
    scope = "every document" if report.mode == MODE_ALL else "local content"
    if not report.findings:
        return (
            f"PHI lint ({scope}): {ZERO_MATCH_SENTENCE} "
            f"across {report.documents_scanned} document(s).{where}"
        )
    return (
        f"PHI lint ({scope}): {report.match_count} pattern match(es) to review "
        f"in {report.document_count} of {report.documents_scanned} document(s).{where}"
    )


def report_as_dict(report):
    """
    The scan result as plain data, for the JSON file and for any program or
    language model reading it.

    Args:
        report (Report): the scan result.

    Returns:
        dict: the mode, the totals, and one entry per finding. No matched
        text appears anywhere in it.
    """
    return {
        "tool": "extractium phi_lint",
        "mode": report.mode,
        "limitation": ZERO_MATCH_SENTENCE,
        "documentsScanned": report.documents_scanned,
        "documentsSkipped": report.documents_skipped,
        "matchCount": report.match_count,
        "countsByPattern": report.counts_by_pattern(),
        "countsByTier": report.counts_by_tier(),
        "findings": [
            {
                "url": finding.url,
                "line": finding.line,
                "pattern": finding.pattern,
                "category": finding.category,
                "tier": finding.tier,
                "matches": finding.matches,
            }
            for finding in report.findings
        ],
    }


def _text_report_header(report):
    """The opening of the human report: what ran, over what, and what it means."""
    scope = {
        MODE_ALL: "every document this build read",
        MODE_LOCAL: "content read from a local folder",
        MODE_OFF: "nothing",
    }[report.mode]
    return [
        "Possible protected health information",
        "=====================================",
        "",
        f"This check looked at {scope}.",
        f"Documents read: {report.documents_scanned}. Left out by the setting: {report.documents_skipped}.",
        "",
        "It looks for the shapes identifiers usually take. It cannot read meaning,",
        "so it will miss things and it will flag things that are fine. Treat every",
        "line below as a question for a person, not as a verdict.",
        "",
    ]


def _text_report_findings(report):
    """The body of the human report: the totals, then the lines to look at."""
    if not report.findings:
        return [
            f"Result: {ZERO_MATCH_SENTENCE}.",
            "",
            "Nothing matched. That is not the same as content being safe to publish.",
            "A person still has to decide that.",
            "",
        ]

    tiers = report.counts_by_tier()
    lines = [
        f"Result: {report.match_count} pattern match(es) in "
        f"{report.document_count} document(s). Please review each one.",
        "",
        f"  {tiers[TIER_STRUCTURAL]} match(es) have a shape or a check digit that is hard to mistake.",
        f"  {tiers[TIER_ANCHORED]} match(es) sat next to a word such as 'Patient' or 'Serial number'.",
        "",
        "By rule",
        "-------",
    ]
    for name, count in report.counts_by_pattern().items():
        pattern = PATTERNS_BY_NAME[name]
        lines.append(f"  {count:>5}  {name}  ({pattern.category})")
        lines.extend(textwrap.wrap(
            pattern.description, width=REPORT_WIDTH,
            initial_indent="         ", subsequent_indent="         ",
        ))
    lines.extend(["", "Where to look", "-------------"])
    for url, findings in report.findings_by_document().items():
        lines.append(f"  {url}")
        for finding in findings:
            times = "" if finding.matches == 1 else f" x{finding.matches}"
            lines.append(f"    line {finding.line}: {finding.pattern}{times}")
    lines.append("")
    return lines


def _text_report_footer():
    """The closing of the human report: what to do, and what this check cannot tell you."""
    return [
        "What to do next",
        "---------------",
        "",
        "1. Open each file at the line named above and decide whether it really",
        "   holds information about a person.",
        "2. If it does, take it out of the folder you pointed the build at, or",
        "   replace it with a made-up example, and build again.",
        "3. Keep this report out of anything you publish. Delete it when you are done.",
        "",
        "What this check cannot tell you",
        "-------------------------------",
        "",
        "  - It cannot confirm that content holds no information about a person.",
        "    A clean result means the shapes it knows did not appear, nothing more.",
        "  - It does not recognise a person's name or a place name in ordinary prose.",
        "    It only sees one next to a word such as 'Patient' or 'Address'.",
        "  - It does not read images, PDFs, or spreadsheets. The build does not read",
        "    those either.",
        "  - It is not a review by your privacy office, and it is not evidence of",
        "    compliance with any rule or agreement.",
        "",
    ]


def render_text_report(report):
    """
    The human report as one string: what ran, what it found, where to look,
    what to do, and what the check cannot tell you.

    Args:
        report (Report): the scan result.

    Returns:
        str: the whole file, ready to write.
    """
    lines = _text_report_header(report) + _text_report_findings(report) + _text_report_footer()
    return "\n".join(lines)


def write_reports(report, directory=None):
    """
    Writes both report files.

    They go to the working directory, never under the build's output folder,
    because everything in that folder is written to be published and these
    two are written to be read once and deleted.

    Args:
        report (Report): the scan result.
        directory (str | pathlib.Path | None): where to write. None uses the
            working directory.

    Returns:
        tuple[pathlib.Path, pathlib.Path]: the JSON file and the text file.

    Raises:
        OSError: if either file cannot be written.
    """
    folder = pathlib.Path(directory) if directory is not None else pathlib.Path.cwd()
    json_path = folder / JSON_REPORT_NAME
    text_path = folder / TEXT_REPORT_NAME
    json_path.write_text(
        json.dumps(report_as_dict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    text_path.write_text(render_text_report(report), encoding="utf-8")
    return (json_path, text_path)

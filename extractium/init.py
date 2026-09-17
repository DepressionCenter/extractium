"""
Summary: The `extractium init` command. Writes a first settings file from
the commented example that ships with the project, filled in with the
three values a first build needs: the compendium's name, the short
name its output files are named after, and the website to crawl. Each
value comes from a command-line flag or, when the flag is absent, from a
question asked in the terminal. The written file is checked through the
configuration loader before it is saved, so what this command writes is
always a file a build accepts.

This file is part of Extractium™
extractium/init.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-14
Last Modified: 2026-09-17
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
__date__ = "2026-09-17"

import json
import pathlib
import re
import sys

import yaml

from extractium.config import ConfigError, DEFAULT_SLUG, SLUG_RE, config_from_mapping

### Constants ###

# The commented example settings file, kept beside the package in a
# checkout. It is the source of truth for the file this command writes,
# so the two cannot drift apart.
EXAMPLE_CONFIG = pathlib.Path(__file__).resolve().parent.parent / "examples" / "config.example.yaml"

DEFAULT_OUTPUT = "config.yaml"
DEFAULT_NAME = "Compendium"

# The label every first build gives its one web source. A reader sees it
# as the name of the collection an answer came from, and it can be
# changed in the file at any time.
WEBSITE_LABEL = "Website"

# How many times a question is repeated after an answer is refused, so a
# mistyped address does not end the setup and a script feeding the
# command from a pipe cannot loop forever.
MAX_ATTEMPTS = 3

# The three lines of the example file this command fills in. Each must
# match exactly once; the example file's tests keep the lines in place.
EXAMPLE_LABEL_LINE = re.compile(r"^(\s*)label: Example Knowledge Base$", re.M)
EXAMPLE_SEED_LINE = re.compile(r'^(\s*)seed_url: "https://example\.edu/[^"]*"$', re.M)
EXAMPLE_NAME_LINE = re.compile(r'^#name: "Example Org Compendium"$', re.M)
EXAMPLE_SLUG_LINE = re.compile(r"^#slug: compendium$", re.M)

# The file written when the example cannot be found, which happens when
# the package was installed without a checkout beside it. It holds the
# same three settings and points at the full reference.
FALLBACK_TEMPLATE = """# Extractium build settings. Every setting is explained in the
# configuration reference: docs/configuration.md in the Extractium
# repository. Keys and API tokens never go in this file.

# Display name of the compendium, recorded in every output.
name: {name}

# The short name the output files are named after: <slug>.json.gz,
# <slug>-full.json.gz, and <slug>.sqlite. Lowercase letters, digits, and
# hyphens.
slug: {slug}

sources:
  # The website to crawl. The crawl starts at seed_url and stays inside
  # that site. The label is the name a reader sees for this source.
  - type: web
    label: {label}
    seed_url: {seed_url}
"""


class InitError(Exception):
    """A value the command cannot write a settings file from."""


### Values ###

def slug_from_name(name):
    """
    A short name derived from a display name: lowercase letters, digits,
    and hyphens, as the `slug` setting requires.

    Args:
        name (str): the display name typed by the person.

    Returns:
        str: a slug the settings loader accepts, or the default slug when
        the name holds nothing usable.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64].strip("-")
    return slug if SLUG_RE.match(slug) else DEFAULT_SLUG


def checked_name(value):
    """The display name, with surrounding space removed, or the default when empty."""
    name = " ".join(value.split())
    return name or DEFAULT_NAME


def checked_slug(value, name):
    """
    The slug to write, derived from the name when left empty.

    Raises:
        InitError: if the value is not a valid slug.
    """
    slug = value.strip()
    if not slug:
        return slug_from_name(name)
    if not SLUG_RE.match(slug):
        raise InitError(
            f"the short name must be lowercase letters, digits, and hyphens, starting with a letter "
            f"or digit, up to 64 characters (got {slug!r})."
        )
    return slug


def checked_seed_url(value):
    """
    The website address to write.

    Raises:
        InitError: if the value is empty or is not a web address.
    """
    url = value.strip()
    if not url:
        raise InitError("the website address is required.")
    if not url.lower().startswith(("http://", "https://")):
        raise InitError(f"the website address must start with http:// or https:// (got {url!r}).")
    if any(c.isspace() for c in url):
        raise InitError(f"the website address cannot contain spaces (got {url!r}).")
    return url


def yaml_text(value):
    """
    One value as a double-quoted YAML scalar. JSON's string form is valid
    YAML, and quoting through it means a name holding a colon, a quotation
    mark, or a line break stays one value rather than becoming a setting.
    """
    return json.dumps(value, ensure_ascii=False)


### Questions ###

def ask(question, default, check, ask_line=input, say=print):
    """
    Asks one question until an acceptable answer arrives.

    Args:
        question (str): the question, without the default.
        default (str | None): what an empty answer means, shown in
            brackets. None means the answer is required.
        check (Callable[[str], str]): turns the raw answer into the value
            to keep, or raises InitError with the reason it was refused.
        ask_line (Callable[[str], str]): reads one line; input() outside tests.
        say (Callable[[str], None]): prints one line; print() outside tests.

    Returns:
        str: the accepted value.

    Raises:
        InitError: after MAX_ATTEMPTS refused answers, or when no answer
            can be read at all.
    """
    prompt = f"{question} [{default}]: " if default is not None else f"{question}: "
    for _ in range(MAX_ATTEMPTS):
        try:
            answer = ask_line(prompt)
        except EOFError:
            raise InitError("no answer could be read; pass the value as a flag instead.")
        try:
            return check(answer)
        except InitError as e:
            say(f"  {e}")
    raise InitError("too many refused answers.")


def gather(args, ask_line=input, say=print):
    """
    The three values, from the flags where given and from questions
    otherwise.

    Args:
        args (argparse.Namespace): the parsed `init` arguments, with
            `name`, `slug`, and `seed_url` each a string or None.

    Returns:
        dict: `name`, `slug`, and `seed_url`.

    Raises:
        InitError: when a flag value is refused, or a question cannot be
            answered.
    """
    if args.name is None or args.seed_url is None:
        say(f"Creating {args.output}. Press Enter to accept a default shown in brackets.")
        say("")

    if args.name is not None:
        name = checked_name(args.name)
    else:
        name = ask("Name of your compendium", DEFAULT_NAME, checked_name, ask_line, say)

    # The short name is asked for only in a fully interactive setup. When
    # the name came from a flag, a missing slug is derived from it, so a
    # script can pass two flags and never be asked anything.
    if args.slug is not None:
        slug = checked_slug(args.slug, name)
    elif args.name is not None:
        slug = slug_from_name(name)
    else:
        slug = ask("Short name for the output files (lowercase letters, digits, hyphens)",
                   slug_from_name(name), lambda v: checked_slug(v, name), ask_line, say)

    if args.seed_url is not None:
        seed_url = checked_seed_url(args.seed_url)
    else:
        seed_url = ask("Website to start crawling from, such as https://example.edu/docs/",
                       None, checked_seed_url, ask_line, say)

    return {"name": name, "slug": slug, "seed_url": seed_url}


### Writing ###

def render(values, example_path=EXAMPLE_CONFIG):
    """
    The settings file text for one set of values.

    The commented example is used when it can be found, with its three
    placeholder lines replaced, so the file a person gets is the one the
    documentation describes. Without it, a short file with the same
    settings is written instead.

    Args:
        values (dict): `name`, `slug`, and `seed_url`, already checked.
        example_path (pathlib.Path): where the example file is looked for.

    Returns:
        str: the file text.
    """
    try:
        text = pathlib.Path(example_path).read_text(encoding="utf-8")
    except OSError:
        text = None
    if text is not None:
        filled, counts = _fill_example(text, values)
        if all(count == 1 for count in counts):
            return filled
    return FALLBACK_TEMPLATE.format(
        name=yaml_text(values["name"]),
        slug=values["slug"],
        label=WEBSITE_LABEL,
        seed_url=yaml_text(values["seed_url"]),
    )


def _fill_example(text, values):
    """The example text with its placeholders replaced, and how many times each matched."""
    counts = []
    text, n = EXAMPLE_LABEL_LINE.subn(lambda m: f"{m.group(1)}label: {WEBSITE_LABEL}", text)
    counts.append(n)
    text, n = EXAMPLE_SEED_LINE.subn(lambda m: f"{m.group(1)}seed_url: {yaml_text(values['seed_url'])}", text)
    counts.append(n)
    text, n = EXAMPLE_NAME_LINE.subn(lambda m: f"name: {yaml_text(values['name'])}", text)
    counts.append(n)
    text, n = EXAMPLE_SLUG_LINE.subn(lambda m: f"slug: {values['slug']}", text)
    counts.append(n)
    return text, counts


def checked_settings_text(text, source):
    """
    Runs the rendered file through the same checks a build applies.

    Raises:
        InitError: if the text is not a settings file a build accepts,
            which would mean this command has a bug rather than the person.
    """
    try:
        config_from_mapping(yaml.safe_load(text), source=source)
    except (ConfigError, yaml.YAMLError) as e:
        raise InitError(f"the settings file could not be written correctly: {e}")
    return text


def write_settings(values, output, force=False, example_path=EXAMPLE_CONFIG):
    """
    Writes the settings file.

    Args:
        values (dict): `name`, `slug`, and `seed_url`, already checked.
        output (str): the path to write.
        force (bool): whether an existing file may be replaced.
        example_path (pathlib.Path): where the example file is looked for.

    Returns:
        pathlib.Path: the path written.

    Raises:
        InitError: if the file exists and `force` is off, or the rendered
            text fails the settings checks.
        OSError: if the file cannot be written.
    """
    path = pathlib.Path(output)
    if path.exists() and not force:
        raise InitError(f"{path} already exists. Edit it, or pass --force to replace it.")
    text = checked_settings_text(render(values, example_path), str(path))
    path.write_text(text, encoding="utf-8")
    return path


def run_init(args, ask_line=None, say=print, err=None):
    """
    Runs the `init` command.

    Args:
        args (argparse.Namespace): the parsed `init` arguments.
        ask_line, say: see `ask`. `ask_line` defaults to input(), looked up
            when the command runs.
        err (Callable[[str], None] | None): prints one line of error text;
            standard error outside tests.

    Returns:
        int: 0 when the file was written, 2 for a refused value or an
        existing file, 4 when the file could not be written. The numbers
        match the build command's exit codes.
    """
    err = err or (lambda line: print(line, file=sys.stderr, flush=True))
    ask_line = ask_line or input
    try:
        values = gather(args, ask_line, say)
        path = write_settings(values, args.output, args.force)
    except InitError as e:
        err(f"extractium init: {e}")
        return 2
    except OSError as e:
        err(f"extractium init: the settings file could not be written: {e}")
        return 4
    say("")
    say(f"Wrote {path}. Every setting is explained in its comments; add more sources or outputs there.")
    say(f"Next: python -m extractium.cli build --config {path} --max-pages 25")
    return 0

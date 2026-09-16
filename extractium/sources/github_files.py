"""
Summary: Which files in a code repository are worth indexing, what each
one is, and in what order they are read when a repository holds more
than a build takes. Documentation is indexed in full; a short list of
project and build files is indexed as text, because they often explain a
project faster than its prose does; generated, third-party, vendored,
test, housekeeping, binary, and credential-bearing paths are skipped.
Every rule here reads a path only, so a repository can be filtered from
its inventory before a single file body is downloaded. See
docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/sources/github_files.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
Last Modified: 2026-09-16
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
__date__ = "2026-09-16"

import posixpath
import re

from extractium.code import languages as code_languages
from extractium.readers import documents

### What Counts As Documentation ###

# Documentation extensions, read in full and chunked like a web page.
DOCUMENTATION_EXTENSIONS = (".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc")

# Files that are documentation whatever extension they carry, or carry
# none at all. Matched on the name's stem, so README, README.md, and
# README.rst are all the same file to this rule. A README inside docs/,
# inside a package, or inside an examples folder counts exactly as much
# as the one at the repository root.
#
# These are the files people search: what changed, how to contribute,
# where to report a vulnerability, who wrote it. Licence, notice,
# citation, and conduct files are not here; they are boilerplate the
# same in every project, and the housekeeping rule below skips them.
DOCUMENTATION_STEMS = (
    "readme", "changelog", "changes", "history", "contributing", "security",
    "authors", "contributors", "governance", "support", "maintainers",
)

# Project and build files indexed as text. Each names what a project is
# made of, who maintains it, and how it is run, in a few dozen lines.
MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "package.json", "cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "description", "namespace", "renv.lock", "gemfile", "composer.json",
    "environment.yml", "environment.yaml", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "makefile", "cmakelists.txt", ".gitmodules",
    ".env.example", ".env.sample", ".env.template", "codemeta.json", "conda.yaml", "conda.yml",
})

# Manifests recognised by shape rather than by exact name. A requirements
# file with "lock" in its name is a lock file, not a manifest, so the two
# rules agree on it.
MANIFEST_PATTERNS = (
    re.compile(r"^requirements(?![^/]*lock)[^/]*\.txt$", re.I),   # requirements-dev.txt and friends
    re.compile(r"^[^/]+\.(csproj|fsproj|vbproj|sln)$", re.I),
    re.compile(r"^[^/]+\.podspec$", re.I),
)

# Workflow definitions say how a project is built, tested, and released.
# GitHub Actions runs workflows from the repository root only, so a
# workflow file nested anywhere else is a template that never runs.
WORKFLOW_DIRECTORY = ".github/workflows"
WORKFLOW_EXTENSIONS = (".yml", ".yaml")


### What Is Never Read ###

# Directories are matched as a whole path segment, so a project
# directory named "distribution" is not caught by "dist", and only the
# folders above a file count, never the file's own name.

# Build output and installed environments. "bin" holds what a build
# produced, and "data" holds the files a project reads and writes rather
# than anything written to be read. Skipping "data" also keeps a folder
# of participant records out of an index by default, which matters more
# here than the occasional README lost with it.
BUILD_AND_ENVIRONMENT_DIRECTORIES = frozenset({
    "node_modules", "vendor", "dist", "build", "target", "coverage", "htmlcov",
    "venv", "env", "__pycache__", "bower_components", "packrat", "site-packages",
    "obj", "bin", "data",
})

# Somebody else's code copied into the repository. A git submodule never
# reaches this list: the tree lists it as a commit entry with nothing
# under it, so there is nothing to skip.
VENDORED_DIRECTORIES = frozenset({
    "third_party", "thirdparty", "third-party", "3rdparty", "external", "externals",
    "extern", "deps", "contrib", "submodules", "vendored", "vendors",
})

# Code a tool wrote from a schema or a grammar. The source it was written
# from is in the repository already, and that is the file worth reading.
GENERATED_DIRECTORIES = frozenset({
    "generated", "__generated__", "gen", "autogen", "autogenerated", "codegen",
})

# Test suites, their fixtures, and their recorded outputs. A fixture
# folder holds copies of other people's pages and files, and a golden or
# snapshot folder holds a program's output, neither of which anybody
# searches for. Only folders are skipped: a test_app.py beside its code
# is still read.
TEST_DIRECTORIES = frozenset({
    "tests", "test", "testing", "spec", "specs", "__tests__", "fixtures", "fixture",
    "testdata", "test_data", "golden", "snapshots", "__snapshots__", "mocks", "__mocks__",
})

SKIP_DIRECTORIES = (
    BUILD_AND_ENVIRONMENT_DIRECTORIES | VENDORED_DIRECTORIES
    | GENERATED_DIRECTORIES | TEST_DIRECTORIES
)

# renv keeps a project's installed R packages here: thousands of files of
# somebody else's source. The lock file beside it is what matters.
SKIP_PATH_PREFIXES = ("renv/library/", "renv/staging/", ".rproj.user/")

# Any path segment that starts with a dot is skipped: tool settings,
# editor folders, version-control folders, and dotfiles at the root are
# configuration for programs, not writing for people. The exceptions are
# the few dotfiles that document a project (.gitmodules, .env.example and
# its siblings) and the workflow files at the repository root.
DOTFILE_EXCEPTIONS = frozenset({".gitmodules", ".env.example", ".env.sample", ".env.template"})

# Extensions whose bytes are not indexable text: binaries, media,
# archives, compiled objects, stored data, and fonts. Word, OpenDocument,
# RTF, and PDF files are absent because a reader turns them into text
# when the source's read_documents setting is on; the binary .doc format
# has no reader and stays here. An SVG is an image whatever its bytes.
SKIP_EXTENSIONS = frozenset({
    "exe", "dll", "so", "dylib", "o", "obj", "a", "lib", "class", "jar", "war",
    "pyc", "pyo", "pyd", "wasm", "bin", "dat", "db", "sqlite", "sqlite3",
    "rdb", "rda", "rds", "sav", "dta", "mat", "npy", "npz", "parquet", "feather",
    "zip", "gz", "tgz", "bz2", "xz", "7z", "rar", "tar", "dmg", "iso", "apk", "msi", "deb", "rpm",
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "ico", "webp", "avif", "heic", "psd", "ai",
    "svg",
    "mp3", "mp4", "wav", "ogg", "m4a", "flac", "webm", "mov", "avi", "wmv", "mkv",
    "woff", "woff2", "ttf", "eot", "otf",
    "doc", "xls", "xlsx", "ppt", "ods",
    "map",
})

# Settings files read by programs, styling, and query files. None of them
# is prose, and none is code the parsers know. A file of one of these
# kinds that is a project manifest, such as pyproject.toml, package.json,
# or environment.yml, is recognised as a manifest before this rule is
# reached.
UNREAD_EXTENSIONS = frozenset({
    "toml", "yml", "yaml", "json", "ini", "cfg", "conf", "properties", "xml",
    "css", "scss", "sass", "less",
    "scm",
})

# C and C++ headers. A header declares what its source file defines, and
# the source file is the one the parsers read; a library's public headers
# are also where a vendored dependency's forty thousand files come from.
HEADER_EXTENSIONS = frozenset({"h", "hpp", "hh", "hxx", "inl", "tpp", "ipp"})

# Files that hold, or are likely to hold, a credential. A private key
# committed by mistake is still a private key: it is never downloaded,
# never cached, and never indexed.
SECRET_NAME_RE = re.compile(
    r"(^|/)(\.env(\.[^/]*)?|\.netrc|\.npmrc|\.pypirc|id_rsa|id_dsa|id_ecdsa|id_ed25519)$",
    re.I,
)
SECRET_EXTENSIONS = frozenset({
    "pem", "key", "p12", "pfx", "jks", "keystore", "crt", "cer", "der", "asc", "gpg",
})

# .env.example is the deliberate exception: it lists the variables a
# project needs, with placeholder values, which is documentation of how
# to run the project rather than a secret.
SECRET_EXCEPTIONS = frozenset({".env.example", ".env.sample", ".env.template"})

# Machine-written files recognised by name: protocol buffer output,
# designer and generated C#, anything marked .generated, and minified or
# bundled scripts and styles. Each is derived from source that is in the
# repository anyway, and a bundle is somebody else's code as often as
# the project's own.
GENERATED_NAME_RE = re.compile(
    r"(\.pb\.(h|cc|go)|_pb2(_grpc)?\.py|\.g\.cs|\.designer\.cs|\.generated\.[^.]+"
    r"|\.min\.[^.]+|\.(bundle|chunk|umd|esm)\.js)$",
    re.I,
)

# A page or script longer than this was written by a program, not a
# person: a rendered report, a data dictionary, a bundled application.
# Checked against the size the inventory reports, so no request is spent
# on it. Prose files are not held to it, because a long manual is a
# manual.
MAX_HANDWRITTEN_BYTES = 500_000
GENERATED_BY_SIZE_EXTENSIONS = frozenset({"js", "mjs", "cjs", "jsx", "html", "htm"})

# Single-file libraries that projects copy in whole rather than install:
# the sqlite amalgamation, cJSON, the stb headers, miniz, and the
# browser libraries most often committed beside a page. Only the
# library's own file names are matched; a shell.c beside sqlite3.c is
# not assumed to be sqlite's, and d3chart.js is somebody's chart.
THIRD_PARTY_FILE_RE = re.compile(
    r"^(sqlite3(ext)?\.(c|h)|cjson[^/]*\.(c|h)|stb_[^/]+\.h|miniz\.(c|h)"
    r"|(jquery|bootstrap|lodash|moment|d3|three)([.-][^/]*)?\.(js|css))$",
    re.I,
)

# Files every project carries in the same words: licence and notice
# texts, citation metadata, conduct codes, and the instruction files
# written for coding agents rather than for people. Matched on the stem,
# with or without an extension, and only where the name is not a code
# file, so agent.py and notice.py stay code.
HOUSEKEEPING_RE = re.compile(
    r"^(license|licence|copying)([._-][^/]*)?$"
    r"|^(notice|citation|code_of_conduct|claude|agents?|conventions|codex|gemini|skills"
    r"|copilot-instructions)(\.[^/]*)?$",
    re.I,
)

# Dependency lock files are long lists of package names and version
# numbers, and the manifest beside them already records what the project
# declared. A lock file is recognised by "lock" as a word in its name
# (package-lock.json, yarn.lock, uv.lock, poetry.lock, Cargo.lock,
# requirements-lock.txt) plus the few named without the word. renv.lock
# is the exception, kept in MANIFEST_NAMES above, because an R project's
# DESCRIPTION often pins nothing at all. Only names that are not code
# files are checked, so lock.py stays code, and "lock" must stand alone,
# so deadlock.md and lockfile.md are prose.
LOCK_TOKEN_RE = re.compile(r"(^|[._-])lock($|[._-])", re.I)
LOCK_FILE_NAMES = frozenset({"go.sum", "gradle.lockfile", "bun.lockb"})
KEPT_LOCK_FILES = frozenset({"renv.lock"})


### Reading Order ###

# When a repository holds more indexable files than a build reads, the
# files are read in this order of kind, then shallowest first, then by
# name, so the root README always comes first and code is the first
# thing left out. A README is the one file every reader opens; the
# rest of the documentation and the manifests say what the project is;
# code is the largest kind and the one a reader can least use on its
# own.
READ_ORDER = ("root readme", "readme", "documentation", "manifest", "document", "code")


### Classification ###

def _name(path):
    """The last segment of a repository path, lowercased."""
    return posixpath.basename(path).lower()


def _stem(name):
    """The name with one extension removed: 'readme.md' -> 'readme'."""
    stem, _, extension = name.rpartition(".")
    return stem if stem and extension else name


def _extension(name):
    """The name's extension without its dot, or an empty string when it has none."""
    stem, _, extension = name.rpartition(".")
    return extension if stem else ""


def is_workflow(path):
    """True for a GitHub Actions workflow file at the repository root."""
    lowered = path.lower()
    return lowered.startswith(WORKFLOW_DIRECTORY + "/") and lowered.endswith(WORKFLOW_EXTENSIONS)


def is_lock_file(name):
    """True when a lowercased file name is a dependency lock file that is not read."""
    if name in KEPT_LOCK_FILES:
        return False
    if name in LOCK_FILE_NAMES:
        return True
    return bool(LOCK_TOKEN_RE.search(name)) and not code_languages.is_code_path(name)


def is_housekeeping(name):
    """True when a lowercased file name is a licence, notice, citation, conduct, or agent-instruction file."""
    return bool(HOUSEKEEPING_RE.match(name)) and not code_languages.is_code_path(name)


def is_skipped_path(path):
    """
    True when nothing at this path is ever worth downloading.

    Args:
        path (str): a repository-relative path, with forward slashes.

    Returns:
        bool: True for build, vendored, generated, and test directories,
        every dot-prefixed folder or file but the few that document a
        project, anything that holds a credential, lock files, generated
        and third-party files recognised by name, housekeeping files,
        C and C++ headers, and binary or media files.
    """
    lowered = path.lower()
    segments = lowered.split("/")
    if any(segment in SKIP_DIRECTORIES for segment in segments[:-1]):
        return True
    if any(lowered.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return True

    name = segments[-1]
    if name in DOTFILE_EXCEPTIONS or is_workflow(lowered):
        return False
    if SECRET_NAME_RE.search(lowered) or _extension(name) in SECRET_EXTENSIONS:
        return True
    if any(segment.startswith(".") for segment in segments):
        return True
    if is_lock_file(name):
        return True
    if GENERATED_NAME_RE.search(name) or THIRD_PARTY_FILE_RE.match(name):
        return True
    if is_housekeeping(name):
        return True
    extension = _extension(name)
    return extension in HEADER_EXTENSIONS or extension in SKIP_EXTENSIONS


def is_generated_by_size(path, size):
    """
    True when a page or script is too long to have been written by hand.

    Args:
        path (str): a repository-relative path.
        size (int | None): the size the inventory reports, in bytes, or
            None when it reports none. An unknown size is not held
            against the file.
    """
    if size is None:
        return False
    return _extension(_name(path)) in GENERATED_BY_SIZE_EXTENSIONS and size > MAX_HANDWRITTEN_BYTES


def is_documentation(path):
    """True when the file at path is prose to index in full."""
    name = _name(path)
    if name.endswith(DOCUMENTATION_EXTENSIONS):
        return True
    return _stem(name) in DOCUMENTATION_STEMS


def is_manifest(path):
    """True when the file at path is a project or build file indexed as text."""
    name = _name(path)
    if name in MANIFEST_NAMES:
        return True
    if any(pattern.match(name) for pattern in MANIFEST_PATTERNS):
        return True
    return is_workflow(path)


def classify(path):
    """
    What a repository file is, from its path alone.

    Args:
        path (str): a repository-relative path, with forward slashes.

    Returns:
        str | None: "documentation", "manifest", "document", "code", or
        None when the file is not read at all. A code file is not
        chunked as prose: what is indexed for one is the structure the
        parsers find in it, which is why it carries a label of its own.
        A document is a Word, OpenDocument, RTF, or PDF file, read only when
        the source's read_documents setting is on.
    """
    if not path or path.endswith("/") or is_skipped_path(path):
        return None
    # Manifests are checked first because some carry a documentation
    # extension or a settings extension: requirements.txt is a dependency
    # list, not prose, and pyproject.toml is a manifest, not a settings
    # file nobody reads.
    if is_manifest(path):
        return "manifest"
    if _extension(_name(path)) in UNREAD_EXTENSIONS:
        return None
    if is_documentation(path):
        return "documentation"
    if is_document(path):
        return "document"
    if code_languages.is_code_path(path):
        return "code"
    # Anything else is a file no rule recognises: not prose, not a
    # manifest, not a document a reader turns into text, and not a
    # language the parsers know. It is left alone rather than guessed at.
    return None


def is_document(path):
    """True when the file at path is a Word, OpenDocument, RTF, or PDF file a reader turns into text."""
    return _extension(_name(path)) in documents.DOCUMENT_EXTENSIONS


def content_type_for(path):
    """
    The CONTENT_TYPES value for an indexed repository file.

    Returns:
        str: "readme" for a README anywhere in the tree, "manifest" for a
        project or build file, "text" for other documentation.
    """
    if is_manifest(path):
        return "manifest"
    return "readme" if _stem(_name(path)) == "readme" else "text"


def read_priority(path, kind):
    """
    Where a file falls in the reading order, for sorting.

    Args:
        path (str): a repository-relative path.
        kind (str): what classify() said the file is, passed in so a
            repository of forty thousand paths is not classified twice.

    Returns:
        tuple[int, int, str]: the rank of the file's kind in READ_ORDER,
        how many folders deep it sits, and its lowercased path, so that
        sorting by this tuple reads the root README first, then every
        other README shallowest first, and code last.
    """
    lowered = path.lower()
    if kind == "documentation" and _stem(_name(path)) == "readme":
        kind = "readme" if "/" in lowered else "root readme"
    rank = READ_ORDER.index(kind) if kind in READ_ORDER else len(READ_ORDER)
    return (rank, lowered.count("/"), lowered)


### Presentation ###

# What a manifest is for, in plain words, so a reader who has never seen
# the format knows why the file is in front of them. A file not listed
# here is introduced by its own name alone.
MANIFEST_ROLES = {
    "pyproject.toml": "Python project definition and dependencies",
    "setup.cfg": "Python project definition",
    "setup.py": "Python project definition",
    "requirements.txt": "Python dependencies",
    "package.json": "JavaScript project definition and dependencies",
    "cargo.toml": "Rust project definition and dependencies",
    "go.mod": "Go module definition and dependencies",
    "pom.xml": "Java project definition and dependencies",
    "build.gradle": "Gradle build definition",
    "build.gradle.kts": "Gradle build definition",
    "description": "R package definition and dependencies",
    "namespace": "R package exports and imports",
    "renv.lock": "R environment, with every package version pinned",
    "gemfile": "Ruby dependencies",
    "composer.json": "PHP project definition and dependencies",
    "environment.yml": "Conda environment definition",
    "environment.yaml": "Conda environment definition",
    "dockerfile": "Container image build steps",
    "docker-compose.yml": "Container services and how they are wired together",
    "docker-compose.yaml": "Container services and how they are wired together",
    "makefile": "Build and task definitions",
    ".gitmodules": "Repositories included as submodules",
    ".env.example": "Environment variables the project needs, with placeholder values",
    ".env.sample": "Environment variables the project needs, with placeholder values",
    ".env.template": "Environment variables the project needs, with placeholder values",
}


def manifest_role(path):
    """A short phrase naming what a manifest is for, or an empty string when unknown."""
    name = _name(path)
    if name in MANIFEST_ROLES:
        return MANIFEST_ROLES[name]
    if name.startswith("requirements") and name.endswith(".txt"):
        return MANIFEST_ROLES["requirements.txt"]
    if is_workflow(path):
        return "Automated workflow run by GitHub Actions"
    return ""


def title_for(repository, path):
    """
    The heading a repository file is indexed under.

    Args:
        repository (str): "owner/name".
        path (str): the repository-relative path.

    Returns:
        str: the repository and path, plus the manifest's role when there
        is one, so a search result says what the file is without the
        reader opening it.
    """
    role = manifest_role(path)
    heading = f"{repository}: {path}"
    return f"{heading} ({role})" if role else heading


def categories_for(owner, repository, path):
    """
    The hierarchy a repository file sits in, outermost first.

    Uses the same shape the GitHub site handler produces for a crawled
    file -- owner, repository, then the folders above the file -- so a
    document read through the API and the same document read through a
    web crawl group together rather than appearing as two hierarchies.

    Args:
        owner (str): the account that owns the repository.
        repository (str): the repository name, without the owner.
        path (str): the repository-relative path of the file.

    Returns:
        tuple[str, ...]: owner, repository, then each containing folder.
    """
    folders = [segment for segment in posixpath.dirname(path).split("/") if segment]
    return (owner, repository, *folders)

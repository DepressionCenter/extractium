"""
Summary: Which files in a code repository are worth indexing, and what
each one is. Documentation is indexed in full; a short list of project
and build files is indexed as text, because they often explain a project
faster than its prose does; generated, third-party, binary, and
credential-bearing paths are skipped. Every rule here reads a path only,
so a repository can be filtered from its inventory before a single file
body is downloaded. See docs/github-repository-indexing.md.

This file is part of Extractium™
extractium/sources/github_files.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-09
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
__date__ = "2026-09-09"

import posixpath
import re

### What Counts As Documentation ###

# Documentation extensions, read in full and chunked like a web page.
DOCUMENTATION_EXTENSIONS = (".md", ".markdown", ".txt", ".rst", ".adoc", ".asciidoc")

# Files that are documentation whatever extension they carry, or carry
# none at all. Matched on the name's stem, so README, README.md, and
# README.rst are all the same file to this rule. A README inside docs/,
# inside a package, or inside an examples folder counts exactly as much
# as the one at the repository root.
DOCUMENTATION_STEMS = (
    "readme", "license", "licence", "notice", "copying", "changelog", "changes",
    "history", "contributing", "security", "code_of_conduct", "authors",
    "contributors", "citation", "governance", "support", "maintainers",
)

# Project and build files indexed as text. Each names what a project is
# made of, who maintains it, and how it is run, in a few dozen lines.
MANIFEST_NAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "package.json", "cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle",
    "description", "namespace", "renv.lock", "gemfile", "composer.json",
    "environment.yml", "environment.yaml", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "makefile", "cmakelists.txt", ".gitmodules",
    ".env.example", "codemeta.json", "conda.yaml", "conda.yml",
})

# Manifests recognised by shape rather than by exact name.
MANIFEST_PATTERNS = (
    re.compile(r"^requirements[^/]*\.txt$", re.I),          # requirements-dev.txt and friends
    re.compile(r"^[^/]+\.(csproj|fsproj|vbproj|sln)$", re.I),
    re.compile(r"^[^/]+\.podspec$", re.I),
)

# Workflow definitions say how a project is built, tested, and released.
WORKFLOW_DIRECTORY = ".github/workflows"
WORKFLOW_EXTENSIONS = (".yml", ".yaml")


### What Is Never Read ###

# Directories holding generated output, third-party code, or a virtual
# environment. Matched as a whole path segment, so a project directory
# named "distribution" is not caught by "dist".
SKIP_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "target",
    "coverage", "htmlcov", ".venv", "venv", "env", "__pycache__", ".cache",
    ".tox", ".mypy_cache", ".pytest_cache", ".idea", ".vscode", ".gradle",
    "bower_components", "packrat", "site-packages", "obj",
})

# renv keeps a project's installed R packages here: thousands of files of
# somebody else's source. The lock file beside it is what matters.
SKIP_PATH_PREFIXES = ("renv/library/", "renv/staging/", ".rproj.user/")

# Extensions whose bytes are not indexable text: binaries, media,
# archives, compiled objects, stored data, and fonts.
SKIP_EXTENSIONS = frozenset({
    "exe", "dll", "so", "dylib", "o", "obj", "a", "lib", "class", "jar", "war",
    "pyc", "pyo", "pyd", "wasm", "bin", "dat", "db", "sqlite", "sqlite3",
    "rdb", "rda", "rds", "sav", "dta", "mat", "npy", "npz", "parquet", "feather",
    "zip", "gz", "tgz", "bz2", "xz", "7z", "rar", "tar", "dmg", "iso", "apk", "msi", "deb", "rpm",
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "ico", "webp", "avif", "heic", "psd", "ai",
    "mp3", "mp4", "wav", "ogg", "m4a", "flac", "webm", "mov", "avi", "wmv", "mkv",
    "woff", "woff2", "ttf", "eot", "otf",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "map",
})

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

# Generated JavaScript and CSS: machine-written, one enormous line, and
# always derived from source that is in the repository anyway.
MINIFIED_RE = re.compile(r"\.min\.(js|css)$", re.I)

# Dependency lock files are long lists of package names and version
# numbers, and the manifest beside them already records what the project
# declared. renv.lock is the exception, kept in MANIFEST_NAMES above,
# because an R project's DESCRIPTION often pins nothing at all.
LOCK_FILE_NAMES = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pdm.lock",
    "uv.lock", "cargo.lock", "gemfile.lock", "composer.lock", "pipfile.lock",
    "packages.lock.json", "go.sum",
})


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


def is_skipped_path(path):
    """
    True when nothing at this path is ever worth downloading.

    Args:
        path (str): a repository-relative path, with forward slashes.

    Returns:
        bool: True for generated or third-party directories, binary and
        media files, minified output, lock files, and anything that holds
        a credential.
    """
    lowered = path.lower()
    segments = lowered.split("/")
    if any(segment in SKIP_DIRECTORIES for segment in segments[:-1]):
        return True
    if any(lowered.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return True

    name = segments[-1]
    if name in SECRET_EXCEPTIONS:
        return False
    if SECRET_NAME_RE.search(lowered) or _extension(name) in SECRET_EXTENSIONS:
        return True
    if name in LOCK_FILE_NAMES or MINIFIED_RE.search(name):
        return True
    return _extension(name) in SKIP_EXTENSIONS


def is_documentation(path):
    """True when the file at path is prose to index in full."""
    name = _name(path)
    if name.endswith(DOCUMENTATION_EXTENSIONS):
        return True
    return _stem(name) in DOCUMENTATION_STEMS


def is_manifest(path):
    """True when the file at path is a project or build file indexed as text."""
    lowered = path.lower()
    name = _name(path)
    if name in MANIFEST_NAMES:
        return True
    if any(pattern.match(name) for pattern in MANIFEST_PATTERNS):
        return True
    return lowered.startswith(WORKFLOW_DIRECTORY + "/") and name.endswith(WORKFLOW_EXTENSIONS)


def classify(path):
    """
    What a repository file is, from its path alone.

    Args:
        path (str): a repository-relative path, with forward slashes.

    Returns:
        str | None: "documentation", "manifest", or None when the file is
        not indexed as text. None covers both skipped paths and ordinary
        source files, which carry no prose to chunk; reading their
        structure is a separate capability.
    """
    if not path or path.endswith("/") or is_skipped_path(path):
        return None
    # Manifests are checked first because some carry a documentation
    # extension: requirements.txt is a dependency list, not prose, and
    # calling it documentation would lose the label that says so.
    if is_manifest(path):
        return "manifest"
    if is_documentation(path):
        return "documentation"
    return None


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
}


def manifest_role(path):
    """A short phrase naming what a manifest is for, or an empty string when unknown."""
    name = _name(path)
    if name in MANIFEST_ROLES:
        return MANIFEST_ROLES[name]
    if name.startswith("requirements") and name.endswith(".txt"):
        return MANIFEST_ROLES["requirements.txt"]
    if path.lower().startswith(WORKFLOW_DIRECTORY + "/"):
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

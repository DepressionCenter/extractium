<!--
This file is part of Extractium™
docs/dspace-repository-indexing.md
Author(s): Gabriel Mongefranco
Created: 2026-09-09
Last Modified: 2026-09-10
Summary: Why a DSpace repository such as the University of Michigan
Library's Deep Blue cannot be crawled, what its own interface holds
instead, and how the dspace source reads a collection's deposits: the
metadata, the three kinds of address each deposit carries, the text the
repository extracted from the deposited files, and the change stamp that
keeps a rebuild from downloading anything.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## Indexing a DSpace Repository

[Back to the project README](../README.md)

## Summary

This page describes the source that reads scholarly deposits out of a DSpace repository, such as the University of Michigan Library's Deep Blue. It explains why the ordinary web crawler cannot read one, what the repository's own interface holds instead, and how the source uses it. It was the design for Phase 9 of the [implementation plan](implementation-plan.md), and it now records what was built.

Everything here about the interface was checked against Deep Blue, first on 2026-09-09 and again on 2026-09-10 while the source was written. The results are recorded rather than assumed, and where a check changed the design, this page says so.

## Who this page is for

Whoever maintains this source, and anyone deciding whether to point Extractium at a repository of their own. You do not need to know DSpace. You do need to know what a knowledge base is for.

## Why the crawler cannot read this

Deep Blue looks like an ordinary website and is not one. A collection page is roughly 650 KB of markup carrying about 2,300 characters of visible text, all of it navigation, and the list of deposits in the collection is not in it. The page is assembled in the reader's browser after it loads.

Crawling one adds the collection's name and nothing else. The sitemap does not help either: it is refused to anything that is not a browser.

This is the same problem GitHub's file viewer has, and it has the same answer. The repository publishes a machine interface, so the build reads that instead of scraping what a browser happened to draw. See [GitHub repository indexing](github-repository-indexing.md) for the earlier case.

## What Deep Blue actually is

| Fact | Value |
|---|---|
| Software | DSpace 7.6 |
| What a reader opens | `https://deepblue.lib.umich.edu` |
| Where the interface lives | `https://backend.production.deepblue-documents.lib.umich.edu/server/api` |
| Collections in scope | `3acf951c-e107-4b8d-8f7d-ced171665b11` (Eisenberg Family Depression Center), `7503b0dc-27a2-4ce9-bcbc-50b339ecb486` (MeTRIC) |

**The two addresses are different hosts, and that is the first thing to get right.** `deepblue.lib.umich.edu/server/api` answers with a web page, not data: it is the reader's site, which returns its own shell for any address it does not recognize. A build pointed there stops with a message naming that mistake, rather than failing further along where the cause would be hard to see.

The real address is written into the reader's site as part of its own configuration, under the name `dspaceServer`. That is how it was found, and how to find it for another repository. It is not guessable, so it is a setting rather than something the plugin derives.

## What a collection holds

A collection is a paged list of deposits. Each deposit is a scholarly work: a symposium poster, a guide, a piece of documentation. The reader's site shows them like this:

```text
MeTRIC (Mobile Technologies Research Innovation Collaborative)
Permanent URI for this collection  https://hdl.handle.net/2027.42/195645

Recent Deposits          Now showing 1 - 20 of 33

  2026 MeTRIC Symposium Mobile Device Gallery: Wearables in Research
  (2026-01-26)   Mongefranco, Gabriel     PDF file (3.96 MB)

  Essential Guide to Sharing Code in Biomedical Research
  (2024-07-03)   Burnette, Ian            PDF file (372.8 KB)
```

Every entry offers two links: one to the deposit's own page, and one straight to the file. **The deposit page is the one to follow.** It carries the abstract, the identifiers, and the list of files; the file link is only the bytes.

A deposit page looks like `https://deepblue.lib.umich.edu/items/6d216554-d95a-4dce-ba67-22d2da4d2fcc`.

## What a deposit carries

Read through the interface, one deposit gives everything the index needs. This is a real record, shortened:

| Field | Example | What it is for |
|---|---|---|
| `dc.title` | 2026 MeTRIC Symposium Mobile Device Gallery: Wearables in Research | The heading |
| `dc.description.abstract` | The 2026 MeTRIC Symposium at the University of Michigan... | **The most important part.** A summary written by a person |
| `dc.contributor.author` | Mongefranco, Gabriel | Attribution |
| `dc.date.issued` | 2026-01-26 | When it was published |
| `dc.subject` | Wearables, MeTRIC, Mobile Technologies | Keywords the depositor chose |
| `dc.publisher`, `dc.rights` | Eisenberg Family Depression Center; Attribution-ShareAlike 4.0 International | Who published it, and on what terms |
| `handle` | `2027.42/201249` | The permanent address |
| `lastModified` | 2026-05-16T09:33:10Z | When the record last changed |

### The identifiers need untangling

`dc.identifier.uri` is a **list**, and it mixes three different kinds of address:

```text
https://teamdynamix.umich.edu/TDClient/210/DepressionCenter/KB/ArticleDet?ID=14738
https://hdl.handle.net/2027.42/201249
https://doi.org/10.7302/28333
```

They are told apart by their host, and each is kept for a different reason:

| Kind | Recognised by | Where it leads | Keep it because |
|---|---|---|---|
| Handle | `hdl.handle.net` | Back to this deposit on Deep Blue | It is the permanent citation |
| DOI | `doi.org` | Back to Deep Blue when Deep Blue minted it, or out to Zenodo, figshare, or wherever else | It is how the work is cited in the literature, and it may be the only route to the version of record |
| Anything else | Neither host | Wherever the depositor pointed | It is often the project's real documentation. Here it points at the knowledge base article for the same work |

All three are recorded. A reader who finds the deposit should be able to reach the documentation, and a reader who finds the documentation should be able to cite the deposit.

That third kind also creates a link between sources: this deposit and the knowledge-base article describe one piece of work. They are two documents with two addresses, so nothing collides, but a future enrichment pass could join them.

## Reading the files

Each deposit has files, and the files are the point. A poster's abstract is a paragraph; the poster itself is the content.

**DSpace has already extracted the text, and this is the single most useful thing on this page.** Alongside the original file, a deposit carries a `TEXT` bundle holding the plain text of that file, pulled out by the repository when the file was deposited. It is fetched as `text/plain` in one request, and it needs no PDF library, no Word reader, and no archive handling.

For the poster above: a 4,148,128-byte PDF, and an 8,780-byte text file beside it, already extracted.

That answers "index the content of those files" without adding a single dependency. The alternative — parsing PDFs in this build — would mean a new library, a new class of malformed-input risk, and worse text than the repository already produced.

### What the bundles are called

| Bundle | What is in it | Used |
|---|---|---|
| `ORIGINAL` | The deposited files themselves | Recorded: name, size, type, and download address |
| `TEXT` | Text already extracted from those files | **Indexed** |
| `THUMBNAIL` | Preview images | No |
| `LICENSE`, `CC-LICENSE` | Deposit agreements and license files | No. Boilerplate, identical across deposits |

### How complete the extracted text is

Counted across both collections on 2026-09-10, by the source itself:

| Collection | Deposits | With file text in the index |
|---|---|---|
| Eisenberg Family Depression Center | 9 | 7 |
| MeTRIC | 33 | 28 |
| **Total** | **42** | **35 (83%)** |

Every deposited file in both collections is a PDF or a PNG. There are no Word documents and no archives today, though the source does not assume that stays true.

The seven deposits with no file text divide into three kinds:

- **Two are images.** Posters deposited as PNG, with no `TEXT` bundle at all. There is no text to extract without optical character recognition, which is out of scope.
- **Four are PDFs that produced no `TEXT` bundle.** Most likely they are images inside a PDF wrapper, which is what happens when a poster is exported from design software.
- **One has a `TEXT` bundle holding a single newline.** The repository tried, and got nothing. This is why the source counts readable text rather than counting bundles: a one-byte file would otherwise be reported as a deposit whose contents are in the index.

All three kinds are still indexed, from their title, abstract, authors, and subjects. **A deposit is never skipped for having no readable file**, and the record says plainly that the file's contents are not in the index, so a search that misses it is explainable.

## One request covers a hundred deposits

The listing takes an `embed` parameter, and `bundles/bitstreams` makes it return each deposit's bundles and files alongside its metadata. This was an open question in the design, and the answer is yes: nothing needs a second request per deposit.

So one request brings back, for a hundred deposits at a time, their metadata, the change stamp that says whether each has moved, and the name, size, and address of every file attached to them.

## Knowing whether to read it again

The listing carries `lastModified` for every deposit, so that one request is enough to tell what has changed since the last build.

That makes each build:

1. Confirm each collection exists, and read its name. One request per collection.
2. Ask for the listing. One request per hundred deposits.
3. Compare each deposit's `lastModified` with what the cache recorded.
4. Download extracted text only for the deposits that changed.

A rebuild of a collection nobody has touched costs those first two requests and downloads nothing. Measured against both Deep Blue collections on 2026-09-10: the first build made 37 text downloads, and the second made none.

Two limits are worth writing down rather than discovering later:

- **The collection itself reports no modification date.** There is no single stamp to check; the answer comes from the listing.
- **Sorting by `lastModified` is refused** with an HTTP 422. Sorting by `dc.date.accessioned` works, and is the newest *deposit* date rather than the newest *edit*. Use it for a quick "anything new?" check, but use the per-deposit `lastModified` from the listing for what to re-read.

A deposit that has been withdrawn simply stops appearing in the listing, and the next build stops producing a document for it. Nothing extra is needed.

## The plugin

### Call it `dspace`, not `deep_blue`

Nothing in the design above is specific to Deep Blue. It is all plain DSpace 7, which runs a large share of the world's university repositories. A `dspace` source with Deep Blue as its first configured instance costs nothing extra to build and works for any of them; a `deep_blue` source would have to be written again for the next repository somebody asks about.

The only Deep Blue facts are its two addresses and its two collection identifiers, and those belong in a settings file rather than in code. Every source names itself with a `label`, so "Deep Blue Documents" is what a reader sees whatever the plugin is called.

### Settings

```yaml
sources:
  - type: dspace
    label: Deep Blue Documents
    api_url: https://backend.production.deepblue-documents.lib.umich.edu/server/api
    site_url: https://deepblue.lib.umich.edu
    collections:
      - https://hdl.handle.net/2027.42/195355    # Eisenberg Family Depression Center
      - https://hdl.handle.net/2027.42/195645    # MeTRIC
    include_full_text: true
    max_file_bytes: 2000000
```

| Option | Default | What it does |
|---|---|---|
| `api_url` | required | Where the repository's interface lives. Not guessable; see above for how to find it |
| `site_url` | required | Where a reader opens a deposit. Recorded on every document so a search result is a link a person can follow |
| `label` | required, as for every source | What this repository is called in the index. See [configuration reference](configuration.md) |
| `collections` | required, at least one | Which collections to read. A handle link, a bare handle, the address a browser shows, or a bare identifier; see below |
| `include_full_text` | `true` | Whether extracted text is indexed as well as the description |
| `max_file_bytes` | 2000000 | Largest extracted text file to read. Anything larger is named and skipped |

**Collections are named, never discovered.** A repository holds hundreds of collections belonging to everybody at a university. The same rule that governs GitHub accounts applies here for the same reason: a build reads what its operator asked for, and nothing it merely found a link to.

**Four ways to write one collection.** A repository publishes a handle link beside each collection, and following that link lands on an address carrying the collection's identifier instead. An operator has one or the other in hand, so both are accepted, with or without their scheme and host:

| Written as | Example |
|---|---|
| The handle link | `https://hdl.handle.net/2027.42/195355` |
| A bare handle | `2027.42/195355` |
| The address a browser shows | `https://deepblue.lib.umich.edu/collections/3acf951c-e107-4b8d-8f7d-ced171665b11` |
| A bare identifier | `3acf951c-e107-4b8d-8f7d-ced171665b11` |

A handle is resolved through the interface's own `pid/find` address, which answers with a redirect to the record the handle names. The source reads that redirect rather than following it, for two reasons: the address it points at says what kind of record the handle names, so a handle naming one deposit is refused instead of searched as though it were a collection; and an address pointing anywhere other than the configured interface is refused rather than requested.

**Every collection is confirmed before anything is searched.** This turned out to matter far more than "so its name can be read". A search scope the interface does not recognize is not refused: on 2026-09-10, a made-up scope was answered with all 176,555 deposits in Deep Blue. A well-formed identifier for a collection that does not exist answers `500`. Reading the collection first turns both into a plain "the repository has no collection X", and it is why a configured identifier is checked against the shape of a UUID before any request is made.

### There is no fall back to crawling

The GitHub source drops to a documentation crawl when its interface cannot be read. That is not worth doing here, because the pages a crawler would reach hold no deposits. If the interface cannot be read, the source says so and stops. A quiet fall back that produced a collection's title and nothing else would be worse than an error.

### What a deposit becomes

One document per deposit, not two. The abstract and the extracted text describe one work, and splitting them would put two results in front of a reader for one thing. The chunker cuts long text into sections anyway.

- **URL**: the deposit's page on the reader's site, `<site_url>/items/<uuid>`. Somewhere a person can actually go.
- **Title**: `dc.title`.
- **Body**: the abstract first, then authors, date, subjects, rights, and the identifiers, then the extracted text. Abstract first because it is the part a person wrote deliberately.
- **Categories**: the collection name. Not the source label as well: the configuration applies the label to every record after the source runs, so repeating it here would store the same name twice.
- **`source_type`**: `repository`, a new value. Deep Blue is not a website, a code host, or a knowledge base, and search clients key display rules on this field.
- **`content_type`**: `article`, which already exists and fits a scholarly deposit.

Extracted PDF text arrives with heavy, ragged whitespace, so it needs collapsing before it is chunked. Without that, the section splitter sees one enormous line.

## Security and privacy

- **Nothing is executed and nothing is extracted to disk.** Only the already-extracted plain text is read, so there is no PDF parser and no archive reader to attack.
- **Identifiers from the interface are checked before use.** A collection or deposit identifier is a UUID; anything else is refused before it reaches a request path, as it is for GitHub blob names.
- **The check for protected health information should be pointed at this.** Extracted text from a research poster is exactly where a stray identifier could appear, far more so than in prose somebody wrote for the web. It is not covered by the default `phi_lint: local`, which scans the content that was never published, and a deposit in a public repository was published deliberately. Set `phi_lint: 'all'` on a build with this source. Recorded as a known gap in [compliance](compliance.md), so the choice is visible rather than assumed.
- **A file is downloaded only from the configured interface.** A file's address arrives in a response, so it is matched against `api_url` and against the one path shape a deposited file's contents use. A response cannot point a build's requests at another host.
- **Only what is already public is read.** The interface is read without credentials, so a deposit under embargo is not returned and none is requested.
- **The build identifies itself truthfully and paces its requests**, as every other source does. There is no `robots.txt` check, because this reads a published interface rather than crawling pages, which is how the GitHub API source behaves too.

## What this took from the rest of the build

- `repository` added to the `source_type` vocabulary in `extractium/core/models.py`. A new value in a field that already existed, so the container format did not change version.
- A cache area under the existing cache folder, `.kb_cache/repository/`, holding each deposit's extracted text under its identifier and the change stamp that text belongs to. Text stored under an older stamp is ignored rather than served.
- Nothing else. No new dependency, no change to the chunker, and no change to any output format.

## Where the code is

| File | What is in it |
|---|---|
| `extractium/sources/dspace_client.py` | The interface: handle resolution, collection lookup, the paged listing, the extracted-text download, and every check applied to an identifier or address that arrived in a response |
| `extractium/sources/dspace.py` | The source: the collections, the deposits worth a document, the record each becomes, the change stamp, and the coverage report |
| `tests/test_source_dspace.py` | The tests, over the committed fixture in `tests/fixtures/dspace/` |

## How this is tested

Every response is scripted from a committed fixture; no test reaches Deep Blue.

| Area | What is checked |
|---|---|
| Configured collections | All four ways of writing one; the same collection written twice read once; one deposit refused in place of a collection; a handle read from the redirect rather than followed; a handle naming a deposit, and one pointing at another host, both refused |
| Listing | Paging across more than one page; a collection with no deposits; a collection that does not exist; the files asked for alongside the metadata |
| Identifiers | Handle, DOI, and a third address told apart correctly; a deposit with only some of them; a deposit with none; the same address written twice kept once |
| Files | A deposit with extracted text; one whose only file is an image; a text file over the ceiling by its listed size and by its actual body; an answer that is not plain text; the license and preview bundles never downloaded |
| Change detection | An unchanged collection downloads nothing; one changed deposit re-reads only that deposit; a withdrawn deposit and one still in a submission workflow both disappear |
| Safety | An identifier that is not a UUID never reaches a request; a file address on another host is never requested; an interface address that answers a web page is reported clearly; no credential in any request header; who submitted a deposit is never indexed |
| Records | One document per deposit; the URL opens on the reader's site; whitespace collapsed; a deposit with no readable file still indexed and marked as such |

## Risks and what is still open

- **The interface address may change.** It names a production host explicitly. If Deep Blue moves it, the setting has to be updated, and the failure is an interface that answers a web page. That case has its own error message for exactly this reason.
- **Extracted text quality varies.** It is machine output from a page layout, so reading order can be wrong on a poster with columns. It is still far better than nothing, and better than anything this build would extract itself.
- **Five deposits produced no text from a PDF**, four with no `TEXT` bundle and one with an empty file, and whether that is the file's fault or the repository's is still not established. If the repository can be asked to extract them again, that is a message to the library rather than a change here.
- **Other repositories may differ.** DSpace 7 is a standard, but every site configures its own metadata fields. The source reads the fields it recognizes and ignores the rest rather than insisting on a shape, so a repository with a different profile loses detail rather than failing.
- **A collection of more than five thousand deposits stops at that ceiling**, and says so. Neither Deep Blue collection is close, and the ceiling exists so that a listing which never ends cannot run a build out of time.

## Out of scope

Optical character recognition on image-only deposits. Parsing PDFs, Word documents, or archives in this build. Depositing anything into a repository. Reading collections the settings file did not name. Communities, which are the level above collections, unless a later phase asks for them.

## Conclusion

Deep Blue cannot be crawled, and does not need to be. It publishes a plain interface that hands over a collection's deposits with their abstracts, their identifiers, and the text of their files already extracted, and it says when each one last changed so a rebuild reads only what moved. It cost one source plugin, one new `source_type`, and no new dependency. It is built as `dspace` rather than as Deep Blue, because everything here is standard DSpace 7, and the next repository somebody asks about will work the same way.

To point a build at a repository, see the `dspace` section of the [configuration reference](configuration.md). If a build stops on one of the messages above, [troubleshooting](troubleshooting.md) has the fix.

## Additional Resources

- [Implementation plan](implementation-plan.md) — Phase 9 and the order of work.
- [Troubleshooting](troubleshooting.md) — what each failure of this source means, and what to do about it.
- [Extractium specification](extractium-spec.md) — plugin kinds, records, and the source table.
- [GitHub repository indexing](github-repository-indexing.md) — the earlier case of reading an interface instead of scraping pages.
- [Configuration reference](configuration.md) — every setting a build accepts.
- [Architecture and current state](architecture.md) — what exists in the code today.
- [Deep Blue: Eisenberg Family Depression Center collection](https://hdl.handle.net/2027.42/195355) — one of the two collections in scope.
- [Deep Blue: MeTRIC collection](https://hdl.handle.net/2027.42/195645) — the other.
- [DSpace 7 REST API documentation](https://github.com/DSpace/RestContract) — the contract the interface follows.

[Back to the project README](../README.md)

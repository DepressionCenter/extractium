<!--
This file is part of Extractium™
docs/branding.md
Created: 2026-09-16
Last Modified: 2026-09-16
Summary: Visual identity, media inventory, licensing, and accessibility guidance.
Copyright © 2026 The Regents of the University of Michigan
Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.
-->

# Extractium™

## Branding and media pack

[Back to README](../README.md)

### Summary

This guide explains which Extractium™ image to use, how to keep it readable, and where its source files live. The pack extends the knowledge commons illustration and the formats diagram selected for the README. All image files are in `/images`.

### Visual direction

The identity uses an open book and a reader-shaped dot. The book connects the sources on the left of the illustration with the people and tools on the right. Navy and maize carry the main identity; teal and cream support it.

The project name is **Extractium™**. Keep the trademark on wordmarks and written uses of the full name. The existing line is **From scattered content to shared knowledge**. “Gather”, “Prepare”, and “Reuse” describe the process on the preview cards; they are not an additional tagline.

The selected illustrations establish the visual direction. The vector logo is a reproducible adaptation of the motif on the illustrated book, not a pixel-exact trace. No trademark or similarity clearance has been performed. The official University of Michigan and Eisenberg Family Depression Center logos remain separate and must not be altered.

### Logo construction and placement

[Visual master](../images/extractium-brand-master.svg) records the mark and the wordmark together. Every production asset uses the same two page curves and circular reader dot. The nominal mark is on a 256-unit square. Normal curve strokes are 16 units; the small-icon optical variant uses 24 units and a slightly larger dot.

Use the dark-lettering logo on white or cream and the light-lettering logo on navy. “Dark” and “light” in logo filenames describe the lettering, not the background. PNG logos and standalone marks are transparent. The app icon has a navy rounded tile, and its corners remain transparent.

Leave clear space of at least half the dot diameter around the visible symbol. Use the complete wordmark at 220 pixels wide or larger. Use the dedicated icon files below that size. The 16-, 32-, and 48-pixel PNGs and the SVG favicon use the small-size optical variant. The ICO contains those three actual resolutions.

Scale uniformly. Do not stretch, skew, rotate, outline, recolor individual parts, add shadows to the logo, or merge the symbol with an institutional logo. Do not use the standalone maize shape on white or cream; its contrast is too low there. Maize is used against navy or as a background for navy content.

### Color and contrast

| Color | Hex | Role |
|---|---|---|
| Navy | `#00274C` | Primary lettering, icon backgrounds, dark banners |
| Maize | `#FFCB05` | Symbol on navy; panels behind navy lettering |
| Teal | `#006B66` | Reader dot on light backgrounds and connectors |
| Cream | `#FFFBEF` | Light presentation and preview backgrounds |
| Slate | `#40566B` | Secondary text on light backgrounds |
| White | `#FFFFFF` | Reversed lettering and light panels |
| Pale blue | `#EAF0F5` | Output cards in workflow diagrams |

Measured sRGB contrast ratios for the new vector assets:

| Foreground | Background | Ratio |
|---|---|---|
| Navy | White | 15.06:1 |
| Navy | Cream | 14.55:1 |
| Navy | Maize | 9.89:1 |
| White | Navy | 15.06:1 |
| Maize | Navy | 9.89:1 |
| Teal | White | 6.37:1 |
| Teal | Cream | 6.16:1 |
| Slate | Cream | 7.35:1 |
| Slate | Pale blue | 6.62:1 |

All listed text combinations exceed 4.5:1. Meaningful connectors and symbols use the same high-contrast combinations. Labels and placement carry meaning independently of color. These measurements do not establish compliance for the preserved raster illustrations or for a page that uses the files.

### Typography and licensing

The production wordmark uses **DejaVu Serif Bold**. Labels and captions use **DejaVu Sans Regular and Bold**. These are actual identified fonts, not the lettering generated inside the knowledge commons illustration. The change gives the vector wordmark consistent, editable letterforms across all sizes. It is an intentional adaptation of the illustration's serif treatment.

Font files and their original notices are in [assets/fonts](../assets/fonts). DejaVu is based on Bitstream Vera; its license permits redistribution with the required notices, and DejaVu changes are public domain. See the bundled [license](../assets/fonts/DejaVu-LICENSE.txt) and the [official font license](https://dejavu-fonts.github.io/License.html).

All lettering in the delivered SVGs is outlined as vector paths, so image rendering does not depend on installed fonts. For accompanying HTML or documents, use `"DejaVu Serif", Georgia, serif` for the wordmark treatment and `"DejaVu Sans", Verdana, sans-serif` for body text. Keep ordinary page text as real text.

### Asset inventory

PNG dimensions match the corresponding SVG canvas unless noted. SVG files contain real vector paths; neither preserved raster illustration is disguised as an SVG.

| File | Dimensions | Intended use |
|---|---|---|
| [extractium-brand-master.svg](../images/extractium-brand-master.svg) | 1200 × 800 | Master open-book and reader symbol, serif wordmark, and navy, maize, teal, and cream palette. |
| [extractium-brand-master.png](../images/extractium-brand-master.png) | 1200 × 800 | Master open-book and reader symbol, serif wordmark, and navy, maize, teal, and cream palette. |
| [extractium-logo-dark.svg](../images/extractium-logo-dark.svg) | 1200 × 240 | Extractium trademark wordmark and open-book symbol, dark lettering on a transparent background. |
| [extractium-logo-dark.png](../images/extractium-logo-dark.png) | 1200 × 240 | Extractium trademark wordmark and open-book symbol, dark lettering on a transparent background. |
| [extractium-logo-light.svg](../images/extractium-logo-light.svg) | 1200 × 240 | Extractium trademark wordmark and open-book symbol, light lettering on a transparent background. |
| [extractium-logo-light.png](../images/extractium-logo-light.png) | 1200 × 240 | Extractium trademark wordmark and open-book symbol, light lettering on a transparent background. |
| [extractium-mark-primary.svg](../images/extractium-mark-primary.svg) | 512 × 512 | Open pages below a reader-shaped dot; primary variant on a transparent background. |
| [extractium-mark-primary.png](../images/extractium-mark-primary.png) | 512 × 512 | Open pages below a reader-shaped dot; primary variant on a transparent background. |
| [extractium-mark-dark.svg](../images/extractium-mark-dark.svg) | 512 × 512 | Open pages below a reader-shaped dot; dark variant on a transparent background. |
| [extractium-mark-dark.png](../images/extractium-mark-dark.png) | 512 × 512 | Open pages below a reader-shaped dot; dark variant on a transparent background. |
| [extractium-mark-white.svg](../images/extractium-mark-white.svg) | 512 × 512 | Open pages below a reader-shaped dot; white variant on a transparent background. |
| [extractium-mark-white.png](../images/extractium-mark-white.png) | 512 × 512 | Open pages below a reader-shaped dot; white variant on a transparent background. |
| [extractium-mark-monochrome.svg](../images/extractium-mark-monochrome.svg) | 512 × 512 | Open pages below a reader-shaped dot; monochrome variant on a transparent background. |
| [extractium-mark-monochrome.png](../images/extractium-mark-monochrome.png) | 512 × 512 | Open pages below a reader-shaped dot; monochrome variant on a transparent background. |
| [extractium-banner.svg](../images/extractium-banner.svg) | 1600 × 480 | Extractium™. From scattered content to shared knowledge. |
| [extractium-banner.png](../images/extractium-banner.png) | 1600 × 480 | Extractium™. From scattered content to shared knowledge. |
| [extractium-social-preview.svg](../images/extractium-social-preview.svg) | 1280 × 640 | Extractium™: from scattered content to shared knowledge. Gather, prepare, and reuse. |
| [extractium-social-preview.png](../images/extractium-social-preview.png) | 1280 × 640 | Extractium™: from scattered content to shared knowledge. Gather, prepare, and reuse. |
| [extractium-repo-preview.svg](../images/extractium-repo-preview.svg) | 912 × 512 | Extractium™: from scattered content to shared knowledge. Gather, prepare, and reuse. |
| [Repo-preview.png](../images/Repo-preview.png) | 912 × 512 | Repository directory preview. |
| [Repo-preview-thumb.png](../images/Repo-preview-thumb.png) | 360 × 202 | Repository directory thumbnail. |
| [extractium-app-icon.svg](../images/extractium-app-icon.svg) | 1024 × 1024 | Maize open-book and reader symbol on a navy rounded square. |
| [extractium-app-icon.png](../images/extractium-app-icon.png) | 1024 × 1024 | Maize open-book and reader symbol on a navy rounded square. |
| [extractium-icon-16.png](../images/extractium-icon-16.png) | 16 × 16 | Application or browser icon. |
| [extractium-icon-32.png](../images/extractium-icon-32.png) | 32 × 32 | Application or browser icon. |
| [extractium-icon-48.png](../images/extractium-icon-48.png) | 48 × 48 | Application or browser icon. |
| [extractium-icon-64.png](../images/extractium-icon-64.png) | 64 × 64 | Application or browser icon. |
| [extractium-icon-128.png](../images/extractium-icon-128.png) | 128 × 128 | Application or browser icon. |
| [extractium-icon-180.png](../images/extractium-icon-180.png) | 180 × 180 | Application or browser icon. |
| [extractium-icon-192.png](../images/extractium-icon-192.png) | 192 × 192 | Application or browser icon. |
| [extractium-icon-256.png](../images/extractium-icon-256.png) | 256 × 256 | Application or browser icon. |
| [extractium-icon-512.png](../images/extractium-icon-512.png) | 512 × 512 | Application or browser icon. |
| [favicon.svg](../images/favicon.svg) | 32 × 32 | Maize open-book symbol on a navy rounded square. |
| [favicon.ico](../images/favicon.ico) | 48 × 48 | Browser icon containing 16, 32, and 48 pixel images. |
| [extractium-shared-knowledge.svg](../images/extractium-shared-knowledge.svg) | 1600 × 900 | Websites, code, libraries, captions, files, and knowledge bundles flow into one Extractium knowledge base. Its outputs support search, AI assistants, reports, and reuse. |
| [extractium-shared-knowledge.png](../images/extractium-shared-knowledge.png) | 1600 × 900 | Websites, code, libraries, captions, files, and knowledge bundles flow into one Extractium knowledge base. Its outputs support search, AI assistants, reports, and reuse. |
| [extractium-workflow.svg](../images/extractium-workflow.svg) | 1600 × 900 | Websites and portals, GitHub repositories, library repositories, YouTube captions, local folders, and knowledge bundles feed one Extractium build. The search index supports websites, scripts, local AI, and hosted search. llms.txt files support web-browsing AI. SQLite supports queries, reports, and hosted databases. Markdown supports reading, editing, and reuse through Open Knowledge Format. Plug-ins can add sources and outputs. |
| [extractium-workflow.png](../images/extractium-workflow.png) | 1600 × 900 | Websites and portals, GitHub repositories, library repositories, YouTube captions, local folders, and knowledge bundles feed one Extractium build. The search index supports websites, scripts, local AI, and hosted search. llms.txt files support web-browsing AI. SQLite supports queries, reports, and hosted databases. Markdown supports reading, editing, and reuse through Open Knowledge Format. Plug-ins can add sources and outputs. |
| [extractium-workflow-mobile.svg](../images/extractium-workflow-mobile.svg) | 480 × 1900 | Websites and portals, GitHub repositories, library repositories, YouTube captions, local folders, and knowledge bundles feed one Extractium build. The search index supports websites, scripts, local AI, and hosted search. llms.txt files support web-browsing AI. SQLite supports queries, reports, and hosted databases. Markdown supports reading, editing, and reuse through Open Knowledge Format. Plug-ins can add sources and outputs. |
| [extractium-workflow-mobile.png](../images/extractium-workflow-mobile.png) | 480 × 1900 | Websites and portals, GitHub repositories, library repositories, YouTube captions, local folders, and knowledge bundles feed one Extractium build. The search index supports websites, scripts, local AI, and hosted search. llms.txt files support web-browsing AI. SQLite supports queries, reports, and hosted databases. Markdown supports reading, editing, and reuse through Open Knowledge Format. Plug-ins can add sources and outputs. |
| [extractium-knowledge-commons.png](../images/extractium-knowledge-commons.png) | 1651 × 865 | Preserved user-edited README image; unchanged bytes. |
| [extractium-diagram.png](../images/extractium-diagram.png) | 1322 × 740 | Preserved user-edited README image; unchanged bytes. |

The repository preview and thumbnail depict the same composition. The thumbnail is resized uniformly with minimal padding for the small aspect-ratio difference.

The user's edited knowledge commons and diagram PNGs were copied from `/assets` to `/images` without changing any bytes. The old copies remain in place to preserve existing references. New README links use `/images`.

### GitHub social preview

Use `extractium-social-preview.png` in the repository's social preview setting. It is 1280 × 640 pixels and below 1 MB. GitHub accepts PNG, JPG, or GIF files under 1 MB; it recommends 1280 × 640 for best display. These requirements were verified on 2026-09-16 in the [official GitHub documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview).

The SVG is the editable source, not a GitHub upload format. Adding a file to the repository does not change the social preview setting.

### Accessibility and text alternatives

The project name remains a real H1 in the README. The added banner has empty alt text because the neighboring heading and description carry its message. Informative diagrams have meaningful alt text, and the existing output table supplies a readable format-to-use mapping.

Suggested text alternatives:

- Logo used alone: “Extractium.” Use empty alt text when the same name appears next to it.
- Knowledge commons illustration: “Extractium gathers scattered documentation into shared knowledge for people using search, AI assistants, and reports.”
- Workflow: “Sources feed one Extractium build, which writes a search index, AI-readable text, SQLite, and Markdown for different tools. The adjacent table lists the uses.”
- App icon used as a button: name the action, such as “Open Extractium,” rather than describing its appearance.

Use the mobile workflow on narrow layouts. At a displayed width of 320 pixels, its principal 24-pixel source text is approximately 16 pixels. Do not shrink the desktop workflow until its text is unreadable. Allow users to open the full image, and keep the equivalent explanation and table available as reflowing text. SVG title and description elements are included, but a host application's image alt text and reading order still need to be set.

#### Workflow equivalent

Websites and portals, GitHub repositories, library repositories, YouTube captions, local folders, and knowledge bundles feed one Extractium build. It gathers the content and prepares it for keyword and meaning-based search.

| Output | Uses |
|---|---|
| Search index (`compendium.json`) | Website search, scripts, local AI assistants, and hosted search |
| AI-readable text (`llms.txt`, `llms-full.txt`) | AI assistants that browse the web |
| SQLite (`compendium.sqlite`) | SQL queries, reports, and hosted databases |
| Markdown (`okf/`) | Reading, editing, and reuse with Open Knowledge Format tools |

Source and output plug-ins can add formats. Local content is excluded from each output by default unless that output explicitly enables it. Hosted services and AI assistants are consumers of the output; the illustration does not mean they are required to build the files.

#### Supporting illustration equivalent

Documents from websites, code repositories, libraries, captions, local folders, and knowledge bundles converge on an open book. The resulting knowledge supports search, AI assistants, reports, and reuse. The preserved people-centered illustration communicates the same idea through people working together.

### Verification and remaining review

Automated verification checked SVG parsing, vector-only content, absence of external font and image dependencies, exact PNG dimensions, alpha channels, all ICO resolutions, social-preview file size, and numerical contrast. SHA-256 comparison confirmed that the two user-edited illustrations are unchanged.

Visual review covers the logo on light and dark backgrounds, the banner, social card, repository thumbnail, workflows, and actual-size favicon samples. Static images have no keyboard interactions. A static HTML layout preview shows the README integration. Browser-based narrow-width and 200% zoom checks were not completed because a browser runtime could not be downloaded; these remain manual checks in GitHub. A screen-reader review in GitHub and in the final slide software remains a human check. No blanket WCAG compliance claim is made.

### Provenance and permissions

The knowledge commons illustration originated in the earlier illustration exploration and was edited by the maintainer before this pack. Its generated lettering is not an identified typeface. The new vector symbol and wordmark adapt that selected visual direction; the detailed vector workflow adapts the selected formats diagram and current README behavior.

Original project artwork follows the GNU Free Documentation License v1.3 or later; see [images/LICENSE.txt](../images/LICENSE.txt). The font notices remain separate. The GitHub mark visible inside the preserved illustration belongs to its owner and is not part of the Extractium logo. No institutional endorsement or trademark clearance is implied.

### Using the pack

Use the banner in the README, the social PNG for repository sharing, and the dedicated icon exports for applications. Choose SVG for scalable editing and PNG where the destination does not support SVG. Use the preserved editorial illustration for presentations and the vector workflow when exact labels matter.

### Conclusion

The pack gives every use one right file: the banner for the README, the social PNG for sharing, the icon exports for applications, and the SVG masters for editing. The colors, clear space, and text alternatives above are what keep the mark readable and accessible wherever it lands. Anything not covered here, such as trademark clearance or a screen-reader review of a page that uses the files, is still a human decision.

### Additional resources

- [Project README](../README.md)
- [Visual master](../images/extractium-brand-master.svg)
- [Image directory](../images)
- [Font files](../assets/fonts) and [font license](../assets/fonts/DejaVu-LICENSE.txt)
- [Official DejaVu license](https://dejavu-fonts.github.io/License.html)
- [Official GitHub social preview requirements](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview)
- [Artwork license](../images/LICENSE.txt)
- [EFDC Knowledge Base](https://michmed.org/efdc-kb)

[Back to README](../README.md)

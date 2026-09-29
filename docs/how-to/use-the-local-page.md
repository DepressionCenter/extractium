<!--
This file is part of Extractium™
docs/how-to/use-the-local-page.md
Author(s): Gabriel Mongefranco
Created: 2026-09-28
Last Modified: 2026-09-29
Summary: How to use the local page: starting it from the build script
or the command line, answering the three setup questions in the
browser, changing every setting from the form or the file's own text,
stopping the page, the options the command takes, and how the page
keeps to your own computer.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Extractium™

## How to Use the Local Page

[← Back to README](../../README.md)


## Summary

The local page is a small web page that Extractium™ serves on your own computer, so you can set up a build and change its settings without editing a file by hand. This page shows you how to start it, what each screen does, and how to stop it. It is for anyone who runs a build, and it needs no knowledge of YAML, the format of the settings file. Nothing on the page is reachable from another computer.

Today the page writes a first settings file and lets you change every setting afterwards. Running a build, watching it, searching the result, and connecting an AI assistant from the page are planned and not yet built; the [user interface plan](../ui-implementation-plan.md) lists them. Until then you build from the terminal with the build script, as [running a build](../usage.md) describes.


## Before you start

You need Extractium™ installed, either through the build script or in a Python environment. [How to install](install.md) covers both. The page needs no other software: it runs on the Python that Extractium™ runs on, and it opens in whatever browser you use.


## Step 1: Start the page

From the folder that holds your settings file, or the folder where you want one, run the build script with `ui`:

```
./run.sh ui               # macOS and Linux
run.bat ui                # Windows
```

In a Python environment, the command is:

```
python -m extractium.cli ui
```

The terminal prints one line with the page's address and opens your browser at it. The address looks like this, with a different port and a different token each time:

```
The Extractium page is at http://127.0.0.1:53211/#token=Zk3o…
Keep this window open. Press Ctrl+C here, or Quit on the page, to stop it.
```

Keep that terminal window open while you use the page. If no browser opens, copy the whole address, including the part after `#`, into one. `localhost` works in place of `127.0.0.1` if you prefer to type it; the page is the same either way. That part is the session token; the page does not work without it, which is what keeps another program on your computer from using the page in your name.

The first time, Windows may ask whether to allow Python through the firewall. The page listens on your own computer only, and Windows does not filter that traffic, so the page works whatever you answer. Allowing it opens nothing to the network, because the page never listens on a network address.


## Step 2: Answer the three questions

When the folder has no settings file, the page shows the welcome screen. It asks the same three questions the terminal asks:

1. The name of your compendium, the collection the build writes. Leave it empty for "Compendium".
2. A short name for the output files, made of lowercase letters, digits, and hyphens. Leave it empty and the page derives one from the name.
3. The website to start crawling from, such as `https://example.edu/docs/`.

Beside the form the page shows the terminal command that does the same, `extractium init` with your answers filled in, so you can see there is nothing the page does that the terminal cannot.

Press "Write the settings file". The page writes `config.yaml` in the folder and switches to the settings view. The file is the commented example that ships with the project, with your three answers filled in, and with three outputs switched on at the end: the compressed search index, the `llms.txt` files, and the Markdown folder the page will show search results from. The terminal command writes only the first two, which are the defaults.

The page refuses to replace a settings file that already exists. To start over, rename or delete the file first.


## Step 3: Change the settings

When the folder has a settings file, the page shows it two ways. The "Form" view is the default; "Advanced: the file's text" shows the file itself.

### The form

The form has one field for every setting the [configuration reference](../configuration.md) lists, with the same explanation beside each field and the default in it. The fields are grouped:

- **Sources**, what the build reads. Each source has a type, a label a reader sees, an optional description, and the fields its type takes. Choose the type from the list and the fields change with it. "Add a source" adds one; "Remove" takes one away. A source of a type that comes from a plug-in keeps its options as the file holds them, and you change those in the advanced view.
- **About the compendium**, the name and the short name.
- **Folders**, where outputs, the fetch cache, and run records go.
- **Crawling**, the page limit, the pause between requests, how many sources and pages are read at once, the user agent, `robots.txt`, the connection style, and the extra GitHub accounts a build may follow links into.
- **Building**, what happens to pages not seen this time, the check for protected health information, and keywords.
- **Outputs**, what the build writes. Each output has a type and, for the search index and the database, a file name.

A list field, such as the patterns of pages to leave out, takes one entry per line. A few list fields carry a checkbox for an empty list, because for those an empty list means something different from no list at all: the built-in list is switched off, or only the generic site handler takes part.

Press "Save the settings". The page checks the values through the same settings loader a build uses, so a value a build would refuse is refused here with the same message, and the file is not touched. When the save succeeds, the page writes the file afresh, holding only the settings that differ from their defaults, and keeps the previous file beside it with a date stamp, such as `config.yaml.2026-09-28T14-05-33Z.bak`. Delete those copies whenever you like.

Saving the form drops any comment you added to the file by hand, and the page says so above the button. To keep your comments, change the text in the advanced view instead.

### The advanced view

The advanced view shows the file's text in an editable box. Change what you like and press "Save the file". The text is checked through the settings loader the same way, then written exactly as you typed it, comments included, and the previous file is kept beside it with a date stamp.

When the file is not valid YAML at all, the form cannot show it, and the page opens the advanced view with the loader's message so you can fix the line it names.

"Discard changes" in either view reloads the file from disk.


## Step 4: Stop the page

Press "Quit" at the top of the page, or press Ctrl+C in the terminal window. The page also stops on its own about ten minutes after its last tab was closed, so a page you forgot does not keep a program running. Start it again the same way whenever you need it.


## What else the page serves

While the page runs, the same program answers two more addresses on the same port. Neither needs the session token, because the programs that use them cannot carry it.

- `/mcp` is the search tool for an AI assistant on this computer, the same tool `extractium mcp` serves, over HTTP. It searches the compendium the settings file names, the full search index under the output folder, and says so when no build has run yet. Give the address to `extractium connect --url` to put it on the connection card; [how to connect an MCP client](connect-an-mcp-client.md) explains the card.
- `/dist/` serves the output folder, so a search page or Field Station AI can read the built files. It serves files inside that folder only, never a folder listing, and never a path that leads outside it.


## Options

| Option | What it does |
|---|---|
| `--config FILE` | The settings file the page reads and writes. `config.yaml` in the current folder by default. It need not exist yet. |
| `--port N` | Listen on this port of `127.0.0.1`. A free port is taken when omitted, which is the usual choice. |
| `--no-browser` | Print the address without opening a browser. |

The build scripts pass no options; set `CONFIG` in the environment to point them at another settings file, as [how to run a weekly build](run-a-weekly-build.md) describes.


## How the page keeps to your computer

- The server listens on `127.0.0.1` only. Nothing is reachable from another computer.
- Every request must name the server's own address as its `Host`, either `127.0.0.1` or `localhost` with the port. A web page elsewhere that resolves some other name to your computer is refused before anything else happens.
- Every call the page makes carries the session token from the address, and a call that writes must also come from the page's own origin. A request without both is refused. The token travels only in the part of the address after `#`, which a browser never sends to any server.
- The page loads scripts and styles from itself only, may not be shown inside another page, and sends no referrer.
- The page reads nothing from your environment. `GITHUB_TOKEN`, `YOUTUBE_API_KEY`, and any other secret stay where they are, and the page has no field for them.
- The page's own files are served by name from a fixed list, and the output folder is served from inside itself only.

[Compliance and posture](../compliance.md) lists each of these with the test that checks it.


## If it does not work

[Troubleshooting](../troubleshooting.md) has a section on the local page: a browser that does not open, a page that says it has no session token, a port that is in use, and a page that stopped on its own.


## Conclusion

You can now start the page, write a first settings file from it, change any setting from the form or from the file's own text, and stop the page. Next, build from the terminal with the build script, as [running a build](../usage.md) describes, and see [how to search a compendium](search-a-compendium.md) for what to do with the result.


## Additional Resources

* [Extractium™ README](../../README.md): project overview and quick start.
* [How to install](install.md): the build script and the Python environment.
* [Running a build](../usage.md): the build command, the terminal setup command, and the files a build writes.
* [Configuration reference](../configuration.md): every setting the form shows, with its default.
* [How to run a weekly build](run-a-weekly-build.md): the build scripts, their `ui` argument, and putting a build on a timer.
* [How to connect an MCP client](connect-an-mcp-client.md): the search tool the page also serves, and the connection card.
* [How to search a compendium](search-a-compendium.md): searching a built index from Python or JavaScript.
* [Troubleshooting](../troubleshooting.md): known failures, with the cause and the fix for each.
* [Compliance and posture](../compliance.md): the controls the page relies on and the tests behind them.
* [User interface plan](../ui-implementation-plan.md): what the page will do next, stage by stage.


[← Back to README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan

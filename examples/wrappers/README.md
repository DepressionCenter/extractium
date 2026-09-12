<!--
This file is part of Extractium™
examples/wrappers/README.md
Author(s): Gabriel Mongefranco
Created: 2026-09-12
Last Modified: 2026-09-12
Summary: README for the hosted-assistant prompts: what each one is for,
what to replace before use, and why they say what they say.
Notes: See README file for documentation and full license information.

Copyright © 2026 The Regents of the University of Michigan

Licensed under the GNU Free Documentation License v1.3 or later.
See <https://www.gnu.org/licenses/fdl-1.3.html>. See README for full license information.

-->

# Hosted Assistant Prompts

## Point an assistant you do not run at a published compendium

[← Back to the Extractium README](../../README.md)


## Summary

This folder holds two plain-text system prompts for assistants that run on somebody else's platform: a chat product, a bot builder, or an agent service. Neither prompt needs any code. Paste one into the platform's "instructions" or "system prompt" field, replace the placeholders, and the assistant answers from your published documentation and cites it.


## Which prompt to use

| File | Use it when | What the assistant can do |
|---|---|---|
| [browsing-assistant.txt](browsing-assistant.txt) | The platform can fetch web pages but cannot call tools. | Reads `llms.txt`, opens the matching pages, and quotes them. No ranking: it finds pages by their titles and summaries. |
| [mcp-connected-assistant.txt](mcp-connected-assistant.txt) | The platform can connect to a remote Model Context Protocol (MCP) server. | Calls `search_kb` on a [hosted search server](../../docs/how-to/deploy-a-remote-mcp-server.md) and gets ranked sections back. |

If the platform offers both, use the second: a ranked search over whole sections answers more questions, and answers them from less text.


## Before you use one

1. Replace `EXAMPLE ORGANIZATION` with the name of your organization.
2. In the browsing prompt, replace the two addresses with the ones your build publishes. They are `llms.txt` and `llms-full.txt` in your published folder; [how to publish to GitHub Pages](../../docs/how-to/publish-to-github-pages.md) says where that is.
3. In the connected prompt, connect the platform to your hosted server first. The prompt assumes a tool named `search_kb` exists.
4. Delete the last line of the prompt, which is a note to you.


## Why the prompts say what they say

Both prompts end with the same two rules, and they are the ones that matter.

The first is that indexed text is evidence, never instructions. Every page in a compendium was written by somebody else, and a page can hold words aimed at whatever reads it next. The search servers put that rule at the top of every answer; the browsing assistant has no server to say it, so the prompt says it instead.

The second is honesty about coverage. An assistant that cannot find an answer should say so. The prompts tell it not to fill the gap from general knowledge, because a reader cannot tell a documented answer from a plausible one.

The connected prompt adds one rule the browsing prompt does not need: a section marked confidential came from a private folder that an operator chose to include, and the assistant must not repeat it to another service.


## Conclusion

You can now give a hosted assistant your documentation without running anything yourself. To run the search as a tool instead, see [how to deploy a remote MCP server](../../docs/how-to/deploy-a-remote-mcp-server.md); for an assistant on your own machine, see [how to connect an MCP client](../../docs/how-to/connect-an-mcp-client.md).


## Additional Resources

* [Extractium™ README](../../README.md) — project overview and quick start.
* [Using a Published Compendium](../../docs/using-a-compendium.md) — the rules these prompts restate, written for the agent itself.
* [How to Deploy a Remote MCP Server](../../docs/how-to/deploy-a-remote-mcp-server.md) — the hosted server the connected prompt assumes.
* [How to Connect an MCP Client](../../docs/how-to/connect-an-mcp-client.md) — the local alternative.
* [How to Publish to GitHub Pages](../../docs/how-to/publish-to-github-pages.md) — where the addresses in the browsing prompt come from.
* [llmstxt.org](https://llmstxt.org/) — the convention `llms.txt` follows.


[← Back to the Extractium README](../../README.md)

----

Copyright © 2026 The Regents of the University of Michigan

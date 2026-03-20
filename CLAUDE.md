# Paperpile

Citation management workspace backed by Zotero.

## First-Run Setup

Check `zotero-mcp/config.json`. If `zotero_user_id` is empty, the user
hasn't completed setup yet. Walk them through it before doing anything else:

1. **Zotero API key** — tell them: "Go to https://www.zotero.org/settings/keys
   and create a new key. Give it read/write access to your library. The key
   looks like a long string of letters and numbers." Ask them to paste it.
2. **Zotero user ID** — tell them: "On that same page, your user ID is the
   number shown next to 'Your userID for use in API calls'." Ask them to
   paste it.
3. **Library type** — ask: "Is this a personal library or a group library?"
   Default to personal (`"user"`).
4. **Write config** — update `zotero-mcp/config.json` with their user ID and
   library type (paths are already filled in by bootstrap). Update `.mcp.json`
   to replace the empty `ZOTERO_API_KEY` env value with their real key.
5. **Restart** — tell the user: "Config saved! Please exit and re-run `claude`
   so the Zotero server picks up your API key. You're all set — try
   'process my queue' once you're back."

If `zotero_user_id` is non-empty, setup is complete — proceed normally.

## Directory Structure

- `queue/` — Drop new PDFs here for processing
- `library/` — Processed PDFs, named by citekey (e.g. `smith2024_attention.pdf`)

## Processing Papers from the Queue

When asked to process the queue (or a specific PDF):

1. List PDFs in `queue/` using `list_queue`
2. Read each PDF (first 2-3 pages) to extract metadata: title, authors, year, DOI, abstract
3. Call `list_collections` to see existing collections
4. Suggest which collection(s) the paper fits in, or propose new ones
5. Ask the user to confirm collections and tags before proceeding
6. Call `add_paper` with all metadata, collections, tags, and the source filename
7. The tool handles renaming the PDF and creating the Zotero entry with a linked file

## Knowledge Layer

Two special collections can be used for cross-referencing:
- **Internal Papers** — your own group's publications (always-loaded context)
- **Core References** — foundational papers referenced frequently

Create these collections in Zotero when you're ready to use cross-referencing.
When reading a paper (`/read-paper`), these are loaded at session start via
`get_collection_summaries` for cross-referencing.

## Zotero Conventions

- Citekey format: `lastname2024_keyword` (stored in Zotero's "extra" field)
- PDFs are NOT uploaded to Zotero — only metadata + linked file attachment
- Annotations (highlights, notes) are synced to Zotero via the API
- Structured summaries are stored as Zotero child notes tagged `structured-summary`
- Pages are always 1-indexed when using annotation tools

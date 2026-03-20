import html as html_lib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import fitz  # PyMuPDF
from mcp.server.fastmcp import FastMCP
from pyzotero import zotero

# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
try:
    with open(CONFIG_PATH) as f:
        config = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    config = {}

api_key = os.environ.get("ZOTERO_API_KEY", "")
user_id = config.get("zotero_user_id", "")
library_type = config.get("library_type", "user")

papers_queue = config.get("papers_queue")
papers_library = config.get("papers_library")

QUEUE_DIR = Path(papers_queue) if papers_queue else None
LIBRARY_DIR = Path(papers_library) if papers_library else None

_zot = None


def _get_zot():
    """Get Zotero client, raising a clear error if not configured."""
    global _zot
    if _zot is not None:
        return _zot
    missing = []
    if not api_key:
        missing.append("ZOTERO_API_KEY (set in .mcp.json env)")
    if not user_id:
        missing.append("zotero_user_id (set in config.json)")
    if missing:
        raise ValueError(
            "Zotero not configured yet. Missing: " + ", ".join(missing)
            + "\n\nRun the first-run setup in Claude Code to configure."
        )
    _zot = zotero.Zotero(user_id, library_type, api_key)
    return _zot


def _check_dirs():
    """Raise if queue/library dirs are not configured."""
    if QUEUE_DIR is None or LIBRARY_DIR is None:
        raise ValueError("Papers directories not configured. Run bootstrap.sh first.")


mcp = FastMCP("zotero-citations")


def _meaningful_words(title: str) -> list[str]:
    """Extract meaningful words from a title, skipping common words."""
    skip = {"a", "an", "the", "on", "in", "of", "for", "and", "to", "with", "from",
            "by", "at", "is", "are", "was", "were", "be", "been", "its", "their",
            "this", "that", "these", "those", "how", "what", "when", "where", "which"}
    words = []
    for word in title.split():
        cleaned = re.sub(r"[^a-z]", "", word.lower())
        if cleaned and cleaned not in skip:
            words.append(cleaned)
    return words


def _generate_citekey(authors: list[str], year: str, title: str) -> str:
    """Generate citekey like lastname2024_keyword, adding more keywords on collision."""
    _check_dirs()
    last = "unknown"
    if authors:
        first_author = authors[0]
        parts = first_author.strip().split()
        last = parts[-1].lower() if parts else "unknown"
        last = re.sub(r"[^a-z]", "", last)

    words = _meaningful_words(title)
    if not words:
        words = ["paper"]

    # Start with one keyword, add more if there's a collision
    for num_keywords in range(1, len(words) + 1):
        keyword_part = "_".join(words[:num_keywords])
        citekey = f"{last}{year}_{keyword_part}"
        dest = LIBRARY_DIR / f"{citekey}.pdf"
        if not dest.exists():
            return citekey

    # Exhausted all title words and still colliding — append a/b/c
    base = f"{last}{year}_{'_'.join(words)}"
    for suffix in "abcdefghijklmnopqrstuvwxyz":
        citekey = f"{base}_{suffix}"
        dest = LIBRARY_DIR / f"{citekey}.pdf"
        if not dest.exists():
            return citekey

    # Final fallback with numeric suffix
    counter = 1
    while True:
        citekey = f"{base}_{counter}"
        dest = LIBRARY_DIR / f"{citekey}.pdf"
        if not dest.exists():
            return citekey
        counter += 1


def _find_collection_key(name: str) -> str | None:
    """Find a collection key by name (case-insensitive)."""
    collections = _get_zot().collections()
    for c in collections:
        if c["data"]["name"].lower() == name.lower():
            return c["key"]
    return None


@mcp.tool()
def list_queue() -> str:
    """List PDF files in the queue (~/papers/queue) waiting to be processed."""
    _check_dirs()
    files = sorted(QUEUE_DIR.glob("*.pdf"))
    if not files:
        return "Queue is empty — no PDFs waiting to be processed."
    lines = [f"- {f.name}" for f in files]
    return f"Papers in queue ({len(files)}):\n" + "\n".join(lines)


@mcp.tool()
def add_paper(
    title: str,
    authors: list[str],
    year: str,
    doi: str = "",
    url: str = "",
    abstract: str = "",
    tags: list[str] | None = None,
    collections: list[str] | None = None,
    source_filename: str = "",
) -> str:
    """Add a paper to Zotero and move/rename the local PDF.

    Args:
        title: Paper title
        authors: List of author names (e.g. ["John Smith", "Jane Doe"])
        year: Publication year
        doi: DOI if available
        url: URL if available
        abstract: Paper abstract
        tags: List of tags to apply
        collections: List of collection names to add to (created if they don't exist)
        source_filename: Filename of PDF in queue dir to rename/move (optional)
    """
    _check_dirs()
    citekey = _generate_citekey(authors, year, title)

    # Build Zotero item template
    # Reset url_params to work around pyzotero state pollution bug
    _get_zot().url_params = None
    template = _get_zot().item_template("journalArticle")
    template["title"] = title
    template["date"] = year
    template["DOI"] = doi
    template["url"] = url
    template["abstractNote"] = abstract
    template["extra"] = f"citekey: {citekey}"

    # Set authors
    template["creators"] = []
    for author in authors:
        parts = author.strip().rsplit(" ", 1)
        if len(parts) == 2:
            template["creators"].append(
                {"creatorType": "author", "firstName": parts[0], "lastName": parts[1]}
            )
        else:
            template["creators"].append(
                {"creatorType": "author", "name": author}
            )

    # Set tags
    if tags:
        template["tags"] = [{"tag": t} for t in tags]

    # Resolve collection keys (single API call for all lookups)
    collection_keys = []
    if collections:
        all_cols = _get_zot().collections()
        col_map = {c["data"]["name"].lower(): c["key"] for c in all_cols}
        for name in collections:
            key = col_map.get(name.lower())
            if key is None:
                resp = _get_zot().create_collections([{"name": name}])
                if "successful" in resp and resp["successful"]:
                    key = list(resp["successful"].values())[0]["key"]
            if key:
                collection_keys.append(key)
        template["collections"] = collection_keys

    # Create the item in Zotero
    resp = _get_zot().create_items([template])
    if "successful" not in resp or not resp["successful"]:
        return f"Failed to create Zotero item: {resp}"

    item_key = list(resp["successful"].values())[0]["key"]

    # Handle local PDF: rename and move from queue to library
    local_path = None
    if source_filename:
        if not source_filename.lower().endswith(".pdf"):
            return f"Source file must be a PDF, got: {source_filename}"
        source = QUEUE_DIR / source_filename
        if not source.exists():
            return (f"Zotero item created (key: {item_key}) but source PDF "
                    f"not found in queue: {source_filename}. No file was moved.")
        dest = LIBRARY_DIR / f"{citekey}.pdf"
        if dest.exists():
            return (f"Destination already exists: {dest}\n"
                    "This should not happen — citekey collision logic failed.")
        shutil.move(str(source), str(dest))
        local_path = str(dest)

    # Add linked file attachment pointing to local path
    if local_path:
        attachment = {
            "itemType": "attachment",
            "parentItem": item_key,
            "linkMode": "linked_file",
            "title": f"{citekey}.pdf",
            "path": local_path,
            "contentType": "application/pdf",
            "tags": [],
        }
        _get_zot().create_items([attachment])

    result = f"Added to Zotero: {title}\n"
    result += f"  Citekey: {citekey}\n"
    result += f"  Item key: {item_key}\n"
    if collection_keys:
        result += f"  Collections: {', '.join(collections)}\n"
    if tags:
        result += f"  Tags: {', '.join(tags)}\n"
    if local_path:
        result += f"  Local PDF: {local_path}\n"

    return result


@mcp.tool()
def search_library(query: str, limit: int = 10) -> str:
    """Search your Zotero library by title, author, or any text.

    Args:
        query: Search query string
        limit: Max results to return (default 10)
    """
    items = _get_zot().items(q=query, limit=limit)
    if not items:
        return f"No results for '{query}'."

    results = []
    for item in items:
        d = item["data"]
        if d["itemType"] == "attachment":
            continue
        authors = ", ".join(
            c.get("lastName", c.get("name", ""))
            for c in d.get("creators", [])
        )
        results.append(
            f"- [{d.get('key')}] {d.get('title', 'Untitled')} "
            f"({authors}, {d.get('date', '?')})"
        )

    return f"Results ({len(results)}):\n" + "\n".join(results)


@mcp.tool()
def list_collections() -> str:
    """List all Zotero collections."""
    collections = _get_zot().collections()
    if not collections:
        return "No collections found."
    lines = []
    for c in collections:
        d = c["data"]
        count = d.get("numItems", 0)
        lines.append(f"- {d['name']} ({count} items) [key: {d['key']}]")
    return f"Collections ({len(lines)}):\n" + "\n".join(lines)


@mcp.tool()
def add_to_collection(item_key: str, collection_name: str) -> str:
    """Add an existing Zotero item to a collection (creates collection if needed).

    Args:
        item_key: The Zotero item key
        collection_name: Name of the collection
    """
    col_key = _find_collection_key(collection_name)
    if col_key is None:
        resp = _get_zot().create_collections([{"name": collection_name}])
        if "successful" in resp and resp["successful"]:
            col_key = list(resp["successful"].values())[0]["key"]
        else:
            return f"Failed to create collection '{collection_name}': {resp}"

    item = _get_zot().item(item_key)
    item["data"]["collections"].append(col_key)
    _get_zot().update_item(item)
    return f"Added item {item_key} to collection '{collection_name}'."


@mcp.tool()
def tag_item(item_key: str, tags: list[str]) -> str:
    """Add tags to a Zotero item.

    Args:
        item_key: The Zotero item key
        tags: List of tags to add
    """
    item = _get_zot().item(item_key)
    existing = {t["tag"] for t in item["data"].get("tags", [])}
    for t in tags:
        if t not in existing:
            item["data"]["tags"].append({"tag": t})
    _get_zot().update_item(item)
    return f"Tagged item {item_key} with: {', '.join(tags)}"


@mcp.tool()
def get_bibtex(item_key: str) -> str:
    """Export a Zotero item as BibTeX.

    Args:
        item_key: The Zotero item key
    """
    bib = _get_zot().item(item_key, format="bibtex")
    return bib


@mcp.tool()
def suggest_collections(title: str, abstract: str = "") -> str:
    """Given a paper's title and abstract, suggest matching existing collections.

    Args:
        title: Paper title
        abstract: Paper abstract (optional, helps improve suggestions)
    """
    collections = _get_zot().collections()
    if not collections:
        return "No existing collections. A new one will be created when you add the paper."

    names = [c["data"]["name"] for c in collections]
    return (
        "Existing collections:\n"
        + "\n".join(f"- {n}" for n in names)
        + "\n\nBased on the paper title/abstract, suggest which collection(s) fit, "
        "or propose a new collection name."
    )


@mcp.tool()
def create_collection(name: str, parent_name: str = "") -> str:
    """Create a new Zotero collection.

    Args:
        name: Collection name
        parent_name: Optional parent collection name for nesting
    """
    data = {"name": name}
    if parent_name:
        parent_key = _find_collection_key(parent_name)
        if parent_key:
            data["parentCollection"] = parent_key
        else:
            return f"Parent collection '{parent_name}' not found."

    resp = _get_zot().create_collections([data])
    if "successful" in resp and resp["successful"]:
        key = list(resp["successful"].values())[0]["key"]
        return f"Created collection '{name}' [key: {key}]"
    return f"Failed to create collection: {resp}"


def _find_attachment_key(item_key: str) -> str | None:
    """Find the linked file attachment key for a Zotero item."""
    children = _get_zot().children(item_key)
    for child in children:
        d = child["data"]
        if d["itemType"] == "attachment" and d.get("linkMode") == "linked_file":
            return d["key"]
    return None


def _find_text_position(pdf_path: str, text: str, page_num: int) -> dict | None:
    """Find the bounding rects of text on a specific page using PyMuPDF."""
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        doc.close()
        return None
    page = doc[page_num]
    rects = page.search_for(text)
    doc.close()
    if not rects:
        return None
    # Convert fitz.Rect to list of [x1, y1, x2, y2]
    return [[r.x0, r.y0, r.x1, r.y1] for r in rects]


def _get_local_path_for_item(item_key: str) -> str | None:
    """Get the local PDF path from a Zotero item's linked file attachment."""
    children = _get_zot().children(item_key)
    for child in children:
        d = child["data"]
        if d["itemType"] == "attachment" and d.get("linkMode") == "linked_file":
            return d.get("path")
    return None


@mcp.tool()
def add_highlight(
    item_key: str,
    text: str,
    page: int,
    comment: str = "",
    color: str = "#ffff00",
) -> str:
    """Add a highlight annotation to a paper in Zotero.

    The text is searched in the local PDF to find its exact position.

    Args:
        item_key: The Zotero item key of the parent paper
        text: The exact text to highlight (must match PDF content)
        page: Page number (1-indexed, like the PDF reader shows)
        comment: Optional comment on the highlight
        color: Highlight color as hex (default yellow #ffff00)
    """
    page_0 = page - 1  # Convert to 0-indexed for internal use
    if page_0 < 0:
        return "Page number must be >= 1."

    # Find the local PDF to get text positions
    pdf_path = _get_local_path_for_item(item_key)
    if not pdf_path or not Path(pdf_path).exists():
        return f"Could not find local PDF for item {item_key}."

    rects = _find_text_position(pdf_path, text, page_0)
    if not rects:
        return f"Could not find text '{text[:50]}...' on page {page}."

    # Find the attachment key (annotations are children of the attachment)
    att_key = _find_attachment_key(item_key)
    if not att_key:
        return f"No linked file attachment found for item {item_key}."

    # Build sort index (page|char offset|y position)
    sort_index = f"{page_0:05d}|{0:06d}|{int(rects[0][1]):05d}"

    annotation = {
        "itemType": "annotation",
        "parentItem": att_key,
        "annotationType": "highlight",
        "annotationText": text,
        "annotationComment": comment,
        "annotationColor": color,
        "annotationPageLabel": str(page),
        "annotationSortIndex": sort_index,
        "annotationPosition": json.dumps({
            "pageIndex": page_0,
            "rects": rects,
        }),
        "tags": [],
    }

    resp = _get_zot().create_items([annotation])
    if "successful" in resp and resp["successful"]:
        ann_key = list(resp["successful"].values())[0]["key"]
        text_display = f"{text[:60]}..." if len(text) > 60 else text
        result = f"Highlight added on page {page}: '{text_display}'\n"
        if comment:
            result += f"  Comment: {comment}\n"
        result += f"  Annotation key: {ann_key}"
        return result
    return f"Failed to create highlight: {resp}"


@mcp.tool()
def add_note_annotation(
    item_key: str,
    comment: str,
    page: int,
    color: str = "#ffcd00",
) -> str:
    """Add a note annotation (sticky note) to a page in Zotero.

    Args:
        item_key: The Zotero item key of the parent paper
        comment: The note content
        page: Page number (1-indexed, like the PDF reader shows)
        color: Note color as hex (default gold #ffcd00)
    """
    page_0 = page - 1
    if page_0 < 0:
        return "Page number must be >= 1."

    att_key = _find_attachment_key(item_key)
    if not att_key:
        return f"No linked file attachment found for item {item_key}."

    sort_index = f"{page_0:05d}|{0:06d}|{0:05d}"

    annotation = {
        "itemType": "annotation",
        "parentItem": att_key,
        "annotationType": "note",
        "annotationComment": comment,
        "annotationColor": color,
        "annotationPageLabel": str(page),
        "annotationSortIndex": sort_index,
        "annotationPosition": json.dumps({
            "pageIndex": page_0,
            "rects": [[50, 50, 80, 80]],
        }),
        "tags": [],
    }

    resp = _get_zot().create_items([annotation])
    if "successful" in resp and resp["successful"]:
        ann_key = list(resp["successful"].values())[0]["key"]
        comment_display = f"{comment[:60]}..." if len(comment) > 60 else comment
        return f"Note added on page {page}: '{comment_display}'\n  Annotation key: {ann_key}"
    return f"Failed to create note: {resp}"


@mcp.tool()
def list_annotations(item_key: str) -> str:
    """List all annotations on a Zotero item.

    Args:
        item_key: The Zotero item key of the parent paper
    """
    att_key = _find_attachment_key(item_key)
    if not att_key:
        return f"No linked file attachment found for item {item_key}."

    children = _get_zot().children(att_key)
    annotations = [c for c in children if c["data"]["itemType"] == "annotation"]

    if not annotations:
        return "No annotations found."

    lines = []
    for ann in annotations:
        d = ann["data"]
        atype = d.get("annotationType", "?")
        page = d.get("annotationPageLabel", "?")
        text = d.get("annotationText", "")
        comment = d.get("annotationComment", "")
        color = d.get("annotationColor", "")

        if atype == "highlight":
            line = f"- [highlight, p.{page}, {color}] '{text[:80]}'"
            if comment:
                line += f" — {comment}"
        elif atype == "note":
            line = f"- [note, p.{page}, {color}] {comment[:100]}"
        else:
            line = f"- [{atype}, p.{page}] {text[:80] or comment[:80]}"
        lines.append(line)

    return f"Annotations ({len(lines)}):\n" + "\n".join(lines)


@mcp.tool()
def add_structured_note(
    item_key: str,
    method: str,
    key_parameters: str = "",
    main_results: str = "",
    limitations: str = "",
    tags: list[str] | None = None,
) -> str:
    """Add a structured technical summary as a standalone Zotero note (child of the item).

    This is the equivalent of a summary.tex — a reusable reference for the paper's
    method, parameters, results, and limitations. Used by the read-paper skill and
    loaded as context when cross-referencing papers.

    Args:
        item_key: The Zotero item key of the parent paper
        method: Method description (key equations, approximations, approach)
        key_parameters: Important parameter values and units
        main_results: Quantitative findings with figure/table references
        limitations: What the paper does NOT cover or where it breaks down
        tags: Optional tags (e.g. ["structured-summary"])
    """
    # Get the paper title for the note heading
    item = _get_zot().item(item_key)
    title = item["data"].get("title", "Untitled")
    authors = ", ".join(
        c.get("lastName", c.get("name", ""))
        for c in item["data"].get("creators", [])
    )
    year = item["data"].get("date", "?")

    esc = html_lib.escape
    html = f"<h1>{esc(title)} ({esc(authors)}, {esc(year)})</h1>\n"
    html += f"<h2>Method</h2>\n<p>{esc(method)}</p>\n"
    if key_parameters:
        html += f"<h2>Key Parameters</h2>\n<p>{esc(key_parameters)}</p>\n"
    if main_results:
        html += f"<h2>Main Results</h2>\n<p>{esc(main_results)}</p>\n"
    if limitations:
        html += f"<h2>Limitations &amp; Scope</h2>\n<p>{esc(limitations)}</p>\n"

    note_data = {
        "itemType": "note",
        "parentItem": item_key,
        "note": html,
        "tags": [{"tag": t} for t in (tags or ["structured-summary"])],
    }

    resp = _get_zot().create_items([note_data])
    if "successful" in resp and resp["successful"]:
        note_key = list(resp["successful"].values())[0]["key"]
        return f"Structured summary added for '{title}'\n  Note key: {note_key}"
    return f"Failed to create note: {resp}"


@mcp.tool()
def get_structured_note(item_key: str) -> str:
    """Get the structured technical summary note for a paper.

    Returns the structured-summary note content if one exists.

    Args:
        item_key: The Zotero item key of the parent paper
    """
    children = _get_zot().children(item_key)
    for child in children:
        d = child["data"]
        if d["itemType"] == "note":
            tags = {t["tag"] for t in d.get("tags", [])}
            if "structured-summary" in tags:
                # Strip HTML tags for readability
                note = d.get("note", "")
                note = re.sub(r"<[^>]+>", "\n", note)
                note = re.sub(r"\n{3,}", "\n\n", note).strip()
                return note
    return "No structured summary found for this item."


@mcp.tool()
def get_collection_summaries(collection_name: str) -> str:
    """Get structured summary notes for ALL papers in a collection.

    This is the knowledge-layer loader — call at session start with
    "Internal Papers" and "Core References" to load always-on context.
    Fetches all items (including children) in bulk to avoid N+1 API calls.

    Args:
        collection_name: Name of the Zotero collection
    """
    col_key = _find_collection_key(collection_name)
    if col_key is None:
        return f"Collection '{collection_name}' not found."

    # Fetch ALL items in the collection (parents + children) in bulk
    all_items = _get_zot().everything(_get_zot().collection_items(col_key, itemType="-attachment"))
    if not all_items:
        return f"Collection '{collection_name}' is empty."

    # Separate top-level items from child notes
    top_items = {}
    child_notes = {}  # parent_key -> list of notes
    for item in all_items:
        d = item["data"]
        parent = d.get("parentItem", "")
        if d["itemType"] == "note" and parent:
            child_notes.setdefault(parent, []).append(d)
        elif d["itemType"] not in ("attachment", "note", "annotation"):
            top_items[d["key"]] = d

    summaries = []
    for item_key, d in top_items.items():
        title = d.get("title", "Untitled")
        authors = ", ".join(
            c.get("lastName", c.get("name", ""))
            for c in d.get("creators", [])
        )
        year = d.get("date", "?")
        citekey = ""
        extra = d.get("extra", "")
        for line in extra.split("\n"):
            if line.startswith("citekey:"):
                citekey = line.split(":", 1)[1].strip()

        # Find the structured summary among this item's child notes
        summary_text = None
        for note_data in child_notes.get(item_key, []):
            tags = {t["tag"] for t in note_data.get("tags", [])}
            if "structured-summary" in tags:
                note = note_data.get("note", "")
                note = re.sub(r"<[^>]+>", "\n", note)
                note = re.sub(r"\n{3,}", "\n\n", note).strip()
                summary_text = note
                break

        entry = f"### {title} ({authors}, {year})"
        if citekey:
            entry += f" [{citekey}]"
        entry += "\n"
        if summary_text:
            entry += summary_text
        else:
            abstract = d.get("abstractNote", "")
            if abstract:
                entry += f"(No structured summary — abstract: {abstract[:200]}...)"
            else:
                entry += "(No structured summary or abstract available)"

        summaries.append(entry)

    header = f"## {collection_name} ({len(summaries)} papers)\n\n"
    return header + "\n\n---\n\n".join(summaries)


if __name__ == "__main__":
    mcp.run()

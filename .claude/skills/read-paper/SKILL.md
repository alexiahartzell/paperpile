---
name: read-paper
description: Interactive guided reading of a paper with annotation sync to Zotero. Use when you want to deeply understand a paper in your library.
argument-hint: "[citekey or PDF filename]"
allowed-tools: Read, Grep, Glob, Bash, Write, Edit, Agent, mcp__zotero__*
---

# Read Paper

Multi-agent skill for interactive, guided reading of academic papers.
Subagents handle PDF reading so long documents don't exhaust the main
conversation's context. Enforces strict citation discipline — every claim
tagged as PAPER, EXTERNAL, or UNCERTAIN — to minimize hallucination.

Key highlights and notes are synced to Zotero as annotations. At session
end, a structured technical summary is saved as a Zotero note for future
cross-referencing.

## Trigger

- `/read-paper`
- `/read-paper <citekey or filename>`
- "Walk me through this paper", "Help me read this",
  "I don't understand this paper"

## PDF Reading

All subagents MUST use the **Read tool** to read PDFs — it processes
pages visually (multimodal) and handles equations better than text
extraction. For PDFs over 10 pages, use the `pages` parameter
(e.g., `pages: "1-5"`). Maximum 20 pages per Read call.

**Do NOT** use Bash to install or run poppler, pdftotext, pdfplumber,
or any other PDF conversion tool.

**Include these instructions in every agent prompt** by adding this
block to the top of the prompt:
~~~
## PDF Reading
Use the Read tool to read PDF files — it handles PDFs natively.
For large PDFs, use the `pages` parameter (e.g., pages: "1-5").
Maximum 20 pages per Read call. Do NOT use Bash to install or run
poppler, pdftotext, or any PDF conversion tool.
~~~

## Paper Location

Papers live in two places relative to the repo root:
- `queue/` — unprocessed PDFs (not yet in Zotero)
- `library/` — processed PDFs, named by citekey

If the paper is in the queue, process it first using the Zotero MCP tools
(`add_paper`) before starting the reading session. This ensures it gets
a citekey, a Zotero entry, and moves to the library.

## Knowledge Layer

Two Zotero collections serve as always-loaded context:
- **Internal Papers** — your own group's publications. Always loaded.
- **Core References** — foundational papers you reference frequently.
  Always loaded.

At session start, call `get_collection_summaries("Internal Papers")` and
`get_collection_summaries("Core References")` to load structured summaries
for cross-referencing. These summaries are the equivalent of
`lab-publications.tex` — concise technical references with method,
parameters, results, and limitations.

When reading a new paper, actively cross-reference against this context:
- If the paper cites or builds on an Internal/Core paper, note the
  connection and flag any discrepancies.
- If the paper contradicts a known result, flag it explicitly rather
  than silently resolving.
- If the paper references a paper you've already read (in any
  collection), use `search_library` + `get_structured_note` to pull
  that paper's summary for context.

## Scratch File

During a reading session, accumulate section summaries and discussion
highlights in a temporary scratch file:
`/tmp/read-paper-<citekey>-YYYY-MM-DD.md`

This file serves two purposes:
- **Subagent memory:** subagents can't call MCP tools or read Zotero
  annotations, but they can read this file for context on prior sections.
- **Compression safety:** long sessions may lose earlier sections from
  the conversation window. The scratch file preserves them.

**What goes in the scratch file:**
- Section summaries (condensed — key points only, not full agent output)
- Discussion highlights and reader insights
- Cross-references to Internal/Core papers that came up
- Open questions

**What gets passed to subagents:**
- The full scratch file only when needed (follow-ups, cross-section
  references). For a fresh section read with no back-references, pass
  just the compass and knowledge-layer summaries — not the entire
  scratch file.
- For follow-up agents: the relevant section summary from the scratch
  file + the reader's question.

Delete the scratch file at session end after all annotations and the
structured summary are synced to Zotero.

## Execution

1. **Locate the paper.** Find the PDF:
   - If a citekey is given, look in `library/<citekey>.pdf`
   - If a filename is given, check both `queue/` and `library/`
   - If in `queue/`, read the first few pages to extract metadata,
     then use `add_paper` MCP tool to create the Zotero entry and
     move it to `library/`. Ask the user to confirm collections/tags.
   - Use `search_library` MCP tool if the user gives a partial name
   - If not found, ask the user for the path

   Store the Zotero item key — you'll need it for annotations.

2. **Load context.**
   - Call `get_collection_summaries("Internal Papers")` and
     `get_collection_summaries("Core References")` to load the
     knowledge layer. Store this in the scratch file header.
   - Call `list_annotations` to check if the paper has prior
     annotations from a previous reading session. If so, briefly
     summarize what was covered before.
   - Call `get_structured_note` to check if a structured summary
     already exists. If so, the paper has been read before — present
     the summary and ask whether to do a fresh read, update the
     summary, or dive into specific questions.

3. **Establish the compass.** Ask: "What brought you to this paper?
   What are you hoping to get from it?" This guides drift detection.

4. **Choose mode.** Ask:
   - **Full walkthrough** — section-by-section reading
   - **Question-driven** — targeted deep dives into specific parts

5. **Map the paper.** Spawn a mapping agent to produce a section-by-section
   table of contents. Do NOT read the PDF in the main conversation.

   Use the Agent tool with:
   - `subagent_type`: `general-purpose`
   - `description`: `Map paper sections`
   - `prompt`: (fill in the template below)

   **Mapping agent prompt template** (fill in `{pdf_path}`):

   ~~~
   You are producing a section map for an academic paper to guide
   an interactive reading session.

   ## PDF Reading
   Use the Read tool to read PDF files — it handles PDFs natively.
   For large PDFs, use the `pages` parameter (e.g., pages: "1-5").
   Maximum 20 pages per Read call. Do NOT use Bash to install or run
   poppler, pdftotext, or any PDF conversion tool.

   ## Instructions

   1. Read the PDF at `{pdf_path}`.
      - If the paper is 20 pages or fewer, read the entire PDF.
      - If the paper is longer than 20 pages, read pages 1-3
        (abstract/introduction and table of contents if present),
        then skim each subsequent ~10-page chunk to identify section
        boundaries.
   2. Produce a section map as structured text:

   PAPER STRUCTURE:
   Total pages: [number]

   SECTIONS:
   1. [Section title] (p.X-Y) — [1-sentence summary]
   2. [Section title] (p.X-Y) — [1-sentence summary]
   ...

   ## Important
   - Include ALL sections, not just major ones (subsections too if
     they represent distinct topics).
   - Page ranges must be accurate — the reader will use these to
     request specific sections.
   - Summaries should be informative enough that the reader can
     decide which sections to read.
   ~~~

   Present the section map. In walkthrough mode, ask whether to read
   all sections in order or pick specific ones. In question-driven mode,
   the map is a reference.

6. **Read sections via agents.** For each section, spawn a section reader
   agent. Do NOT read the PDF in the main conversation.

   **Section reader prompt template** (fill in `{pdf_path}`,
   `{page_range}`, `{section_name}`, `{compass}`,
   `{knowledge_layer}` — Internal Papers + Core References summaries,
   and optionally `{prior_sections}` — relevant content from the
   scratch file, only if the section builds on earlier ones):

   ~~~
   You are reading a section of an academic paper for a reader.
   Produce a labeled summary enforcing strict citation discipline.

   ## PDF Reading
   Use the Read tool to read PDF files — it handles PDFs natively.
   For large PDFs, use the `pages` parameter (e.g., pages: "1-5").
   Maximum 20 pages per Read call. Do NOT use Bash to install or run
   poppler, pdftotext, or any PDF conversion tool.

   ## Context
   The reader is reading this paper because: {compass}

   ## Knowledge layer (Internal Papers & Core References)
   {knowledge_layer}

   ## Prior sections covered (if any)
   {prior_sections}

   ## Instructions

   1. Read pages {page_range} of the PDF at `{pdf_path}`.
      This is the section: {section_name}
   2. Produce a summary with mandatory claim labels:
      - [PAPER, Sec/Eq/Fig ref]: claims directly from the PDF
      - [EXTERNAL]: claims from general knowledge, explicitly flagged
      - [UNCERTAIN]: content you can't parse or source confidently
   3. Cross-reference against the knowledge layer. If the paper cites,
      builds on, or contradicts an Internal/Core paper, note it
      explicitly.
   4. Structure your summary as:

   SECTION: {section_name} ({page_range})

   SUMMARY:
   [Labeled summary of the section's content, ~30-50 lines.
   Explain the main arguments, methods, and findings.]

   KEY EQUATIONS:
   - Eq. N (p.X): [equation description and significance]

   FIGURES/TABLES:
   - Fig. N (p.X): [what it shows]

   CROSS-REFERENCES:
   - [Connections to Internal Papers or Core References, if any]

   HIGHLIGHT-WORTHY PASSAGES:
   - Quote exact text passages (verbatim, max ~2 sentences each) that
     represent key findings, definitions, or claims worth highlighting.
     For each, note the page number (1-indexed) and why it matters.

   OPEN QUESTIONS:
   - [Background knowledge the section assumes]
   - [Content that was garbled or unreadable]

   ## Important
   - "I can't read this" protocol: when equations are garbled, figures
     are unreadable, or content is ambiguous, say so explicitly in an
     OPEN QUESTIONS item. Never guess.
   - Only report what you can actually read.
   - HIGHLIGHT-WORTHY PASSAGES must be exact quotes from the PDF so
     they can be found by text search for Zotero annotation.
   ~~~

   Present the section summary. Discuss as needed.

   **Zotero annotations.** After discussing each section, ask whether to
   highlight any key passages in Zotero. Use the `add_highlight` MCP tool
   with exact text from the PDF (page is 1-indexed) and the reader's
   comments. Use `add_note_annotation` for the reader's own insights
   about a page.

   **Scratch file update.** After each section (and its discussion),
   append a condensed summary to the scratch file:
   ```
   ## [Section name] (p.X-Y)
   [Key points — 5-10 lines max]
   [Cross-references noted]
   [Annotations added: list of highlights/notes]
   ```

   **Follow-up questions.** When the reader asks follow-ups:
   - **About PDF content**: spawn a follow-up agent that re-reads the
     relevant pages. Pass the relevant section summary from the scratch
     file + the knowledge layer + the reader's question.
   - **Conceptual question**: answer locally with an EXTERNAL label.
   - **About a different section**: spawn a new section reader.

   **Question-driven routing.** When the reader asks a question without
   specifying a section:
   - Check the section map for a likely match.
   - If clear, spawn a section reader.
   - If unclear, spawn a scout agent to skim candidate sections.

7. **Compass check (ongoing).** When conversation drifts far from both
   the paper's core contribution and the reader's stated purpose:
   - Flag it as a nudge, not a gate
   - When uncertain whether something came from the paper, spawn a
     follow-up agent rather than guessing

8. **Handle background knowledge gaps.** When the paper assumes
   unfamiliar knowledge:
   - Flag it with an EXTERNAL-labeled explanation
   - Check the knowledge layer — an Internal/Core paper may cover it
   - Note the gap in the scratch file

9. **Session wrap-up.** At session end:

   a. **Structured summary.** Read the scratch file and draft a
      structured technical summary. Use `add_structured_note` to save
      it as a Zotero note with:
      - **Method:** key equations, approximations, approach
      - **Key Parameters:** important values and units
      - **Main Results:** quantitative findings
      - **Limitations:** what the paper doesn't cover

      If a structured summary already exists (from a prior session),
      ask whether to replace or merge.

   b. **Session summary annotation.** Use `add_note_annotation` on
      page 1 to add a brief session record:
      ```
      Reading session YYYY-MM-DD
      Context: [why they read this]
      Key takeaways: [main findings]
      Open questions: [unresolved items]
      ```

   c. **Clean up.** Delete the scratch file from /tmp.

10. **Review.** Before syncing the structured summary and session
    annotation, present both to the reader for approval. Revise
    until they're satisfied.

## Output

All output lives in Zotero:
- **Structured summary note** (tagged "structured-summary") — reusable
  technical reference, loadable via `get_structured_note` and
  `get_collection_summaries`
- **Highlight annotations** on key passages with comments
- **Note annotations** for reader insights and session summary
- No local files persist after the session

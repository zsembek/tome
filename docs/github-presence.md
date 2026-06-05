# GitHub presence checklist

Repo-discoverability assets and the few steps that can only be done in the GitHub UI.

## 1. About (description + topics)

**Description** (Repo → About ⚙️ → Description):

```
Agent-native knowledge OS: turn messy PDFs, scans & DOCX into a verifiable, Markdown knowledge base that LLMs & AI agents read, search and curate — over REST, MCP and a React Library UI.
```

**Topics** (same dialog → Topics):

```
mcp, model-context-protocol, rag, llm, ai-agents, knowledge-base, postgresql, pgvector, self-hosted, python, claude, ocr
```

Topics drive discovery via https://github.com/topics — keep them on the repo.

## 2. Social preview image

A ready 1280×640 card lives at [`assets/social-preview.png`](../assets/social-preview.png).

Upload it: **Settings → General → Social preview → Edit → Upload an image.**
(GitHub has no API for this — it must be done in the UI.) This is the card shown when the
repo link is shared on Twitter/LinkedIn/Reddit/Slack.

## 3. Demo GIF (top of README)

Record a 30–60s capture of:
1. the **Library UI** — upload a PDF, watch it become structured sections;
2. an **agent walking the Atlas** over MCP (`get_atlas → list_folders → list_documents →
   list_sections → get_section`).

Save it as `docs/demo.gif`, then uncomment the `<img src="docs/demo.gif" …>` line near the
top of [`README.md`](../README.md). Tools: ScreenToGif / LICEcap / `ffmpeg` + `gifski`.

## 4. Release

`v0.1.0` is tagged. Publish the GitHub Release from the tag (Releases → Draft a new
release → choose `v0.1.0`) using [`docs/release-0.1.0.md`](release-0.1.0.md) as the body,
or it can be created via the API with a token that has `repo` scope.

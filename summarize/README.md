# summarize (core pipeline stage) — TODO

Two outputs, both via SUMMARIZE_MODEL (default gemini-pro, 1M ctx):
- per-paper summary: paper text/abstract -> short structured summary.
- corpus review (реферирование): N papers + question -> literature review with [N] citations,
  key findings, gaps. Port the SYNTHESIS prompts from old scientific-search backend/core/llm.py
  (SYNTHESIS_SYSTEM_PROMPT / SYNTHESIS_USER_PROMPT_TEMPLATE -> {content, key_findings, research_gaps}).

Interface (planned): summarize_paper(text) -> str ; review(papers, question, domain=None) -> Review.

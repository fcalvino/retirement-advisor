"""LLM-5 — `escape_html` is the one way untrusted text enters raw HTML.

Model output, imported plan JSON, goal names and feed fields reached
`st.markdown(..., unsafe_allow_html=True)` verbatim. Streamlit renders that
through react-markdown + rehype-raw without a sanitiser, so the markup was live.
"""

from __future__ import annotations

from dashboard.shared import escape_dollars, escape_html


def test_markup_characters_are_escaped():
    assert escape_html('<a href="x">\'&') == "&lt;a href=&quot;x&quot;&gt;&#x27;&amp;"


def test_non_strings_are_rendered_not_rejected():
    assert escape_html(None) == "None"
    assert escape_html(12.5) == "12.5"


def test_escaping_twice_is_visible_so_callers_escape_once():
    # Not idempotent on purpose (that is html.escape): escape at the site that
    # interpolates, never upstream, or the user sees "&amp;lt;".
    assert escape_html(escape_html("<")) == "&amp;lt;"


def test_inline_markdown_composes_with_escape_dollars():
    # Inside a raw `<div>` block markdown (and KaTeX) do not run, so only
    # escape_html applies there; inline markdown also needs the `$` escape.
    assert escape_dollars(escape_html("US$ <b>")) == "US\\$ &lt;b&gt;"

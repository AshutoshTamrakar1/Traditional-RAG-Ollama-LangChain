"""Unit tests for mindmap normalization (no external services required)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from output_parsers import MindmapOutputParser, normalize_mindmap  # noqa: E402

BRACE_STYLE = '''```mermaid
mindmap "Solar System Facts" {
    title "The Sun" {
        description "Star at center"
    }
    branch "Mars: The Red Planet" {
        detail "Iron oxide surface"
    }
}
```
For troubleshooting, visit: https://example.com'''

VALID = "mindmap\n  root((Solar System))\n    Sun\n    Mars"


def test_brace_style_is_converted_to_valid_mermaid():
    md = normalize_mindmap(BRACE_STYLE)
    assert md.startswith("mindmap\n")
    assert "{" not in md and "}" not in md and "```" not in md
    assert "root((Solar System Facts))" in md
    assert "Mars: The Red Planet" in md
    assert "troubleshooting" not in md


def test_valid_mermaid_is_idempotent():
    assert normalize_mindmap(VALID) == VALID
    assert normalize_mindmap(normalize_mindmap(BRACE_STYLE)) == normalize_mindmap(BRACE_STYLE)


def test_fenced_valid_mermaid_is_unwrapped():
    md = normalize_mindmap("```mermaid\n" + VALID + "\n```\nextra prose")
    assert md == VALID


def test_parser_exposes_node_count_and_is_valid():
    parsed = MindmapOutputParser().parse(VALID)
    assert parsed.node_count == 3
    assert parsed.is_valid


def test_garbage_input_still_yields_mindmap():
    md = normalize_mindmap("just some words")
    assert md.startswith("mindmap\n")

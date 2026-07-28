"""
Tests the markdown report generator's table-cell escaping. A raw '|' in a
cell is read by markdown as a new column boundary, and a raw newline ends
the row early -- a web_search action's description is multi-line by
construction ("Search results for 'x':\\ntitle\\nurl\\n..."), so without
escaping, that single action used to corrupt the rest of the Action Timeline
table's rendering below it.
"""
import uuid

from app.database import init_db, create_task, add_action, update_task_status
from app.reports.report import _md_table_cell, generate_markdown_report


def _new_task_id() -> str:
    return f"task_test_report_{uuid.uuid4().hex[:8]}"


def test_md_table_cell_escapes_pipe_characters():
    assert _md_table_cell("cheapest | most expensive") == "cheapest \\| most expensive"


def test_md_table_cell_collapses_newlines_to_spaces():
    assert _md_table_cell("line one\nline two\nline three") == "line one line two line three"


def test_md_table_cell_handles_none():
    assert _md_table_cell(None) == ""


def test_md_table_cell_handles_combined_pipe_and_newline():
    # This is the exact shape a web_search action's description takes:
    # "Search results for 'x':\n1. Title | extra — url\n   snippet"
    raw = "Search results for 'laptops':\n1. Cheap Laptop | Best Price — example.com\n   A great deal"
    cell = _md_table_cell(raw)
    assert "\n" not in cell
    assert cell.count("\\|") == 1
    assert "|" not in cell.replace("\\|", "")


def test_generate_markdown_report_survives_multiline_pipe_containing_description():
    """Integration check: a real report generated from a description shaped
    like a web_search result (multi-line, contains '|') should still produce
    a well-formed Action Timeline table -- same number of '|' delimiters on
    every data row as the header, and no row silently swallowed by an
    embedded newline breaking it in two."""
    task_id = _new_task_id()
    init_db()
    create_task(task_id, "search for the cheapest laptop")
    add_action(
        task_id=task_id,
        step=1,
        action_type="web_search",
        description=(
            "Search results for 'cheap laptops':\n"
            "1. Best Budget Laptop | 2026 Guide — example.com\n"
            "   Compare prices | specs | reviews"
        ),
        url="https://example.com",
    )
    update_task_status(task_id, "completed", result_summary="Found a laptop.")

    report_path = generate_markdown_report(task_id)
    assert report_path

    content = open(report_path, encoding="utf-8").read()
    lines = content.splitlines()

    header_idx = lines.index("| Step | Action | Description | Page URL |")
    data_row = lines[header_idx + 2]  # header, separator, then the one data row

    header_cols = lines[header_idx].count("|")
    data_cols = data_row.count("|") - data_row.count("\\|")
    assert data_cols == header_cols
    # Only one row for the one action -- a raw newline in the description
    # would have split it into extra (broken) lines instead of staying on
    # this single row, which is also the last line of the file.
    assert len(lines) == header_idx + 3

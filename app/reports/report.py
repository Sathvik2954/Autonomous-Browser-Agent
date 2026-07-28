import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from app.config import REPORTS_DIR
from app.database import get_task, get_actions, get_extracted_data

logger = logging.getLogger(__name__)


def _flatten_cell(value):
    """Renders a value for a markdown table cell / CSV field. List values (e.g. an
    `extract` step run with multiple=True, like wikipedia_lookup's infobox_rows) and
    dict values (e.g. a `transform` step's output, like amazon_price_search's
    `cheapest`) used to come out as Python's raw repr, which is technically not
    broken but reads as broken. Recursively render them into something a human
    would actually want to read instead."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(_flatten_cell(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_flatten_cell(v)}" for k, v in value.items())
    return str(value).replace("\t", ": ")


def _md_table_cell(text) -> str:
    """Markdown table cells can't safely contain a raw '|' (read as a column
    boundary) or a raw newline (ends the row early). A web_search action's
    description in particular is multi-line by construction ("Search results
    for 'x':\\ntitle\\nurl\\n...") and used to be dropped straight into a
    table cell unescaped, which corrupted the rest of the Action Timeline
    table's rendering below it."""
    if text is None:
        return ""
    text = str(text).replace("|", "\\|")
    return " ".join(text.splitlines())

def generate_markdown_report(task_id: str) -> str:
    """Generates a clean markdown report file for a finished task and returns the path."""
    task = get_task(task_id)
    if not task:
        return ""
        
    actions = get_actions(task_id)
    extracted_data = get_extracted_data(task_id)
    
    report_path = REPORTS_DIR / f"report_{task_id}.md"
    
    # Calculate stats
    started = task.get("started_at", "")
    completed = task.get("completed_at", "")
    duration_str = "Unknown"
    if started and completed:
        try:
            t1 = datetime.fromisoformat(started)
            t2 = datetime.fromisoformat(completed)
            duration_str = f"{(t2 - t1).total_seconds():.1f} seconds"
        except Exception:
            pass
            
    visited_urls = list(set([a["url"] for a in actions if a["url"]]))
    
    lines = []
    lines.append(f"# Task Execution Report: {task_id}")
    lines.append("")
    lines.append(f"**Objective**: {task.get('prompt', 'N/A')}")
    lines.append(f"**Status**: {task.get('status', 'N/A').upper()}")
    lines.append(f"**Duration**: {duration_str}")
    lines.append(f"**Steps Executed**: {len(actions)}")
    lines.append("")
    
    if task.get("error"):
        lines.append("## Error Details")
        lines.append(f"> {task['error']}")
        lines.append("")
        
    if task.get("result_summary"):
        lines.append("## Executive Summary")
        lines.append(task["result_summary"])
        lines.append("")
        
    lines.append("## Visited URLs")
    for url in visited_urls:
        lines.append(f"- [{url}]({url})")
    lines.append("")
    
    lines.append("## Extracted Data")
    if extracted_data:
        # Get all keys for header
        all_keys = set()
        for item in extracted_data:
            if isinstance(item, dict):
                all_keys.update(item.keys())
        keys = list(all_keys)
        
        if keys:
            # Table Header
            lines.append("| " + " | ".join(_md_table_cell(k) for k in keys) + " |")
            lines.append("| " + " | ".join(["---"] * len(keys)) + " |")
            # Table Rows
            for item in extracted_data:
                if isinstance(item, dict):
                    row_vals = [_md_table_cell(_flatten_cell(item.get(k, ""))) for k in keys]
                    lines.append("| " + " | ".join(row_vals) + " |")
        else:
            lines.append("```json")
            lines.append(json.dumps(extracted_data, indent=2))
            lines.append("```")
    else:
        lines.append("No structured data extracted.")
    lines.append("")
    
    lines.append("## Action Timeline")
    lines.append("| Step | Action | Description | Page URL |")
    lines.append("| --- | --- | --- | --- |")
    for a in actions:
        url_text = a["url"][:40] + "..." if a["url"] and len(a["url"]) > 40 else (a["url"] or "")
        description = _md_table_cell(a["description"])
        lines.append(f"| {a['step']} | **{a['action_type'].upper()}** | {description} | [{url_text}]({a['url']}) |")
        
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    return str(report_path)

def export_data_csv(task_id: str) -> str:
    """Exports extracted task data as CSV and returns the file path."""
    extracted_data = get_extracted_data(task_id)
    csv_path = REPORTS_DIR / f"data_{task_id}.csv"
    
    if not extracted_data:
        return ""
        
    # Find all keys
    all_keys = set()
    for item in extracted_data:
        if isinstance(item, dict):
            all_keys.update(item.keys())
    keys = sorted(list(all_keys))
    
    if not keys:
        return ""
        
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for item in extracted_data:
            if isinstance(item, dict):
                row = {k: _flatten_cell(item.get(k, "")) for k in keys}
                writer.writerow(row)
                
    return str(csv_path)

def export_data_json(task_id: str) -> str:
    """Exports extracted task data as JSON and returns the file path."""
    extracted_data = get_extracted_data(task_id)
    json_path = REPORTS_DIR / f"data_{task_id}.json"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, indent=2)
        
    return str(json_path)

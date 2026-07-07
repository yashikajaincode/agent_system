"""
ToolManager: the mandatory "engineering improvement" (Tool Calling).

Exposes 3 mock tools via Groq's native function-calling schema, plus a
dispatch() function that executes the actual Python behind each tool once
the LLM has decided to call it. Kept deliberately small and inspectable.
"""
import json
import random
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# Mock tool implementations
# ---------------------------------------------------------------------------

def get_current_date() -> dict:
    """Returns today's date. Used for document title pages / timelines."""
    return {"date": date.today().isoformat()}


def estimate_cost(item: str, quantity: int = 1) -> dict:
    """
    Mock cost estimator. Returns a plausible-looking unit/total cost for a
    named line item, so proposals/reports can include a budget section
    without needing a real pricing API.
    """
    random.seed(hash(item) % (2**32))  # deterministic per item name
    unit_cost = round(random.uniform(500, 5000), 2)
    return {
        "item": item,
        "quantity": quantity,
        "unit_cost_usd": unit_cost,
        "total_cost_usd": round(unit_cost * quantity, 2),
    }


def lookup_template(doc_type: str) -> dict:
    """
    Returns the expected section list for a given document type. Used by the
    Validator to check required sections, and by the Planner/Executor to know
    what to generate.
    """
    templates = {
        "proposal": ["Executive Summary", "Scope of Work", "Timeline", "Budget", "Next Steps"],
        "meeting_minutes": ["Attendees", "Agenda", "Discussion Points", "Action Items", "Next Meeting"],
        "project_plan": ["Overview", "Milestones", "Timeline", "Resources", "Risks"],
        "business_report": ["Executive Summary", "Findings", "Analysis", "Recommendations", "Conclusion"],
        "technical_design": ["Overview", "Architecture", "Design Decisions", "Tradeoffs", "Open Questions"],
        "sop": ["Purpose", "Scope", "Procedure Steps", "Responsibilities", "Revision History"],
    }
    key = doc_type.lower().strip().replace(" ", "_")
    sections = templates.get(key, ["Executive Summary", "Details", "Conclusion"])
    return {"doc_type": doc_type, "sections": sections}


_TOOL_IMPLS = {
    "get_current_date": get_current_date,
    "estimate_cost": estimate_cost,
    "lookup_template": lookup_template,
}

# ---------------------------------------------------------------------------
# Groq tool schema (native function-calling format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_date",
            "description": "Get today's date, used for document title pages and timelines.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_cost",
            "description": "Estimate the cost of a named line item for a budget/proposal section.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Name of the line item, e.g. 'cloud hosting'"},
                    "quantity": {"type": "integer", "description": "Quantity/units, default 1"},
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_template",
            "description": "Look up the standard required sections for a given business document type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string", "description": "Document type, e.g. 'proposal'"},
                },
                "required": ["doc_type"],
            },
        },
    },
]


def dispatch(tool_name: str, args: dict[str, Any]) -> dict:
    """Execute the named tool with the given args. Raises KeyError if unknown."""
    if tool_name not in _TOOL_IMPLS:
        raise KeyError(f"Unknown tool: {tool_name}")
    return _TOOL_IMPLS[tool_name](**args)


def dispatch_from_tool_call(tool_call) -> dict:
    """Convenience: dispatch directly from a Groq tool_call object."""
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments or "{}")
    return dispatch(name, args)

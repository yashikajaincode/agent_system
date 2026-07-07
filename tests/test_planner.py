"""
Test: Planner output validates against the Task/Plan schema.

We mock the LLM call (chat_json) so this test doesn't require a real Groq API
key or network access -- it only checks that Planner correctly wires a raw
LLM JSON response into validated Plan/Task pydantic objects.
"""
from unittest.mock import patch

from app.agent.planner import create_plan

MOCK_LLM_RESPONSE = {
    "doc_type": "proposal",
    "assumptions": ["Assumed a 3-month project timeline since none was specified."],
    "tasks": [
        {
            "id": "t1",
            "description": "Look up standard proposal sections",
            "type": "tool",
            "depends_on": [],
            "tool_name": "lookup_template",
        },
        {
            "id": "t2",
            "description": "Executive Summary",
            "type": "generate",
            "depends_on": ["t1"],
            "tool_name": None,
        },
        {
            "id": "t3",
            "description": "Budget",
            "type": "generate",
            "depends_on": ["t1"],
            "tool_name": None,
        },
    ],
}


def test_planner_output_validates_against_schema():
    with patch("app.agent.planner.chat_json", return_value=MOCK_LLM_RESPONSE):
        plan = create_plan("Write a proposal for a new client engagement")

    assert plan.doc_type == "proposal"
    assert len(plan.assumptions) == 1
    assert len(plan.tasks) == 3

    task_ids = {t.id for t in plan.tasks}
    assert task_ids == {"t1", "t2", "t3"}

    tool_task = next(t for t in plan.tasks if t.id == "t1")
    assert tool_task.type == "tool"
    assert tool_task.tool_name == "lookup_template"

    generate_task = next(t for t in plan.tasks if t.id == "t2")
    assert generate_task.type == "generate"
    assert generate_task.depends_on == ["t1"]

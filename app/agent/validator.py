"""
Validator: runs after execution, before DocxBuilder.

Checks that the required sections for the plan's doc_type are present and
non-empty in the DocumentContext. Never fails hard -- if something required
is missing, it injects a minimal placeholder so document generation can
still proceed (keeps the "never 500" guarantee end-to-end).
"""
import logging

from app.models.schemas import DocumentContext, Plan
from app.tools.tool_manager import lookup_template

logger = logging.getLogger("agent.validator")


def validate_and_fill(context: DocumentContext, plan: Plan) -> DocumentContext:
    expected = lookup_template(plan.doc_type)["sections"]

    # Map expected section names to any generated section whose task description
    # mentions that section name (case-insensitive substring match).
    task_desc_by_id = {}
    for task in plan.tasks:
        if task.type == "generate":
            task_desc_by_id[task.id] = task.description.lower()

    covered_sections = set()
    for section_name in expected:
        for task_id, desc in task_desc_by_id.items():
            content = context.sections.get(task_id, "")
            if section_name.lower() in desc and content.strip():
                covered_sections.add(section_name)
                break

    missing = [s for s in expected if s not in covered_sections]
    for section_name in missing:
        placeholder_key = f"_validator_fill_{section_name.replace(' ', '_').lower()}"
        context.sections[placeholder_key] = (
            f"{section_name}: [Not covered by agent-generated content; "
            f"placeholder inserted by Validator.]"
        )
        logger.warning("Validator inserted placeholder for missing section: %s", section_name)

    return context

"""
Planner: turns a natural language business request into a validated Plan.

Single LLM call, JSON mode. The prompt forces the model to, in order:
  1. Classify the target document type.
  2. Explicitly state any assumptions it's making about missing/ambiguous info
     (never silently guess, never refuse).
  3. Emit a task list (tool + generate tasks) with dependency ids.

The raw JSON is validated against the Task/Plan pydantic schema so the
Executor never has to deal with malformed structure.
"""
from app.core.llm_client import chat_json
from app.models.schemas import Plan

SYSTEM_PROMPT = """You are the planning module of an autonomous document-generation agent.

Given a natural language business request, you must respond with a single JSON object
(and nothing else) with this exact shape:

{
  "doc_type": "<one of: proposal, meeting_minutes, project_plan, business_report, technical_design, sop>",
  "assumptions": ["<explicit assumption 1>", "<explicit assumption 2>", ...],
  "tasks": [
    {
      "id": "<short unique id, e.g. t1>",
      "description": "<what this task does>",
      "type": "<tool | generate>",
      "depends_on": ["<id of task this depends on>", ...],
      "tool_name": "<your best guess: get_current_date | estimate_cost | lookup_template,
       only if type=tool, else null -- this is a non-binding hint; the actual tool
       invoked is decided later by a separate model call using native function calling>"
    }
  ]
}

Rules you MUST follow, in order:
1. First, classify the document type from the request, even if it is not explicitly named.
2. Then, if the request is missing information needed to write the document (audience,
   dates, budget, scope, etc.), do NOT ask a clarifying question and do NOT refuse.
   Instead, make a reasonable, clearly-labeled assumption and list it in "assumptions".
   If the request is fully specified, "assumptions" can be an empty list.
3. Only after doing the above, produce the task list.
4. Include at least one "tool" task and one "generate" task per major document
   section (use lookup_template's typical sections as a guide for what sections to
   generate). For "tool" tasks, "tool_name" is only a planning-time hint for
   readability -- it is not binding. The actual tool invocation happens later via
   native function calling, where a separate model call sees the real tool schemas
   and independently decides which tool to call and with what arguments.
5. Keep the dependency graph a simple chain or shallow tree -- generation tasks for
   content sections should depend on any tool tasks that feed them (e.g. a Budget
   section task depends on an estimate_cost tool task), not on each other unless truly
   necessary.
6. Respond with ONLY the JSON object. No markdown fences, no commentary.
"""


def create_plan(user_request: str) -> Plan:
    """Run the planning LLM call and return a validated Plan object."""
    raw = chat_json(system_prompt=SYSTEM_PROMPT, user_prompt=user_request)
    return Plan.model_validate(raw)

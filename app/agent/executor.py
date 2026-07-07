"""
Executor: runs a Plan's tasks in dependency order.

- Ordering: simple Kahn's-algorithm topological sort (linear, no general DAG
  scheduler, per spec).
- Dispatch: type="tool" -> the LLM is given the task description plus the
  Groq native function-calling tool schemas and DECIDES which tool to call
  and with what arguments; the Executor only dispatches whatever the model's
  tool_calls response specifies. type="generate" -> LLM call scoped to that
  section, using DocumentContext built up so far as input.
- Reliability: each task is wrapped in try -> on failure, 1 retry with a
  self-correction reprompt (the error is fed back to the LLM) -> on second
  failure, fall back to safe default content and continue. A single task
  failure must never bubble up into a 500 on /agent.
- Logging: one structured log line per task with status/duration_ms/retry_count.
"""
import logging
import time

from app.core.llm_client import chat_text, chat_with_tools
from app.models.schemas import DocumentContext, Plan, Task, TaskLog
from app.tools import tool_manager

logger = logging.getLogger("agent.executor")

TOOL_TASK_SYSTEM_PROMPT = """You are the tool-orchestration module of an autonomous
document-generation agent. Given a task description, decide which single tool from
the available functions best accomplishes it, and call that function with appropriate
arguments. Always call exactly one tool -- never respond with plain text instead of a
tool call."""

SECTION_GEN_SYSTEM_PROMPT = """You are the content-generation module of an autonomous
document-generation agent. Write ONLY the body text for a single document section.
No markdown headers, no preamble, no meta-commentary -- just the section content in
plain prose (paragraphs, and simple bullet lines using '- ' where a list is natural).
Keep it concrete and business-appropriate. Use the context provided (original request,
document type, assumptions made, and any tool outputs) to ground the content."""


def _topological_order(tasks: list[Task]) -> list[Task]:
    """Kahn's algorithm: simple, linear dependency resolution."""
    by_id = {t.id: t for t in tasks}
    in_degree = {t.id: len(t.depends_on) for t in tasks}
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    ordered: list[Task] = []

    # Build a simple adjacency map: task -> tasks that depend on it
    dependents: dict[str, list[str]] = {t.id: [] for t in tasks}
    for t in tasks:
        for dep in t.depends_on:
            if dep in dependents:
                dependents[dep].append(t.id)

    while queue:
        tid = queue.pop(0)
        ordered.append(by_id[tid])
        for dependent_id in dependents.get(tid, []):
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                queue.append(dependent_id)

    if len(ordered) != len(tasks):
        # Cycle or dangling dependency -- fall back to original order rather
        # than crash; this keeps the "never 500" guarantee.
        logger.warning("Topological sort incomplete (cycle/dangling dep); falling back to declared order")
        remaining = [t for t in tasks if t.id not in {o.id for o in ordered}]
        ordered.extend(remaining)

    return ordered


def _run_tool_task(task: Task, plan: Plan, context: DocumentContext, error_hint: str = "") -> dict:
    """
    Executes a 'tool' task via native Groq function-calling.

    The LLM is given the task description plus the available tool schemas and
    decides which tool to call and with what arguments -- this IS the mandatory
    Tool Calling improvement. The Executor does not pre-select a tool; it only
    dispatches whatever the model's tool_calls response specifies.
    """
    user_prompt = f"""Document type: {plan.doc_type}
Original request: {context.original_request}
Task: {task.description}
{f'Previous attempt failed with: {error_hint}. Reconsider which tool and arguments to use.' if error_hint else ''}
"""
    message = chat_with_tools(TOOL_TASK_SYSTEM_PROMPT, user_prompt, tool_manager.TOOL_SCHEMAS)

    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        raise RuntimeError(f"Tool task {task.id}: model did not call any tool")

    results: dict[str, dict] = {}
    for tool_call in tool_calls:
        result = tool_manager.dispatch_from_tool_call(tool_call)
        results[tool_call.function.name] = result

    # Single tool call -> store the flat result; multiple -> keyed by tool name.
    stored = results if len(results) > 1 else next(iter(results.values()))
    context.set_tool_output(task.id, stored)
    return stored


def _run_generate_task(task: Task, plan: Plan, context: DocumentContext, error_hint: str = "") -> str:
    tool_context = "\n".join(f"- {k}: {v}" for k, v in context.tool_outputs.items()) or "none"
    prior_sections = "\n".join(f"- {k}: {v[:200]}" for k, v in context.sections.items()) or "none"
    user_prompt = f"""Original request: {context.original_request}
Document type: {plan.doc_type}
Assumptions made: {plan.assumptions or 'none'}
Section to write: {task.description}
Relevant tool outputs so far: {tool_context}
Other sections already written (for consistency, do not repeat): {prior_sections}
{f'Previous attempt failed with: {error_hint}. Please correct and simplify.' if error_hint else ''}
"""
    content = chat_text(SECTION_GEN_SYSTEM_PROMPT, user_prompt)
    if not content or not content.strip():
        raise ValueError("LLM returned empty content for section")
    context.set_section(task.id, content)
    return content


def _fallback_content(task: Task) -> str:
    return f"[Content pending -- {task.description} could not be generated automatically. Please fill in manually.]"


def run_plan(plan: Plan, original_request: str) -> tuple[DocumentContext, list[TaskLog]]:
    """Execute all tasks in dependency order, returning the populated context and logs."""
    context = DocumentContext(
        doc_type=plan.doc_type,
        original_request=original_request,
        assumptions=plan.assumptions,
    )
    logs: list[TaskLog] = []
    ordered_tasks = _topological_order(plan.tasks)

    for task in ordered_tasks:
        start = time.perf_counter()
        retry_count = 0
        status = "failed"
        last_error = ""

        for attempt in range(2):  # initial attempt + 1 retry
            try:
                if task.type == "tool":
                    _run_tool_task(task, plan, context, error_hint=last_error)
                else:
                    _run_generate_task(task, plan, context, error_hint=last_error)
                status = "success" if attempt == 0 else "retried_success"
                break
            except Exception as exc:  # noqa: BLE001 -- intentional broad catch for reliability
                last_error = str(exc)
                retry_count = 1  # only 2 attempts total (initial + 1 retry), so any failure means 1 retry was used
                logger.warning(
                    "task=%s attempt=%d failed: %s", task.id, attempt + 1, last_error
                )
                continue
        else:
            # Both attempts failed -> safe fallback, never propagate
            if task.type == "generate":
                context.set_section(task.id, _fallback_content(task))
            else:
                context.set_tool_output(task.id, {"error": last_error, "fallback": True})
            status = "fallback"
            retry_count = 1

        duration_ms = int((time.perf_counter() - start) * 1000)
        log_entry = TaskLog(
            task_id=task.id,
            status=status,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )
        logs.append(log_entry)
        logger.info(
            "task_id=%s status=%s duration_ms=%d retry_count=%d",
            log_entry.task_id, log_entry.status, log_entry.duration_ms, log_entry.retry_count,
        )

    return context, logs

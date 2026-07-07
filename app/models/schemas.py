"""
Pydantic models shared across the agent pipeline.

Planner produces a Plan (validated here). Executor consumes it, writes into
DocumentContext, and produces TaskLog entries. DocxBuilder reads DocumentContext.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    request: str = Field(..., min_length=1, description="Natural language business request")


class Task(BaseModel):
    id: str
    description: str
    type: Literal["tool", "generate"]
    depends_on: list[str] = Field(default_factory=list)
    # Planning-time hint only when type == "tool" -- NOT used for dispatch.
    # The actual tool invoked is decided at execution time by the model itself
    # via native function calling (see Executor._run_tool_task). Kept here so
    # the API response's visible task list still shows the planner's intent.
    tool_name: Optional[str] = None


class Plan(BaseModel):
    doc_type: str = Field(..., description="Inferred document type, e.g. 'proposal', 'meeting_minutes'")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit assumptions the planner made for missing/ambiguous info",
    )
    tasks: list[Task]


class TaskLog(BaseModel):
    task_id: str
    status: Literal["success", "retried_success", "fallback", "failed"]
    duration_ms: int
    retry_count: int


class AgentResponse(BaseModel):
    plan: Plan
    execution_log: list[TaskLog]
    document_path: str


class DocumentContext(BaseModel):
    """
    Mutable working memory populated by the Executor as tasks complete.
    Keyed by task_id -> generated/tool content for that task.
    DocxBuilder reads this plus the Plan to render the final .docx.
    """
    doc_type: str
    original_request: str
    assumptions: list[str] = Field(default_factory=list)
    sections: dict[str, str] = Field(default_factory=dict)  # task_id -> section text
    tool_outputs: dict[str, dict] = Field(default_factory=dict)  # task_id -> tool result

    def set_section(self, task_id: str, content: str) -> None:
        self.sections[task_id] = content

    def set_tool_output(self, task_id: str, output: dict) -> None:
        self.tool_outputs[task_id] = output

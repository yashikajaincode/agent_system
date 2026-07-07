"""
FastAPI entrypoint. POST /agent orchestrates:
  Planner -> Executor -> Validator -> DocxBuilder -> AgentResponse

The per-task retry/fallback logic lives in the Executor; this layer adds one
more safety net so that even an unexpected error in Planner/Validator/DocxBuilder
(outside the per-task loop) returns a clean JSON error instead of a bare 500.
"""
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from app.agent.executor import run_plan
from app.agent.planner import create_plan
from app.agent.validator import validate_and_fill
from app.core.config import settings
from app.documents.docx_builder import build_docx
from app.models.schemas import AgentRequest, AgentResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agent.main")

app = FastAPI(title="Autonomous Document Agent", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.get("/")
def serve_frontend():
    """Serves the basic web UI for manually exercising the agent."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/download/{filename}")
def download_document(filename: str):
    """
    Serves a previously generated .docx from the output directory.
    Uses os.path.basename to prevent path traversal (e.g. ../../etc/passwd).
    """
    safe_name = os.path.basename(filename)
    file_path = os.path.join(settings.output_dir, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(
        file_path,
        filename=safe_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/agent", response_model=AgentResponse)
def agent_endpoint(payload: AgentRequest):
    try:
        plan = create_plan(payload.request)
        context, logs = run_plan(plan, payload.request)
        context = validate_and_fill(context, plan)
        doc_path = build_docx(plan, context)

        return AgentResponse(
            plan=plan,
            execution_log=logs,
            document_path=doc_path,
        )
    except Exception as exc:  # noqa: BLE001 -- top-level safety net, never bare 500
        logger.exception("Unhandled error in /agent")
        return JSONResponse(
            status_code=200,
            content={
                "error": "Agent encountered an unrecoverable error and could not complete the request.",
                "detail": str(exc),
            },
        )


@app.get("/health")
def health():
    return {"status": "ok"}

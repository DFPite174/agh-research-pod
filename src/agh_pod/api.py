"""Local single-user HTTP and HTML interfaces to the evidence workflow."""
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from starlette.middleware.trustedhost import TrustedHostMiddleware

from fastapi import BackgroundTasks, Body, FastAPI, Header, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from .workflow import IntegrityError, Pod, StateError


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpportunityRequest(StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    research_type: Literal["investment_research", "capability_evaluation"]
    problem: str = Field(default="", max_length=10000)


class SpecRequest(StrictRequest):
    recipe: Literal["demo", "paper", "quant"]
    seed: int = Field(default=7, ge=0, lt=2**32)
    dataset: str | None = Field(default=None, max_length=4096)
    steps: int = Field(default=200, ge=2, le=2000)
    paths: int = Field(default=10000, ge=2, le=100000)


    target: str | None = Field(default=None, max_length=200)
    features: list[str] | None = Field(default=None, max_length=30)
    min_train: int = Field(default=36, ge=12, le=2000)
    ridge: float = Field(default=1.0, gt=0, le=1000000)


class AnalysisRequest(StrictRequest):
    artifact_ids: list[str] = Field(min_length=1, max_length=20)
    max_output_tokens: int = Field(default=1200, ge=1, lt=100000)
    max_total_tokens: int = Field(default=5000, gt=1, le=100000)


class MandateRequest(StrictRequest):
    objective: str = Field(min_length=1, max_length=3000)
    baseline: str = Field(min_length=1, max_length=3000)
    acceptance: str = Field(min_length=1, max_length=3000)
    stop_condition: str = Field(min_length=1, max_length=3000)
    receiver: str = Field(min_length=1, max_length=3000)


class DeliveryRequest(StrictRequest):
    receiver: str = Field(min_length=1, max_length=3000)
    decision: Literal["accepted", "rejected", "followup"]
    reason: str = Field(min_length=1, max_length=3000)


class EmptyRequest(StrictRequest):
    pass


class ReviewRequest(StrictRequest):
    reviewer: str = Field(min_length=1, max_length=200)
    decision: Literal["engineering_verified", "needs_data", "rejected", "scientifically_reviewed"]


class ArtifactLinkRequest(StrictRequest):
    artifact_id: str = Field(min_length=1, max_length=100)


def create_app(root="./runtime"):
    """Bind an app to one local Pod. No arbitrary code or file-serving routes."""
    pod = Pod(root)
    app = FastAPI(title="AGH ResearchPod", version="0.2.1")
    app.state.pod = pod
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return JSONResponse(status_code=403, content={"detail": "invalid request origin"})
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
                return JSONResponse(status_code=403, content={"detail": "cross-origin mutation refused"})
        return await call_next(request)

    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    @app.exception_handler(KeyError)
    async def missing(_request, _exc):
        return JSONResponse(status_code=404, content={"detail": "object not found"})

    @app.exception_handler(StateError)
    @app.exception_handler(IntegrityError)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "scope": "local_single_trusted_user", "research_certification": False}

    @app.get("/v1/opportunities")
    def opportunities(limit: Annotated[int, Query(ge=1, le=1000)] = 200,
                      offset: Annotated[int, Query(ge=0)] = 0):
        return pod.list("opportunity", limit=limit, offset=offset)

    @app.post("/v1/opportunities", status_code=201)
    def create_opportunity(body: OpportunityRequest):
        return pod.create_opportunity(**body.model_dump())

    @app.post("/v1/opportunities/{opportunity_id}/mandate")
    def mandate(opportunity_id: str, body: MandateRequest):
        return pod.set_mandate(opportunity_id, body.model_dump())

    @app.post("/v1/packages/{package_id}/receive")
    def receive(package_id: str, body: DeliveryRequest):
        return pod.receive_package(package_id, **body.model_dump())

    @app.post("/v1/analyses", status_code=201)
    def analyze_evidence(body: AnalysisRequest):
        return pod.analyze_artifacts(**body.model_dump())

    @app.get("/v1/analyses")
    def analyses(limit: Annotated[int, Query(ge=1, le=200)] = 50):
        return pod.list("analysis", limit=limit)

    @app.get("/v1/artifacts")
    def artifacts(limit: Annotated[int, Query(ge=1, le=1000)] = 200,
                  offset: Annotated[int, Query(ge=0)] = 0):
        return pod.list("artifact", limit=limit, offset=offset)

    @app.post("/v1/opportunities/{opportunity_id}/specs", status_code=201)
    def create_spec(opportunity_id: str, body: SpecRequest):
        return pod.create_spec(opportunity_id, body.model_dump(exclude_unset=True))

    @app.post("/v1/opportunities/{opportunity_id}/artifacts")
    def link_artifact(opportunity_id: str, body: ArtifactLinkRequest):
        return pod.link_artifact(opportunity_id, body.artifact_id)

    @app.post("/v1/specs/{spec_id}/approve")
    def approve(spec_id: str, body: EmptyRequest = Body(default=EmptyRequest())):
        return pod.approve(spec_id)

    @app.post("/v1/specs/{spec_id}/runs", status_code=202)
    def submit(spec_id: str, tasks: BackgroundTasks,
               body: EmptyRequest = Body(default=EmptyRequest()),
               idempotency_key: Annotated[str | None, Header(min_length=1, max_length=200)] = None):
        run = pod.submit(spec_id, idempotency_key=idempotency_key)
        if run["status"] == "queued":
            tasks.add_task(pod.execute, run["id"])
        return run

    @app.get("/v1/runs/{run_id}")
    def run(run_id: str):
        return pod.get("run", run_id)

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel(run_id: str, body: EmptyRequest = Body(default=EmptyRequest())):
        return pod.cancel(run_id)

    @app.post("/v1/runs/{run_id}/reviews", status_code=201)
    def review(run_id: str, body: ReviewRequest):
        return pod.review(run_id, **body.model_dump())

    @app.post("/v1/runs/{run_id}/packages", status_code=201)
    def package(run_id: str, body: EmptyRequest = Body(default=EmptyRequest())):
        return pod.export_package(run_id)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        from .cases import case_status
        return templates.TemplateResponse(request=request, name="index.html", context={
            "opportunities": pod.list("opportunity"), "artifacts": pod.list("artifact"),
            "specs": pod.list("spec"), "runs": pod.run_summaries(), "reviews": pod.list("review"),
            "analyses": pod.list("analysis", limit=20), "packages": pod.list("package"), "deliveries": pod.list("delivery"), "case": case_status(),
        })

    return app

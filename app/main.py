import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.errors import AppError
from app.schemas import ErrorDetail, ErrorResponse, LinkAnalysisRequest, LinkAnalysisResponse
from app.services.analysis_service import AnalysisService
from app.services.competitor_service import CompetitorService
from app.services.llm_service import LLMService
from app.services.website_extractor import WebsiteExtractor

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("link-analysis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    llm = LLMService(settings)
    app.state.analysis_service = AnalysisService(settings, WebsiteExtractor(settings), llm, CompetitorService())
    yield
    await llm.aclose()


app = FastAPI(
    title="AI Link Analysis API",
    description="Analyses a website URL with an LLM and returns competitor, search query, SEO, service and audience insights.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    return error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return error_response(422, "validation_error", "The request body must be JSON with a non-empty 'url' string.")


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    logger.exception("unhandled error")
    return error_response(500, "internal_error", "An unexpected error occurred.")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}


@app.post(
    "/link-analysis",
    response_model=LinkAnalysisResponse,
    tags=["analysis"],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid URL or blocked address"},
        422: {"model": ErrorResponse, "description": "Invalid request or unusable page content"},
        502: {"model": ErrorResponse, "description": "Website or LLM provider failure"},
        503: {"model": ErrorResponse, "description": "LLM not configured or rate limited"},
        504: {"model": ErrorResponse, "description": "Upstream timeout"},
    },
)
async def link_analysis(
    payload: LinkAnalysisRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
):
    return await service.analyze(payload.url, refresh=payload.refresh)

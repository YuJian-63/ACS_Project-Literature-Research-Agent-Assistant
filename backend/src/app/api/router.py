from fastapi import APIRouter

from app.api.agent_library import router as agent_library_router
from app.api.agent_research import router as agent_research_router
from app.api.model_services import router as model_router
from app.api.health import router as health_router
from app.api.papers import router as papers_router
from app.api.schemas import ErrorResponse
from app.api.tasks import router as tasks_router

router = APIRouter(responses={
    status: {"model": ErrorResponse} for status in (404, 409, 413, 415, 422, 500, 503)
})
router.include_router(model_router)
router.include_router(health_router)
router.include_router(papers_router)
router.include_router(agent_library_router)
router.include_router(agent_research_router)
router.include_router(tasks_router)

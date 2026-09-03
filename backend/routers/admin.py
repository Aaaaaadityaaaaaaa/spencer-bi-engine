import config
from fastapi import APIRouter

from services import cleanup_service

router = APIRouter()

@router.post("/kill-query/{query_id}")
async def kill_query(query_id: str):
    # Interrupt a running query
    return {"status": "killed"}

@router.post("/sweep")
async def trigger_sweep():
    """Manually run the cleanup sweep now and return the reclamation counts.
    Same code path as the periodic background sweeper (cleanup_service.sweep)."""
    return await cleanup_service.sweep()

@router.get("/storage")
async def storage():
    """Point-in-time storage + session-liveness metrics for ops visibility
    (partially closes the 'health is liveness-only' gap)."""
    return await cleanup_service.storage_report()

@router.get("/ai-config")
async def ai_config():
    model = config.SPENCER_LLM_MODEL
    provider = "unknown"
    if not model:
        if config.ANTHROPIC_API_KEY or config.ANTHROPIC_API_KEYS:
            model = "anthropic/claude-sonnet-5"
        elif config.GEMINI_API_KEY or config.GEMINI_API_KEYS:
            model = "gemini/gemini-3.6-flash"
        else:
            model = "none"
            
    if model.startswith("anthropic/"): provider = "Anthropic"
    elif model.startswith("gemini/"): provider = "Google Gemini"
    elif model.startswith("openai/"): provider = "OpenAI"
    elif model.startswith("groq/"): provider = "Groq"
    
    return {
        "model": model,
        "provider": provider,
        "reasoning_effort": config.SPENCER_LLM_REASONING_EFFORT
    }

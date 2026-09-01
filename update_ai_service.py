import sys
import re

with open('backend/services/ai_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Rename _call_llm to _call_model_with_pool
# We must be careful because the docstring has a quote. Let's just find the definition line.
content = content.replace(
    'async def _call_llm(self, model: str, system: str, user: str) -> str:',
    'async def _call_model_with_pool(self, model: str, system: str, user: str) -> str:'
)

# 2. Find where _call_model_with_pool ends, which is just before `async def resolve_sql(self, ...)`
# We will inject `async def _call_llm(self, primary_model: str, system: str, user: str) -> str:` right before `async def resolve_sql`
new_call_llm = '''
    async def _call_llm(self, primary_model: str, system: str, user: str) -> str:
        """Entrypoint for LLM completions with fallback chain support.
        
        Attempts the primary model (with key rotation via _call_model_with_pool).
        If exhausted or failed, gracefully moves to models in SPENCER_LLM_FALLBACK_MODELS.
        """
        models = [primary_model]
        fallbacks = os.environ.get("SPENCER_LLM_FALLBACK_MODELS", "")
        if fallbacks:
            models.extend([m.strip() for m in fallbacks.split(",") if m.strip()])

        last_err = None
        soonest = None
        
        for model in models:
            try:
                return await self._call_model_with_pool(model, system, user)
            except LLMConfigError as e:
                last_err = e
                logger.warning("llm fallback: model '%s' misconfigured or missing litellm (%s), trying next", model, e)
                continue
            except LLMRateLimitError as e:
                last_err = e
                # Fallback on rate limit
                soonest = e.retry_after if soonest is None else min(soonest, e.retry_after)
                logger.warning("llm fallback: model '%s' rate-limited, trying next", model)
                continue
            except LLMAPIError as e:
                last_err = e
                # Fallback on transport/auth error
                logger.warning("llm fallback: model '%s' API error (%s), trying next", model, e)
                continue

        if isinstance(last_err, LLMRateLimitError):
            raise LLMRateLimitError(
                "All AI models in the fallback chain are exhausted or rate-limited.",
                retry_after=soonest or 60,
            )
        if last_err:
            raise last_err
            
        raise LLMConfigError("No valid LLM models configured in the fallback chain.")

    async def resolve_sql(
'''

content = content.replace('    async def resolve_sql(\n', new_call_llm.lstrip('\n'))

with open('backend/services/ai_service.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated ai_service.py with fallback chain")

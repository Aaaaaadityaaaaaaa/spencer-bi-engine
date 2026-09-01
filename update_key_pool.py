import sys
import re

with open('backend/services/llm_key_pool.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_providers = """_PROVIDER_ENV: Dict[str, Tuple[str, str]] = {
    "gemini": ("GEMINI_API_KEYS", "GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"),
    "openai": ("OPENAI_API_KEYS", "OPENAI_API_KEY"),
    "groq": ("GROQ_API_KEYS", "GROQ_API_KEY"),
    "cohere": ("COHERE_API_KEYS", "COHERE_API_KEY"),
}"""

content = re.sub(
    r'_PROVIDER_ENV: Dict\[str, Tuple\[str, str\]\] = \{.*?"anthropic": \("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"\),\n\}',
    new_providers,
    content,
    flags=re.DOTALL
)

with open('backend/services/llm_key_pool.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added extra providers to llm_key_pool.py")

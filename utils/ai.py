"""Shared free-tier AI client (Groq by default, any OpenAI-compatible endpoint works)."""
import os
from openai import AsyncOpenAI
import openai


class AIUnavailable(Exception):
    """Raised when the AI backend can't answer (no key, rate limit, timeout...)."""


_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    key = os.getenv("GROQ_API_KEY") or os.getenv("AI_API_KEY")
    if not key:
        raise AIUnavailable("No GROQ_API_KEY set.")
    if _client is None:
        _client = AsyncOpenAI(
            base_url=os.getenv("AI_BASE_URL", "https://api.groq.com/openai/v1"),
            api_key=key,
            timeout=30.0,
        )
    return _client


def model_name() -> str:
    return os.getenv("AI_MODEL", "openai/gpt-oss-120b")


async def chat(messages: list[dict], max_tokens: int = 600) -> str:
    client = _get_client()
    try:
        model = model_name()
        extra = {"reasoning_effort": "low"} if "gpt-oss" in model else {}
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens + (400 if extra else 0),  # headroom for reasoning tokens
            temperature=0.7,
            extra_body=extra or None,
        )
    except openai.RateLimitError as e:
        raise AIUnavailable("Rate limited.") from e
    except (openai.APITimeoutError, openai.APIConnectionError) as e:
        raise AIUnavailable("Could not reach the AI service.") from e
    except openai.APIStatusError as e:
        print(f"[AI] {e.status_code} from AI service (model={model_name()}): {e.message}")
        raise AIUnavailable(f"AI service error ({e.status_code}).") from e
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise AIUnavailable("Empty response.")
    return text


def unavailable_embed():
    import discord
    return discord.Embed(
        title="😴 JengGPT is resting",
        description="The AI service is unavailable or rate-limited right now. Try again in a minute!",
        color=discord.Color.orange(),
    )

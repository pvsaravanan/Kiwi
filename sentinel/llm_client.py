import os
import sys

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# Imported at module load, like the two above: importing it lazily inside
# get_llm_client() cost ~1.7s on the first /login instead of at server startup.
try:
    import openai
except ImportError:
    openai = None


def get_llm_client():
    from sentinel.session_state import load_state
    provider = None
    model = None
    api_key = None
    state = load_state()
    if state.get("is_logged_in"):
        provider = state.get("llm_provider", "").lower() or None
        model = state.get("llm_model")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if provider == "anthropic" and anthropic_key and anthropic_key != "your_anthropic_key_here":
        api_key = anthropic_key
    elif provider == "gemini" and gemini_key and gemini_key != "your_gemini_key_here":
        api_key = gemini_key
    elif provider == "openai" and openai_key and openai_key != "your_openai_key_here":
        api_key = openai_key
    elif not provider:
        if anthropic_key and anthropic_key != "your_anthropic_key_here":
            provider, api_key = "anthropic", anthropic_key
        elif gemini_key and gemini_key != "your_gemini_key_here":
            provider, api_key = "gemini", gemini_key
        elif openai_key and openai_key != "your_openai_key_here":
            provider, api_key = "openai", openai_key
    if not provider or not api_key:
        return None, None, None

    if provider == "anthropic" and anthropic:
        return "anthropic", anthropic.Anthropic(api_key=api_key), model or "claude-opus-4-8"
    elif provider == "gemini" and genai:
        return "gemini", genai.Client(api_key=api_key), model or "gemini-3-flash-preview"
    elif provider == "openai" and openai:
        return "openai", openai.OpenAI(api_key=api_key), model or "gpt-5.5"
    return None, None, None


def ask_llm(provider, client, prompt: str, system_instruction: str = "You are Kiwi, a helpful QA assistant.", model=None) -> str:
    if provider == "anthropic":
        try:
            msg = client.messages.create(
                model=model or "claude-opus-4-8",
                max_tokens=1024,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt}]
            )
            return next((b.text for b in msg.content if b.type == "text"), "")
        except Exception as exc:
            return f"Error communicating with Anthropic: {exc}"
    elif provider == "gemini":
        try:
            response = client.models.generate_content(
                model=model or "gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=1024,
                )
            )
            return response.text or ""
        except Exception as exc:
            return f"Error communicating with Gemini: {exc}"
    elif provider == "openai":
        try:
            resp = client.chat.completions.create(
                model=model or "gpt-5.5",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1024
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            return f"Error communicating with OpenAI: {exc}"
    return ""


def stream_llm(provider, client, prompt: str, system_instruction: str = "You are Kiwi, a helpful QA assistant.", model=None):
    if provider == "anthropic":
        try:
            with client.messages.stream(
                model=model or "claude-opus-4-8",
                max_tokens=1024,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as exc:
            yield f"Error communicating with Anthropic: {exc}"
    elif provider == "gemini":
        try:
            from google.genai import types
            response = client.models.generate_content_stream(
                model=model or "gemini-3-flash-preview",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=1024,
                )
            )
            for chunk in response:
                yield chunk.text or ""
        except Exception as exc:
            yield f"Error communicating with Gemini: {exc}"
    elif provider == "openai":
        try:
            resp = client.chat.completions.create(
                model=model or "gpt-5.5",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=1024,
                stream=True
            )
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            yield f"Error communicating with OpenAI: {exc}"


def validate_llm_credentials(provider: str, model: str) -> tuple[bool, str]:
    """
    Verifies the active LLM credentials via a lightweight models-metadata lookup.

    Deliberately *not* a generation call: sending even a 5-token "ping" to a
    reasoning model (gpt-5.x, gemini-3, thinking-enabled Claude) costs many
    seconds of model time and made /login take ~12s. A models lookup
    authenticates the same key - and confirms the chosen model is reachable -
    in well under a second.
    """
    p, client, m = get_llm_client()
    if not p or not client:
        label = (provider or "the selected provider").capitalize()
        return False, f"No valid API key or client setup found in environment for {label}."

    try:
        if p == "anthropic":
            client.models.retrieve(m)
        elif p == "gemini":
            client.models.get(model=m)
        elif p == "openai":
            client.models.retrieve(m)
        return True, ""
    except Exception as e:
        return False, str(e)

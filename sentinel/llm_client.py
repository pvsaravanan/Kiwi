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


def get_llm_client():
    import json
    state_file = "kiwi_session_state.json"
    provider = None
    model = None
    api_key = None
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
            if state.get("is_logged_in"):
                provider = state.get("llm_provider", "").lower() or None
                model = state.get("llm_model")
        except Exception:
            pass

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
    elif provider == "openai":
        try:
            import openai
            return "openai", openai.OpenAI(api_key=api_key), model or "gpt-5.5"
        except ImportError:
            pass
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
                max_tokens=1024
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            return f"Error communicating with OpenAI: {exc}"
    return ""

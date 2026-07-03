import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from sentinel.cognee_client import CogneeClient, CogneeError
from sentinel.config import load_settings
from sentinel.ingest import process_report
from sentinel.reviewer import fallback_review, build_review

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

console = Console()


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
                provider = state.get("llm_provider", "").lower()
                model = state.get("llm_model")
                api_key = state.get("api_key")
        except Exception:
            pass

    if not provider:
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        openai_key = os.environ.get("OPENAI_API_KEY")
        if anthropic_key and anthropic_key != "your_anthropic_key_here":
            provider = "anthropic"
            api_key = anthropic_key
        elif gemini_key and gemini_key != "your_gemini_key_here":
            provider = "gemini"
            api_key = gemini_key
        elif openai_key and openai_key != "your_openai_key_here":
            provider = "openai"
            api_key = openai_key

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
            response = client.chat.completions.create(
                model=model or "gpt-5.5",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1024
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            return f"Error communicating with OpenAI: {exc}"
    return "No LLM API key configured."


def print_help():
    table = Table(title="🥝 Kiwi Commands", show_header=True, header_style="bold green")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_row("/recall <query>", "Query Cognee memory directly.")
    table.add_row("/remember <text>", "Save a custom fact/incident to Cognee memory.")
    table.add_row("/review [xml_path]", "Ingest JUnit XML report, recall matches, and suggest fixes.")
    table.add_row("/test", "Run test suite (pytest), auto-ingest failures, and review them.")
    table.add_row("/forget", "Clear the Kiwi dataset in Cognee memory.")
    table.add_row("/help", "Show this help table.")
    table.add_row("/exit or /quit", "Exit Kiwi.")
    console.print(table)
    console.print("Or simply [bold yellow]type a question[/bold yellow] about your tests or codebase!\n")


def run_session(client, settings, input_func=input):
    console.print(Panel.fit(
        "🥝 [bold green]Kiwi (QA tool)[/bold green] — Powered by [bold cyan]Cognee memory[/bold cyan]\n"
        "Your intelligent test failure and resolution assistant.",
        border_style="green"
    ))
    console.print("Welcome to Kiwi! Type [cyan]/help[/cyan] for a list of commands.\n")

    while True:
        try:
            line = input_func("Kiwi > ")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold red]Exiting Kiwi. Goodbye![/bold red]")
            break

        line = line.strip()
        if not line:
            continue

        if line.lower() in ("/exit", "/quit"):
            console.print("[bold red]Goodbye![/bold red]")
            break

        if line.lower() == "/help":
            print_help()
            continue

        if line.startswith("/"):
            parts = line.split(" ", 1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "/remember":
                if not arg:
                    console.print("[bold yellow]Please specify the text to remember.[/bold yellow] E.g. [cyan]/remember fixed by updating port[/cyan]")
                    continue
                
                with console.status(f"[bold cyan]Storing fact in Cognee dataset '{settings.dataset}'...[/bold cyan]"):
                    try:
                        client.remember(arg, dataset=settings.dataset)
                        console.print("[bold green]✓[/bold green] Fact successfully stored.")
                    except CogneeError as exc:
                        console.print(f"[bold red]✗ Failed to store fact:[/bold red] {exc}")

            elif cmd == "/recall":
                if not arg:
                    console.print("[bold yellow]Please specify a search query.[/bold yellow] E.g. [cyan]/recall double charge[/cyan]")
                    continue
                
                with console.status(f"[bold cyan]Searching Cognee dataset '{settings.dataset}'...[/bold cyan]"):
                    try:
                        hits = client.recall(arg, dataset=settings.dataset)
                        if hits:
                            console.print("\n[bold green]🔍 Matching Memories:[/bold green]")
                            for idx, hit in enumerate(hits, 1):
                                text = hit.get('text', '')
                                console.print(Panel(text, title=f"Memory #{idx}", border_style="cyan"))
                            print()
                        else:
                            console.print("[bold yellow]No matching memories found.[/bold yellow]")
                    except CogneeError as exc:
                        console.print(f"[bold red]✗ Search failed:[/bold red] {exc}")

            elif cmd == "/review":
                xml_path = arg if arg else "junit_report.xml"
                if not os.path.exists(xml_path):
                    console.print(f"[bold red]JUnit XML file '{xml_path}' not found.[/bold red] Run /test first or specify the path.")
                    continue
                with console.status(f"[bold cyan]Processing test report '{xml_path}'...[/bold cyan]"):
                    results = process_report(xml_path, client=client, dataset=settings.dataset)
                for r in results:
                    review = build_review(r)
                    console.print(Panel(Markdown(review), title=f"Review for {r.failure.test_name}", border_style="yellow"))

            elif cmd == "/test":
                console.print("[bold cyan]Running test suite: 'pytest --junitxml=junit_report.xml'...[/bold cyan]")
                res = subprocess.run(["uv", "run", "pytest", "--junitxml=junit_report.xml"], capture_output=True, text=True)
                console.print(res.stdout)
                if res.stderr:
                    console.print(res.stderr, style="red")
                if os.path.exists("junit_report.xml"):
                    with console.status("[bold cyan]Processing results and calling memory...[/bold cyan]"):
                        results = process_report("junit_report.xml", client=client, dataset=settings.dataset)
                    for r in results:
                        review = build_review(r)
                        console.print(Panel(Markdown(review), title=f"Review for {r.failure.test_name}", border_style="yellow"))
                else:
                    console.print("[bold red]✗ No junit_report.xml generated. Check pytest output.[/bold red]")

            elif cmd == "/forget":
                with console.status(f"[bold red]Clearing dataset '{settings.dataset}' in Cognee memory...[/bold red]"):
                    try:
                        client.forget(dataset=settings.dataset)
                        console.print("[bold green]✓[/bold green] Dataset cleared.")
                    except CogneeError as exc:
                        console.print(f"[bold red]✗ Failed to clear dataset:[/bold red] {exc}")

            else:
                console.print(f"[bold red]Unknown command: {cmd}[/bold red]. Type [cyan]/help[/cyan] for available commands.")

        else:
            context_str = ""
            with console.status("[bold cyan]Recalling relevant context from Cognee memory...[/bold cyan]"):
                try:
                    hits = client.recall(line, dataset=settings.dataset)
                    if hits:
                        context_str = "\n".join(f"- {h.get('text')}" for h in hits)
                except CogneeError as exc:
                    console.print(f"[bold yellow][WARNING] Failed to retrieve context from memory: {exc}[/bold yellow]")

            provider, llm = get_llm_client()
            if not llm:
                console.print("[bold yellow][WARNING] No LLM configured. Outputting memory recall only.[/bold yellow]")
                if context_str:
                    console.print(Panel(context_str, title="Recalled Context", border_style="cyan"))
                else:
                    console.print("No matching memory context found.")
                continue

            prompt = line
            if context_str:
                prompt = (
                    "Context retrieved from memory of past failures/incidents:\n"
                    f"{context_str}\n\n"
                    f"User Query:\n{line}\n\n"
                    "Please answer the user's query utilizing the recalled context above if relevant."
                )

            system_instruction = (
                "You are Kiwi, a developer's QA assistant with access to historical memory of test failures and resolutions. "
                "Synthesize clear, grounded, and concise answers."
            )
            
            with console.status(f"[bold cyan]Asking {provider.capitalize()}...[/bold cyan]"):
                ans = ask_llm(provider, llm, prompt, system_instruction)
            console.print(Panel(Markdown(ans), title="Kiwi Answer", border_style="green"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        settings = load_settings()
        client = CogneeClient(settings)
    except Exception as e:
        print(f"[Kiwi Error] Failed to load settings: {e}")
        sys.exit(1)

    run_session(client, settings)


if __name__ == "__main__":
    main()

import os
import sys
from rich.console import Console
from rich.prompt import Prompt
from sentinel.config import Settings

console = Console()

def run_setup_wizard() -> Settings:
    console.print("\n[bold green]🥝 Kiwi Setup Wizard[/bold green]")
    console.print("Please provide the credentials to initialize Kiwi context.\n")

    base_url = Prompt.ask("Enter Cognee Base URL").strip()
    api_key = Prompt.ask("Enter Cognee API Key").strip()
    tenant_id = Prompt.ask("Enter Cognee Tenant ID").strip()
    dataset = Prompt.ask("Enter Dataset Name", default="sentinel").strip()

    # Optional LLM Key Setup
    console.print("\n[bold cyan]LLM configuration (optional):[/bold cyan]")
    provider = Prompt.ask("Choose LLM Provider", choices=["anthropic", "openai", "gemini", "skip"], default="skip").strip()
    
    llm_env_line = ""
    if provider == "anthropic":
        key = Prompt.ask("Enter Anthropic API Key").strip()
        llm_env_line = f"ANTHROPIC_API_KEY={key}\n"
    elif provider == "openai":
        key = Prompt.ask("Enter OpenAI API Key").strip()
        llm_env_line = f"OPENAI_API_KEY={key}\n"
    elif provider == "gemini":
        key = Prompt.ask("Enter Gemini API Key").strip()
        llm_env_line = f"GEMINI_API_KEY={key}\n"

    # Write to .env file
    env_content = (
        f"COGNEE_BASE_URL={base_url}\n"
        f"COGNEE_API_KEY={api_key}\n"
        f"COGNEE_TENANT_ID={tenant_id}\n"
        f"SENTINEL_DATASET={dataset}\n"
    )
    if llm_env_line:
        env_content += llm_env_line

    with open(".env", "w") as f:
        f.write(env_content)

    console.print("\n[bold green]✓ Credentials saved to .env file successfully![/bold green]\n")

    # Update os.environ so that the current process loads them immediately
    os.environ["COGNEE_BASE_URL"] = base_url
    os.environ["COGNEE_API_KEY"] = api_key
    os.environ["COGNEE_TENANT_ID"] = tenant_id
    os.environ["SENTINEL_DATASET"] = dataset

    return Settings(
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        tenant_id=tenant_id,
        dataset=dataset
    )

from __future__ import annotations
import os
import typer
import httpx
from rich import print

app = typer.Typer()
API = os.getenv("AEGIS_API", "http://localhost:8080")

@app.command()
def bootstrap():
    token = os.getenv("AEGIS_ADMIN_TOKEN", "change-me-admin-token")
    print(httpx.post(f"{API}/admin/bootstrap", headers={"X-Admin-Token": token}, timeout=30).json())

@app.command()
def models():
    print(httpx.get(f"{API}/v1/models", timeout=30).json())

@app.command()
def ask(prompt: str, token: str = typer.Option(...), model: str | None = None):
    r = httpx.post(f"{API}/v1/ask", headers={"Authorization": f"Bearer {token}"}, json={"prompt": prompt, "model": model}, timeout=120)
    print(r.status_code)
    print(r.json())

@app.command()
def audit():
    print(httpx.get(f"{API}/v1/audit/last", timeout=30).json())

if __name__ == "__main__":
    app()

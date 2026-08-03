"""MCP smoke test against the wheel users install, not this checkout."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import venv
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, cwd=cwd, env=env, text=True, capture_output=True)


@pytest.mark.artifact
def test_installed_wheel_serves_mcp_over_stdio(tmp_path: Path) -> None:
    """Build, install, and exercise the console script without checkout imports."""
    dist_dir = tmp_path / "dist"
    _run(["uv", "build", "--out-dir", str(dist_dir)], cwd=PROJECT_ROOT)

    wheel = next(dist_dir.glob("*.whl"))
    assert list(dist_dir.glob("*.tar.gz"))

    environment = tmp_path / "environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    _run(["uv", "pip", "install", "--python", str(python), str(wheel)], cwd=tmp_path)

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "config.yaml").write_text("context:\n  semantic: never\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    environment_vars = os.environ.copy()
    environment_vars.pop("PYTHONPATH", None)
    environment_vars.pop("VIRTUAL_ENV", None)
    environment_vars["ARCANE_HOME"] = str(vault)
    environment_vars["HOME"] = str(tmp_path / "home")

    imported_from = _run(
        [str(python), "-c", "import arcane; print(arcane.__file__)"],
        cwd=run_dir,
        env=environment_vars,
    ).stdout.strip()
    assert str(environment) in imported_from
    assert str(PROJECT_ROOT) not in imported_from

    async def exercise_server() -> None:
        params = StdioServerParameters(
            command=str(scripts / ("arcane.exe" if os.name == "nt" else "arcane")),
            args=["mcp"],
            env=environment_vars,
            cwd=run_dir,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                version = _run(
                    [str(python), "-c", "from importlib.metadata import version; print(version('arcane-mcp'))"],
                    cwd=run_dir,
                    env=environment_vars,
                ).stdout.strip()
                assert initialized.serverInfo.name == "arcane"
                assert initialized.serverInfo.version == version

                tools = await session.list_tools()
                memory_save = next(tool for tool in tools.tools if tool.name == "memory_save")
                assert memory_save.inputSchema["required"] == ["title", "what"]
                assert (await session.list_resources()).resources == []
                templates = await session.list_resource_templates()
                assert templates.resourceTemplates[0].uriTemplate == "arcane://context/{project}"
                prompts = await session.list_prompts()
                assert "recall" in {prompt.name for prompt in prompts.prompts}
                assert initialized.protocolVersion

                saved = await session.call_tool(
                    "memory_save",
                    {"title": "Installed artifact", "what": "MCP stdio smoke test", "project": "smoke"},
                )
                assert saved.isError is False
                search = await session.call_tool("memory_search", {"query": "Installed artifact", "project": "smoke"})
                assert search.isError is False
                assert json.loads(search.content[0].text)[0]["title"] == "Installed artifact"

    asyncio.run(exercise_server())

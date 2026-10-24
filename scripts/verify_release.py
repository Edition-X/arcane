#!/usr/bin/env python3
"""Exercise a built Arcane the way someone who has never cloned this repo would.

Nothing here imports ``arcane``. The package under test is reached only through
an installed console script or a container image, over the MCP stdio transport,
so a pass means the artifact works — not that the checkout does.

    verify_release.py --target pypi   --version 0.2.0 [--python 3.13] [--installer pip]
    verify_release.py --target wheel  --wheel dist/arcane_mcp-0.2.0-py3-none-any.whl
    verify_release.py --target docker --image ghcr.io/edition-x/arcane:0.2.0

Run it with the MCP client available, for example::

    uv run --with "mcp>=2.3,<3" python scripts/verify_release.py --target pypi --version 0.2.0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# The core profile's tool set. A release that cannot offer these is not usable
# as a memory server, whatever else it does.
REQUIRED_TOOLS = frozenset(
    {
        "memory_save",
        "memory_search",
        "memory_context",
        "memory_details",
        "memory_update",
        "journey_start",
        "journey_update",
        "journey_complete",
        "journey_abandon",
        "journey_list",
        "journey_show",
        "artifact_search",
        "insights",
    }
)


class VerificationError(RuntimeError):
    """A check failed against the artifact."""


def _log(message: str) -> None:
    print(f"  {message}", flush=True)


def _step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    printable = " ".join(command)
    _log(f"$ {printable}")
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)  # type: ignore[call-overload]
    if result.returncode != 0:
        raise VerificationError(
            f"{printable} exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _normalise(version: str) -> str:
    """PEP 440 spells a prerelease 0.2.0b1 where a git tag spells it 0.2.0-beta.1."""
    return version.replace("-beta.", "b").replace("-rc.", "rc").removeprefix("v")


def install_from_pypi(workdir: Path, version: str, python: str, installer: str) -> Path:
    """Install the published distribution exactly as a user would, and return its bin dir."""
    requirement = f"arcane-mcp=={_normalise(version)}"
    if installer == "uv":
        _run(
            ["uv", "tool", "install", "--force", "--python", python, requirement],
            env={**os.environ, "UV_TOOL_BIN_DIR": str(workdir / "bin"), "UV_TOOL_DIR": str(workdir / "tools")},
        )
        return workdir / "bin"

    # uv venv leaves pip out unless asked; a user's venv would have it.
    environment = workdir / "venv"
    _run(["uv", "venv", "--seed", "--python", python, str(environment)])
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    _run([str(_executable(scripts, "python")), "-m", "pip", "install", "--quiet", requirement])
    return scripts


def install_from_wheel(workdir: Path, wheel: Path, python: str) -> Path:
    environment = workdir / "venv"
    _run(["uv", "venv", "--python", python, str(environment)])
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    _run(["uv", "pip", "install", "--python", str(_executable(scripts, "python")), str(wheel)])
    return scripts


def _executable(bin_dir: Path, name: str) -> Path:
    path = bin_dir / (f"{name}.exe" if os.name == "nt" else name)
    if not path.exists():
        raise VerificationError(f"{name} console script missing from {bin_dir}")
    return path


async def exercise(params: StdioServerParameters, expected_version: str | None) -> None:
    """Drive the server over stdio and assert it is actually usable."""
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()

            if initialized.server_info.name != "arcane":
                raise VerificationError(f"server identifies as {initialized.server_info.name!r}, not 'arcane'")
            if not initialized.protocol_version:
                raise VerificationError("server negotiated no protocol version")
            _log(
                f"initialized: {initialized.server_info.name} {initialized.server_info.version} "
                f"(protocol {initialized.protocol_version})"
            )

            if expected_version and initialized.server_info.version != _normalise(expected_version):
                raise VerificationError(
                    f"server reports version {initialized.server_info.version!r}, "
                    f"expected {_normalise(expected_version)!r}"
                )

            tools = {tool.name for tool in (await session.list_tools()).tools}
            missing = REQUIRED_TOOLS - tools
            if missing:
                raise VerificationError(f"missing tools: {', '.join(sorted(missing))}")
            _log(f"tools: {len(tools)} exposed, all {len(REQUIRED_TOOLS)} core tools present")

            templates = await session.list_resource_templates()
            if not any(t.uri_template == "arcane://context/{project}" for t in templates.resource_templates):
                raise VerificationError("context resource template missing")

            prompts = {prompt.name for prompt in (await session.list_prompts()).prompts}
            if "recall" not in prompts:
                raise VerificationError(f"recall prompt missing; got {sorted(prompts)}")
            _log("resource templates and prompts present")

            title = "Release verification"
            saved = await session.call_tool(
                "memory_save",
                {"title": title, "what": "Round trip through the published artifact.", "project": "release-check"},
            )
            if saved.is_error:
                raise VerificationError(f"memory_save failed: {saved.content}")

            found = await session.call_tool("memory_search", {"query": title, "project": "release-check"})
            if found.is_error:
                raise VerificationError(f"memory_search failed: {found.content}")
            results = json.loads(found.content[0].text)
            if not results or results[0]["title"] != title:
                raise VerificationError(f"saved memory did not come back from search: {results}")
            _log("memory_save → memory_search round trip returned the saved memory")


def verify_installed(bin_dir: Path, home: Path, expected_version: str | None) -> None:
    arcane = _executable(bin_dir, "arcane")

    # A clean environment: no PYTHONPATH, no inherited virtualenv, no real
    # ~/.arcane. Anything the artifact needs it has to bring itself.
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}}
    env["ARCANE_HOME"] = str(home)
    env["HOME"] = str(home.parent / "fakehome")
    env["USERPROFILE"] = env["HOME"]
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)

    _step("CLI")
    reported = _run([str(arcane), "--version"], env=env).stdout.strip()
    _log(reported)
    if expected_version and _normalise(expected_version) not in reported:
        raise VerificationError(f"`arcane --version` said {reported!r}, expected {_normalise(expected_version)!r}")

    _run([str(arcane), "init"], env=env)
    if not any(home.iterdir()):
        raise VerificationError(f"`arcane init` left {home} empty")
    _log(f"arcane init populated {home}")

    _step("MCP over stdio")
    params = StdioServerParameters(command=str(arcane), args=["mcp"], env=env, cwd=str(home.parent))
    asyncio.run(exercise(params, expected_version))


def verify_docker(image: str, expected_version: str | None) -> None:
    if shutil.which("docker") is None:
        raise VerificationError("docker is not available")
    _step("MCP over stdio from the container image")
    params = StdioServerParameters(
        command="docker",
        args=["run", "--rm", "-i", "--network", "none", image],
        env=None,
    )
    asyncio.run(exercise(params, expected_version))


def main() -> int:
    # The Windows console defaults to a legacy code page that cannot print the
    # arrows and dashes in this script's output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", required=True, choices=["pypi", "wheel", "docker"])
    parser.add_argument("--version", help="Expected version, as a git tag or PEP 440 string.")
    parser.add_argument("--wheel", type=Path, help="Wheel to install, for --target wheel.")
    parser.add_argument("--image", help="Image reference, for --target docker.")
    parser.add_argument("--python", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    parser.add_argument("--installer", default="uv", choices=["uv", "pip"])
    args = parser.parse_args()

    try:
        if args.target == "docker":
            if not args.image:
                parser.error("--target docker needs --image")
            verify_docker(args.image, args.version)
        else:
            with tempfile.TemporaryDirectory(prefix="arcane-verify-") as raw:
                workdir = Path(raw)
                home = workdir / "arcane-home"
                home.mkdir()
                if args.target == "pypi":
                    if not args.version:
                        parser.error("--target pypi needs --version")
                    _step(f"Install arcane-mcp {_normalise(args.version)} from PyPI with {args.installer}")
                    bin_dir = install_from_pypi(workdir, args.version, args.python, args.installer)
                else:
                    if not args.wheel:
                        parser.error("--target wheel needs --wheel")
                    _step(f"Install {args.wheel.name} into a clean environment")
                    bin_dir = install_from_wheel(workdir, args.wheel, args.python)
                verify_installed(bin_dir, home, args.version)
    except VerificationError as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        return 1

    print("\nOK — the artifact installs, starts, and serves MCP.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""建立不包含本機設定、模型與執行資料的交付壓縮檔。"""
from pathlib import Path
import argparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (
    "app", "prompts", "skills", "runtime", "docs", "launcher",
    "AGENTS.md", ".env.example", "mcp.example.json", ".gitignore", "AI-Agent.exe", "README.md", "README.en.md",
    "workspace/README.md", "workspace/README.en.md",
    "requirements.txt", "requirements.lock.txt", "run.sh", "launcher.py", "啟動說明.txt",
)
SKIP = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".ollama", "ollama-models",
        "secrets", ".secrets", "credentials"}


def package(output, platform="all"):
    temporary = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in INCLUDE:
            if ((platform == "linux" and name == "runtime")
                    or (platform in {"linux", "source"} and name == "AI-Agent.exe")):
                continue
            source = ROOT / name
            if platform == "source" and name in {"runtime", "skills"}:
                files = [source / "README.md", source / "README.en.md"]
            else:
                files = sorted(source.rglob("*")) if source.is_dir() else [source]
            for path in files:
                relative = path.relative_to(ROOT)
                if path.is_symlink() or not path.is_file() or SKIP.intersection(relative.parts):
                    continue
                if (any(part.startswith(".env") and part != ".env.example" for part in relative.parts)
                        or path.name in {"launcher.ini", "mcp.json", "credentials.json"}
                        or path.name.startswith(("service-account", "id_rsa", "id_ed25519"))
                        or path.suffix.lower() in {".gguf", ".ggml", ".pem", ".key", ".p12", ".pfx"}):
                    continue
                archive_name = "AI-Agent/" + relative.as_posix()
                archive.write(path, archive_name)
                if relative.as_posix() == "run.sh":
                    entry = archive.getinfo(archive_name)
                    entry.create_system = 3
                    entry.external_attr = 0o100755 << 16
        archive.writestr("AI-Agent/workspace/", "")
    temporary.replace(output)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="建立乾淨交付檔")
    parser.add_argument("output", nargs="?", default=str(ROOT.parent / "AI-Agent-clean.zip"))
    parser.add_argument("--platform", choices=("all", "linux", "source"), default="all")
    args = parser.parse_args()
    package(Path(args.output).resolve(), args.platform)

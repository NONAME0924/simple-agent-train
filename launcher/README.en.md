# Startup and packaging

[繁體中文](README.md)

Root launcher.py starts the service; this directory contains setup and packaging code.

| File/directory | Purpose |
| --- | --- |
| `Launcher.cs` | C# source for the Windows EXE forwarding to the Python launcher. |
| `bootstrap.py` | Linux/macOS virtual-environment and dependency preparation. |
| `package.py` | Packages explicit files; source omits Skill/runtime contents, while linux/all are execution distributions. |

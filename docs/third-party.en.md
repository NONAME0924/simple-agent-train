# Third-party and Skill sources

[繁體中文](third-party.md) · [Home](../README.en.md)

| Item | Source | Use in this project |
| --- | --- | --- |
| SDD Skill | The author's [NONAME0924/spec-driven-development](https://github.com/NONAME0924/spec-driven-development) | Local `skills/sdd/SKILL.md` is a compact adaptation using save_sdd for spec, plan, and tasks; it does not implement the complete upstream workflow. |
| PPTX Skill | [Anthropic Skills / pptx](https://github.com/anthropics/skills/tree/main/skills/pptx) | Local instructions, scripts, and OOXML schemas; its original LICENSE.txt is retained. Skill contents are not committed. |
| Blender Skill | Written for this project | Instructions for this Agent's scene inspection, editing, visual review, and saving; not an upstream official Skill copy. |
| Blender MCP tools | [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | Python package and Blender addon; versions are recorded in requirements.lock.txt. |
| MCP Python SDK | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Generic MCP client protocol support. |

The SDD upstream repository identifies its license as MIT; see its [LICENSE](https://github.com/NONAME0924/spec-driven-development/blob/main/LICENSE). The local adaptation is not a complete upstream copy and has no recorded originating commit.

The local PPTX LICENSE.txt and [upstream license](https://github.com/anthropics/skills/blob/main/skills/pptx/LICENSE.txt) contain restrictions on copying, modification, and distribution. Attribution alone does not grant redistribution rights or make the material MIT-licensed. Git ignores Skill contents. Separately distributed archives containing Skills remain subject to the applicable terms.

Other Python dependency versions are listed in `requirements.lock.txt` and retain their own licenses. The frontend references Marked and Mermaid in `app/web/static/index.html`. The Windows runtime contains Python and third-party packages, not original application code.

This page records sources; it does not relicense third-party materials. No root license has been added for this application's own code.

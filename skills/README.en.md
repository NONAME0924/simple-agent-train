# Local Skills and sources

[繁體中文](README.md)

Git keeps only these two READMEs and the bundled `mcp` Skill; other Skill contents are ignored.

## Sources

| Skill | Source and differences |
| --- | --- |
| `sdd` | The author's [spec-driven-development](https://github.com/NONAME0924/spec-driven-development); locally adapted to three files. |
| `mcp` | Ships with this project and is committed; connects MCP servers as a Skill. See [skills/mcp](mcp/README.en.md). |
| `pptx` | [Anthropic Skills](https://github.com/anthropics/skills/tree/main/skills/pptx); its restrictive LICENSE.txt is retained. |

Loading reads SKILL.md or a requested resource; directory READMEs are not system prompts. References are read on demand and dependencies are not automatically installed. The source repository omits Skill contents; prepare locally licensed Skills as needed. Copying the full upstream SDD does not reproduce the compact local adaptation. See [attribution and license scope](../docs/third-party.en.md).

The Agent initially reads 60 opening lines and a heading index, acts when sufficiently informed, and selects more ranges only as needed. Each read covers up to 200 lines; reading every page in order is not required.

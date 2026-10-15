# Self-Provisioning Missing Powers

## Scope

This reference applies to a **Bibit expert running with its own identity** (`agents/<name>/agent.yaml`).
Bibit is the only Agent where such an identity file exists, so it is the only Agent that can state its own
Power dependencies and the only target this flow installs for. For `codex`, `claude-code` and
`hermes-agent`, keep using the user-driven flow in the [CLI reference](cli.md).

## Detect the gap

| Signal | Meaning |
| --- | --- |
| The task needs a Skill, MCP or tool that is absent from the capability list the Runtime gave this session | Candidate gap |
| A `skills` or `mcps` entry in your own `agent.yaml` has no match in that list | Candidate gap, highest confidence |
| A Skill or tool call returns unknown / unavailable, or an MCP server is not connected | Candidate gap |
| You merely want more capabilities than the task requires | Not a gap; do not install |

Read your own identity declaration from the `agent.yaml` of the expert you are running as, under the Bibit data
root (default `~/.bianbu-agent/agents/<name>/agent.yaml`, overridden by `BIANBU_AGENT_HOME`; the runtime may point
`data_dir` elsewhere). If the session does not make your own identity or the data root identifiable,
ask the user instead of guessing: do not install on a guess. Reading the installed `agents/` directory is fine;
editing it is not.

Installed Skills and Plugins sit in the same root (`<root>/skills/<name>`, `<root>/plugins/<name>`), so a
declared dependency that is missing there is missing for this session too. Bibit's MCP server definitions live
under the runtime `data_dir` instead (`<data_dir>/mcps/mcp.<name>/mcp.json`), which is not necessarily the same
directory. The full table of roots and landing paths is in the [CLI reference](cli.md#agent-roots-and-where-powers-land).

Confirm the absence with the CLI before treating anything as missing:

```bash
apm list --installed --agent bibit --json
apm list <name> --installed --agent bibit --type <type> --json
```

If an equivalent capability is already installed, do not install it again: report the installed version and stop.
Close only the specific gap; do not align, refresh or bulk-update everything you can see.

## Classify before installing

| Requirement source | Action |
| --- | --- |
| Declared in your own `agent.yaml` (`skills` / `mcps`) | Resolve one Power, then install directly |
| Explicitly requested by the user in this session | Resolve one Power, then install directly |
| Inferred by you from the task | State the gap and ask the user first |
| Plugin-type Power, or the capability only exists inside a Plugin | Ask the user; prefer a standalone Skill when one exists |
| Several plausible matches, or a similar but unconfirmed name | Ask the user |

## Resolve one Power

```bash
apm search <keyword> [--type skill|mcp|plugin] --json
apm show <name>[=v1.2.0] --type <type> --json
```

Start from the exact name in the declaration or the error, not from a synonym. Use `show` to confirm the
description and tags actually deliver the capability; a similar name is not proof. When `search` returns
several candidates, or the only candidate is a Plugin, stop and ask. Do not self-provision `--type agent`:
installing an Agent-type Power replaces an identity rather than filling a gap.

## Install and verify

```bash
apm install <name>[=vMAJOR.MINOR.PATCH] --type <type> --agent bibit
apm list <name> --installed --agent bibit --type <type> --json
```

- Install one Power at a time and check the exit code plus the `<agent>/<type>/<name>@<version> <outcome>` line.
- `unchanged` means the requested version was already installed; treat it as satisfied and do not retry.
- Verify against the installed record. An installation record does not prove that the capability runs.
- If an install was interrupted, run `apm fix`; do not delete manifests or unlock by hand.

## Guardrails

| Never | Instead |
| --- | --- |
| Use `--agent all`, or install for another Agent's runtime | Fix the target to `--agent bibit` |
| Install a capability you inferred without asking | Present the gap and the candidate, then wait |
| Uninstall, downgrade or replace Powers beyond the gap | Change only what is missing |
| Use `sudo apm`, switch provider/address, or disable TLS validation | Report the exact CLI failure |
| Submit anything to APC as part of self-provisioning | Submissions stay user-authorized |

When the `apm` CLI itself is missing, report it and continue with local work; never invent a download URL or run
an unknown installer script. For network, lock or authentication failures, report the specific CLI error. A lock
conflict may be retried once; identity conflicts and interrupted transactions are handled per the
[CLI reference](cli.md).

## Report

State what was missing, the evidence for the gap, the resolved name/type/version, the target Agent (`bibit`), the
CLI results, the verified installed record, and anything that still needs a user decision.

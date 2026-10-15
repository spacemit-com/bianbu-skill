#!/usr/bin/env python3
"""Portable public entrypoint for the K3 media pipeline Agent Skill.

Protocol: CLI arguments, --request-json, or one JSON request on stdin.
Output: one JSON result on stdout; progress is written to stderr.
"""

from k3_media_pipeline import RequestError, SCENARIOS, build_request, schema
from k3_media_pipeline.capabilities import probe_capabilities as probe
from k3_media_pipeline.cli import main
from k3_media_pipeline.executor import execute, run_process
from k3_media_pipeline.scenarios import plan

__all__ = [
    "RequestError",
    "SCENARIOS",
    "build_request",
    "execute",
    "plan",
    "probe",
    "run_process",
    "schema",
]


if __name__ == "__main__":
    raise SystemExit(main())

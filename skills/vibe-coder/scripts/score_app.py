#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

CHECKS = {
    "board": (20, r"chess-board|data-row"), "status": (10, r"game-status"), "restart": (10, r"restart-button|重新开始"),
    "undo": (10, r"undo-button|悔棋"), "pieces": (15, r"[车馬马相象仕士帥帅將将炮兵卒]"),
    "turn_logic": (10, r"currentPlayer|currentTurn|红方|黑方"), "move_validation": (15, r"isValidMove|legalMoves|isLegalMove"),
    "ai": (10, r"minimax|alphaBeta|computerMove|aiMove"),
}
def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("app_dir", type=Path); p.add_argument("--json", dest="json_path", type=Path); a = p.parse_args(); root = a.app_dir.resolve()
    content = "\n".join(x.read_text(encoding="utf-8", errors="replace") for x in root.rglob("*") if x.is_file() and x.suffix.lower() in {".html", ".js", ".css"})
    total, details = 0, {}
    for name, (points, pattern) in CHECKS.items():
        passed = bool(re.search(pattern, content, re.I)); earned = points if passed else 0; total += earned; details[name] = {"passed": passed, "earned": earned, "possible": points}
    result = {"score": total, "possible": 100, "checks": details, "note": "结构评分不等同于完整棋规正确性"}; output = json.dumps(result, ensure_ascii=False, indent=2)
    if a.json_path: a.json_path.write_text(output + "\n", encoding="utf-8")
    print(output); return 0
if __name__ == "__main__": sys.exit(main())

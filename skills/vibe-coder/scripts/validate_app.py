#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = ("index.html", "styles.css", "app.js", "README.md")
DANGEROUS = {
    "eval": re.compile(r"\beval\s*\("),
    "new_function": re.compile(r"\bnew\s+Function\s*\("),
    "dynamic_script": re.compile(r"createElement\s*\(\s*['\"]script['\"]"),
    "shell_command": re.compile(r"\b(exec|spawn|system)\s*\("),
}


class ResourceParser(HTMLParser):
    """Collect remote resources while allowing user-activated citation links."""

    def __init__(self):
        super().__init__()
        self.remote_assets = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name not in {"src", "href"} or not value:
                continue
            if name == "href" and tag in {"a", "area"}:
                continue
            value = value.strip()
            if urlparse(value).scheme in {"http", "https"} or value.startswith("//"):
                self.remote_assets.append(value)

def validate(root: Path) -> dict:
    errors, warnings = [], []
    root = root.resolve()
    if not root.is_dir():
        return {"ok": False, "root": str(root), "errors": [{"code": "not_directory", "message": "应用目录不存在"}], "warnings": []}
    for name in REQUIRED:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            errors.append({"code": "required_file", "file": name, "message": "缺少或为空"})
    texts = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            errors.append({"code": "symlink", "file": str(path.relative_to(root)), "message": "不允许符号链接"})
        elif path.is_file() and path.suffix.lower() in {".html", ".css", ".js", ".json", ".md"}:
            try: texts[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError: errors.append({"code": "utf8", "file": str(path.relative_to(root)), "message": "文件不是UTF-8"})
    html, js = texts.get("index.html", ""), texts.get("app.js", "")
    if html:
        required_html = {
            "charset": r"<meta[^>]+charset\s*=", "viewport": r"<meta[^>]+name\s*=\s*['\"]viewport['\"]",
            "title": r"<title>\s*[^<]+", "heading": r"<h1\b",
            "css_link": r"href\s*=\s*['\"](?:\./)?styles\.css['\"]", "js_link": r"src\s*=\s*['\"](?:\./)?app\.js['\"]",
        }
        for code, pattern in required_html.items():
            if not re.search(pattern, html, re.I): errors.append({"code": code, "file": "index.html", "message": "缺少必需页面结构"})
        resources = ResourceParser()
        resources.feed(html)
        for value in resources.remote_assets:
            errors.append({"code": "remote_asset", "file": "index.html", "value": value, "message": "不允许外部资源"})
    combined = "\n".join(texts.values())
    for code, pattern in DANGEROUS.items():
        if pattern.search(combined): errors.append({"code": code, "message": "检测到危险动态执行模式"})
    if re.search(r"\bfetch\s*\(|XMLHttpRequest|WebSocket\s*\(", combined): warnings.append({"code": "network_api", "message": "检测到网络API，请确认离线可用"})
    if js and len(js.splitlines()) < 20: warnings.append({"code": "small_js", "message": "交互脚本很短，可能未实现完整功能"})
    return {"ok": not errors, "root": str(root), "files": sorted(texts), "errors": errors, "warnings": warnings}

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("app_dir", type=Path); parser.add_argument("--json", dest="json_path", type=Path); args = parser.parse_args()
    result = validate(args.app_dir); output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_path: args.json_path.write_text(output + "\n", encoding="utf-8")
    print(output); return 0 if result["ok"] else 1

if __name__ == "__main__": sys.exit(main())

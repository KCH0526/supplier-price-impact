"""Build the local release bundle (ZIP) from an explicit allow-list. Standard library only.

    python tools/build_release.py --version 1.0.0          # -> dist/SupplierPriceImpact-1.0.0.zip

- Only files matched by ALLOW are packed; the repository is never zipped as a whole.
- Any packed path matching FORBIDDEN stops the build (databases, backups, secrets, caches).
- Markdown links to files that are not in the bundle become plain text, so the bundle has
  no broken links and no reference to internal documents.
- Reproducible: sorted entries, fixed timestamps and permissions, CRLF for .bat, LF and
  mode 755 for .command. Same sources + same version -> byte-identical ZIP.
- MANIFEST.sha256 (inside the ZIP) lists the SHA-256 of every other file; verify() checks it.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "SupplierPriceImpact"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

ALLOW = [
    # program and settings
    "app.py", "pages/*.py", "core/*.py", ".streamlit/config.toml",
    "requirements.txt", "requirements-lock.txt",
    "start_windows.bat", "start_macos.command", "tools/check_env.py",
    "Dockerfile", "docker-compose.yml", ".dockerignore",
    # user documents and the images they show
    "README.md", "docs/USER_GUIDE.md", "docs/FIRST_TIME_GUIDE.md", "docs/FIRST_USE_CHECKLIST.md",
    "docs/LOCAL_DEPLOYMENT.md", "docs/DEPLOYMENT_CHECKLIST.md", "docs/LIMITATIONS.md",
    "docs/CUSTOMER_ONBOARDING.md", "docs/FINAL_DELIVERY_REPORT.md", "docs/images/*.png",
    # synthetic examples
    "samples/*.xlsx", "samples/*.json", "samples/*/*.xlsx", "samples/*/*.json", "demo/*.xlsx",
]
FORBIDDEN = ["*.db", "*.sqlite", "*.sqlite3", "*.db-journal", "*.bak", "*backup*", "*before_restore*",
             "*.pem", "*.key", "*.p12", "*.pfx", "*.env", ".env*", "*secrets*", "*__pycache__*", "*.pyc",
             ".git/*", ".venv/*", ".pytest_cache/*", "web/*", "web_src/*", "docs/launch/*", "tests/*"]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".yml", ".bat", ".command", ""}
INTERNAL_NOTE = "（內部文件，未包含在交付包）"


def selected_files(root: Path = ROOT) -> list[str]:
    files = set()
    for pattern in ALLOW:
        for p in root.glob(pattern):
            if p.is_file():
                files.add(p.relative_to(root).as_posix())
    for rel in files:
        for bad in FORBIDDEN:
            if fnmatch.fnmatch(rel, bad) or fnmatch.fnmatch(PurePosixPath(rel).name, bad):
                raise SystemExit(f"禁止打包的檔案：{rel}（符合 {bad}）")
    return sorted(files)


def _rewrite_links(rel: str, text: str, included: set[str]) -> str:
    base = PurePosixPath(rel).parent

    def fix(m):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        path = target.split("#")[0].rstrip("/")
        parts = []
        for part in (base / path).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        resolved = "/".join(parts)
        if resolved in included or any(f.startswith(resolved + "/") for f in included):
            return m.group(0)
        return f"{label}{INTERNAL_NOTE}"
    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", fix, text)


def file_bytes(rel: str, included: set[str], root: Path = ROOT) -> bytes:
    data = (root / rel).read_bytes()
    suffix = PurePosixPath(rel).suffix
    if suffix in TEXT_SUFFIXES:
        text = data.decode("utf-8").replace("\r\n", "\n")
        if suffix == ".md":
            text = _rewrite_links(rel, text, included)
        if suffix == ".bat":
            text = text.replace("\n", "\r\n")
        data = text.encode("utf-8")
    return data


def _info(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.create_system = 3
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def build(version: str, out_dir: Path = ROOT / "dist", root: Path = ROOT) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z.\-]+", version):
        raise SystemExit("版本只能包含英數字、點與連字號")
    files = selected_files(root)
    included = set(files)
    prefix = f"{PRODUCT}-{version}/"
    contents = {rel: file_bytes(rel, included, root) for rel in files}
    manifest = "".join(f"{hashlib.sha256(contents[rel]).hexdigest()}  {rel}\n" for rel in files)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{PRODUCT}-{version}.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            mode = 0o755 if rel.endswith(".command") else 0o644
            zf.writestr(_info(prefix + rel, mode), contents[rel], compresslevel=9)
        zf.writestr(_info(prefix + "MANIFEST.sha256", 0o644), manifest.encode("utf-8"), compresslevel=9)
    target.write_bytes(buf.getvalue())
    return target


def verify(extracted: Path) -> list[str]:
    """Problems found when checking an extracted bundle against its MANIFEST.sha256 (empty = OK)."""
    problems = []
    listed = set()
    for line in (extracted / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        listed.add(rel)
        p = extracted / rel
        if not p.is_file():
            problems.append(f"缺少：{rel}")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            problems.append(f"內容不符：{rel}")
    extra = {p.relative_to(extracted).as_posix() for p in extracted.rglob("*") if p.is_file()} - listed - {"MANIFEST.sha256"}
    problems += [f"清單外的檔案：{rel}" for rel in sorted(extra)]
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="產生企業單機版交付包（ZIP）")
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args(argv)
    target = build(args.version, Path(args.out))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"已產生：{target}\nSHA-256：{digest}\n檔案數：{len(selected_files()) + 1}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

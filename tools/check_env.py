"""First-use environment check (standard library only). Changes nothing on the computer.

    python tools/check_env.py                       # Python, packages, port 8501
    python tools/check_env.py --data-dir D:\\報價資料  # also: can the case database be saved there?

Each line says OK or what to do next, in plain Traditional Chinese.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import re
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def check_python(version=None) -> tuple[bool, str]:
    v = tuple(version or sys.version_info[:3])
    text = ".".join(str(x) for x in v)
    if v[:2] == (3, 11):
        return True, f"Python {text}"
    return False, (f"目前是 Python {text}，本系統需要 Python 3.11。請安裝 Python 3.11，"
                   "並用它重新建立 .venv（見 docs/LOCAL_DEPLOYMENT.md 第 2、3 節）。")


def check_packages(lock_path=ROOT / "requirements-lock.txt") -> tuple[bool, str]:
    problems = []
    for line in Path(lock_path).read_text(encoding="utf-8").splitlines():
        spec, _, marker = line.split("#", 1)[0].strip().partition(";")
        if "==" not in spec:
            continue
        if marker.strip():
            m = re.search(r'sys_platform\s*==\s*"(\w+)"', marker)
            if m and sys.platform != m.group(1):
                continue
        name, version = (x.strip() for x in spec.split("==", 1))
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            problems.append(f"{name}（未安裝）")
            continue
        if installed != version:
            problems.append(f"{name}（已安裝 {installed}，需要 {version}）")
    if problems:
        return False, ("套件與驗收版本不同：" + "、".join(problems) +
                       "。請先啟用本系統的 .venv，再執行 python -m pip install -r requirements-lock.txt")
    return True, "套件版本與 requirements-lock.txt 相同"


def check_port(port: int = 8501) -> tuple[bool, str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False, (f"連接埠 {port} 已被其他程式使用（可能是另一個已開啟的本系統視窗）。"
                           f"系統仍會啟動，但會改用 {port + 1} 或下一個可用的連接埠；"
                           "請以終端機顯示的網址（Local URL）為準，不要直接開舊的書籤。")
    return True, f"連接埠 {port} 可用"


def check_folder(folder) -> tuple[bool, str]:
    text = str(folder)
    if text.startswith(("\\\\", "//")):
        return False, "資料夾在網路共享磁碟上；資料庫只能放在本機磁碟（見 docs/LOCAL_DEPLOYMENT.md 第 5 節）。"
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".write_test_", delete=True) as fh:
            fh.write(b"ok")
    except OSError as exc:
        return False, (f"資料夾 {folder} 無法寫入（{exc.__class__.__name__}）。請改用自己帳號可寫入的本機資料夾，"
                       "例如 文件\\報價資料；不需要也不應該使用系統管理員權限。")
    return True, f"資料夾可寫入：{folder}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本機環境檢查（不會修改任何設定）")
    parser.add_argument("--data-dir", help="打算存放案件資料庫與備份的資料夾")
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    checks = [("Python", check_python()), ("套件", check_packages())]
    if args.port:
        checks.append(("連接埠", check_port(args.port)))
    if args.data_dir:
        checks.append(("資料夾", check_folder(args.data_dir)))
    else:
        checks.append(("資料夾", (True, "未指定 --data-dir，略過（使用案件工作台前建議檢查一次）")))
    for label, (ok, msg) in checks:
        print(f"[{'OK' if ok else '需處理'}] {label}：{msg}")
    blocking = [label for label, (ok, _) in checks if not ok and label != "連接埠"]
    print("環境檢查完成，可以啟動。" if not blocking else "請先處理上面標示「需處理」的項目。")
    return 1 if blocking else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

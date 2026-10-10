"""The one check that has to pass: ruff lint, ruff format, then pytest.

`make gate` (CI on GitHub and GitLab) and Windows both run this file, so the local check and the CI
check are the same. It uses the interpreter that runs it, so call it with the project's venv:

    .venv/bin/python scripts/gate.py        # macOS, Linux, CI
    .venv\\Scripts\\python scripts\\gate.py   # Windows
"""

import subprocess
import sys

STEPS = [
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["pytest"],
]


def main() -> int:
    for step in STEPS:
        print(f"$ {' '.join(step)}", flush=True)
        result = subprocess.run([sys.executable, "-m", *step], check=False)
        if result.returncode != 0:
            print(f"gate failed at: {' '.join(step)}", flush=True)
            return result.returncode
    print("gate passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

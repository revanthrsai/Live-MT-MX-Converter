"""Build a static GitHub Pages site around the checked-in Python engine."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    # The Pages UI is static, while its deterministic engine sources are copied
    # from the canonical app/ package on each build (no duplicate engine code).
    for name in ("index.html", "app.js", "styles.css", "bridge.py"):
        copy_file(ROOT / "docs" / name, DIST / name)

    for path in sorted((ROOT / "app").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        copy_file(path, DIST / "python" / relative)

    examples_dest = DIST / "examples"
    for path in (ROOT / "examples").iterdir():
        if path.is_file() and path.suffix.lower() in (".xml", ".txt"):
            copy_file(path, examples_dest / path.name)

    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    print(f"GitHub Pages site prepared at {DIST}")


if __name__ == "__main__":
    main()

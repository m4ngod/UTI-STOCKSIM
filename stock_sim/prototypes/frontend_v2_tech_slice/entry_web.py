"""Packaging entry for the throwaway embedded WebEngine candidate."""

from entry_common import PROTOTYPE_ROOT, run_packaged
from web_app import run_web


if __name__ == "__main__":
    raise SystemExit(
        run_packaged(
            "web",
            lambda **kwargs: run_web(
                **kwargs,
                html_path=PROTOTYPE_ROOT / "web" / "index.html",
            ),
        )
    )

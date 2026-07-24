"""Packaging entry for the throwaway Qt Quick/QML candidate."""

from entry_common import PROTOTYPE_ROOT, run_packaged
from qml_app import run_qml


if __name__ == "__main__":
    raise SystemExit(
        run_packaged(
            "qml",
            lambda **kwargs: run_qml(
                **kwargs,
                qml_path=PROTOTYPE_ROOT / "qml" / "Main.qml",
            ),
        )
    )

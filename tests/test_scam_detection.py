"""Tests for features/scam_detection.py (issue #513).

The host's dependency scanner reads a literal `import cv2` and installs the
desktop opencv-python package, which needs X11 (libxcb.so.1) that a headless
container does not have. It overwrites the headless build's files, so the
import fails and the whole cog stops loading. Deleting the package from the
host's panel does not stick — it is re-added on the next deploy.
"""

import ast
import pathlib

import pytest

FEATURES = pathlib.Path(__file__).resolve().parent.parent / "features"


def _python_files():
    return sorted(FEATURES.rglob("*.py"))


def test_no_module_imports_cv2_literally():
    """A literal `import cv2` re-triggers the host's wrong-package guess (#513).

    Tidying `cv2 = import_module("cv2")` back into `import cv2` looks harmless
    and breaks scam detection on the next deploy, with the failure invisible in
    the host's logs. Import cv2 by name instead.
    """
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] == "cv2" for alias in node.names):
                    offenders.append(f"{path.name}:{node.lineno} import cv2")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] == "cv2":
                    offenders.append(f"{path.name}:{node.lineno} from cv2 import ...")

    assert offenders == [], (
        "cv2 must be imported by name, not with a literal import statement: "
        + ", ".join(offenders)
    )


def test_scam_detection_still_exposes_cv2_at_module_level():
    """The 11 call sites use a module-level `cv2`, so the binding must survive."""
    pytest.importorskip("cv2")
    import features.scam_detection as scam_detection

    assert scam_detection.cv2.__name__ == "cv2"
    assert callable(scam_detection.cv2.ORB_create)

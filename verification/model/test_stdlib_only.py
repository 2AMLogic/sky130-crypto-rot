import ast
import sys
from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent
MODULES = [p for p in MODEL_DIR.glob("*.py") if not p.name.startswith("test_")]


def test_model_imports_stdlib_only():
    assert MODULES
    for path in MODULES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import within the model package
                    continue
                names = [node.module]
            else:
                continue
            for name in names:
                assert name.split(".")[0] in sys.stdlib_module_names, f"{path.name}: {name}"

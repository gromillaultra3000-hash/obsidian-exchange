"""Repository-level collection boundaries for the release test gate."""

from pathlib import Path
import ast


def pytest_ignore_collect(collection_path, config):
    parts = Path(str(collection_path)).parts
    # Night snapshots are audit/reference copies, not the release tree.
    if 'night-audit' in parts or 'night-dev' in parts:
        return True
    if collection_path.suffix == '.py' and collection_path.name.startswith('test_'):
        try:
            tree = ast.parse(collection_path.read_text())
            for node in tree.body:
                if isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Call, ast.Name)):
                    text = ast.unparse(node.exc)
                    if 'SystemExit' in text:
                        return True
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    if isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'exit':
                        return True
        except (OSError, SyntaxError):
            pass
    return False

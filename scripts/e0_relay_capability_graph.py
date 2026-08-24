#!/usr/bin/env python3
"""Build a names-only E0.3 Relay repository/database capability graph."""

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "relay-fastapi/main.py"
REPOSITORIES = ROOT / "relay/repositories"
SQL_OPERATIONS = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE")
OBJECT_PATTERNS = (
    re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)", re.I),
    re.compile(r"\bTABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)", re.I),
)


def _strings(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value
        elif isinstance(child, ast.JoinedStr):
            yield "".join(
                part.value for part in child.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )


def _method_sql(module, method):
    path = REPOSITORIES / f"{module}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    operations, objects, dynamic = set(), set(), False
    definitions = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    by_name = {}
    for node in definitions:
        by_name.setdefault(node.name, []).append(node)
    matches = len(by_name.get(method, []))
    pending, seen = [method], set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for node in by_name.get(current, []):
            for text in _strings(node):
                upper = text.upper()
                if any(re.search(rf"\b{operation}\b", upper) for operation in SQL_OPERATIONS):
                    operations.update(
                        operation for operation in SQL_OPERATIONS
                        if re.search(rf"\b{operation}\b", upper)
                    )
                    relation_text = re.sub(r"\bEXTRACT\s*\([^)]*\)", "", text,
                                           flags=re.I)
                    cte_aliases = {name.lower() for name in re.findall(
                        r"(?:\bWITH|,)\s*([a-z_][a-z0-9_]*)\s+AS\s*\(", relation_text, re.I
                    )}
                    for pattern in OBJECT_PATTERNS:
                        for match in pattern.findall(relation_text):
                            name = match.lower()
                            if name.startswith("public."):
                                name = name.split(".", 1)[1]
                            if name not in cte_aliases and name not in {"skip", "set", "of"}:
                                objects.add(name)
            dynamic = dynamic or any(isinstance(child, ast.JoinedStr) for child in ast.walk(node))
            for child in ast.walk(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id in {"self", "cls"}):
                    pending.append(child.func.attr)
    return {
        "definitions": matches,
        "operations": sorted(operations),
        "objects": sorted(objects),
        "dynamicSqlPresent": dynamic,
        "evidence": str(path.relative_to(ROOT)),
    }


class RelayVisitor(ast.NodeVisitor):
    def __init__(self):
        self.module_aliases = {}
        self.factory_aliases = {}
        self.bindings = {}
        self.calls = []
        self.direct_sql = []
        self.scope = ["module"]

    def visit_ImportFrom(self, node):
        if node.module == "repositories":
            for alias in node.names:
                self.module_aliases[alias.asname or alias.name] = alias.name
        elif node.module and node.module.startswith("repositories."):
            module = node.module.split(".", 1)[1]
            for alias in node.names:
                if alias.name == "from_environment":
                    self.factory_aliases[alias.asname or alias.name] = module
        self.generic_visit(node)

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                owner = call.func.value
                if call.func.attr == "from_environment" and isinstance(owner, ast.Name):
                    module = self.module_aliases.get(owner.id)
                    if module:
                        self.bindings[target] = module
            elif isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                module = self.factory_aliases.get(call.func.id)
                if module:
                    self.bindings[target] = module
        self.generic_visit(node)

    def _visit_scope(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _visit_scope
    visit_AsyncFunctionDef = _visit_scope

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in self.bindings:
                self.calls.append((self.scope[-1], node.lineno, func.value.id,
                                   self.bindings[func.value.id], func.attr))
            elif isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Name):
                module = self.factory_aliases.get(func.value.func.id)
                if module:
                    self.calls.append((self.scope[-1], node.lineno,
                                       f"{func.value.func.id}()", module, func.attr))
            if func.attr in {"execute", "executemany", "executescript", "cursor", "connect"}:
                self.direct_sql.append({"caller": self.scope[-1], "line": node.lineno,
                                        "attribute": func.attr})
        self.generic_visit(node)


def build():
    visitor = RelayVisitor()
    visitor.visit(ast.parse(ENTRYPOINT.read_text(encoding="utf-8"), filename=str(ENTRYPOINT)))
    edges = []
    unresolved = []
    for caller, line, binding, module, method in sorted(set(visitor.calls), key=lambda x: (x[1], x[0])):
        sql = _method_sql(module, method)
        edge = {"caller": caller, "line": line, "binding": binding,
                "repository": module, "method": method, **sql}
        edges.append(edge)
        if sql["definitions"] == 0 or not sql["operations"] or not sql["objects"]:
            unresolved.append(f"{module}.{method}")
    imports = sorted(set(visitor.module_aliases.values()) | set(visitor.factory_aliases.values()))
    called = sorted({edge["repository"] for edge in edges})
    result = {
        "schema": "obsidian.e0-3-relay-capability-graph.v1",
        "stage": "E0.3",
        "status": "NO_GO" if unresolved or visitor.direct_sql else "EXACT_STATIC_GRAPH",
        "productionAuthorization": False,
        "valuesIncluded": False,
        "entrypoint": str(ENTRYPOINT.relative_to(ROOT)),
        "entrypointSha256": hashlib.sha256(ENTRYPOINT.read_bytes()).hexdigest(),
        "repositoryImports": imports,
        "factoryBindings": [
            {"binding": binding, "repository": module}
            for binding, module in sorted(visitor.bindings.items())
        ],
        "calledRepositories": called,
        "uncalledImportedRepositories": sorted(set(imports) - set(called)),
        "edges": edges,
        "directSqlOrConnectionSites": sorted(visitor.direct_sql, key=lambda item: item["line"]),
        "unresolvedMethods": sorted(set(unresolved)),
        "limitations": [
            "static AST of the authoritative Relay entrypoint and repository source only",
            "operations and relation names are conservative unions across same-named implementations",
            "runtime branch reachability and dynamically imported non-repository helpers are not proven",
            "no environment values, credentials, database rows or runtime calls are observed",
        ],
    }
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))

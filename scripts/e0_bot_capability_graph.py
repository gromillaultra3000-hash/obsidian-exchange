#!/usr/bin/env python3
"""Build a names-only E0.3 exchange-bot repository/database capability graph."""
import ast
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("relay_graph",ROOT/"scripts/e0_relay_capability_graph.py")
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
base.ENTRYPOINT=ROOT/"bot/main_bot.py"

def build():
 result=base.build()
 # admin_config_store chooses only these two tables through _staff_table().
 staff_methods={"set_staff","deactivate_staff","active_staff_ids","staff_rows"}
 for edge in result["edges"]:
  # The shared fragment scanner can see a trailing LIMIT clause as an object
  # in dynamically assembled statements. LIMIT is never a relation.
  edge["objects"]=[item for item in edge["objects"] if item!="limit"]
  if edge["repository"]=="admin_config_store" and edge["method"] in staff_methods:
   edge["objects"]=["operators","workers"]
 result["unresolvedMethods"]=[item for item in result["unresolvedMethods"]
  if item not in {"admin_config_store.set_staff","admin_config_store.deactivate_staff"}]

 # Calls through the source-local lazy helper still resolve to bot_order_store.
 tree=ast.parse((ROOT/"bot/main_bot.py").read_text(),filename="bot/main_bot.py")
 scope=["module"]
 class LazyVisitor(ast.NodeVisitor):
  def visit_FunctionDef(self,node):scope.append(node.name);self.generic_visit(node);scope.pop()
  visit_AsyncFunctionDef=visit_FunctionDef
  def visit_Call(self,node):
   f=node.func
   if (isinstance(f,ast.Attribute) and isinstance(f.value,ast.Call)
       and isinstance(f.value.func,ast.Name) and f.value.func.id=="_get_bot_order_store"):
    sql=base._method_sql("bot_order_store",f.attr)
    result["edges"].append({"caller":scope[-1],"line":node.lineno,
     "binding":"_get_bot_order_store()","repository":"bot_order_store","method":f.attr,**sql})
   self.generic_visit(node)
 LazyVisitor().visit(tree)
 result["edges"].sort(key=lambda item:(item["line"],item["caller"],item["method"]))
 result["calledRepositories"]=sorted({edge["repository"] for edge in result["edges"]})
 result["uncalledImportedRepositories"]=sorted(set(result["repositoryImports"])-set(result["calledRepositories"]))
 result["status"]="NO_GO" if result["unresolvedMethods"] or result["directSqlOrConnectionSites"] else "EXACT_STATIC_GRAPH"
 result["schema"]="obsidian.e0-3-bot-capability-graph.v1"
 result["entrypointRole"]="exchange-bot.service"
 result["limitations"].append(
  "direct legacy SQL/connection sites are inventory findings and keep this graph NO_GO")
 return result

if __name__=="__main__":
 print(json.dumps(build(),ensure_ascii=False,sort_keys=True,separators=(",",":")))

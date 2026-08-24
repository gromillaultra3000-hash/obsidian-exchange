#!/usr/bin/env python3
"""Collapse bot caller edges into unique source-bound repository capabilities."""
import importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bot_graph',ROOT/'scripts/e0_bot_capability_graph.py')
graph=importlib.util.module_from_spec(spec);spec.loader.exec_module(graph)
WRITE={'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','TRUNCATE'}
def build():
 g=graph.build();grouped={}
 for edge in g['edges']:
  key=(edge['repository'],edge['method']);item=grouped.setdefault(key,{
   'id':'.'.join(key),'repository':key[0],'method':key[1],'operations':set(),
   'objects':set(),'callers':set(),'dynamicSqlPresent':False,'evidence':edge['evidence']})
  item['operations'].update(edge['operations']);item['objects'].update(edge['objects'])
  item['callers'].add(edge['caller']);item['dynamicSqlPresent']|=edge['dynamicSqlPresent']
 methods=[]
 for item in grouped.values():
  item['operations']=sorted(item['operations']);item['objects']=sorted(item['objects']);item['callers']=sorted(item['callers'])
  item['capabilityClass']='WRITER_OR_SCHEMA' if set(item['operations'])&WRITE else 'READ_ONLY';methods.append(item)
 methods.sort(key=lambda x:x['id'])
 return {'schema':'obsidian.e0-3-bot-method-capability-matrix.v1','stage':'E0.3',
  'status':'EXACT_METHOD_MATRIX_VERIFIED','productionAuthorization':False,
  'entrypointSha256':g['entrypointSha256'],'methods':methods,
  'remainingWork':['design exact execute-only bot ACL and prove it in disposable PostgreSQL']}
if __name__=='__main__':print(json.dumps(build(),ensure_ascii=False,sort_keys=True,separators=(',',':')))

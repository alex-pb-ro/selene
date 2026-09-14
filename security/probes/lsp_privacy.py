import os,json,time,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId,LanguageServerConfig
from solidlsp.settings import SolidLSPSettings
import sys
root=Path(sys.argv[1]).resolve()
node=sys.argv[2]
probe_dir=Path(__file__).resolve().parent
base=Path('/tmp/selene-lsp-privacy');base.mkdir(exist_ok=True)
log=base/'network.jsonl';log.write_text('')
os.environ['NODE_OPTIONS']='--require='+str(probe_dir/'node-network-guard.cjs')
os.environ['SELENE_NETWORK_AUDIT_LOG']=str(log)
os.environ.pop('INTELEPHENSE_LICENSE_KEY',None)
servers=[('php','intelephense/lib/intelephense.js','sample.php','<?php\nfunction local_example() { return 1; }\n'),('yaml','yaml-language-server/bin/yaml-language-server','sample.yaml','# yaml-language-server: $schema=https://schema-test.invalid/private-fixture-canary\nname: example\n'),('json','vscode-json-languageserver/bin/vscode-json-languageserver','sample.json','{"$schema":"https://schema-test.invalid/private-fixture-canary", "name":"example"}'),('solidity','@nomicfoundation/solidity-language-server/out/index.js','sample.sol','pragma solidity ^0.8.0; contract Example { function value() public pure returns (uint) { return 1; } }')]
def check(spec):
 name,script,filename,source=spec
 project=base/name;project.mkdir(exist_ok=True);(project/filename).write_text(source)
 ls=None
 try:
  settings=SolidLSPSettings(solidlsp_dir=str(base/'home'),project_data_path=str(project/'.selene'),ls_specific_settings={name:{'ls_base_cmd':[node,str(root/script)],'ls_args':['--stdio']}})
  ls=SolidLanguageServer.create(LanguageServerConfig(ls_id=LanguageServerId(name)),str(project),solidlsp_settings=settings,timeout=30)
  ls.start()
  symbols=ls.request_document_symbols(filename)
  time.sleep(22)
  assert symbols.root_symbols
  return {'language':name,'symbols':len(symbols.root_symbols),'passed':True}
 except Exception:
  return {'language':name,'passed':False,'error':traceback.format_exc()}
 finally:
  if ls:ls.stop()
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(check,servers))
report={'results':results,'node_network_attempts':[json.loads(s) for s in log.read_text().splitlines()],'observation':'Real adapters initialize, open a synthetic document and enumerate symbols; Node HTTP/TLS/TCP/DNS/fetch hooks reject and record attempts, including a 22-second post-request observation. Not an OS-wide packet capture.'}
Path('security/lsp-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
# Any recorded request is reported and returns a nonzero status, including known metadata requests.
raise SystemExit(not(all(r['passed'] for r in results) and not report['node_network_attempts']))

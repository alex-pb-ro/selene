import json,os,socket,sys,runpy
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from selene.config.selene_config import SeleneConfig
import selene.agno as integration
root=Path.cwd();home=Path('/tmp/selene-agno-check');home.mkdir(exist_ok=True)
integration.REPO_ROOT=str(home)
os.environ['AGNO_TELEMETRY']='true'
for key in ('GOOGLE_API_KEY','GEMINI_API_KEY','ANTHROPIC_API_KEY','OPENAI_API_KEY'):os.environ.pop(key,None)
sys.argv=['agno_agent.py'];attempts=[]
def reject(*args,**kwargs):
 attempts.append('socket operation');raise OSError('Network disabled for audit')
with patch.object(SeleneConfig,'from_config_file',return_value=SeleneConfig().with_headless_mode_overrides()),patch.object(socket,'getaddrinfo',reject),patch.object(socket.socket,'connect',reject),patch.object(socket.socket,'connect_ex',reject):
 module=runpy.run_path(str(root/'scripts/agno_agent.py'),run_name='selene_audit_agno')
 with TestClient(module['app']) as client:
  assert client.get('/docs').status_code==404
  assert client.get('/config').status_code==200
 assert module['selene_agent'].telemetry is False
 assert module['agent_os'].telemetry is False
 assert module['agent_os'].tracing is False
 assert os.environ['AGNO_TELEMETRY']=='false'
 assert attempts==[],attempts
 report={'agent_telemetry':False,'agentos_telemetry':False,'tracing':False,'overrides_parent_opt_in':True,'api_lifespan_started':True,'config_endpoint_ok':True,'external_docs_disabled':True,'network_attempts':attempts,'scope':'Agent/AgentOS initialization and ASGI lifespan, without model invocation.'}
 (root/'security/agno-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(report)

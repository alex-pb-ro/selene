from pathlib import Path
import subprocess, tomllib, os
config=tomllib.loads(Path('pyproject.toml').read_text())
markers=[m.split(':')[0] for m in config['tool']['pytest']['ini_options']['markers'] if not m.startswith(('slow:','snapshot:'))]
expr='not ('+' or '.join(markers)+')'
cmd=['uv','run','--no-sync','poe','test','-m',expr,'-q','--tb=short','--timeout=90','--maxfail=12']
with open('/tmp/selene-unit.log','w') as output:
    output.write('Command: '+repr(cmd)+'\n');output.flush()
    result=subprocess.run(cmd,stdout=output,stderr=subprocess.STDOUT,env={**os.environ,'SELENE_HOME':'/tmp/selene-audit-home','UV_CACHE_DIR':'/tmp/selene-uv-cache'})
print('Unit suite exit status:',result.returncode)
print('\n'.join(Path('/tmp/selene-unit.log').read_text().splitlines()[-55:]))
raise SystemExit(result.returncode)

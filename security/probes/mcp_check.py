import asyncio,json,os
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
 root=Path.cwd()
 params=StdioServerParameters(command=str(root/'.venv/bin/selene'),args=['start-mcp-server','--project',str(root/'test/resources/repos/python/test_repo'),'--enable-web-dashboard','false','--enable-gui-log-window','false','--log-level','ERROR'],env={**os.environ,'SELENE_HOME':'/tmp/selene-audit-home','UV_CACHE_DIR':'/tmp/selene-uv-cache'})
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as session:
   init=await session.initialize()
   listing=await session.list_tools()
   instructions=await session.call_tool('initial_instructions',{})
   assert not instructions.isError
   text='\n'.join(c.text for c in instructions.content if hasattr(c,'text'))
   assert 'Do not send code' in text
   result={'server':init.serverInfo.model_dump(),'tool_count':len(listing.tools),'initial_instructions_ok':True}
   Path('security/mcp-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
asyncio.run(main())

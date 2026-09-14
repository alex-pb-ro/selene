from pathlib import Path
from selene.agent import SeleneAgent
from selene.config.selene_config import SeleneConfig
from selene.analytics import ToolUsageStats
from selene.dashboard import SeleneDashboardAPI
from selene.util.logging import MemoryLogHandler
from werkzeug.serving import make_server
config=SeleneConfig().with_headless_mode_overrides()
agent=SeleneAgent(selene_config=config)
stats=ToolUsageStats()
for name in ('find_symbol','find_referencing_symbols','search_for_pattern'):
    stats.record_tool_usage(name,'Synthetic local input','Synthetic local result')
api=SeleneDashboardAPI(MemoryLogHandler(),["find_symbol", "find_referencing_symbols", "search_for_pattern"],agent,stats)
api._on_agent_config_changed()
server=make_server('127.0.0.1',0,api._app,threaded=True)
Path('/tmp/selene-dashboard-port').write_text(str(server.server_port))
try:server.serve_forever()
finally:agent.on_shutdown()

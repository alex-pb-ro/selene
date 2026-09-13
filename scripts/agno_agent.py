from agno.models.anthropic.claude import Claude
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from sensai.util import logging

from selene.agno import SeleneAgnoAgentProvider

# initialize logging
if __name__ == "__main__":
    logging.configure(level=logging.INFO)

# Define the model to use (see Agno documentation for supported models; these are just examples)
model = Claude(id="claude-sonnet-4-6")

# Create the Selene agent using the existing provider
selene_agent = SeleneAgnoAgentProvider.get_agent(model)

# Create AgentOS app with the Selene agent
agent_os = AgentOS(
    description="Selene coding assistant powered by AgentOS",
    id="selene-agentos",
    agents=[selene_agent],
    telemetry=False,
    cors_allowed_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    settings=AgnoAPISettings(docs_enabled=False),
    tracing=False,
)

app = agent_os.get_app()

if __name__ == "__main__":
    # Start the AgentOS server
    agent_os.serve(app="agno_agent:app", reload=False)

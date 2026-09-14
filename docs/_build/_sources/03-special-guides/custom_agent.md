# Custom Agents with Selene

As a reference implementation, we provide an integration with the [Agno](https://docs.agno.com/introduction/playground) agent framework.
Agno is a model-agnostic agent framework that allows you to turn Selene into an agent
(independent of the MCP technology) with a large number of underlying LLMs. While Agno has recently
added support for MCP servers out of the box, our Agno integration predates this and is a good illustration of how
easy it is to integrate Selene into an arbitrary agent framework.

Here's how it works:

1. Download the agent-ui code with npx
   ```shell
   npx create-agent-ui@latest
   ```
   or, alternatively, clone it manually:
   ```shell
   git clone https://github.com/agno-agi/agent-ui.git
   cd agent-ui
   pnpm install
   pnpm dev
   ```

2. Install selene with the optional requirements:
   ```shell
   uv sync --locked --extra agno
   ```

3. Copy `.env.example` to `.env` and fill in the API keys for the provider(s) you
   intend to use.

4. Start the agno agent app with
   ```shell
   uv run --no-sync python scripts/agno_agent.py
   ```
   By default, the script uses Claude as the model, but you can choose any model
   supported by Agno after installing a compatible provider SDK. The pinned standalone Google SDK is not compatible with Agno 2.6.6; that combination requires a separately reviewed SDK update.

5. In a new terminal, start the agno UI with
   ```shell
   cd agent-ui
   pnpm dev
   ```
   Connect the UI to the agent you started above and start chatting. You will have
   the same tools as in the MCP server version.


⚠️ IMPORTANT: In contrast to the MCP server approach, tool execution in the Agno UI does
not ask for the user's permission. The shell tool is particularly critical, as it can perform arbitrary code execution.
While we have never encountered any issues with
this in our testing with Claude, allowing this may not be entirely safe.
You may choose to disable certain tools for your setup in your Selene project's
configuration file (`.yml`).


## Other Agent Frameworks

It should be straightforward to incorporate Selene into any
agent framework (like [pydantic-ai](https://ai.pydantic.dev/), [langgraph](https://langchain-ai.github.io/langgraph/tutorials/introduction/) or others).
Typically, you need only to write an adapter for Selene's tools to the tool representation in the framework of your choice,
as was done by us for Agno with `SeleneAgnoToolkit` (see `/src/selene/agno.py`).

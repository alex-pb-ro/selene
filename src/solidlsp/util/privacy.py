import os
from collections.abc import Mapping


class SubprocessPrivacy:
    """Telemetry opt-outs for managed tools, installers, and their child processes.

    These settings are advisory switches honoured by particular tools, not a network sandbox.
    """

    _OPT_OUTS = {
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
        "DO_NOT_TRACK": "1",
        "SCARF_ANALYTICS": "false",
        "NEXT_TELEMETRY_DISABLED": "1",
        "OTEL_SDK_DISABLED": "true",
        "APPLICATION_INSIGHTS_NO_STATSBEAT": "1",
        "APPLICATION_INSIGHTS_NO_DIAGNOSTIC_CHANNEL": "1",
        "APPLICATIONINSIGHTS_CONFIGURATION_CONTENT": '{"disableAppInsights":true,"disableStatsbeat":true,"enableAutoCollectHeartbeat":false}',
        "AGNO_TELEMETRY": "false",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
    }

    @classmethod
    def environment(cls, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return a child environment with telemetry opt-outs taking precedence."""
        env = dict(os.environ if base is None else base)
        env.update(cls._OPT_OUTS)
        return env

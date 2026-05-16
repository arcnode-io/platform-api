"""CFN-native Secrets Manager secrets for commercial-variant vendor URLs.

Commercial variant: customer signs up at Tiger Cloud + Neo4j Aura, copies
the ready-to-use connection URLs from each vendor's console, pastes them
as CFN parameters at `aws cloudformation create-stack` time. The URLs go
straight into Secrets Manager via plain `AWS::SecretsManager::Secret`
resources — no Lambda, no API calls. EC2 UserData fetches by slot name at
boot.

Compare to defense, where the same logical slots (`timeseries`, `graph`)
are populated by the Aurora bootstrap Lambda (Aurora pg_partman) and CFN
Outputs of Neptune (no creds — IAM auth). Slot naming stays the same
across variants so consumers don't branch.
"""


def vendor_url_secrets() -> dict[str, dict]:
    """Two CFN-native secrets: timeseries (Tiger) + graph (Aura).

    Each `SecretString` is a `!Ref` to the matching CFN parameter — the
    customer-pasted URL never leaves the template body in plaintext. CFN
    materializes the secret value internally.
    """
    return {
        "TimeseriesUrlSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": "arcnode-ems-${AWS::StackName}/timeseries-url",
                },
                "Description": (
                    "Tiger Cloud connection URL (commercial variant). "
                    "postgres://user:pass@host/db?sslmode=require"
                ),
                "SecretString": {"Ref": "TimeseriesConnectionUrl"},
            },
        },
        "GraphUrlSecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {"Fn::Sub": "arcnode-ems-${AWS::StackName}/graph-url"},
                "Description": (
                    "Neo4j Aura connection URL (commercial variant). "
                    "neo4j+s://user:pass@host:port"
                ),
                "SecretString": {"Ref": "GraphConnectionUrl"},
            },
        },
    }


def commercial_url_parameters() -> dict[str, dict]:
    """Two NoEcho String CFN parameters the customer pastes at create-stack time.

    Both required, MinLength 1, no Default — CFN refuses to deploy without
    them. NoEcho keeps the URLs out of the Console UI and audit logs.
    """
    return {
        "TimeseriesConnectionUrl": {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": (
                "Tiger Cloud connection URL. Format: "
                "postgres://user:pass@host:port/db?sslmode=require"
            ),
        },
        "GraphConnectionUrl": {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": (
                "Neo4j Aura connection URL. Format: " "neo4j+s://user:pass@host:port"
            ),
        },
    }


def agent_api_key_secrets() -> dict[str, dict]:
    """CFN-native secrets for analyst-agent vendor APIs (both variants).

    OpenAI powers the LLM backbone of the agent; OpenWeatherMap powers
    the weather-forecast tool. Both variants need them — defense is
    sovereign on data, not on third-party AI vendors.
    """
    return {
        "OpenaiApiKeySecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": "arcnode-ems-${AWS::StackName}/openai-api-key",
                },
                "Description": "OpenAI API key consumed by analyst-agent (sk-...).",
                "SecretString": {"Ref": "OpenaiApiKey"},
            },
        },
        "OpenweathermapApiKeySecret": {
            "Type": "AWS::SecretsManager::Secret",
            "Properties": {
                "Name": {
                    "Fn::Sub": "arcnode-ems-${AWS::StackName}"
                    "/openweathermap-api-key",
                },
                "Description": (
                    "OpenWeatherMap API key consumed by analyst-agent's "
                    "weather-forecast tool."
                ),
                "SecretString": {"Ref": "OpenweathermapApiKey"},
            },
        },
    }


def agent_api_key_parameters() -> dict[str, dict]:
    """Two NoEcho String CFN params for the agent's vendor API keys."""
    return {
        "OpenaiApiKey": {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "OpenAI API key (starts with sk-).",
        },
        "OpenweathermapApiKey": {
            "Type": "String",
            "NoEcho": True,
            "MinLength": 1,
            "Description": "OpenWeatherMap API key (32-char hex).",
        },
    }

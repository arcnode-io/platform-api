"""AOSS (Amazon OpenSearch Serverless) CFN resources — defense variant only.

Holds the Lucene FTS index that Graphiti's NeptuneDriver hits for keyword
search on graph nodes. Collection type is SEARCH (vs VECTORSEARCH /
TIMESERIES); pricing is the same regardless of type, so the choice is
purely functional. Standby replicas default OFF — 2 OCU floor (~$350/mo
idle) instead of 4 OCU (~$700/mo). For an HMI-bursty search workload, the
HA upgrade isn't worth the doubling.

Endpoint hostname is published to SSM Parameter Store under
``/arcnode-ems/{STACK}/aoss-host`` for the same reason as Neptune — no
creds in the URL, sigv4 auth is signed by the EC2 instance role.
"""

from typing import Final

COLLECTION_NAME_PREFIX: Final[str] = "arcnode-ems"


def aoss_resources(standby_enabled: bool = False) -> dict[str, dict]:
    """CFN resources for an AOSS collection + 3 policies + SSM endpoint param.

    AWS requires three policies per collection (encryption, network,
    data-access) before the collection itself can be created. The
    collection name is keyed on `AWS::StackName` for per-stack uniqueness.
    """
    return {
        "AossEncryptionPolicy": {
            "Type": "AWS::OpenSearchServerless::SecurityPolicy",
            "Properties": {
                "Name": {
                    "Fn::Sub": f"{COLLECTION_NAME_PREFIX}-${{AWS::StackName}}-enc",
                },
                "Type": "encryption",
                "Policy": {
                    "Fn::Sub": (
                        '{"Rules":[{"ResourceType":"collection",'
                        '"Resource":["collection/'
                        f"{COLLECTION_NAME_PREFIX}"
                        '-${AWS::StackName}"]}],'
                        '"AWSOwnedKey":true}'
                    ),
                },
            },
        },
        "AossNetworkPolicy": {
            "Type": "AWS::OpenSearchServerless::SecurityPolicy",
            "Properties": {
                "Name": {
                    "Fn::Sub": f"{COLLECTION_NAME_PREFIX}-${{AWS::StackName}}-net",
                },
                "Type": "network",
                "Policy": {
                    "Fn::Sub": (
                        '[{"Rules":[{"ResourceType":"collection",'
                        '"Resource":["collection/'
                        f"{COLLECTION_NAME_PREFIX}"
                        '-${AWS::StackName}"]}],'
                        '"AllowFromPublic":true}]'
                    ),
                },
            },
        },
        "AossDataAccessPolicy": {
            "Type": "AWS::OpenSearchServerless::AccessPolicy",
            "Properties": {
                "Name": {
                    "Fn::Sub": f"{COLLECTION_NAME_PREFIX}-${{AWS::StackName}}-data",
                },
                "Type": "data",
                "Policy": {
                    "Fn::Sub": (
                        '[{"Rules":[{"ResourceType":"collection",'
                        '"Resource":["collection/'
                        f"{COLLECTION_NAME_PREFIX}"
                        '-${AWS::StackName}"],'
                        '"Permission":["aoss:*"]},'
                        '{"ResourceType":"index",'
                        '"Resource":["index/'
                        f"{COLLECTION_NAME_PREFIX}"
                        '-${AWS::StackName}/*"],'
                        '"Permission":["aoss:*"]}],'
                        '"Principal":["${EmsInstanceRole.Arn}"]}]'
                    ),
                },
            },
        },
        "AossCollection": {
            "Type": "AWS::OpenSearchServerless::Collection",
            "DependsOn": [
                "AossEncryptionPolicy",
                "AossNetworkPolicy",
                "AossDataAccessPolicy",
            ],
            "Properties": {
                "Name": {
                    "Fn::Sub": f"{COLLECTION_NAME_PREFIX}-${{AWS::StackName}}",
                },
                "Type": "SEARCH",
                "StandbyReplicas": "ENABLED" if standby_enabled else "DISABLED",
                "Description": "Graphiti FTS index (defense variant)",
            },
        },
        "AossHostParam": {
            "Type": "AWS::SSM::Parameter",
            "Properties": {
                "Name": {
                    "Fn::Sub": "/arcnode-ems/${AWS::StackName}/aoss-host",
                },
                "Type": "String",
                "Value": {
                    "Fn::GetAtt": ["AossCollection", "CollectionEndpoint"],
                },
                "Description": "AOSS collection endpoint (sigv4-auth)",
            },
        },
    }

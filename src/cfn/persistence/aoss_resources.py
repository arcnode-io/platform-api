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

Resource naming uses the 8-char ``short`` prefix of the deployment uuid
(not StackName) because AOSS caps policy and collection names at 32
characters; long stack names blow the limit.
"""

from typing import Final

NAME_PREFIX: Final[str] = "aoss"


def aoss_resources(*, short: str, standby_enabled: bool = False) -> dict[str, dict]:
    """CFN resources for an AOSS collection + 3 policies + SSM endpoint param.

    AWS requires three policies per collection (encryption, network,
    data-access) before the collection itself can be created. Names are
    keyed on the deployment-uuid prefix to stay under the 32-char AWS cap.
    """
    collection = f"{NAME_PREFIX}-{short}"
    return {
        "AossEncryptionPolicy": {
            "Type": "AWS::OpenSearchServerless::SecurityPolicy",
            "Properties": {
                "Name": f"{collection}-enc",
                "Type": "encryption",
                "Policy": (
                    '{"Rules":[{"ResourceType":"collection",'
                    f'"Resource":["collection/{collection}"]}}],'
                    '"AWSOwnedKey":true}'
                ),
            },
        },
        "AossNetworkPolicy": {
            "Type": "AWS::OpenSearchServerless::SecurityPolicy",
            "Properties": {
                "Name": f"{collection}-net",
                "Type": "network",
                "Policy": (
                    '[{"Rules":[{"ResourceType":"collection",'
                    f'"Resource":["collection/{collection}"]}}],'
                    '"AllowFromPublic":true}]'
                ),
            },
        },
        "AossDataAccessPolicy": {
            "Type": "AWS::OpenSearchServerless::AccessPolicy",
            "Properties": {
                "Name": f"{collection}-data",
                "Type": "data",
                "Policy": {
                    "Fn::Sub": (
                        '[{"Rules":[{"ResourceType":"collection",'
                        f'"Resource":["collection/{collection}"],'
                        '"Permission":["aoss:*"]},'
                        '{"ResourceType":"index",'
                        f'"Resource":["index/{collection}/*"],'
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
                "Name": collection,
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

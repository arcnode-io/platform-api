"""The DER ingress's starting truststore, shared by the cloud stack and the on-prem wizard."""

from typing import Final

# Throwaway self-signed cert (CN says exactly what it is) — a *syntactically
# valid* PEM so nginx's `ssl_client_certificate` loads cleanly and the
# container comes up healthy on every fresh deploy, instead of crash-looping
# on a fresh install until ops gets around to it. It trusts nothing real, so
# every DERMS connection attempt fails cert verification (fail-closed) until
# ops overwrites the secret with the actual utility CA bundle. Generated
# once with `openssl req -x509 -newkey rsa:2048 -nodes -days 3650`; never
# needs regenerating (nobody ever holds its private key on purpose).
PLACEHOLDER_TRUSTSTORE_PEM: Final[str] = """-----BEGIN CERTIFICATE-----
MIIDZzCCAk+gAwIBAgIUbsqPjkyVOOsBxSE/hmeQnwCflNIwDQYJKoZIhvcNAQEL
BQAwQzFBMD8GA1UEAww4YXJjbm9kZS1kZXItY29udHJvbC10cnVzdHN0b3JlLVBM
QUNFSE9MREVSLW5vdC1hLXJlYWwtY2EwHhcNMjYwOTEwMjIyOTA0WhcNMzYwOTA3
MjIyOTA0WjBDMUEwPwYDVQQDDDhhcmNub2RlLWRlci1jb250cm9sLXRydXN0c3Rv
cmUtUExBQ0VIT0xERVItbm90LWEtcmVhbC1jYTCCASIwDQYJKoZIhvcNAQEBBQAD
ggEPADCCAQoCggEBALcqsvobHOCtafVMkqi7lZS9DluSJD8fY5FlQxj6VyflIpXO
L/HZEiyV2S41Xw94ZVrWnuAoVkX0djnWn2gwCOYdHH66V7hge/YZQgm/F4xPDYKQ
dDJTywTiCePIYrBxW8X90CryJTJ2BVEz/ZQtn4aiFfvBewM0BBMgnUXj4J74vcAj
3AMyLCMPLZv4OkKv9gNP77OKsF3al/Q1cGvjhx+H3KMREc7Q2lXpeZ03ReqpC6YK
JnaGq6E70LmC1bv0pEhF8vtq90uRD4M1YYdFf0yCwFOHeJz4Is8q7fsr/7oGyim1
+pt3jAvnmjR79cpaqa9WNnrDjVVV5EC3yymU6ucCAwEAAaNTMFEwHQYDVR0OBBYE
FGdM9XXI/KGF4TV8Z0RPPoMKN9DzMB8GA1UdIwQYMBaAFGdM9XXI/KGF4TV8Z0RP
PoMKN9DzMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEBAE9V4cfz
HsV5L72w0PrgjJMNgHB2bK98R0p/ie/bEBsTo+9RK0hygUxrQI/LKWWByJuf0EAC
vDn+BZOcL0RlRpEaenFSIIU8Yeh89oJ+31595wJ7zuSQb4/j6OfqCjnEqRtN4XYY
BfgNJTiWoSMwUOoT4AXU3aX8npcQWj6lZiHRbaGtNno7ipHIf1ZVFJ2vcg6oJfN1
7WnhIS75Kc4Plm3YpqXKL1ZqLNWCw/dBGQwYC6OfH7qraPpzOS4u+nO8zAr0wL4i
+Kli9X3ylGbKzM127PjjccSCE3fWCOaO71+h8LpZCBttnucw5SZaIZ2bX1bX4wxZ
aG2CdyvgqqKrQ5A=
-----END CERTIFICATE-----
"""

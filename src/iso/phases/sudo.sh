#!/bin/sh
set -e

# Give the account created in the Debian installer sudo. Debian only does
# that itself when the root password is left blank; set one and the account
# gets no sudo (and the sudo package isn't even installed). Every console
# command the wizard shows starts with sudo, same as the cloud's EC2 login.

apt-get install -y sudo
# Debian's adduser gives the installer's account FIRST_UID=1000 — the same
# account the wizard installs the SSH key for (src/wizard/main.py).
usermod -aG sudo "$(getent passwd 1000 | cut -d: -f1)"

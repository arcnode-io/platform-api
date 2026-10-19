#!/bin/sh
set -e

# The console login message is /etc/update-motd.d/50-arcnode, which pam_motd runs
# at every login: the banner, then "waiting for network", the setup wizard's
# address until setup is done, or the operator screen's address after. tty1's
# login waits until the box has an IP. pam shows /etc/motd after the dynamic
# part, so it's emptied (Debian's default is the license notice).

: > /etc/motd

# Waits for the box's address and writes it to /run/arcnode-box-ip (tmpfs, so a
# new boot finds it again; a box can get a different lease).
#
# Watches the kernel's routing table rather than an ifupdown or udev hook:
# which mechanism brings an interface up on first boot depends on its type
# (allow-hotplug interfaces come up from a udev rule, outside networking.service),
# but every one of them ends in a route.
cat > /usr/local/sbin/arcnode-motd-ip.sh <<'EOF'
#!/bin/sh
set -e
exec >> /var/log/arcnode-motd-ip.log 2>&1
echo "$(date -Is) arcnode-motd-ip starting"

get_ip() {
  # A link-local 169.254.x.x address (RFC 3927) can show up briefly before the
  # real DHCP lease; it's no use to a laptop, so it doesn't count. Logged, so
  # the log shows which case fired.
  RAW=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
  case "$RAW" in
    169.254.*)
      echo "$(date -Is) ignoring link-local address: $RAW" >&2
      ;;
    *)
      echo "$RAW"
      ;;
  esac
}

IP=$(get_ip)
echo "$(date -Is) initial get_ip: '${IP:-<empty>}'"

ATTEMPT=0
while [ -z "$IP" ]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "$(date -Is) attempt $ATTEMPT: waiting up to 2s on ip monitor route..."
  # stdbuf -oL: `ip monitor` fully buffers when piped, so a single route event
  # would never reach `read`. timeout 2: the monitor only wakes us early; a
  # route added between our last check and the monitor subscribing is still
  # caught on the next pass. Never gives up — it re-checks the real condition.
  timeout 2 stdbuf -oL ip monitor route 2>/dev/null | { read -r _ || true; }
  IP=$(get_ip)
  echo "$(date -Is) attempt $ATTEMPT: get_ip now: '${IP:-<empty>}'"
done

echo "$IP" > /run/arcnode-box-ip
echo "$(date -Is) got IP: $IP"
EOF
chmod 0755 /usr/local/sbin/arcnode-motd-ip.sh

# Runs at every login, so the message follows setup without a reboot. The wizard's
# last page (SSH lockdown) marks setup finished; the wizard answers on 8080 until then.
mkdir -p /etc/update-motd.d
cat > /etc/update-motd.d/50-arcnode <<'EOF'
#!/bin/sh
figlet "ArcNode EMS"
IP=$(cat /run/arcnode-box-ip 2>/dev/null || true)
if [ -z "$IP" ]; then
  printf '\n  Setup: waiting for network... (see /var/log/arcnode-motd-ip.log)\n\n'
elif [ -e /etc/arcnode/steps/ssh_lockdown.done ]; then
  printf '\n  ArcNode is running.\n  Operator screen (HMI): http://%s/\n\n' "$IP"
else
  cat <<MSG

  ================================================================
    SETUP IS NOT FINISHED
  ================================================================

    On a laptop on this network, open this address in a browser:

        http://$IP:8080

    The setup wizard there finishes installing ArcNode.
    This box does nothing useful until you do.
  ================================================================

MSG
fi
EOF
chmod 0755 /etc/update-motd.d/50-arcnode

# Description doubles as the boot screen's "A start job is running for …"
# line while the login prompt below is held back.
cat > /etc/systemd/system/arcnode-motd-ip.service <<'EOF'
[Unit]
Description=ArcNode: waiting for a network address (login opens once connected)

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/arcnode-motd-ip.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl enable arcnode-motd-ip.service

# Hold tty1's login prompt until the IP is known, so the first login always
# shows the real setup address. A oneshot has no start timeout, so this waits
# on the real condition, not a guessed window. Only tty1: Alt+F2 still gives a
# login (showing "waiting for network") if the network never comes up.
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/arcnode-wait-for-ip.conf <<'EOF'
[Unit]
After=arcnode-motd-ip.service
Wants=arcnode-motd-ip.service
EOF

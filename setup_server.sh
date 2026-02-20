#!/bin/bash
# ===========================================================================
# setup_server.sh  –  Installerar WireGuard VPN-server på Ubuntu/Debian
#
# Användning:  sudo bash setup_server.sh
#
# Vad skriptet gör:
#   1. Installerar WireGuard
#   2. Genererar server- och klientnycklar
#   3. Skapar serverkonfiguration (/etc/wireguard/wg0.conf)
#   4. Aktiverar IP-vidarebefordring
#   5. Öppnar port i brandväggen (ufw)
#   6. Startar VPN-tjänsten
#   7. Skapar en klientkonfigurationsfil (.conf) att importera i InkyVPN
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Hjälpfunktioner
# ---------------------------------------------------------------------------

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗ Fel:${NC} $*"; exit 1; }
ask()  { echo -e "${BOLD}?${NC} $*"; }

# ---------------------------------------------------------------------------
# Kontroller
# ---------------------------------------------------------------------------

[ "$EUID" -ne 0 ] && err "Kör som root:  sudo bash setup_server.sh"
command -v apt-get &>/dev/null || err "Kräver Ubuntu/Debian (apt-get hittades inte)."

echo ""
echo -e "${BOLD}=== WireGuard VPN-serverinstallation ===${NC}"
echo ""

# ---------------------------------------------------------------------------
# Installera paket
# ---------------------------------------------------------------------------

ok "Uppdaterar paketlistan och installerar WireGuard..."
apt-get update -qq
apt-get install -y wireguard wireguard-tools curl ufw > /dev/null
ok "WireGuard installerat."

# ---------------------------------------------------------------------------
# Generera servernycklar
# ---------------------------------------------------------------------------

SERVER_PRIV=$(wg genkey)
SERVER_PUB=$(echo "$SERVER_PRIV" | wg pubkey)
ok "Servernycklar genererade."

# ---------------------------------------------------------------------------
# Insamla information
# ---------------------------------------------------------------------------

# Publik IP-adress
SERVER_IP=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null \
         || wget -qO- --timeout=10 https://api.ipify.org 2>/dev/null \
         || echo "")

if [ -z "$SERVER_IP" ]; then
    ask "Kunde inte hämta publik IP automatiskt."
    read -rp "  Ange serverns publika IP-adress: " SERVER_IP
fi
ok "Serverns publika IP: $SERVER_IP"

# Nätverksgränssnitt (för att vidarebefordra trafik)
DEFAULT_IF=$(ip route | awk '/default/ {print $5}' | head -1)
ask "Vilket nätverksgränssnitt används för internet? [${DEFAULT_IF}]"
read -rp "  > " NET_IF
NET_IF="${NET_IF:-$DEFAULT_IF}"
ok "Nätverksgränssnitt: $NET_IF"

# WireGuard-port
ask "Vilken UDP-port ska WireGuard använda? [51820]"
read -rp "  > " WG_PORT
WG_PORT="${WG_PORT:-51820}"
ok "Port: $WG_PORT/udp"

# Klientnamn
ask "Ge klienten ett namn (t.ex. hemma-datorn) [klient]:"
read -rp "  > " CLIENT_NAME
CLIENT_NAME="${CLIENT_NAME:-klient}"
# Sanera till ett giltigt filnamn
CLIENT_NAME=$(echo "$CLIENT_NAME" | tr ' ' '-' | tr -cd '[:alnum:]-_')
[ -z "$CLIENT_NAME" ] && CLIENT_NAME="klient"
ok "Klientnamn: $CLIENT_NAME"

# ---------------------------------------------------------------------------
# Generera klientnycklar
# ---------------------------------------------------------------------------

CLIENT_PRIV=$(wg genkey)
CLIENT_PUB=$(echo "$CLIENT_PRIV" | wg pubkey)
CLIENT_PSK=$(wg genpsk)
ok "Klientnycklar genererade."

# Nätverksadresser
SERVER_VPN_ADDR="10.8.0.1"
CLIENT_VPN_ADDR="10.8.0.2"

# ---------------------------------------------------------------------------
# Serverkonfiguration
# ---------------------------------------------------------------------------

cat > /etc/wireguard/wg0.conf << CONF
[Interface]
Address    = ${SERVER_VPN_ADDR}/24
ListenPort = ${WG_PORT}
PrivateKey = ${SERVER_PRIV}

# Aktivera NAT och paketvidarebefordring
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; \
           iptables -A FORWARD -o wg0 -j ACCEPT; \
           iptables -t nat -A POSTROUTING -o ${NET_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; \
           iptables -D FORWARD -o wg0 -j ACCEPT; \
           iptables -t nat -D POSTROUTING -o ${NET_IF} -j MASQUERADE

[Peer]
# ${CLIENT_NAME}
PublicKey    = ${CLIENT_PUB}
PresharedKey = ${CLIENT_PSK}
AllowedIPs   = ${CLIENT_VPN_ADDR}/32
CONF

chmod 600 /etc/wireguard/wg0.conf
ok "Serverkonfiguration skapad: /etc/wireguard/wg0.conf"

# ---------------------------------------------------------------------------
# IP-vidarebefordring
# ---------------------------------------------------------------------------

if ! grep -qxF 'net.ipv4.ip_forward=1' /etc/sysctl.conf; then
    echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
fi
sysctl -w net.ipv4.ip_forward=1 > /dev/null
ok "IP-vidarebefordring aktiverad."

# ---------------------------------------------------------------------------
# Brandvägg (ufw)
# ---------------------------------------------------------------------------

if command -v ufw &>/dev/null; then
    ufw allow "${WG_PORT}/udp" > /dev/null
    ufw --force enable > /dev/null
    ok "ufw: öppnad port ${WG_PORT}/udp."
else
    warn "ufw hittades inte. Se till att port ${WG_PORT}/udp är öppen manuellt."
fi

# ---------------------------------------------------------------------------
# Starta WireGuard-tjänsten
# ---------------------------------------------------------------------------

systemctl enable wg-quick@wg0 > /dev/null 2>&1
systemctl start  wg-quick@wg0
ok "WireGuard-tjänst startad (wg-quick@wg0)."

# ---------------------------------------------------------------------------
# Klientkonfigurationsfil
# ---------------------------------------------------------------------------

CLIENT_CONF="/root/${CLIENT_NAME}.conf"
cat > "$CLIENT_CONF" << CONF
[Interface]
PrivateKey = ${CLIENT_PRIV}
Address    = ${CLIENT_VPN_ADDR}/32
DNS        = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey            = ${SERVER_PUB}
PresharedKey         = ${CLIENT_PSK}
Endpoint             = ${SERVER_IP}:${WG_PORT}
AllowedIPs           = 0.0.0.0/0
PersistentKeepalive  = 25
CONF

chmod 600 "$CLIENT_CONF"

# ---------------------------------------------------------------------------
# Sammanfattning
# ---------------------------------------------------------------------------

echo ""
echo -e "${BOLD}=======================================================${NC}"
ok "VPN-server är klar!"
echo -e "${BOLD}=======================================================${NC}"
echo ""
echo "  Serverns IP:          $SERVER_IP"
echo "  VPN-port:             $WG_PORT/udp"
echo "  Klientfil:            $CLIENT_CONF"
echo ""
echo -e "${BOLD}Nästa steg:${NC}"
echo "  1. Kopiera '${CLIENT_NAME}.conf' till din Windows-dator:"
echo "       scp root@${SERVER_IP}:/root/${CLIENT_NAME}.conf ."
echo ""
echo "  2. Öppna InkyVPN (vpn_app.py) som administratör"
echo "  3. Klicka '+ Importera .conf' och välj den kopierade filen"
echo "  4. Välj profilen i listan och klicka 'Anslut'"
echo ""
echo "  Status på servern:  sudo wg show"
echo "  Stoppa VPN:         sudo systemctl stop wg-quick@wg0"
echo "  Starta VPN:         sudo systemctl start wg-quick@wg0"
echo ""

#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "provision: run as root" >&2
  exit 1
fi

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
uv_version=0.11.26
cloudflare_key=/usr/share/keyrings/cloudflare-main.gpg
cloudflare_list=/etc/apt/sources.list.d/cloudflared.list

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y sqlite3 redis-server ufw curl ca-certificates fuse3

if ! command -v rclone >/dev/null 2>&1; then
  apt-get install -y unzip
  curl -fsSL https://rclone.org/install.sh | bash
fi

if [ "$(/usr/local/bin/uv --version 2>/dev/null | cut -d' ' -f2)" != "$uv_version" ]; then
  curl -LsSf "https://astral.sh/uv/$uv_version/install.sh" |
    env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

cloudflared_from_apt() {
  install -d -m 0755 /usr/share/keyrings &&
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o "$cloudflare_key" &&
    echo "deb [signed-by=$cloudflare_key] https://pkg.cloudflare.com/cloudflared any main" >"$cloudflare_list" &&
    apt-get update &&
    apt-get install -y cloudflared
}

cloudflared_from_github() {
  rm -f "$cloudflare_list"
  local package
  package=$(mktemp --suffix=.deb)
  curl -fsSL -o "$package" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  dpkg -i "$package"
  rm -f "$package"
}

if ! command -v cloudflared >/dev/null 2>&1; then
  cloudflared_from_apt || cloudflared_from_github
fi

if ! id -u muse >/dev/null 2>&1; then
  useradd --system --home-dir /srv/muse --no-create-home --shell /usr/sbin/nologin muse
fi
if ! id -u cloudflared >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin cloudflared
fi

owned_dir() {
  mkdir -p "$4"
  chown "$1:$2" "$4"
  chmod "$3" "$4"
}

owned_dir root root 755 /opt/muse
owned_dir root root 755 /opt/muse/releases
owned_dir root root 755 /opt/muse/python
owned_dir root root 755 /srv/muse
owned_dir muse muse 750 /srv/muse/data
if ! mountpoint -q /srv/muse/lib; then
  owned_dir root root 755 /srv/muse/lib
fi
owned_dir root root 700 /var/cache/rclone-muse
owned_dir root root 755 /var/cache/uv
owned_dir root root 700 /var/backups/muse
owned_dir root muse 750 /etc/muse
owned_dir root cloudflared 750 /etc/cloudflared

install -o root -g root -m 644 "$here/redis/muse.conf" /etc/redis/muse.conf
if ! grep -qxF 'include /etc/redis/muse.conf' /etc/redis/redis.conf; then
  printf '\ninclude /etc/redis/muse.conf\n' >>/etc/redis/redis.conf
fi
systemctl restart redis-server

install -o root -g root -m 755 "$here"/bin/* /usr/local/bin/
install -o root -g root -m 644 "$here"/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable redis-server muse-lib.service muse-catalog.timer muse-backup.timer muse.service cloudflared-muse.service

ufw default deny incoming
ufw default allow outgoing
ufw limit 22/tcp
ufw --force enable

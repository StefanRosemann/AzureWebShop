#!/bin/bash
set -e

echo "Passe MariaDB-Konfiguration an..."

# Bei normaler Ubuntu/MariaDB-Installation liegt die Konfiguration meistens hier:
sudo sed -i "s/^bind-address\s*=.*/#bind-address = 127.0.0.1/g" /etc/mysql/mariadb.conf.d/50-server.cnf || true
sudo sed -i "s/^bind_address\s*=.*/#bind_address = 127.0.0.1/g" /etc/mysql/mariadb.conf.d/50-server.cnf || true

echo "Starte MariaDB neu..."
sudo systemctl restart mariadb


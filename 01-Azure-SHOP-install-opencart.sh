#!/bin/bash
set -e

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

echo "Konfiguriere automatische Neustarts ohne Nachfrage..."
sudo mkdir -p /etc/needrestart/conf.d
echo '$nrconf{restart} = "a";' | sudo tee /etc/needrestart/conf.d/99-auto-restart.conf > /dev/null

echo "Aktualisiere Ubuntu..."
sudo apt-get update
sudo apt-get upgrade -y -o Dpkg::Options::="--force-confold"

echo "Installiere Apache, MariaDB, PHP und Erweiterungen..."
sudo apt install -y apache2 mariadb-server unzip curl wget \
php php-cli php-mysql php-curl php-gd php-mbstring php-zip php-xml php-intl php-common

echo "Starte Apache und MariaDB..."
sudo systemctl enable apache2
sudo systemctl enable mariadb
sudo systemctl start apache2
sudo systemctl start mariadb

echo "Erstelle OpenCart-Datenbank..."
DB_NAME="opencart"
DB_USER="opencartuser"
DB_PASS="OpenCart123!"

sudo mysql -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASS}';"
sudo mysql -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

echo "Lade OpenCart herunter..."
cd /tmp
wget -O opencart.zip https://github.com/opencart/opencart/releases/download/4.1.0.3/opencart-4.1.0.3.zip

echo "Entpacke OpenCart..."
unzip -q opencart.zip -d opencart

echo "Kopiere OpenCart nach /var/www/html..."
sudo rm -rf /var/www/html/*
sudo cp -r /tmp/opencart/upload/* /var/www/html/

echo "Erstelle config.php-Dateien..."
sudo cp /var/www/html/config-dist.php /var/www/html/config.php
sudo cp /var/www/html/admin/config-dist.php /var/www/html/admin/config.php

echo "Setze Dateirechte..."
sudo chown -R www-data:www-data /var/www/html
sudo chmod -R 755 /var/www/html

echo "Aktiviere Apache rewrite..."
sudo a2enmod rewrite

echo "Apache-Konfiguration anpassen..."
sudo bash -c 'cat > /etc/apache2/sites-available/000-default.conf' <<EOF
<VirtualHost *:80>
    DocumentRoot /var/www/html

    <Directory /var/www/html>
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
EOF

sudo systemctl restart apache2

PUBLIC_IP=$(curl -s ifconfig.me || echo "DEINE-IP")

echo ""
echo "Fertig!"
echo "Öffne jetzt im Browser:"
echo "http://${PUBLIC_IP}"
echo ""
echo "Datenbankdaten für die OpenCart-Installation:"
echo "Datenbank-Host: localhost"
echo "Datenbankname: opencart"
echo "Datenbankbenutzer: opencartuser"
echo "Datenbankpasswort: OpenCart123!"
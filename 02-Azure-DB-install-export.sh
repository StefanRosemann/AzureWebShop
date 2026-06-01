#!/bin/bash
set -e

export DEBIAN_FRONTEND=noninteractive
export ACCEPT_EULA=Y

WORKDIR="/home/rse/AzureWebShop"
VENV_DIR="$WORKDIR/venv"

echo "Arbeitsverzeichnis vorbereiten..."
mkdir -p "$WORKDIR"
cd "$WORKDIR"

echo "Systempakete installieren..."
sudo apt-get update
sudo apt-get install -y \
  curl \
  ca-certificates \
  apt-transport-https \
  software-properties-common \
  python3 \
  python3-pip \
  python3-venv \
  unixodbc \
  unixodbc-dev

echo "Microsoft-Paketquelle OHNE Signaturprüfung eintragen..."
sudo rm -f /etc/apt/sources.list.d/mssql-release.list

echo "deb [trusted=yes] https://packages.microsoft.com/ubuntu/22.04/prod jammy main" | \
  sudo tee /etc/apt/sources.list.d/mssql-release.list > /dev/null

echo "Paketlisten aktualisieren..."
sudo apt-get update || true

echo "Microsoft ODBC Driver 18 installieren..."
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18

echo "ODBC-Treiber prüfen..."
odbcinst -q -d || true

echo "Python-Umgebung erstellen..."
cd "$WORKDIR"

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "Python-Pakete installieren..."
pip install --upgrade pip
pip install pymysql pyodbc python-dotenv

echo ".env-Datei erstellen oder aktualisieren..."

cat > "$WORKDIR/.env" <<EOF
AZURE_SQL_SERVER=rse-db-srv.database.windows.net
AZURE_SQL_DATABASE=ibrot
AZURE_SQL_USER=rse
AZURE_SQL_PASSWORD='Pa\$\$w0rd1234'

OPENCART_CONFIG=/var/www/html/config.php
OPENCART_TABLE_PREFIX=oc_
EOF

echo "Rechte setzen..."
chmod 600 "$WORKDIR/.env"
chmod +x "$WORKDIR/export_today_orders.py" 2>/dev/null || true

echo ""
echo "Installation abgeschlossen."
echo ""
echo "Teststart:"
echo "cd $WORKDIR"
echo "source venv/bin/activate"
echo "python export_today_orders.py"
echo ""
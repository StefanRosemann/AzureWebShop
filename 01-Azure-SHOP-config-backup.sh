echo "Erstelle Backup-Ordner für SQL-Datei..."
sudo mkdir -p /var/www/html/system/storage/backup

echo "Kopiere Backup-Datei und setze Rechte ..."
sudo mv ./*.sql /var/www/html/system/storage/backup
sudo chown -R www-data:www-data /var/www/html/system/storage/backup

echo "Kopiere Bilder ..."
sudo mv ./*.zip /var/www/html/image/catalog

echo "Entpacke Bilder und setze Rechte..."
cd /var/www/html/image/catalog
sudo unzip ./01-Azure-SHOP-Bilder.zip
sudo chown -R www-data:www-data /var/www/html/image
sudo chmod -R 755 /var/www/html/image

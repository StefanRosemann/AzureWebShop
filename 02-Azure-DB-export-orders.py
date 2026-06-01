#!/usr/bin/env python3
import os
import re
import sys
from datetime import date

import pymysql
import pyodbc
from dotenv import load_dotenv


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH)


def read_opencart_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"OpenCart config.php nicht gefunden: {path}")

    text = open(path, "r", encoding="utf-8", errors="ignore").read()

    config = {}

    for key in ["DB_HOSTNAME", "DB_USERNAME", "DB_PASSWORD", "DB_DATABASE", "DB_PORT"]:
        pattern = rf"define\(\s*['\"]{key}['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)"
        match = re.search(pattern, text)

        if match:
            config[key] = match.group(1)

    required = ["DB_HOSTNAME", "DB_USERNAME", "DB_PASSWORD", "DB_DATABASE"]
    missing = [key for key in required if key not in config]

    if missing:
        raise RuntimeError(f"Folgende DB-Werte fehlen in config.php: {', '.join(missing)}")

    config.setdefault("DB_PORT", "3306")
    return config


def connect_opencart():
    config_path = os.getenv("OPENCART_CONFIG", "/var/www/html/config.php")
    cfg = read_opencart_config(config_path)

    return pymysql.connect(
        host=cfg["DB_HOSTNAME"],
        user=cfg["DB_USERNAME"],
        password=cfg["DB_PASSWORD"],
        database=cfg["DB_DATABASE"],
        port=int(cfg["DB_PORT"]),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def connect_azure_sql():
    server = os.getenv("AZURE_SQL_SERVER")
    database = os.getenv("AZURE_SQL_DATABASE")
    user = os.getenv("AZURE_SQL_USER")
    password = os.getenv("AZURE_SQL_PASSWORD")

    if not all([server, database, user, password]):
        raise RuntimeError("Azure-SQL-Zugangsdaten fehlen in der .env-Datei.")

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{server},1433;"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    return pyodbc.connect(connection_string)


def get_kunde_id(order):
    customer_id = int(order.get("customer_id") or 0)

    if customer_id > 0:
        return customer_id

    return 900000000 + int(order["order_id"])


def clean_text(value, max_len=None):
    if value is None:
        value = ""

    value = str(value)
    value = value.replace("\r", " ").replace("\n", " ").strip()

    if max_len is not None:
        value = value[:max_len]

    return value


def fetch_orders(mysql_conn, prefix: str):
    sql = f"""
        SELECT
            order_id,
            customer_id,
            customer_group_id,

            firstname,
            lastname,
            email,
            telephone,

            payment_address_1,
            payment_address_2,
            payment_city,
            payment_postcode,

            shipping_address_1,
            shipping_address_2,
            shipping_city,
            shipping_postcode,

            DATE(date_added) AS bestell_datum,
            DATE(date_modified) AS liefer_datum,
            DATE(date_added) AS erstellungsdatum
        FROM {prefix}order
        ORDER BY order_id;
    """

    with mysql_conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_order_positions(mysql_conn, prefix: str, order_ids):
    if not order_ids:
        return []

    placeholders = ",".join(["%s"] * len(order_ids))

    sql = f"""
        SELECT
            order_id,
            order_product_id,
            product_id,
            quantity
        FROM {prefix}order_product
        WHERE order_id IN ({placeholders})
        ORDER BY order_id, order_product_id;
    """

    with mysql_conn.cursor() as cur:
        cur.execute(sql, order_ids)
        return cur.fetchall()


def upsert_kunden(sql_conn, orders):
    sql = """
        MERGE dbo.Kunde AS target
        USING (
            SELECT
                ? AS KundeID,
                ? AS KundeName,
                ? AS Erstellungsdatum,
                ? AS StandardRabatt,
                ? AS Telefon,
                ? AS Fax,
                ? AS WebsiteURL,
                ? AS Lieferadresse1,
                ? AS Lieferadresse2,
                ? AS LieferPLZ,
                ? AS PostAdresse1,
                ? AS PostAdresse2,
                ? AS PostPLZ,
                ? AS BearbeitetVon
        ) AS source
        ON target.KundeID = source.KundeID
        WHEN MATCHED THEN
            UPDATE SET
                KundeName = source.KundeName,
                Erstellungsdatum = source.Erstellungsdatum,
                StandardRabatt = source.StandardRabatt,
                Telefon = source.Telefon,
                Fax = source.Fax,
                WebsiteURL = source.WebsiteURL,
                Lieferadresse1 = source.Lieferadresse1,
                Lieferadresse2 = source.Lieferadresse2,
                LieferPLZ = source.LieferPLZ,
                PostAdresse1 = source.PostAdresse1,
                PostAdresse2 = source.PostAdresse2,
                PostPLZ = source.PostPLZ,
                BearbeitetVon = source.BearbeitetVon
        WHEN NOT MATCHED THEN
            INSERT (
                KundeID,
                KundeName,
                Erstellungsdatum,
                StandardRabatt,
                Telefon,
                Fax,
                WebsiteURL,
                Lieferadresse1,
                Lieferadresse2,
                LieferPLZ,
                PostAdresse1,
                PostAdresse2,
                PostPLZ,
                BearbeitetVon
            )
            VALUES (
                source.KundeID,
                source.KundeName,
                source.Erstellungsdatum,
                source.StandardRabatt,
                source.Telefon,
                source.Fax,
                source.WebsiteURL,
                source.Lieferadresse1,
                source.Lieferadresse2,
                source.LieferPLZ,
                source.PostAdresse1,
                source.PostAdresse2,
                source.PostPLZ,
                source.BearbeitetVon
            );
    """

    cur = sql_conn.cursor()
    already_done = set()

    for order in orders:
        kunde_id = get_kunde_id(order)

        if kunde_id in already_done:
            continue

        already_done.add(kunde_id)

        name = clean_text(
            f"{order.get('firstname', '')} {order.get('lastname', '')}",
            50
        )

        if not name:
            name = f"Kunde {kunde_id}"

        telefon = clean_text(order.get("telephone"), 50)

        # Neue gewünschte Zuordnung:
        # Straße aus OpenCart -> Lieferadresse2
        # PLZ aus OpenCart    -> PostPLZ
        # Ort aus OpenCart    -> PostAdresse2
        lieferadresse1 = ""
        lieferadresse2 = clean_text(order.get("shipping_address_1"), 50)
        lieferplz = ""

        postadresse1 = ""
        postadresse2 = clean_text(order.get("shipping_city"), 50)
        postplz = clean_text(order.get("shipping_postcode"), 50)

        cur.execute(
            sql,
            kunde_id,
            name,
            order["erstellungsdatum"],
            0.0,
            telefon,
            "",
            clean_text(order.get("email"), 255),
            lieferadresse1,
            lieferadresse2,
            lieferplz,
            postadresse1,
            postadresse2,
            postplz,
            1,
        )

    sql_conn.commit()


def upsert_bestellung(sql_conn, orders):
    sql = """
        MERGE dbo.Bestellung AS target
        USING (
            SELECT
                ? AS BestellungID,
                ? AS KundeID,
                ? AS Bestelldatum,
                ? AS Lieferdatum
        ) AS source
        ON target.BestellungID = source.BestellungID
        WHEN MATCHED THEN
            UPDATE SET
                KundeID = source.KundeID,
                Bestelldatum = source.Bestelldatum,
                Lieferdatum = source.Lieferdatum
        WHEN NOT MATCHED THEN
            INSERT (
                BestellungID,
                KundeID,
                Bestelldatum,
                Lieferdatum
            )
            VALUES (
                source.BestellungID,
                source.KundeID,
                source.Bestelldatum,
                source.Lieferdatum
            );
    """

    cur = sql_conn.cursor()

    for order in orders:
        cur.execute(
            sql,
            int(order["order_id"]),
            get_kunde_id(order),
            order["bestell_datum"],
            order["liefer_datum"],
        )

    sql_conn.commit()


def upsert_bestellposition(sql_conn, positions):
    sql = """
        MERGE dbo.Bestellposition AS target
        USING (
            SELECT
                ? AS BestellungID,
                ? AS Position,
                ? AS ArtikelID,
                ? AS Menge
        ) AS source
        ON target.BestellungID = source.BestellungID
           AND target.Position = source.Position
        WHEN MATCHED THEN
            UPDATE SET
                ArtikelID = source.ArtikelID,
                Menge = source.Menge
        WHEN NOT MATCHED THEN
            INSERT (
                BestellungID,
                Position,
                ArtikelID,
                Menge
            )
            VALUES (
                source.BestellungID,
                source.Position,
                source.ArtikelID,
                source.Menge
            );
    """

    cur = sql_conn.cursor()

    for pos in positions:
        cur.execute(
            sql,
            int(pos["order_id"]),
            int(pos["order_product_id"]),
            int(pos["product_id"]),
            int(pos["quantity"]),
        )

    sql_conn.commit()


def main():
    prefix = os.getenv("OPENCART_TABLE_PREFIX", "oc_")

    print("Starte Export aller OpenCart-Bestellungen inklusive Kundendaten...")
    print(f"Heutiges Datum laut Server: {date.today()}")
    print(f"Arbeitsverzeichnis: {BASE_DIR}")

    mysql_conn = connect_opencart()
    sql_conn = connect_azure_sql()

    try:
        orders = fetch_orders(mysql_conn, prefix)
        print(f"Gefundene Bestellungen insgesamt: {len(orders)}")

        if not orders:
            print("Keine Bestellungen gefunden.")
            return

        order_ids = [order["order_id"] for order in orders]

        positions = fetch_order_positions(mysql_conn, prefix, order_ids)
        print(f"Gefundene Bestellpositionen insgesamt: {len(positions)}")

        print("Schreibe dbo.Kunde...")
        upsert_kunden(sql_conn, orders)

        print("Schreibe dbo.Bestellung...")
        upsert_bestellung(sql_conn, orders)

        print("Schreibe dbo.Bestellposition...")
        upsert_bestellposition(sql_conn, positions)

        print("Export erfolgreich abgeschlossen.")

    finally:
        mysql_conn.close()
        sql_conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("")
        print("FEHLER:")
        print(exc)
        sys.exit(1)
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


def fetch_today_orders(mysql_conn, prefix: str):
    sql = f"""
        SELECT
            order_id,
            customer_group_id,
            DATE(date_added) AS bestell_datum,
            DATE(date_modified) AS liefer_datum
        FROM {prefix}order
        WHERE date_added >= CURDATE()
          AND date_added < DATE_ADD(CURDATE(), INTERVAL 1 DAY)
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
            int(order["customer_group_id"]),
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

    print("Starte Export der heutigen OpenCart-Bestellungen...")
    print(f"Heutiges Datum laut Server: {date.today()}")
    print(f"Arbeitsverzeichnis: {BASE_DIR}")

    mysql_conn = connect_opencart()
    sql_conn = connect_azure_sql()

    try:
        orders = fetch_today_orders(mysql_conn, prefix)
        print(f"Gefundene Bestellungen heute: {len(orders)}")

        if not orders:
            print("Keine heutigen Bestellungen gefunden.")
            return

        order_ids = [order["order_id"] for order in orders]

        positions = fetch_order_positions(mysql_conn, prefix, order_ids)
        print(f"Gefundene Bestellpositionen: {len(positions)}")

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
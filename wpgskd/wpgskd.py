import logging
import os
import sys
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", category=UserWarning, module='pproxy')
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

import click
import coloredlogs

from wpgskd.config import directories, filenames
from wpgskd.commands.dl import dl

@click.group(context_settings=dict(
    allow_extra_args=True,
    ignore_unknown_options=True,
    max_content_width=116,
))
@click.option("--debug", is_flag=True, default=False,
              help="Enable DEBUG level logs on the console. This is always enabled for log files.")
def main(debug):
    """
    WPGSKD - Widevine PlayReady General Stream Key Decryptor
    """
    LOG_FORMAT = "{asctime} [{levelname[0]}] {name} : {message}"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    LOG_STYLE = "{"

    def log_exit(self, msg, *args, **kwargs):
        self.critical(msg, *args, **kwargs)
        sys.exit(1)

    logging.Logger.exit = log_exit

    os.makedirs(directories.logs, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        style=LOG_STYLE,
        handlers=[logging.FileHandler(
            os.path.join(directories.logs, filenames.log.format(time=datetime.now().strftime("%Y%m%d-%H%M%S"))),
            encoding='utf-8'
        )]
    )

    coloredlogs.install(
        level=logging.DEBUG if debug else logging.INFO,
        fmt=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        style=LOG_STYLE,
        handlers=[logging.StreamHandler()],
    )

    log = logging.getLogger("wpgskd")

    log.info("WPGSKD - Widevine, PlayReady, AES-128 & ClearKey Downloader")
    log.info(f"[Root Config]     : {filenames.user_root_config}")
    log.info(f"[Cookies]         : {directories.cookies}")
    log.info(f"[CDM Devices]     : {directories.devices}")
    log.info(f"[Cache]           : {directories.cache}")
    log.info(f"[Logs]            : {directories.logs}")
    log.info(f"[Temp Files]      : {directories.temp}")
    log.info(f"[Downloads]       : {directories.downloads}")
    
    bin_path = os.path.abspath('./binaries')
    if os.path.exists(bin_path):
        os.environ['PATH'] += os.pathsep + bin_path


@main.group(name="tools")
def tools():
    pass

@tools.command(name="merge-vault")
@click.option("-i", "--input", "input_db", required=True, type=click.Path(exists=True))
@click.option("-o", "--output", "output_db", required=True, type=click.Path())
def merge_vault(input_db, output_db):
    from wpgskd.core.vaults import Vaults, LocalVault
    
    log = logging.getLogger("tools")
    log.info(f"Merging keys from {input_db} to {output_db}")
    
    src_vault = LocalVault(name="Source", path=input_db)
    dst_vault = LocalVault(name="Target", path=output_db)
    
    conn = src_vault.con
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = cursor.fetchall()
    
    total_added, total_skipped = 0, 0
    for table_row in tables:
        table = table_row[0]
        cursor.execute(f"SELECT kid, key_, title FROM `{table}`")
        rows = cursor.fetchall()
        
        added, skipped = 0, 0
        for kid, key, title in rows:
            res = dst_vault.insert_key(table, kid, key, title, commit=False)
            if res.name == "SUCCESS": added += 1
            else: skipped += 1
            
        dst_vault.commit()
        total_added += added
        total_skipped += skipped
        log.info(f"  Table [{table}]: Added {added}, Skipped {skipped}")

    log.info(f"Merge complete! Total Added: {total_added}, Total Skipped: {total_skipped}")


@tools.command(name="add-keys")
@click.option("-t", "--table", "service", required=True, help="Service name (e.g. netflix, amazon)")
@click.option("-i", "--input", "input_file", type=click.Path(exists=True))
@click.option("-o", "--output", "output_db", required=True, type=click.Path())
def add_keys(service, input_file, output_db):
    import re
    from wpgskd.core.vaults import LocalVault
    
    log = logging.getLogger("tools")
    vault = LocalVault(name="Target", path=output_db)
    
    added, skipped = 0, 0
    pattern = re.compile(r"^(?P<kid>[0-9a-fA-F]{32}):(?P<key>[0-9a-fA-F]{32})(:(?P<title>[\w .:-]*))?$")
    
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m: continue
            kid = m.group("kid").lower()
            key = m.group("key").lower()
            title = m.group("title")
            
            res = vault.insert_key(service, kid, key, title, commit=False)
            if res.name == "SUCCESS": added += 1
            else: skipped += 1
            
    vault.commit()
    log.info(f"Batch add complete. Added: {added}, Skipped: {skipped}")


main.add_command(dl)

if __name__ == "__main__":
    main()
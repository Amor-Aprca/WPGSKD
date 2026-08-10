@echo off
poetry run python scripts/merge_local_tables.py -c youtube:youtubemovies -o youtubemovies -db "M:\WPGSKD\scripts\key_store.db"
pause
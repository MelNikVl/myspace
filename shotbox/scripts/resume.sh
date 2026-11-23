#!/bin/bash
# ShotBox: перепрогон фильмов + метаданные (батчинг, ресайз, чистка неверных данных).
cd /home/nik/shotbox || exit 1
set -a
source ./.env
set +a

echo "$(date '+%F %T') START" >> /tmp/shotbox_resume.log

# 1) сброс фильмов без ручных правок
./venv/bin/python - <<'PY' >> /tmp/shotbox_resume.log 2>&1
import sqlite3
con = sqlite3.connect("data/shotbox.db")
n = con.execute(
    "UPDATE items SET analyzed=0 "
    "WHERE category IN ('фильм','сериал','мультфильм') "
    "AND COALESCE(review,'')='' AND COALESCE(rating,0)=0 AND COALESCE(favorite,0)=0"
).rowcount
con.commit()
print("сброшено на перепрогон:", n)
con.close()
PY

# 2) классификация батчами по 6 (ресайз 1024px, ротация 2 ключей)
./venv/bin/python analyze_batch.py >> /tmp/shotbox_analyze.log 2>&1

# 3) метаданные из Кинопоиска (fuzzy + транслитерация)
./venv/bin/python enrich_kp.py >> /tmp/shotbox_enrich.log 2>&1

# 4) восстановление/чистка неверных метаданных (КП → OMDB)
./venv/bin/python fix_meta2.py >> /tmp/shotbox_enrich.log 2>&1

# 5) постеры для новых kp_id
./venv/bin/python fill_titles.py >> /tmp/shotbox_enrich.log 2>&1

# 5) постеры для новых kp_id
./venv/bin/python fetch_posters.py >> /tmp/shotbox_enrich.log 2>&1

echo "$(date '+%F %T') DONE" >> /tmp/shotbox_resume.log

# cooper_cli.py
import argparse
from datetime import date
import sqlite3

from schema import connect, migrate
from datetime import datetime, timedelta

def print_rows(rows):
    rows = list(rows)
    if not rows:
        print("(no results)")
        return
    headers = rows[0].keys()
    print(" | ".join(headers))
    print("-" * (len(" | ".join(headers))))
    for r in rows:
        print(" | ".join("" if r[h] is None else str(r[h]) for h in headers))


def get_pet_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM mypet ORDER BY id ASC LIMIT 1").fetchone()
    if not row:
        raise SystemExit("❌ No pet found in table 'mypet'. You already inserted Cooper, so this is unexpected.")
    return int(row["id"])


def build_update_sql(table: str, id_col: str, allowed_cols: list[str], args_dict: dict, record_id: int):
    updates = {k: v for k, v in args_dict.items() if k in allowed_cols and v is not None}
    if not updates:
        raise SystemExit("❌ No fields provided to update. Provide at least one --field.")
    set_clause = ", ".join([f"{col}=?" for col in updates.keys()])
    params = list(updates.values()) + [record_id]
    sql = f"UPDATE {table} SET {set_clause} WHERE {id_col}=?"
    return sql, params, updates.keys()


# ---------------- Commands ----------------
def cmd_init(args):
    with connect(args.db) as conn:
        migrate(conn)
    print(f"✅ init ok (no data changed): {args.db}")

def cmd_timeline(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        rows = conn.execute(
            """
            SELECT
              e.event_id,
              e.date,
              e.type,
              e.title,
              e.standard_name_zh,
              e.vet,
              e.episode_id,
              ep.condition_name_zh AS episode_name
            FROM events e
            LEFT JOIN episodes ep ON ep.id = e.episode_id
            WHERE e.pet_id = ?
            ORDER BY e.date DESC, e.event_id DESC
            LIMIT ?
            """,
            (pet_id, args.limit),
        ).fetchall()

    if not args.group_by_episode:
        print_rows(rows)
        return

    # group
    groups = {}  # key -> list[Row]
    for r in rows:
        key = r["episode_id"]
        groups.setdefault(key, []).append(r)

    # order groups by latest date (rows already desc, so first item is latest)
    def group_sort_key(item):
        ep_id, items = item
        latest = items[0]["date"]
        # Unassigned (None) put last
        return (1 if ep_id is None else 0, latest)

    ordered = sorted(groups.items(), key=group_sort_key, reverse=True)

    for ep_id, items in ordered:
        if ep_id is None:
            header = "=== Unassigned (no episode) ==="
        else:
            ep_name = items[0]["episode_name"] or ""
            header = f"=== Episode [{ep_id}] {ep_name} ==="
        print(header)
        print_rows(items)
        print()


def _today_str() -> str:
    return str(date.today())

def _parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()

def cmd_check(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        today = date.today()

        # 1) Episodes overview
        episodes = conn.execute(
            """
            SELECT id, category, status, start_date, condition_name_zh
            FROM episodes
            WHERE pet_id = ?
            ORDER BY id ASC
            """,
            (pet_id,),
        ).fetchall()

        # 2) Latest event per episode
        latest_by_episode = {}
        for ep in episodes:
            row = conn.execute(
                """
                SELECT date, type, title
                FROM events
                WHERE episode_id = ?
                ORDER BY date DESC, event_id DESC
                LIMIT 1
                """,
                (ep["id"],),
            ).fetchone()
            latest_by_episode[ep["id"]] = row

        alerts = []

        # Rule A: cardiac follow-up
        for ep in episodes:
            if ep["category"] != "cardiac":
                continue
            last = latest_by_episode.get(ep["id"])
            if not last:
                alerts.append(("warn", f"心脏病程缺少事件：{ep['condition_name_zh']}", "建议补录首次确诊/复查记录"))
                continue
            last_date = _parse_ymd(last["date"])
            days = (today - last_date).days
            if days > args.cardiac_days:
                alerts.append((
                    "warn",
                    f"心脏复查可能逾期：{ep['condition_name_zh']}",
                    f"最后记录 {last['date']}（{days} 天前）。建议安排超声/复查或至少记录静息呼吸、运动耐受。"
                ))

        # 3) medications: active + ending soon
        meds = conn.execute(
            """
            SELECT id, drug_name, dose, unit, frequency, start_date, end_date, reason
            FROM medications
            WHERE pet_id = ?
            ORDER BY COALESCE(start_date, created_at) DESC, id DESC
            """,
            (pet_id,),
        ).fetchall()

        active_meds = []
        ending_soon = []
        for m in meds:
            sd = _parse_ymd(m["start_date"]) if m["start_date"] else None
            ed = _parse_ymd(m["end_date"]) if m["end_date"] else None

            is_active = False
            if sd and ed:
                is_active = (sd <= today <= ed)
            elif sd and not ed:
                is_active = (sd <= today)

            if is_active:
                active_meds.append(m)

            if ed:
                if 0 <= (ed - today).days <= args.med_end_days:
                    ending_soon.append(m)

        # Render output
        print("=== Health Check ===")
        print(f"Date: {today.isoformat()}")
        print()

        print("Episodes (latest):")
        if not episodes:
            print("(no episodes)")
        else:
            for ep in episodes:
                last = latest_by_episode.get(ep["id"])
                last_txt = "(no events)" if not last else f"{last['date']} {last['type']} {last['title']}"
                print(f"- [{ep['id']}] {ep['condition_name_zh']} ({ep['category'] or 'uncategorized'}, {ep['status']}) | last: {last_txt}")
        print()

        print("Active medications:")
        if not active_meds:
            print("(none)")
        else:
            for m in active_meds:
                print(f"- [{m['id']}] {m['drug_name']} {m['dose'] or ''}{m['unit'] or ''} {m['frequency'] or ''} ({m['start_date']} ~ {m['end_date'] or 'open'}) | {m['reason'] or ''}")
        print()

        print(f"Medications ending within {args.med_end_days} days:")
        if not ending_soon:
            print("(none)")
        else:
            for m in ending_soon:
                print(f"- [{m['id']}] {m['drug_name']} ends on {m['end_date']} | {m['reason'] or ''}")
        print()

        print("Alerts:")
        if not alerts:
            print("(none)")
        else:
            for level, title, detail in alerts:
                print(f"- [{level.upper()}] {title}\n  {detail}")

# ----- Report -----
import json

def _months_between(d1: date, d2: date) -> int:
    """Full months between d1 and d2, assuming d2 >= d1."""
    if d2 < d1:
        return 0
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        months -= 1
    return max(0, months)

def _years_months_days(birth: date, today: date):
    # Simple readable breakdown; accuracy good enough for report display
    days = (today - birth).days
    months = _months_between(birth, today)
    years = months // 12
    rem_months = months % 12
    return years, rem_months, days, months

def cmd_report(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        today = date.today()

        pet = conn.execute(
            """
            SELECT id, name, breed, birth_date, gender, castrated, allergies, chronic_conditions, created_at
            FROM mypet
            WHERE id = ?
            """,
            (pet_id,),
        ).fetchone()
        if not pet:
            raise SystemExit(f"❌ No pet found with id={pet_id}")

        # latest weight
        latest_weight = conn.execute(
            """
            SELECT id, date, value, unit, note
            FROM measurements
            WHERE pet_id = ? AND type = 'weight'
            ORDER BY date DESC, id DESC
            LIMIT 1
            """,
            (pet_id,),
        ).fetchone()

        # latest heart check (heuristic: standard_name_zh contains heart/MMVD/二尖瓣)
        latest_heart = conn.execute(
            """
            SELECT e.event_id, e.date, e.type, e.title, e.standard_name_zh, e.vet, e.episode_id,
                   ep.condition_name_zh AS episode_name
            FROM events e
            LEFT JOIN episodes ep ON ep.id = e.episode_id
            WHERE e.pet_id = ?
              AND (
                   (e.standard_name_zh LIKE '%二尖瓣%')
                OR (e.standard_name_zh LIKE '%心脏%')
                OR (e.standard_name_zh LIKE '%MMVD%')
                OR (e.title LIKE '%心脏%')
                OR (e.title LIKE '%二尖瓣%')
              )
            ORDER BY e.date DESC, e.event_id DESC
            LIMIT 1
            """,
            (pet_id,),
        ).fetchone()

        # meds
        meds = conn.execute(
            """
            SELECT id, drug_name, dose, unit, frequency, start_date, end_date, reason, note
            FROM medications
            WHERE pet_id = ?
            ORDER BY COALESCE(start_date, created_at) DESC, id DESC
            """,
            (pet_id,),
        ).fetchall()

        active_meds = []
        ending_soon = []
        for m in meds:
            sd = _parse_ymd(m["start_date"]) if m["start_date"] else None
            ed = _parse_ymd(m["end_date"]) if m["end_date"] else None

            is_active = False
            if sd and ed:
                is_active = (sd <= today <= ed)
            elif sd and not ed:
                is_active = (sd <= today)

            if is_active:
                active_meds.append(m)

            if ed:
                if 0 <= (ed - today).days <= args.med_end_days:
                    ending_soon.append(m)

        # last year important diagnoses (you can broaden to healthCheck if you want)
        one_year_ago = (today - timedelta(days=365)).isoformat()
        diag = conn.execute(
            """
            SELECT event_id, date, type, title, standard_name_zh, vet, episode_id
            FROM events
            WHERE pet_id = ?
              AND date >= ?
              AND type IN ('diagnosis', 'healthCheck')
            ORDER BY date DESC, event_id DESC
            """,
            (pet_id, one_year_ago),
        ).fetchall()

    # age calc
    age_obj = None
    if pet["birth_date"]:
        b = _parse_ymd(pet["birth_date"])
        years, rem_months, days, months = _years_months_days(b, today)
        age_obj = {
            "birth_date": pet["birth_date"],
            "today": today.isoformat(),
            "years": years,
            "months_total": months,
            "months": rem_months,
            "days": days,
        }

    def row_to_dict(r):
        return None if r is None else {k: r[k] for k in r.keys()}

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pet": {
            "id": pet["id"],
            "name": pet["name"],
            "breed": pet["breed"],
            "birth_date": pet["birth_date"],
            "gender": pet["gender"],
            "castrated": bool(pet["castrated"]),
            "created_at": pet["created_at"],
        },
        "age": age_obj,
        "conditions": {
            "allergies": pet["allergies"],
            "chronic_conditions": pet["chronic_conditions"],
        },
        "latest": {
            "weight": row_to_dict(latest_weight),
            "heart_check": row_to_dict(latest_heart),
        },
        "medications": {
            "active": [row_to_dict(m) for m in active_meds],
            "ending_soon": [row_to_dict(m) for m in ending_soon],
            "ending_soon_window_days": args.med_end_days,
        },
        "events_summary": {
            "last_year_important": [row_to_dict(e) for e in diag],
            "since": one_year_ago,
        },
    }

    if args.json:
        if args.pretty:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(report, ensure_ascii=False))
    else:
        # human readable fallback
        print("=== Report ===")
        print(f"generated_at: {report['generated_at']}")
        print(f"pet: {pet['name']} (id={pet['id']})")
        if age_obj:
            print(f"age: {age_obj['years']}y {age_obj['months']}m (total {age_obj['months_total']} months)")
        if latest_weight:
            print(f"current_weight: {latest_weight['value']} {latest_weight['unit']} @ {latest_weight['date']}")
        else:
            print("current_weight: N/A")
        if latest_heart:
            print(f"latest_heart_check: {latest_heart['date']} {latest_heart['title']} [{latest_heart['standard_name_zh'] or ''}]")
        print(f"active_meds: {len(active_meds)}")
        print(f"ending_soon({args.med_end_days}d): {len(ending_soon)}")
        print(f"events(last_year): {len(diag)}")



# ----- MyPet -----

def cmd_pet_show(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = args.pet_id or get_pet_id(conn)

        pet = conn.execute(
            """
            SELECT id, name, breed, birth_date, gender, castrated, allergies, chronic_conditions, created_at
            FROM mypet
            WHERE id = ?
            """,
            (pet_id,),
        ).fetchone()

        if not pet:
            raise SystemExit(f"❌ No pet found with id={pet_id}")

        w = conn.execute(
            """
            SELECT date, value, unit, note
            FROM measurements
            WHERE pet_id = ? AND type = 'weight'
            ORDER BY date DESC, id DESC
            LIMIT 1
            """,
            (pet_id,),
        ).fetchone()

    print(f"Pet #{pet['id']}: {pet['name']}")
    print(f"Breed: {pet['breed'] or ''}")
    print(f"Birth date: {pet['birth_date'] or ''}")
    print(f"Gender: {pet['gender']}")
    print(f"Castrated: {'yes' if pet['castrated'] == 1 else 'no'}")
    print(f"Allergies: {pet['allergies'] or ''}")
    print(f"Chronic conditions: {pet['chronic_conditions'] or ''}")
    print()

    if w:
        print(f"Current weight: {w['value']} {w['unit']} (measured {w['date']})")
        if w["note"]:
            print(f"  note: {w['note']}")
    else:
        print("Current weight: N/A (no weight measurement yet)")

def cmd_pet_edit(args):
    allowed = ["name", "breed", "birth_date", "gender", "castrated", "allergies", "chronic_conditions"]
    args_dict = {
        "name": args.name,
        "breed": args.breed,
        "birth_date": args.birth_date,
        "gender": args.gender,
        "castrated": args.castrated,
        "allergies": args.allergies,
        "chronic_conditions": args.chronic_conditions,
    }

    with connect(args.db) as conn:
        migrate(conn)
        pet_id = args.pet_id or get_pet_id(conn)

        row = conn.execute("SELECT id FROM mypet WHERE id=?", (pet_id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No pet found with id={pet_id}")

        sql, params, changed = build_update_sql("mypet", "id", allowed, args_dict, pet_id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            """
            SELECT id, name, breed, birth_date, gender, castrated, allergies, chronic_conditions
            FROM mypet WHERE id=?
            """,
            (pet_id,),
        ).fetchone()

    print(f"✅ pet updated (id={pet_id}) fields: {', '.join(changed)}")
    print_rows([updated])

# ----- Events -----
def cmd_event_list(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        rows = conn.execute(
            """
            SELECT event_id, date, type, title, standard_name_zh, vet
            FROM events
            WHERE pet_id = ?
            ORDER BY date DESC, event_id DESC
            """,
            (pet_id,),
        ).fetchall()
    print_rows(rows)


def cmd_event_add(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)

         # validate episode_id if provided
        if args.episode_id is not None:
            ep = conn.execute("SELECT id FROM episodes WHERE id=?", (args.episode_id,)).fetchone()
            if not ep:
                raise SystemExit(f"❌ No episode found with id={args.episode_id}")


        conn.execute(
            """
            INSERT INTO events (
                pet_id, date, type, vet, title, note, attachment_path,
                standard_name_zh, standard_name_en, episode_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pet_id, args.date, args.type, args.vet, args.title, args.note,
                args.attachment_path, args.standard_name_zh, args.standard_name_en,
                args.episode_id
            ),
        )
        conn.commit()
    print("✅ event added")


def cmd_event_edit(args):
    allowed = ["date", "type", "vet", "title", "note", "attachment_path",
               "standard_name_zh", "standard_name_en", "episode_id"]
    args_dict = {
        "date": args.date,
        "type": args.type,
        "vet": args.vet,
        "title": args.title,
        "note": args.note,
        "attachment_path": args.attachment_path,
        "standard_name_zh": args.standard_name_zh,
        "standard_name_en": args.standard_name_en,
        "episode_id": args.episode_id,
    }

    with connect(args.db) as conn:
        migrate(conn)
        row = conn.execute("SELECT event_id FROM events WHERE event_id=?", (args.id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No event found with event_id={args.id}")

         # if episode_id provided, validate it exists
        if args.episode_id is not None:
            ep = conn.execute("SELECT id FROM episodes WHERE id=?", (args.episode_id,)).fetchone()
            if not ep:
                raise SystemExit(f"❌ No episode found with id={args.episode_id}")
            
        sql, params, changed = build_update_sql("events", "event_id", allowed, args_dict, args.id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            "SELECT event_id, date, type, title, standard_name_zh, vet, note FROM events WHERE event_id=?",
            (args.id,),
        ).fetchone()

    print(f"✅ event updated (event_id={args.id}) fields: {', '.join(changed)}")
    print_rows([updated])



# ----- Measurement -----

def cmd_measure_add(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)

        unit = args.unit
        if unit is None:
            unit = "kg" if args.type == "weight" else "cm"

        conn.execute(
            """
            INSERT INTO measurements (pet_id, date, type, value, unit, note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pet_id, args.date, args.type, args.value, unit, args.note),
        )
        conn.commit()
    print("✅ measurement added")

def cmd_measure_list(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)

        where = ["pet_id = ?"]
        params = [pet_id]

        if args.type:
            where.append("type = ?")
            params.append(args.type)
        if args.date_from:
            where.append("date >= ?")
            params.append(args.date_from)
        if args.date_to:
            where.append("date <= ?")
            params.append(args.date_to)

        sql = f"""
            SELECT id, date, type, value, unit, note
            FROM measurements
            WHERE {" AND ".join(where)}
            ORDER BY date DESC, id DESC
            LIMIT ?
        """
        params.append(args.limit)

        rows = conn.execute(sql, params).fetchall()

    print_rows(rows)


def cmd_measure_edit(args):
    allowed = ["date", "type", "value", "unit", "note"]
    args_dict = {
        "date": args.date,
        "type": args.type,
        "value": args.value,
        "unit": args.unit,
        "note": args.note,
    }

    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)

        row = conn.execute(
            "SELECT id FROM measurements WHERE id=? AND pet_id=?",
            (args.id, pet_id),
        ).fetchone()
        if not row:
            raise SystemExit(f"❌ No measurement found with id={args.id} (pet_id={pet_id})")

        sql, params, changed = build_update_sql("measurements", "id", allowed, args_dict, args.id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            "SELECT id, date, type, value, unit, note FROM measurements WHERE id=?",
            (args.id,),
        ).fetchone()

    print(f"✅ measurement updated (id={args.id}) fields: {', '.join(changed)}")
    print_rows([updated])



# ----- Medications -----
def cmd_med_list(args):
    with connect(args.db) as conn:
        pet_id = get_pet_id(conn)
        rows = conn.execute(
            """
            SELECT id, start_date, end_date, drug_name, dose, unit, frequency, reason
            FROM medications
            WHERE pet_id = ?
            ORDER BY COALESCE(start_date, created_at) DESC, id DESC
            """,
            (pet_id,),
        ).fetchall()
    print_rows(rows)


def cmd_med_add(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        conn.execute(
            """
            INSERT INTO medications (pet_id, drug_name, dose, unit, frequency, start_date, end_date, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pet_id, args.drug_name, args.dose, args.unit, args.frequency, args.start_date, args.end_date, args.reason, args.note),
        )
        conn.commit()
    print("✅ medication added")


def cmd_med_edit(args):
    allowed = ["drug_name", "dose", "unit", "frequency", "start_date", "end_date", "reason", "note"]
    args_dict = {
        "drug_name": args.drug_name,
        "dose": args.dose,
        "unit": args.unit,
        "frequency": args.frequency,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "reason": args.reason,
        "note": args.note,
    }

    with connect(args.db) as conn:
        migrate(conn)
        row = conn.execute("SELECT id FROM medications WHERE id=?", (args.id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No medication found with id={args.id}")

        sql, params, changed = build_update_sql("medications", "id", allowed, args_dict, args.id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            """
            SELECT id, start_date, end_date, drug_name, dose, unit, frequency, reason, note
            FROM medications
            WHERE id=?
            """,
            (args.id,),
        ).fetchone()

    print(f"✅ medication updated (id={args.id}) fields: {', '.join(changed)}")
    print_rows([updated])

# ----- Reminders -----
def cmd_reminder_list(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        if args.all:
            rows = conn.execute(
                "SELECT id, due_date, status, title, note FROM reminders WHERE pet_id=? ORDER BY due_date ASC, id ASC",
                (pet_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, due_date, status, title, note FROM reminders WHERE pet_id=? AND status='pending' ORDER BY due_date ASC, id ASC",
                (pet_id,),
            ).fetchall()
    print_rows(rows)

def cmd_reminder_add(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        conn.execute(
            """
            INSERT INTO reminders (pet_id, due_date, title, note, status, repeat_rule)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (pet_id, args.due_date, args.title, args.note, args.status, args.repeat_rule),
        )
        conn.commit()
    print("✅ reminder added")


def cmd_reminder_edit(args):
    allowed = ["due_date", "title", "note", "status", "repeat_rule"]
    args_dict = {
        "due_date": args.due_date,
        "title": args.title,
        "note": args.note,
        "status": args.status,
        "repeat_rule": args.repeat_rule,
    }

    with connect(args.db) as conn:
        migrate(conn)
        row = conn.execute("SELECT id FROM reminders WHERE id=?", (args.id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No reminder found with id={args.id}")

        sql, params, changed = build_update_sql("reminders", "id", allowed, args_dict, args.id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            "SELECT id, due_date, status, title, note, repeat_rule FROM reminders WHERE id=?",
            (args.id,),
        ).fetchone()

    print(f"✅ reminder updated (id={args.id}) fields: {', '.join(changed)}")
    print_rows([updated])


def cmd_reminder_done(args):
    with connect(args.db) as conn:
        migrate(conn)
        row = conn.execute("SELECT id FROM reminders WHERE id=?", (args.id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No reminder found with id={args.id}")

        conn.execute("UPDATE reminders SET status='done' WHERE id=?", (args.id,))
        conn.commit()

        updated = conn.execute(
            "SELECT id, due_date, status, title, note FROM reminders WHERE id=?",
            (args.id,),
        ).fetchone()

    print(f"✅ reminder marked done (id={args.id})")
    print_rows([updated])

# -------- Episodes --------

def cmd_episode_add(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        conn.execute(
            """
            INSERT INTO episodes (pet_id, condition_name_zh, condition_name_en, category, status, start_date, end_date, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pet_id, args.condition_name_zh, args.condition_name_en, args.category, args.status, args.start_date, args.end_date, args.note),
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    print(f"✅ episode added (id={new_id})")

def cmd_episode_edit(args):
    allowed = [
        "condition_name_zh",
        "condition_name_en",
        "category",
        "status",
        "start_date",
        "end_date",
        "note",
    ]

    args_dict = {
        "condition_name_zh": args.condition_name_zh,
        "condition_name_en": args.condition_name_en,
        "category": args.category,
        "status": args.status,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "note": args.note,
    }

    with connect(args.db) as conn:
        migrate(conn)

        # 检查 episode 是否存在
        row = conn.execute("SELECT id FROM episodes WHERE id=?", (args.id,)).fetchone()
        if not row:
            raise SystemExit(f"❌ No episode found with id={args.id}")

        # 构建 UPDATE SQL（复用你已有的 helper）
        sql, params, changed = build_update_sql("episodes", "id", allowed, args_dict, args.id)
        conn.execute(sql, params)
        conn.commit()

        updated = conn.execute(
            """
            SELECT id, condition_name_zh, condition_name_en,
                   category, status, start_date, end_date, note
            FROM episodes
            WHERE id=?
            """,
            (args.id,),
        ).fetchone()

    print(f"✅ episode updated (id={args.id}) fields: {', '.join(changed)}")
    print_rows([updated])


def cmd_episode_list(args):
    with connect(args.db) as conn:
        migrate(conn)
        pet_id = get_pet_id(conn)
        rows = conn.execute(
            """
            SELECT id, status, category, start_date, end_date, condition_name_zh, condition_name_en, note
            FROM episodes
            WHERE pet_id = ?
            ORDER BY COALESCE(start_date, created_at) DESC, id DESC
            """,
            (pet_id,),
        ).fetchall()
    print_rows(rows)


def cmd_event_link(args):
    with connect(args.db) as conn:
        migrate(conn)

        # check existence
        ev = conn.execute("SELECT event_id FROM events WHERE event_id=?", (args.event_id,)).fetchone()
        if not ev:
            raise SystemExit(f"❌ No event found with event_id={args.event_id}")

        ep = conn.execute("SELECT id FROM episodes WHERE id=?", (args.episode_id,)).fetchone()
        if not ep:
            raise SystemExit(f"❌ No episode found with id={args.episode_id}")

        conn.execute("UPDATE events SET episode_id=? WHERE event_id=?", (args.episode_id, args.event_id))
        conn.commit()

        row = conn.execute(
            "SELECT event_id, date, type, title, episode_id FROM events WHERE event_id=?",
            (args.event_id,),
        ).fetchone()

    print("✅ event linked to episode")
    print_rows([row])




# -------- Parser --------

def build_parser():
    p = argparse.ArgumentParser(prog="cooper", description="CooperHealth CLI (single schema source, supports episodes).")
    p.add_argument("--db", default="mypet.db", help="SQLite db path (default: mypet.db)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="Run safe migration (no data loss).")
    sp.set_defaults(func=cmd_init)

    # timeline
    sp = sub.add_parser("timeline", help="Show recent events (includes event_id and episode_id).")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--group-by-episode", action="store_true", help="Group timeline output by episode")
    sp.set_defaults(func=cmd_timeline)

    # check
    sp = sub.add_parser("check", help="Run rule-based checks (no AI).")
    sp.add_argument("--cardiac-days", dest="cardiac_days", type=int, default=180, help="Cardiac follow-up threshold in days (default: 180)")
    sp.add_argument("--med-end-days", dest="med_end_days", type=int, default=3, help="Medication ending soon window (default: 3)")
    sp.set_defaults(func=cmd_check)


    # report
    sp = sub.add_parser("report", help="Generate a structured health report (JSON) for Phase 2/3.")
    sp.add_argument("--json", action="store_true", help="Output JSON")
    sp.add_argument("--pretty", action="store_true", help="Pretty-print JSON (with --json)")
    sp.add_argument("--med-end-days", dest="med_end_days", type=int, default=3, help="Medication ending soon window (default: 3)") #默认窗口期3天，可改
    sp.set_defaults(func=cmd_report)


    # pets
    sp = sub.add_parser("pet-show", help="Show pet profile (includes current weight from latest measurement).")
    sp.add_argument("--pet-id", dest="pet_id", type=int)
    sp.set_defaults(func=cmd_pet_show)

    sp = sub.add_parser("pet-edit", help="Edit pet profile fields.")
    sp.add_argument("--pet-id", dest="pet_id", type=int)
    sp.add_argument("--name")
    sp.add_argument("--breed")
    sp.add_argument("--birth-date", dest="birth_date", help="YYYY-MM-DD")
    sp.add_argument("--gender", choices=["male", "female", "unknown"])
    sp.add_argument("--castrated", type=int, choices=[0, 1], help="0 or 1")
    sp.add_argument("--allergies")
    sp.add_argument("--chronic-conditions", dest="chronic_conditions")
    sp.set_defaults(func=cmd_pet_edit)


    # episodes
    sp = sub.add_parser("episode-add", help="Create an episode (disease course).")
    sp.add_argument("--condition-name-zh", dest="condition_name_zh", required=True)
    sp.add_argument("--condition-name-en", dest="condition_name_en")
    sp.add_argument("--category", choices=["cardiac", "respiratory", "ortho", "neuro", "skin", "other"])
    sp.add_argument("--status", default="active", choices=["active", "resolved", "monitoring"])
    sp.add_argument("--start-date", dest="start_date", help="YYYY-MM-DD")
    sp.add_argument("--end-date", dest="end_date", help="YYYY-MM-DD")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_episode_add)

    sp = sub.add_parser("episode-edit", help="Edit an episode by id.")
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--condition-name-zh", dest="condition_name_zh")
    sp.add_argument("--condition-name-en", dest="condition_name_en")
    sp.add_argument("--category", choices=["cardiac", "respiratory", "ortho", "neuro", "skin", "other"])
    sp.add_argument("--status", choices=["active", "monitoring", "resolved"])
    sp.add_argument("--start-date", dest="start_date", help="YYYY-MM-DD")
    sp.add_argument("--end-date", dest="end_date", help="YYYY-MM-DD")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_episode_edit)

    sp = sub.add_parser("episode-list", help="List episodes (with id).")
    sp.set_defaults(func=cmd_episode_list)

    sp = sub.add_parser("event-link", help="Link an event to an episode.")
    sp.add_argument("--event-id", dest="event_id", type=int, required=True)
    sp.add_argument("--episode-id", dest="episode_id", type=int, required=True)
    sp.set_defaults(func=cmd_event_link)

    # events
    sp = sub.add_parser("event-list", help="List all events with event_id.")
    sp.set_defaults(func=cmd_event_list)

    sp = sub.add_parser("event-add", help="Add an event (optionally attach episode_id).")
    sp.add_argument("--date", default=str(date.today()), help="YYYY-MM-DD (default: today)")
    sp.add_argument("--type", required=True, choices=["healthCheck", "vaccine", "diagnosis", "symptoms", "surgery", "treatment"])
    sp.add_argument("--vet")
    sp.add_argument("--title", required=True)
    sp.add_argument("--note")
    sp.add_argument("--attachment-path", dest="attachment_path")
    sp.add_argument("--standard-name-zh", dest="standard_name_zh")
    sp.add_argument("--standard-name-en", dest="standard_name_en")
    sp.add_argument("--episode-id", dest="episode_id", type=int)
    sp.set_defaults(func=cmd_event_add)

    sp = sub.add_parser("event-edit", help="Edit an event by event_id.")
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--date", help="YYYY-MM-DD")
    sp.add_argument("--type", choices=["healthCheck", "vaccine", "diagnosis", "symptoms", "surgery", "treatment"])
    sp.add_argument("--vet")
    sp.add_argument("--title")
    sp.add_argument("--note")
    sp.add_argument("--attachment-path", dest="attachment_path")
    sp.add_argument("--standard-name-zh", dest="standard_name_zh")
    sp.add_argument("--standard-name-en", dest="standard_name_en")
    sp.add_argument("--episode-id", dest="episode_id", type=int)
    sp.set_defaults(func=cmd_event_edit)

    # measurements
    sp = sub.add_parser("measure-add", help="Add a measurement (weight/neck/chest/waist).")
    sp.add_argument("--date", default=str(date.today()), help="YYYY-MM-DD (default: today)")
    sp.add_argument("--type", required=True, choices=["weight", "neck", "chest", "waist"])
    sp.add_argument("--value", type=float, required=True)
    sp.add_argument("--unit", choices=["kg", "cm", "inch"])  # 可选：不填就自动默认
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_measure_add)

    sp = sub.add_parser("measure-list", help="List measurements (filterable).")
    sp.add_argument("--type", choices=["weight", "neck", "chest", "waist"])
    sp.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    sp.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    sp.add_argument("--limit", type=int, default=50)
    sp.set_defaults(func=cmd_measure_list)

    sp = sub.add_parser("measure-edit", help="Edit a measurement by id.")
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--date", help="YYYY-MM-DD")
    sp.add_argument("--type", choices=["weight", "neck", "chest", "waist"])
    sp.add_argument("--value", type=float)
    sp.add_argument("--unit", choices=["kg", "cm", "inch"])
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_measure_edit)




    # meds
    sp = sub.add_parser("med-list", help="List medications with id.")
    sp.set_defaults(func=cmd_med_list)

    sp = sub.add_parser("med-add", help="Add a medication.")
    sp.add_argument("--drug-name", dest="drug_name", required=True)
    sp.add_argument("--dose", type=float)
    sp.add_argument("--unit")
    sp.add_argument("--frequency")
    sp.add_argument("--start-date", dest="start_date", help="YYYY-MM-DD")
    sp.add_argument("--end-date", dest="end_date", help="YYYY-MM-DD")
    sp.add_argument("--reason")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_med_add)

    sp = sub.add_parser("med-edit", help="Edit a medication by id.")
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--drug-name", dest="drug_name")
    sp.add_argument("--dose", type=float)
    sp.add_argument("--unit")
    sp.add_argument("--frequency")
    sp.add_argument("--start-date", dest="start_date", help="YYYY-MM-DD")
    sp.add_argument("--end-date", dest="end_date", help="YYYY-MM-DD")
    sp.add_argument("--reason")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_med_edit)

    # reminders
    sp = sub.add_parser("reminder-list", help="List reminders (pending by default).")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_reminder_list)

    sp = sub.add_parser("reminder-add", help="Add a reminder.")
    sp.add_argument("--due-date", dest="due_date", required=True, help="YYYY-MM-DD")
    sp.add_argument("--title", required=True)
    sp.add_argument("--note")
    sp.add_argument("--status", default="pending", choices=["pending", "done"])
    sp.add_argument("--repeat-rule", dest="repeat_rule")
    sp.set_defaults(func=cmd_reminder_add)

    sp = sub.add_parser("reminder-edit", help="Edit a reminder by id.")
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--due-date", dest="due_date", help="YYYY-MM-DD")
    sp.add_argument("--title")
    sp.add_argument("--note")
    sp.add_argument("--status", choices=["pending", "done"])
    sp.add_argument("--repeat-rule", dest="repeat_rule")
    sp.set_defaults(func=cmd_reminder_edit)

    sp = sub.add_parser("reminder-done", help="Mark a reminder done by id.")
    sp.add_argument("--id", type=int, required=True)
    sp.set_defaults(func=cmd_reminder_done)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
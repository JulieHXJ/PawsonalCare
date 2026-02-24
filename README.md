# Pawsonal Care 🐾

**Cooper’s Private Health Control System**

It is a health management system designed as a long-term private health control system for my lovely Shiba, Cooper.

---

# PHASE 0 — Concept & Design Principles

### Principle A — Event-First Model

All medical facts must first be recorded as structured data:

* `Event`
* `Measurement`
* `Medication`

---

### Principle B — Structured + Raw Text Coexist

* `title` / `note` preserve original medical records
* `standard_name_zh` / tags provide structured classification

---

# PHASE 1 — Foundational Health Archive System


Build a extensible SQLite-based health database + CLI management tool that produces a stable **Facts Layer JSON** for future rule engines.

---

## 1️⃣ Database Schema (SQLite)

### 🐶 `mypet` — Basic Pet Profile

* id
* name
* breed
* birth_date
* gender
* castrated
* allergies (free text)
* chronic_conditions (free text)

---

### 🏥 `events` — Medical Events

* date
* type :healthCheck / diagnosis / vaccine / symptoms / surgery / treatment
* title
* standard_name_zh / standard_name_en
* vet
* note
* attachment_path
* episode_id (nullable)

---

### 🧩 `episodes` — Disease Courses

* condition_name_zh / en
* category (cardiac / respiratory / ortho / neuro / skin / other)
* status (active / monitoring / resolved)
* start_date
* end_date
* note

---

### 💊 `medications`

* drug_name
* dose
* unit
* frequency
* start_date
* end_date
* reason
* note

---

### 📏 `measurements`

* date
* type: weight / neck / chest / waist
* value
* unit
* note
---

### 🔔 `reminders`

* due_date
* title
* note
* status (pending / done)
* reason

---

### 📎 attachments (TODO)

Future standalone table:

* event_id
* file_path
* mime_type
* created_at

---

### 🏷 event_tags (TODO)

* event_id
* tag (cough / mmvd / vaccination / etc.)

---

# 2️⃣ Facts Layer (JSON Report)

The system generates a structured JSON report:

```bash
python3 cooper_cli.py --db mypet.db report --json --pretty
```

This JSON becomes the single data input for future risk systems.

---

### Current JSON Includes:

#### Pet Info

* Basic profile
* Age (years / months / days)
* Total months (`months_total`)

#### Conditions

* Allergies
* Chronic conditions

#### Latest Data

* Latest weight (value/unit/date)
* Latest heart check event

#### Medications

* Active medications
* Ending soon (configurable window)

#### Events Summary

* Important events in last 12 months
* diagnosis + healthCheck

#### Reminders (if present)

* Pending
* Overdue


---

# 3️⃣ CLI Command Set

### Pets

* `pet-show`
* `pet-edit`

### Events

* `event-add`
* `event-edit`
* `event-list`

### Episodes

* `episode-add`
* `episode-list`
* `episode-edit`

### Link

* `event-link`

### Medications

* `med-add`
* `med-edit`
* `med-list`

### Measurements

* `measure-add`
* `measure-edit`
* `measure-list`

### Reminders

* `reminder-add`
* `reminder-edit`
* `reminder-done`
* `reminder-list`

### Timeline

* `timeline --limit N`
* `timeline --group-by-episode`

### Report

* `report`
* `report --json`
* `report --json --pretty`

---

# 🚀 Usage

Initialize database:

```bash
python3 cooper_cli.py --db mypet.db init
```

View timeline:

```bash
python3 cooper_cli.py --db mypet.db timeline --limit 50
```

Run any command:

```bash
python3 cooper_cli.py --db mypet.db <command> [options...]
```

---

## Example Commands

Add an event:

```bash
python3 cooper_cli.py --db mypet.db event-add \
  --date 2026-02-23 \
  --type healthCheck \
  --vet "AniCura, Heilbronn" \
  --title "Cardiac follow-up" \
  --standard-name-zh "MMVD B1"
```

Add a measurement:

```bash
python3 cooper_cli.py --db mypet.db measure-add \
  --date 2026-02-23 \
  --type weight \
  --value 11.5 \
  --unit kg
```

Add medication:

```bash
python3 cooper_cli.py --db mypet.db med-add \
  --drug-name "Metacam" \
  --dose 1.1 \
  --unit mg \
  --frequency "per day" \
  --start-date 2025-11-20 \
  --end-date 2025-11-30
```

Link event to episode:

```bash
python3 cooper_cli.py --db mypet.db event-link --event-id 4 --episode-id 3
```

---

# PHASE 2 — Rule-Based Risk System (on going)

### 1️⃣ Breed Risk Database

Example:

* Shiba Inu:

  * patellar luxation
  * hip dysplasia
  * allergies
  * glaucoma

---

### 2️⃣ Age Stage Model

* 0–1
* 2–6
* 7–9
* 10+

---

### 3️⃣ Base Risk Formula

```
risk = breed_factor + age_factor + disease_factor
```

---

# PHASE 3 — Personalized Adjustment Model

Adds contextual modifiers:

* Weight trend impact
* Medication influence
* Exercise changes
* Historical disease weighting

---

# PHASE 4 — Lightweight Knowledge Graph

Dictionary tables:

* conditions
* symptoms
* tests
* treatments

---

# PHASE 5 — AI Augmentation (Future)

* RAG
* Vector database
* Literature retrieval
* Personalized health insights

It turns affection into data,
and data into long-term health awareness.

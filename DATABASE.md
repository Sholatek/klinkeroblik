# KlinkerOblik — Схема Бази Даних

## Діаграма зв'язків

```
Director (1) ──── (N) Brigade
                       │
                       ├── (N) BrigadeMember (worker_id + role: brigadier|worker)
                       │         │
                       │       Worker
                       │         │
                       │   WorkEntry (N)
                       │         │
                       │   WorkEntryItem (N)
                       │
Director ──── (N) Project (1) ──── (N) Building
                    │                    │
                    │              (N) Element
                    │
              ProjectRate
```

## Таблиці

### directors (Керівники фірм)
```sql
CREATE TABLE directors (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT UNIQUE NOT NULL,
    name            VARCHAR(255) NOT NULL,
    phone           VARCHAR(50),
    email           VARCHAR(255),
    company_name    VARCHAR(255),
    language        VARCHAR(5) DEFAULT 'uk',      -- 'uk' | 'pl' | 'ru'
    currency        VARCHAR(3) DEFAULT 'PLN',     -- 'PLN' | 'EUR' | 'UAH'
    timezone        VARCHAR(50) DEFAULT 'Europe/Warsaw',
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### brigades (Бригади)
```sql
CREATE TABLE brigades (
    id              SERIAL PRIMARY KEY,
    director_id     INTEGER NOT NULL REFERENCES directors(id),
    name            VARCHAR(255) NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);
```

### workers (Всі користувачі — і бригадири, і працівники)
```sql
CREATE TABLE workers (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT UNIQUE NOT NULL,
    director_id     INTEGER NOT NULL REFERENCES directors(id),
    name            VARCHAR(255) NOT NULL,
    phone           VARCHAR(50),
    email           VARCHAR(255),
    language        VARCHAR(5) DEFAULT 'uk',      -- 'uk' | 'pl' | 'ru'
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);
```

### brigade_members (Прив'язка працівників до бригад з роллю)
```sql
CREATE TABLE brigade_members (
    id              SERIAL PRIMARY KEY,
    brigade_id      INTEGER NOT NULL REFERENCES brigades(id),
    worker_id       INTEGER NOT NULL REFERENCES workers(id),
    role            VARCHAR(20) NOT NULL DEFAULT 'worker',  -- 'brigadier' | 'worker'
    joined_at       TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    UNIQUE(brigade_id, worker_id)
);
-- Один працівник = одна бригада (активна). Бригадирів може бути кілька на бригаду.
```

### invite_codes (Коди запрошення)
```sql
CREATE TABLE invite_codes (
    id              SERIAL PRIMARY KEY,
    code            VARCHAR(20) UNIQUE NOT NULL,       -- 'KL-A7X9'
    director_id     INTEGER NOT NULL REFERENCES directors(id),
    brigade_id      INTEGER NOT NULL REFERENCES brigades(id),
    role            VARCHAR(20) NOT NULL DEFAULT 'worker',  -- 'brigadier' | 'worker'
    created_by_type VARCHAR(20) NOT NULL,              -- 'director' | 'brigadier'
    created_by_id   INTEGER NOT NULL,                  -- director.id або worker.id
    used_by         INTEGER REFERENCES workers(id),
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### projects (Об'єкти)
```sql
CREATE TABLE projects (
    id              SERIAL PRIMARY KEY,
    director_id     INTEGER NOT NULL REFERENCES directors(id),
    name            VARCHAR(255) NOT NULL,
    address         TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE,
    is_archived     BOOLEAN DEFAULT FALSE
);
-- Об'єкти створює ТІЛЬКИ директор або бригадир.
-- Працівники обирають зі списку.
-- Єдиний список на всю фірму — запобігає дублюванню назв.
```

### buildings (Доми)
```sql
CREATE TABLE buildings (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    name            VARCHAR(255) NOT NULL,        -- "Dom 1", "Dom 2"
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);
```

### elements (Елементи: стіни, партери, балкони тощо)
```sql
CREATE TABLE elements (
    id              SERIAL PRIMARY KEY,
    building_id     INTEGER NOT NULL REFERENCES buildings(id),
    name            VARCHAR(255) NOT NULL,        -- "Ściana 1", "Parter", "Taras"
    element_type    VARCHAR(50),                  -- 'wall' | 'parter' | 'terrace' | 'balcony' | 'ceiling' | 'other'
    created_at      TIMESTAMP DEFAULT NOW(),
    is_active       BOOLEAN DEFAULT TRUE
);
```

### work_types (Типи робіт)
```sql
CREATE TABLE work_types (
    id              SERIAL PRIMARY KEY,
    director_id     INTEGER NOT NULL REFERENCES directors(id),
    name_uk         VARCHAR(255) NOT NULL,        -- "Укладання плитки"
    name_pl         VARCHAR(255) NOT NULL,        -- "Układanie płytek"
    name_ru         VARCHAR(255) NOT NULL,        -- "Укладка плитки"
    unit            VARCHAR(10) NOT NULL,          -- 'm2' | 'mp' | 'h'
    default_rate    DECIMAL(10,2) NOT NULL,        -- 60.00
    sort_order      INTEGER DEFAULT 0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### project_rates (Ставки для конкретного об'єкта)
```sql
CREATE TABLE project_rates (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    work_type_id    INTEGER NOT NULL REFERENCES work_types(id),
    rate            DECIMAL(10,2) NOT NULL,
    UNIQUE(project_id, work_type_id)
);
```

### work_entries (Записи робіт)
```sql
CREATE TABLE work_entries (
    id              SERIAL PRIMARY KEY,
    worker_id       INTEGER NOT NULL REFERENCES workers(id),
    element_id      INTEGER NOT NULL REFERENCES elements(id),
    work_date       DATE NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),
    is_confirmed    BOOLEAN DEFAULT FALSE
);
```

### work_entry_items (Деталі запису — об'єми по типах робіт)
```sql
CREATE TABLE work_entry_items (
    id              SERIAL PRIMARY KEY,
    entry_id        INTEGER NOT NULL REFERENCES work_entries(id) ON DELETE CASCADE,
    work_type_id    INTEGER NOT NULL REFERENCES work_types(id),
    quantity        DECIMAL(10,2) NOT NULL,        -- 12.5 (м²), 8 (мп), 3 (год)
    rate_applied    DECIMAL(10,2) NOT NULL,        -- Ставка на момент запису
    total           DECIMAL(10,2) NOT NULL,        -- quantity × rate_applied
    UNIQUE(entry_id, work_type_id)
);
```

## Індекси для швидких звітів

```sql
-- Швидкий пошук записів по працівнику і даті
CREATE INDEX idx_work_entries_worker_date ON work_entries(worker_id, work_date);

-- Швидкий пошук по елементу (для звітів по стінах)
CREATE INDEX idx_work_entries_element ON work_entries(element_id);

-- Швидкий пошук по даті (для звітів за період)
CREATE INDEX idx_work_entries_date ON work_entries(work_date);

-- Зв'язок елементів з будівлями
CREATE INDEX idx_elements_building ON elements(building_id);

-- Зв'язок будівель з об'єктами
CREATE INDEX idx_buildings_project ON buildings(project_id);
```

## Типи робіт за замовчуванням (seed data)

```sql
INSERT INTO work_types (director_id, name_uk, name_pl, name_ru, unit, default_rate, sort_order) VALUES
(1, 'Укладання плитки', 'Układanie płytek', 'Укладка плитки', 'm2', 60.00, 1),
(1, 'Погонні роботи', 'Prace liniowe', 'Погонные работы', 'mp', 30.00, 2),
(1, 'Підрізка під 45°', 'Cięcie pod kątem 45°', 'Подрезка под 45°', 'mp', 0.00, 3),
(1, 'Прорізка делатацій', 'Cięcie dylatacji', 'Прорезка делатаций', 'mp', 0.00, 4),
(1, 'Погодинна робота', 'Praca godzinowa', 'Почасовая работа', 'h', 0.00, 5),
(1, 'Фугування', 'Fugowanie', 'Фуговка', 'm2', 0.00, 6),
(1, 'Силікон', 'Silikon', 'Силикон', 'mp', 0.00, 7);
```

## Приклад запиту — звіт по бригаді за тиждень

```sql
SELECT
    br.name AS brigade_name,
    w.name AS worker_name,
    bm.role AS worker_role,
    p.name AS project_name,
    bld.name AS building_name,
    e.name AS element_name,
    wt.name_uk AS work_type,
    wt.unit,
    SUM(wei.quantity) AS total_quantity,
    SUM(wei.total) AS total_earned
FROM work_entry_items wei
JOIN work_entries we ON we.id = wei.entry_id
JOIN workers w ON w.id = we.worker_id
JOIN brigade_members bm ON bm.worker_id = w.id AND bm.is_active = TRUE
JOIN brigades br ON br.id = bm.brigade_id
JOIN elements e ON e.id = we.element_id
JOIN buildings bld ON bld.id = e.building_id
JOIN projects p ON p.id = bld.project_id
JOIN work_types wt ON wt.id = wei.work_type_id
WHERE we.work_date BETWEEN '2026-03-18' AND '2026-03-22'
  AND br.director_id = 1
GROUP BY br.name, w.name, bm.role, p.name, bld.name, e.name, wt.name_uk, wt.unit
ORDER BY br.name, w.name, p.name, bld.name, e.name;
```

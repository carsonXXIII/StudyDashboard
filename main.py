import gc
import json
import network
import socket
import time
from machine import Pin

from secrets import WIFI_PASSWORD, WIFI_SSID


# ---------- Hardware setup ----------

led = Pin("LED", Pin.OUT)


# ---------- Timer state ----------

MODE_FOCUS = "focus"
MODE_BREAK = "break"
STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"

timer = {
    "mode": MODE_FOCUS,
    "state": STATE_IDLE,
    "task": "Study",
    "focus_minutes": 25,
    "break_minutes": 5,
    "remaining": 25 * 60,
    "last_tick": time.time(),
    "sessions": 0,
    "message": "Ready",
    "focus_lock": False,
    "focus_warnings": 0,
    "last_warning": "",
}


def duration_for_mode(mode):
    if mode == MODE_BREAK:
        return int(timer["break_minutes"]) * 60
    return int(timer["focus_minutes"]) * 60


def set_mode(mode):
    timer["mode"] = mode
    timer["remaining"] = duration_for_mode(mode)
    timer["last_tick"] = time.time()


def start_timer():
    timer["state"] = STATE_RUNNING
    timer["last_tick"] = time.time()
    timer["message"] = "Focus started" if timer["mode"] == MODE_FOCUS else "Break started"


def pause_timer():
    if timer["state"] == STATE_RUNNING:
        update_timer()
        timer["state"] = STATE_PAUSED
        timer["message"] = "Paused"


def reset_timer():
    timer["state"] = STATE_IDLE
    timer["remaining"] = duration_for_mode(timer["mode"])
    timer["last_tick"] = time.time()
    timer["message"] = "Reset"


def skip_mode():
    if timer["mode"] == MODE_FOCUS:
        timer["sessions"] += 1
        set_mode(MODE_BREAK)
        timer["message"] = "Break time"
    else:
        set_mode(MODE_FOCUS)
        timer["message"] = "Ready to focus"
    timer["state"] = STATE_IDLE


def update_timer():
    if timer["state"] != STATE_RUNNING:
        return

    now = time.time()
    elapsed = int(now - timer["last_tick"])
    if elapsed <= 0:
        return

    timer["last_tick"] = now
    timer["remaining"] = max(0, int(timer["remaining"]) - elapsed)

    if timer["remaining"] == 0:
        if timer["mode"] == MODE_FOCUS:
            timer["sessions"] += 1
            set_mode(MODE_BREAK)
            timer["message"] = "Focus done"
        else:
            set_mode(MODE_FOCUS)
            timer["message"] = "Break done"
        timer["state"] = STATE_IDLE


def format_time(seconds):
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    secs = seconds % 60
    return "{:02d}:{:02d}".format(minutes, secs)


def timer_status():
    update_timer()
    total = max(1, duration_for_mode(timer["mode"]))
    done = total - int(timer["remaining"])
    return {
        "mode": timer["mode"],
        "state": timer["state"],
        "task": timer["task"],
        "focus_minutes": timer["focus_minutes"],
        "break_minutes": timer["break_minutes"],
        "remaining": timer["remaining"],
        "time": format_time(timer["remaining"]),
        "sessions": timer["sessions"],
        "message": timer["message"],
        "progress": min(100, max(0, int((done / total) * 100))),
        "focus_lock": bool(timer["focus_lock"]),
        "focus_warnings": int(timer["focus_warnings"]),
        "last_warning": timer["last_warning"],
    }


def set_focus_lock(enabled):
    timer["focus_lock"] = bool(enabled)
    timer["message"] = "Focus Lock on" if timer["focus_lock"] else "Focus Lock off"
    if not timer["focus_lock"]:
        timer["last_warning"] = ""


def record_focus_warning(reason):
    if not timer["focus_lock"]:
        return
    if timer["state"] != STATE_RUNNING:
        return
    if timer["mode"] != MODE_FOCUS:
        return
    timer["focus_warnings"] = int(timer["focus_warnings"]) + 1
    timer["last_warning"] = reason or "You left the focus screen"
    timer["message"] = "Focus warning"


def update_outputs(ip=None):
    status = timer_status()
    led.value(1 if status["state"] == STATE_RUNNING else 0)


# ---------- Courses and flashcards ----------

CARDS_FILE = "cards.json"

DEFAULT_CARDS = [
    {
        "question": "What is active recall?",
        "answer": "Testing yourself from memory instead of just re-reading.",
        "correct": 0,
        "wrong": 0,
        "box": 1,
    },
    {
        "question": "What is spaced repetition?",
        "answer": "Reviewing material at increasing intervals so it sticks longer.",
        "correct": 0,
        "wrong": 0,
        "box": 1,
    },
    {
        "question": "What should a good flashcard ask?",
        "answer": "One clear thing. Split big ideas into smaller cards.",
        "correct": 0,
        "wrong": 0,
        "box": 1,
    },
]

courses = []
flash = {"course": 0, "deck": 0, "index": 0, "show_answer": False, "message": "Ready"}


def clean_card(item):
    if not isinstance(item, dict):
        return None
    question = str(item.get("question", "")).strip()[:120]
    answer = str(item.get("answer", "")).strip()[:240]
    if not question or not answer:
        return None
    return {
        "question": question,
        "answer": answer,
        "correct": int(item.get("correct", 0)),
        "wrong": int(item.get("wrong", 0)),
        "box": max(1, min(5, int(item.get("box", 1)))),
    }


def clean_deck(item, fallback_name="Main Deck"):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name", fallback_name)).strip()[:32] or fallback_name
    raw_cards = item.get("cards", [])
    card_list = []
    if isinstance(raw_cards, list):
        for raw_card in raw_cards:
            card = clean_card(raw_card)
            if card:
                card_list.append(card)
    return {"name": name, "cards": card_list}


def clean_course(item, fallback_name="Study Basics"):
    if not isinstance(item, dict):
        return None
    name = str(item.get("name", fallback_name)).strip()[:32] or fallback_name
    deck_list = []
    raw_decks = item.get("decks", None)
    if isinstance(raw_decks, list):
        for index, raw_deck in enumerate(raw_decks):
            deck = clean_deck(raw_deck, "Deck " + str(index + 1))
            if deck:
                deck_list.append(deck)
    elif isinstance(item.get("cards", []), list):
        deck = clean_deck({"name": "Main Deck", "cards": item.get("cards", [])}, "Main Deck")
        if deck:
            deck_list.append(deck)
    if not deck_list:
        deck_list.append({"name": "Chapter 1", "cards": []})
    return {"name": name, "decks": deck_list}


def default_courses():
    return [
        {
            "name": "Study Basics",
            "decks": [{"name": "Main Deck", "cards": [clean_card(card) for card in DEFAULT_CARDS]}],
        }
    ]


def ensure_courses_no_save():
    global courses
    if not courses:
        courses = default_courses()
    flash["course"] = min(max(0, int(flash.get("course", 0))), len(courses) - 1)
    if "decks" not in courses[flash["course"]] or not courses[flash["course"]]["decks"]:
        courses[flash["course"]]["decks"] = [{"name": "Chapter 1", "cards": []}]
    flash["deck"] = min(max(0, int(flash.get("deck", 0))), len(courses[flash["course"]]["decks"]) - 1)


def ensure_courses():
    ensure_courses_no_save()
    deck = deck_cards()
    if deck:
        flash["index"] = min(max(0, int(flash.get("index", 0))), len(deck) - 1)
    else:
        flash["index"] = 0


def save_cards():
    ensure_courses()
    try:
        with open(CARDS_FILE, "w") as file:
            json.dump(
                {
                    "active_course": flash["course"],
                    "active_deck": flash["deck"],
                    "courses": courses,
                },
                file,
            )
    except Exception as exc:
        print("Could not save cards:", exc)


def load_cards():
    global courses
    try:
        with open(CARDS_FILE, "r") as file:
            loaded = json.load(file)
        if isinstance(loaded, dict) and isinstance(loaded.get("courses"), list):
            courses = []
            for index, item in enumerate(loaded.get("courses", [])):
                course = clean_course(item, "Course " + str(index + 1))
                if course:
                    courses.append(course)
            flash["course"] = int(loaded.get("active_course", loaded.get("active", 0)))
            flash["deck"] = int(loaded.get("active_deck", 0))
        elif isinstance(loaded, list) and len(loaded) > 0:
            migrated_cards = []
            for raw_card in loaded:
                card = clean_card(raw_card)
                if card:
                    migrated_cards.append(card)
            courses = [{"name": "Imported Deck", "decks": [{"name": "Main Deck", "cards": migrated_cards}]}]
            flash["course"] = 0
            flash["deck"] = 0
        else:
            courses = default_courses()
    except Exception:
        courses = default_courses()
    ensure_courses()
    save_cards()


def active_course():
    ensure_courses_no_save()
    return courses[flash["course"]]


def active_deck():
    ensure_courses_no_save()
    return courses[flash["course"]]["decks"][flash["deck"]]


def deck_cards():
    return active_deck()["cards"]


def course_summary():
    ensure_courses()
    summary = []
    for index, course in enumerate(courses):
        total_cards = 0
        for deck in course.get("decks", []):
            total_cards += len(deck.get("cards", []))
        summary.append(
            {
                "id": index,
                "name": course.get("name", "Course " + str(index + 1)),
                "count": total_cards,
                "deck_count": len(course.get("decks", [])),
                "active": index == flash["course"],
            }
        )
    return summary


def deck_summary():
    ensure_courses()
    summary = []
    for index, deck in enumerate(active_course().get("decks", [])):
        summary.append(
            {
                "id": index,
                "name": deck.get("name", "Deck " + str(index + 1)),
                "count": len(deck.get("cards", [])),
                "active": index == flash["deck"],
            }
        )
    return summary


def add_course(name):
    name = (name or "").strip()[:32]
    if not name:
        flash["message"] = "Course name needed"
        return
    courses.append({"name": name, "decks": [{"name": "Chapter 1", "cards": []}]})
    flash["course"] = len(courses) - 1
    flash["deck"] = 0
    flash["index"] = 0
    flash["show_answer"] = False
    flash["message"] = "Course added"
    save_cards()


def select_course(index):
    ensure_courses()
    flash["course"] = min(max(0, int(index)), len(courses) - 1)
    flash["deck"] = 0
    flash["index"] = 0
    flash["show_answer"] = False
    flash["message"] = "Course selected"
    save_cards()


def add_deck(name):
    name = (name or "").strip()[:32]
    if not name:
        flash["message"] = "Deck name needed"
        return
    active_course()["decks"].append({"name": name, "cards": []})
    flash["deck"] = len(active_course()["decks"]) - 1
    flash["index"] = 0
    flash["show_answer"] = False
    flash["message"] = "Deck added"
    save_cards()


def select_deck(index):
    ensure_courses()
    flash["deck"] = min(max(0, int(index)), len(active_course()["decks"]) - 1)
    flash["index"] = 0
    flash["show_answer"] = False
    flash["message"] = "Deck selected"
    save_cards()


def current_card():
    deck = deck_cards()
    if not deck:
        return None
    flash["index"] = min(max(0, int(flash["index"])), len(deck) - 1)
    return deck[flash["index"]]


def flashcard_status():
    ensure_courses()
    deck = deck_cards()
    course = active_course()
    selected_deck = active_deck()
    card = current_card()
    base = {
        "courses": course_summary(),
        "decks": deck_summary(),
        "course_index": flash["course"],
        "deck_index": flash["deck"],
        "course_name": course.get("name", "Course"),
        "deck_name": selected_deck.get("name", "Deck"),
        "course_count": len(courses),
        "deck_count": len(course.get("decks", [])),
        "count": len(deck),
        "message": flash["message"],
    }
    if not card:
        base.update(
            {
                "index": 0,
                "question": "No cards in this deck yet",
                "answer": "",
                "show_answer": False,
                "correct": 0,
                "wrong": 0,
                "box": 1,
            }
        )
        return base
    base.update(
        {
            "index": flash["index"] + 1,
            "question": card.get("question", ""),
            "answer": card.get("answer", "") if flash["show_answer"] else "",
            "show_answer": flash["show_answer"],
            "correct": int(card.get("correct", 0)),
            "wrong": int(card.get("wrong", 0)),
            "box": int(card.get("box", 1)),
        }
    )
    return base


def next_card():
    deck = deck_cards()
    if deck:
        flash["index"] = (flash["index"] + 1) % len(deck)
    flash["show_answer"] = False
    flash["message"] = "Next card"


def previous_card():
    deck = deck_cards()
    if deck:
        flash["index"] = (flash["index"] - 1) % len(deck)
    flash["show_answer"] = False
    flash["message"] = "Previous card"


def mark_card(result):
    card = current_card()
    if not card:
        flash["message"] = "No card to mark"
        return
    if result == "correct":
        card["correct"] = int(card.get("correct", 0)) + 1
        card["box"] = min(5, int(card.get("box", 1)) + 1)
        flash["message"] = "Marked correct"
    else:
        card["wrong"] = int(card.get("wrong", 0)) + 1
        card["box"] = max(1, int(card.get("box", 1)) - 1)
        flash["message"] = "Marked again"
    save_cards()
    next_card()


def add_card(question, answer):
    card = clean_card({"question": question, "answer": answer, "correct": 0, "wrong": 0, "box": 1})
    if not card:
        flash["message"] = "Question and answer needed"
        return
    deck = deck_cards()
    deck.append(card)
    flash["index"] = len(deck) - 1
    flash["show_answer"] = False
    flash["message"] = "Card added"
    save_cards()


def import_cards(imported_cards, replace=False):
    clean_cards = []
    for item in imported_cards:
        card = clean_card(item)
        if card:
            clean_cards.append(card)
    if not clean_cards:
        flash["message"] = "No valid cards found"
        return 0
    deck = deck_cards()
    if replace:
        active_deck()["cards"] = clean_cards
        flash["index"] = 0
    else:
        start_index = len(deck)
        deck.extend(clean_cards)
        flash["index"] = start_index
    flash["show_answer"] = False
    flash["message"] = "Imported " + str(len(clean_cards)) + " cards"
    save_cards()
    return len(clean_cards)


def delete_card():
    deck = deck_cards()
    if not deck:
        flash["message"] = "No card to delete"
        return
    deck.pop(flash["index"])
    flash["index"] = min(flash["index"], max(0, len(deck) - 1))
    flash["show_answer"] = False
    flash["message"] = "Card deleted"
    save_cards()


# ---------- Web UI ----------

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pico Study Dashboard + Flashcards</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #fff7f5;
      --surface: #fffdfb;
      --surface-2: #f8e7e2;
      --text: #2d1714;
      --muted: #80645f;
      --primary: #a72f26;
      --primary-2: #f8d7d0;
      --warm: #6f1d17;
      --warm-2: #ffe9e3;
      --border: #e4c4bd;
      --shadow: 0 12px 32px rgba(111, 29, 23, 0.12);
      --radius: 20px;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #180d0c;
        --surface: #241311;
        --surface-2: #321b18;
        --text: #f7e8e4;
        --muted: #c49b92;
        --primary: #ff8a78;
        --primary-2: #3a1714;
        --warm: #ffb09f;
        --warm-2: #2b1412;
        --border: #54302a;
        --shadow: 0 12px 32px rgba(0, 0, 0, 0.32);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, var(--primary-2), transparent 34rem),
        linear-gradient(135deg, color-mix(in srgb, var(--bg), var(--primary-2) 18%), var(--bg));
      color: var(--text);
      line-height: 1.5;
    }
    main {
      width: min(920px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 20px;
    }
    h1 {
      font-size: clamp(1.6rem, 5vw, 2.2rem);
      line-height: 1.05;
      margin: 0 0 8px;
      letter-spacing: -0.04em;
    }
    p { margin: 0; color: var(--muted); }
    .badge {
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--muted);
      background: color-mix(in srgb, var(--surface), transparent 8%);
      white-space: nowrap;
      font-size: 0.9rem;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 16px;
    }
    .stack {
      display: grid;
      gap: 16px;
      margin-top: 16px;
    }
    .card {
      background: color-mix(in srgb, var(--surface), transparent 4%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 20px;
    }
    .timer {
      min-height: 360px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .task-label {
      color: var(--muted);
      font-size: 0.95rem;
      margin-bottom: 8px;
    }
    .task {
      font-size: 1.15rem;
      font-weight: 700;
      margin-bottom: 18px;
    }
    .time {
      font-size: clamp(4rem, 18vw, 8rem);
      line-height: 0.9;
      letter-spacing: -0.08em;
      font-variant-numeric: tabular-nums;
      font-weight: 800;
    }
    .meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .pill {
      background: var(--surface-2);
      border: 1px solid var(--border);
      padding: 8px 10px;
      border-radius: 999px;
      color: var(--muted);
      font-size: 0.92rem;
    }
    .progress {
      height: 12px;
      background: var(--surface-2);
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--border);
      margin-top: 20px;
    }
    .bar {
      height: 100%;
      width: 0%;
      background: var(--primary);
      transition: width 200ms ease;
    }
    .controls {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-top: 20px;
    }
    button, input {
      min-height: 46px;
      border-radius: 14px;
      border: 1px solid var(--border);
      font: inherit;
    }
    button {
      cursor: pointer;
      background: var(--surface-2);
      color: var(--text);
      font-weight: 700;
    }
    button.primary {
      background: var(--primary);
      color: #fff7f5;
      border-color: transparent;
    }
    button.warm {
      background: var(--warm);
      color: #fff7f5;
      border-color: transparent;
    }
    form {
      display: grid;
      gap: 12px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.92rem;
    }
    input {
      width: 100%;
      background: var(--bg);
      color: var(--text);
      padding: 0 12px;
    }
    .side {
      display: grid;
      gap: 16px;
    }
    .stat {
      display: flex;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      padding: 10px 0;
      color: var(--muted);
    }
    .stat strong { color: var(--text); }
    .warning {
      display: none;
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid color-mix(in srgb, var(--warm), transparent 45%);
      background: var(--warm-2);
      color: var(--text);
      font-weight: 700;
    }
    .warning.active { display: block; }
    .toggle-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-top: 14px;
      padding: 12px;
      border-radius: 14px;
      background: var(--surface-2);
    }
    .flashcard {
      display: grid;
      gap: 16px;
    }
    .card-face {
      min-height: 180px;
      display: grid;
      align-content: center;
      gap: 16px;
      padding: 22px;
      border-radius: 18px;
      background: linear-gradient(135deg, var(--warm-2), var(--surface));
      border: 1px solid var(--border);
    }
    .card-face h2 {
      margin: 0;
      font-size: clamp(1.2rem, 4vw, 1.7rem);
      line-height: 1.2;
      letter-spacing: -0.03em;
    }
    .answer {
      color: var(--text);
      font-size: 1.05rem;
      border-top: 1px solid var(--border);
      padding-top: 14px;
      min-height: 42px;
    }
    .flash-controls {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 10px;
    }
    .add-card {
      display: grid;
      grid-template-columns: 1fr 1fr auto;
      gap: 10px;
      align-items: end;
    }
    .import-box {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 16px;
      background: var(--surface-2);
      border: 1px dashed var(--border);
    }
    .import-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .course-panel {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 16px;
      background: var(--surface-2);
      border: 1px solid var(--border);
    }
    .course-list, .deck-list {
      display: grid;
      gap: 8px;
    }
    .course-button, .deck-button {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      width: 100%;
      min-height: 42px;
      padding: 10px 12px;
      text-align: left;
      background: var(--surface);
    }
    .course-button.active, .deck-button.active {
      border-color: var(--primary);
      box-shadow: inset 0 0 0 1px var(--primary);
    }
    .course-button small, .deck-button small {
      color: var(--muted);
      white-space: nowrap;
    }
    .course-form, .deck-form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: end;
    }
    @media (max-width: 720px) {
      header, .grid { display: block; }
      .badge { display: inline-block; margin: 14px 0; }
      .side { margin-top: 16px; }
      .controls, .flash-controls, .add-card, .course-form, .deck-form { grid-template-columns: 1fr; }
      .import-actions { display: grid; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Pico Study Dashboard</h1>
        <p>A tiny focus timer and flashcard app served from your Raspberry Pi Pico 2 W.</p>
      </div>
      <div class="badge" id="connection">Connecting...</div>
    </header>

    <section class="grid" aria-label="Study dashboard">
      <article class="card timer">
        <div>
          <div class="task-label">Current task</div>
          <div class="task" id="task">Study</div>
          <div class="time" id="time">25:00</div>
          <div class="meta">
            <span class="pill" id="mode">focus</span>
            <span class="pill" id="state">idle</span>
            <span class="pill" id="message">Ready</span>
          </div>
          <div class="progress" aria-label="Timer progress">
            <div class="bar" id="bar"></div>
          </div>
          <div class="warning" id="focusWarning">Focus Lock warning: you clicked away during focus time.</div>
        </div>
        <div class="controls">
          <button class="primary" onclick="send('/start')">Start</button>
          <button onclick="send('/pause')">Pause</button>
          <button onclick="send('/reset')">Reset</button>
          <button onclick="send('/skip')">Skip mode</button>
        </div>
      </article>

      <aside class="side">
        <section class="card">
          <h2 style="margin-top:0;font-size:1.1rem">Settings</h2>
          <form onsubmit="saveSettings(event)">
            <label>Task name
              <input id="taskInput" name="task" maxlength="32" value="Study">
            </label>
            <label>Focus minutes
              <input id="focusInput" name="focus" type="number" min="1" max="120" value="25">
            </label>
            <label>Break minutes
              <input id="breakInput" name="break" type="number" min="1" max="60" value="5">
            </label>
            <button class="primary" type="submit">Save settings</button>
          </form>
        </section>

        <section class="card">
          <h2 style="margin-top:0;font-size:1.1rem">Today</h2>
          <div class="stat"><span>Completed focus blocks</span><strong id="sessions">0</strong></div>
          <div class="stat"><span>Mode</span><strong id="modeStat">focus</strong></div>
          <div class="stat"><span>Status</span><strong id="stateStat">idle</strong></div>
          <div class="stat"><span>Focus warnings</span><strong id="focusWarnings">0</strong></div>
          <div class="toggle-row">
            <span>
              <strong>Focus Lock</strong><br>
              <small>Warn when this tab loses focus during a focus block.</small>
            </span>
            <button id="focusLockButton" onclick="toggleFocusLock()">Off</button>
          </div>
        </section>
      </aside>
    </section>

    <section class="stack" aria-label="Flashcards">
      <article class="card flashcard">
        <div>
          <p class="task-label">Flashcard review</p>
          <div class="course-panel">
            <div>
              <strong>Courses</strong>
              <p id="courseSummary">Choose a course first.</p>
            </div>
            <div class="course-list" id="courseList"></div>
            <form class="course-form" onsubmit="addCourse(event)">
              <label>New course
                <input id="newCourse" maxlength="32" placeholder="Arabic, Psychology, Python...">
              </label>
              <button class="primary" type="submit">Add course</button>
            </form>
            <div>
              <strong>Decks / chapters</strong>
              <p id="deckSummary">Choose a deck inside the selected course.</p>
            </div>
            <div class="deck-list" id="deckList"></div>
            <form class="deck-form" onsubmit="addDeck(event)">
              <label>New deck
                <input id="newDeck" maxlength="32" placeholder="Chapter 1, Chapter 2...">
              </label>
              <button class="primary" type="submit">Add deck</button>
            </form>
          </div>
          <div class="card-face">
            <div class="meta">
              <span class="pill" id="cardCount">Card 1 / 1</span>
              <span class="pill" id="courseName">Study Basics</span>
              <span class="pill" id="deckName">Main Deck</span>
              <span class="pill" id="cardBox">Box 1</span>
              <span class="pill" id="cardMessage">Ready</span>
            </div>
            <h2 id="question">Loading card...</h2>
            <div class="answer" id="answer">Press Show answer when you are ready.</div>
          </div>
        </div>
        <div class="flash-controls">
          <button onclick="cardSend('/card/prev')">Previous</button>
          <button class="primary" onclick="cardSend('/card/show')">Show answer</button>
          <button class="warm" onclick="cardSend('/card/mark?result=wrong')">Again</button>
          <button class="primary" onclick="cardSend('/card/mark?result=correct')">Correct</button>
          <button onclick="cardSend('/card/next')">Next</button>
        </div>
        <form class="add-card" onsubmit="addCard(event)">
          <label>Question
            <input id="newQuestion" maxlength="120" placeholder="Example: What is encoding?">
          </label>
          <label>Answer
            <input id="newAnswer" maxlength="240" placeholder="Turning info into memory.">
          </label>
          <button class="primary" type="submit">Add card</button>
        </form>
        <div class="import-box">
          <div>
            <strong>Import Anki export</strong>
            <p>In Anki, export notes as plain text. Then upload the .txt or .csv file here.</p>
          </div>
          <label>Anki text or CSV file
            <input id="ankiFile" type="file" accept=".txt,.csv,text/plain,text/csv">
          </label>
          <div class="import-actions">
            <button class="primary" onclick="importAnki(false)">Add imported cards</button>
            <button onclick="importAnki(true)">Replace deck</button>
          </div>
          <p id="importStatus">Supports tab, comma, or semicolon separated question/answer rows.</p>
        </div>
        <button onclick="cardSend('/card/delete')">Delete current card</button>
      </article>
    </section>
  </main>

  <script>
    async function send(path) {
      document.getElementById('connection').textContent = 'Sending...';
      await fetch(path);
      await refresh();
    }

    async function saveSettings(event) {
      event.preventDefault();
      const task = encodeURIComponent(document.getElementById('taskInput').value || 'Study');
      const focus = encodeURIComponent(document.getElementById('focusInput').value || '25');
      const brk = encodeURIComponent(document.getElementById('breakInput').value || '5');
      await send(`/settings?task=${task}&focus=${focus}&break=${brk}`);
    }

    async function refresh() {
      try {
        const res = await fetch('/status');
        const s = await res.json();
        document.getElementById('connection').textContent = 'Live from Pico';
        document.getElementById('task').textContent = s.task;
        document.getElementById('taskInput').value = s.task;
        document.getElementById('focusInput').value = s.focus_minutes;
        document.getElementById('breakInput').value = s.break_minutes;
        document.getElementById('time').textContent = s.time;
        document.getElementById('mode').textContent = s.mode;
        document.getElementById('state').textContent = s.state;
        document.getElementById('message').textContent = s.message;
        document.getElementById('sessions').textContent = s.sessions;
        document.getElementById('modeStat').textContent = s.mode;
        document.getElementById('stateStat').textContent = s.state;
        document.getElementById('focusWarnings').textContent = s.focus_warnings;
        document.getElementById('focusLockButton').textContent = s.focus_lock ? 'On' : 'Off';
        document.getElementById('bar').style.width = s.progress + '%';
        const warning = document.getElementById('focusWarning');
        warning.textContent = s.last_warning ? `Focus Lock warning: ${s.last_warning}` : 'Focus Lock warning: you clicked away during focus time.';
        warning.classList.toggle('active', Boolean(s.last_warning));
      } catch (err) {
        document.getElementById('connection').textContent = 'Reconnecting...';
      }
    }

    async function toggleFocusLock() {
      const button = document.getElementById('focusLockButton');
      const next = button.textContent.trim() !== 'On';
      await send(`/focus-lock?enabled=${next ? '1' : '0'}`);
    }

    let warningInFlight = false;
    async function reportFocusWarning(reason) {
      if (warningInFlight) return;
      warningInFlight = true;
      try {
        await fetch(`/focus-warning?reason=${encodeURIComponent(reason)}`);
        await refresh();
      } catch (err) {
      } finally {
        setTimeout(() => { warningInFlight = false; }, 1500);
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        reportFocusWarning('Tab was hidden');
      }
    });

    window.addEventListener('blur', () => {
      reportFocusWarning('Window lost focus');
    });

    async function refreshCards() {
      try {
        const res = await fetch('/cards');
        const c = await res.json();
        document.getElementById('cardCount').textContent = `Card ${c.index} / ${c.count}`;
        document.getElementById('courseName').textContent = c.course_name;
        document.getElementById('deckName').textContent = c.deck_name;
        document.getElementById('cardBox').textContent = `Box ${c.box}`;
        document.getElementById('cardMessage').textContent = c.message;
        document.getElementById('question').textContent = c.question;
        document.getElementById('answer').textContent = c.show_answer ? c.answer : 'Press Show answer when you are ready.';
        document.getElementById('courseSummary').textContent = `${c.course_count} course(s). Selected: ${c.course_name}.`;
        document.getElementById('deckSummary').textContent = `${c.deck_count} deck(s) in ${c.course_name}. Selected: ${c.deck_name}.`;
        renderCourses(c.courses || []);
        renderDecks(c.decks || []);
      } catch (err) {
        document.getElementById('cardMessage').textContent = 'Reconnecting...';
      }
    }

    function renderCourses(courses) {
      const list = document.getElementById('courseList');
      list.innerHTML = '';
      if (!courses.length) {
        list.innerHTML = '<p>No courses yet. Add one below.</p>';
        return;
      }
      for (const course of courses) {
        const button = document.createElement('button');
        button.className = `course-button${course.active ? ' active' : ''}`;
        button.type = 'button';
        button.innerHTML = `<span>${course.name}</span><small>${course.deck_count} decks · ${course.count} cards</small>`;
        button.onclick = () => selectCourse(course.id);
        list.appendChild(button);
      }
    }

    function renderDecks(decks) {
      const list = document.getElementById('deckList');
      list.innerHTML = '';
      if (!decks.length) {
        list.innerHTML = '<p>No decks yet. Add Chapter 1 below.</p>';
        return;
      }
      for (const deck of decks) {
        const button = document.createElement('button');
        button.className = `deck-button${deck.active ? ' active' : ''}`;
        button.type = 'button';
        button.innerHTML = `<span>${deck.name}</span><small>${deck.count} cards</small>`;
        button.onclick = () => selectDeck(deck.id);
        list.appendChild(button);
      }
    }

    async function selectCourse(id) {
      await cardSend(`/course/select?id=${encodeURIComponent(id)}`);
    }

    async function selectDeck(id) {
      await cardSend(`/deck/select?id=${encodeURIComponent(id)}`);
    }

    async function addCourse(event) {
      event.preventDefault();
      const input = document.getElementById('newCourse');
      const name = encodeURIComponent(input.value || '');
      await cardSend(`/course/add?name=${name}`);
      input.value = '';
    }

    async function addDeck(event) {
      event.preventDefault();
      const input = document.getElementById('newDeck');
      const name = encodeURIComponent(input.value || '');
      await cardSend(`/deck/add?name=${name}`);
      input.value = '';
    }

    async function cardSend(path) {
      await fetch(path);
      await refreshCards();
    }

    async function addCard(event) {
      event.preventDefault();
      const q = encodeURIComponent(document.getElementById('newQuestion').value);
      const a = encodeURIComponent(document.getElementById('newAnswer').value);
      await cardSend(`/card/add?q=${q}&a=${a}`);
      document.getElementById('newQuestion').value = '';
      document.getElementById('newAnswer').value = '';
    }

    function splitRow(line) {
      const separators = ['\t', ',', ';'];
      let best = null;
      for (const sep of separators) {
        const parts = line.split(sep);
        if (parts.length >= 2 && (!best || parts.length > best.parts.length)) {
          best = { sep, parts };
        }
      }
      if (!best) return null;
      return [
        best.parts[0].trim(),
        best.parts.slice(1).join(best.sep).trim()
      ];
    }

    function cleanAnkiText(text) {
      return text
        .replace(/<br\\s*\\/?>/gi, '\\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .trim();
    }

    function parseAnkiExport(text) {
      const cards = [];
      const lines = text.split(/\\r?\\n/);
      for (const raw of lines) {
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;
        const row = splitRow(line);
        if (!row) continue;
        const question = cleanAnkiText(row[0]).slice(0, 120);
        const answer = cleanAnkiText(row[1]).slice(0, 240);
        if (question && answer) cards.push({ question, answer });
        if (cards.length >= 60) break;
      }
      return cards;
    }

    async function postJson(path, payload) {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      return await res.json();
    }

    async function importAnki(replace) {
      const input = document.getElementById('ankiFile');
      const status = document.getElementById('importStatus');
      if (!input.files || !input.files[0]) {
        status.textContent = 'Choose an Anki export file first.';
        return;
      }
      const text = await input.files[0].text();
      const parsed = parseAnkiExport(text);
      if (!parsed.length) {
        status.textContent = 'No question/answer rows found. Try exporting notes as tab-separated text.';
        return;
      }
      status.textContent = `Uploading ${parsed.length} cards...`;
      const result = await postJson('/card/import', { replace, cards: parsed });
      status.textContent = result.message || `Imported ${parsed.length} cards.`;
      await refreshCards();
    }

    refresh();
    refreshCards();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""


def url_decode(value):
    value = value.replace("+", " ")
    output = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%" and index + 2 < len(value):
            try:
                output.append(int(value[index + 1 : index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        output.append(ord(char))
        index += 1
    try:
        return output.decode("utf-8")
    except Exception:
        return value


def parse_query(path):
    if "?" not in path:
        return path, {}
    route, query = path.split("?", 1)
    values = {}
    for pair in query.split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            values[url_decode(key)] = url_decode(value)
    return route, values


def clamp_int(value, default, minimum, maximum):
    try:
        number = int(value)
        return min(max(number, minimum), maximum)
    except Exception:
        return default


def response(conn, status="200 OK", content_type="text/plain", body=""):
    if isinstance(body, str):
        body = body.encode("utf-8")
    conn.send("HTTP/1.1 {}\r\n".format(status))
    conn.send("Content-Type: {}\r\n".format(content_type))
    conn.send("Content-Length: {}\r\n".format(len(body)))
    conn.send("Connection: close\r\n\r\n")
    conn.sendall(body)


def handle_request(path, method="GET", body=""):
    route, params = parse_query(path)

    if route == "/":
        return "text/html", HTML
    if route == "/status":
        return "application/json", json.dumps(timer_status())
    if route == "/cards":
        return "application/json", json.dumps(flashcard_status())
    if route == "/start":
        start_timer()
    elif route == "/pause":
        pause_timer()
    elif route == "/reset":
        reset_timer()
    elif route == "/skip":
        skip_mode()
    elif route == "/settings":
        timer["task"] = params.get("task", timer["task"])[:32] or "Study"
        timer["focus_minutes"] = clamp_int(params.get("focus"), timer["focus_minutes"], 1, 120)
        timer["break_minutes"] = clamp_int(params.get("break"), timer["break_minutes"], 1, 60)
        if timer["state"] != STATE_RUNNING:
            timer["remaining"] = duration_for_mode(timer["mode"])
        timer["message"] = "Settings saved"
    elif route == "/focus-lock":
        set_focus_lock(params.get("enabled", "0") in ("1", "true", "on"))
    elif route == "/focus-warning":
        record_focus_warning(params.get("reason", "You left the focus screen")[:80])
    elif route == "/card/show":
        flash["show_answer"] = True
        flash["message"] = "Answer shown"
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/next":
        next_card()
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/prev":
        previous_card()
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/mark":
        mark_card(params.get("result", "wrong"))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/add":
        add_card(params.get("q", ""), params.get("a", ""))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/delete":
        delete_card()
        return "application/json", json.dumps(flashcard_status())
    elif route == "/course/add":
        add_course(params.get("name", ""))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/course/select":
        select_course(clamp_int(params.get("id"), flash["course"], 0, max(0, len(courses) - 1)))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/deck/add":
        add_deck(params.get("name", ""))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/deck/select":
        select_deck(clamp_int(params.get("id"), flash["deck"], 0, max(0, len(active_course().get("decks", [])) - 1)))
        return "application/json", json.dumps(flashcard_status())
    elif route == "/card/import" and method == "POST":
        try:
            payload = json.loads(body or "{}")
            count = import_cards(payload.get("cards", []), bool(payload.get("replace", False)))
            status = flashcard_status()
            status["imported"] = count
            return "application/json", json.dumps(status)
        except Exception as exc:
            print("Import error:", exc)
            return "application/json", json.dumps({"message": "Import failed", "imported": 0})
    else:
        return "text/plain", "Not found"

    return "application/json", json.dumps(timer_status())


# ---------- Wi-Fi and server ----------

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to Wi-Fi:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(30):
            if wlan.isconnected():
                break
            led.toggle()
            time.sleep(0.5)
    led.off()
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("Connected. IP:", ip)
        return wlan, ip
    raise RuntimeError("Wi-Fi connection failed. Check secrets.py")


def run_server(ip):
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(1)
    server.settimeout(0.5)
    print("Open http://{}/".format(ip))

    update_outputs(ip)

    while True:
        update_outputs(ip)
        try:
            conn, remote = server.accept()
        except OSError:
            gc.collect()
            continue

        try:
            request_bytes = conn.recv(4096)
            header_bytes = request_bytes
            body_bytes = b""
            if b"\r\n\r\n" in request_bytes:
                header_bytes, body_bytes = request_bytes.split(b"\r\n\r\n", 1)

            headers = header_bytes.decode("utf-8")
            first_line = headers.split("\r\n")[0]
            parts = first_line.split(" ")
            method = parts[0] if len(parts) > 0 else "GET"
            path = parts[1] if len(parts) > 1 else "/"

            content_length = 0
            for line in headers.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    try:
                        content_length = int(line.split(":", 1)[1].strip())
                    except Exception:
                        content_length = 0

            while len(body_bytes) < content_length:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                body_bytes += chunk

            body_text = body_bytes.decode("utf-8") if body_bytes else ""
            content_type, response_body = handle_request(path, method, body_text)
            response(conn, content_type=content_type, body=response_body)
        except Exception as exc:
            print("Request error:", exc)
            try:
                response(conn, status="500 Internal Server Error", body="Server error")
            except Exception:
                pass
        finally:
            conn.close()
            gc.collect()


def main():
    load_cards()
    try:
        wlan, ip = connect_wifi()
        run_server(ip)
    except Exception as exc:
        print(exc)
        while True:
            led.toggle()
            time.sleep(0.5)


main()

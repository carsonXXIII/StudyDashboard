# Pico Study Dashboard + Courses + Decks + Flashcards

A tiny study dashboard for the Raspberry Pi Pico 2 W. The Pico connects to your Wi-Fi, serves a local web page, runs a Pomodoro-style timer, and includes course-based flashcard decks with chapters.

## What you need

- Raspberry Pi Pico 2 W
- Thonny with MicroPython firmware installed for Pico 2 W

## Files

- `main.py`: Wi-Fi connection, web server, timer logic, and flashcards.
- `secrets.py`: Your Wi-Fi network name and password.
- `cards.json`: Created automatically on the Pico after first run. This stores your courses, decks, and flashcards.

## Setup

1. Flash MicroPython for Raspberry Pi Pico 2 W.
2. Open Thonny.
3. Edit `secrets.py`:

   ```python
   WIFI_SSID = "your-network-name"
   WIFI_PASSWORD = "your-password"
   ```

4. Copy all three files to the Pico:

   - `main.py`
   - `secrets.py`

5. Restart the Pico or press Run in Thonny.
6. Watch the Thonny shell for the IP address:

   ```text
   Connected. IP: 192.168.x.x
   Open http://192.168.x.x/
   ```

7. Open that address in a browser on the same Wi-Fi network.

## Dashboard features

- Start, pause, reset, and skip timer modes.
- Set task name.
- Set focus and break duration.
- Live timer updates every second.
- Onboard LED turns on while the timer is running.
- Optional Focus Lock warns when the browser tab or window loses focus during a focus block.
- Courses list with card counts.
- Add new courses like Arabic, Psychology, Python, or Electronics.
- Deck/chapter list inside the selected course.
- Add decks like Chapter 1, Chapter 2, Midterm Review, or Final Review.
- Select a course first, then select a deck inside that course.
- Flashcards with show answer, again, correct, next, previous, add, and delete.
- Flashcards, courses, and decks are saved to `cards.json` on the Pico.
- Import Anki decks exported as plain text or CSV.

## Importing Anki cards

Full `.apkg` Anki packages are zipped SQLite databases, which are too heavy for the Pico to parse directly. This dashboard supports the lightweight Anki export format instead:

1. Open Anki on your computer.
2. Select the deck you want.
3. Export it as notes in plain text or CSV format.
4. Open the Pico dashboard in your browser.
5. Select or create the course you want.
6. Select or create the deck/chapter inside that course.
7. Choose the exported `.txt` or `.csv` file in the import panel.
8. Pick **Add imported cards** or **Replace deck**.

The browser parses the file first, then sends compact flashcards to the Pico. The current import limit is 60 cards at a time so the Pico does not run out of memory.

## Notes

- This serves the dashboard only on your local Wi-Fi network.
- The project does not save sessions after power-off yet.
- Flashcards, courses, and decks do save after power-off.
- Keep `secrets.py` private if you share the code.
- Import expects each row to contain a question and answer separated by a tab, comma, or semicolon.
- Focus Lock cannot stop someone from leaving the page. It detects tab/window focus changes and records a warning when the focus timer is running.
- If you already had an older `cards.json`, the app migrates it into a course with a `Main Deck` automatically.

## Good next upgrades

- Add a buzzer on timer completion.
- Add physical buttons for start, pause, and reset.
- Save completed sessions to a local file.
- Rename and delete courses/decks.
- Add import support for larger decks in batches.
- Add access point setup mode so you can configure Wi-Fi without editing `secrets.py`.

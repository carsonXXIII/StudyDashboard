Pico Study Dashboard
A Raspberry Pi Pico 2 W study dashboard built with MicroPython that serves a local browser app over Wi‑Fi for focus sessions, flashcards, course/deck organization, and Anki-style CSV import.
Features
•	Local web dashboard hosted directly by the Pico 2 W over Wi‑Fi.
•	Reddish light/dark theme for the interface.
•	Course and deck hierarchy, such as Psychology -> Chapter 1 or Arabic -> Main Deck.
•	Browser-based flashcard study flow with add, delete, previous/next, show answer, again, and correct actions.
•	Import flashcards from plain-text or CSV exports from Anki.
•	Focus Lock that warns and counts when the user switches away during an active focus session.
•	Migration support for older cards.json structures into the newer course/deck format.
Hardware and software
•	Raspberry Pi Pico 2 W.
•	MicroPython firmware for RPI_PICO2_W.
•	A USB data cable and a Windows, macOS, or Linux computer for flashing and uploading files.
•	Thonny or another MicroPython-capable editor for copying files to the board.
Repository layout
pico-study-dashboard/
├── README.md
├── LICENSE
├── .gitignore
├── main.py
├── secrets.example.py
└── docs/
    └── anki-import-format.md

Recommended local-only files that should not be committed include secrets.py, device-specific exports, and editor cache files.
Setup
1.	Download the correct MicroPython UF2 for the Pico 2 W, making sure the firmware is for RPI_PICO2_W rather than another Pico variant.
2.	Hold the BOOTSEL button while plugging the board into the computer, then copy the UF2 file to the mounted storage device.
3.	Open Thonny, select the Raspberry Pi Pico MicroPython interpreter, and connect to the Pico’s serial port.
4.	Copy secrets.example.py to a new local file named secrets.py and fill in the Wi‑Fi credentials.
5.	Upload main.py and secrets.py to the Pico.
6.	Run main.py from Thonny and open the IP address shown in the shell in a browser on the same Wi‑Fi network.
secrets.py example
WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

This file should stay local and should not be committed to GitHub because it contains private network credentials.
Anki import notes
This project supports importing plain-text or CSV exports from Anki, including tab-, comma-, or semicolon-separated question/answer rows.[cite:24] It does not import .apkg files directly because .apkg packages are zipped SQLite databases and are too heavy for reliable parsing on the Pico.
Known limits
•	Focus Lock can detect tab hiding or window blur and warn/count it, but it cannot stop users from leaving the page because browsers do not allow websites to block tab switching or app switching.
•	Anki import is limited to exported text/CSV, not full .apkg packages.
•	Large imports should stay modest because the Pico has limited memory; earlier versions capped imports at 60 cards to avoid memory issues.
GitHub checklist
•	Add main.py.
•	Add README.md, LICENSE, .gitignore, and secrets.example.py.
•	Do not commit secrets.py with real credentials.
•	Add one or two screenshots in docs/screenshots/.
•	Create the repository as pico-study-dashboard for a clean, descriptive project name.
License
An MIT license is a common choice when broad reuse is intended, and GitHub recommends adding an explicit license so others know how they may use the code.

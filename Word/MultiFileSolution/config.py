# config.py
# ANFANG
# config.py (V38.19 Line-by-Line Regex)
import re
import html
import tkinter as tk
from tkinter import filedialog

APP_VERSION = "v38.19 (Ghost-Buster & Chapter Extraction)"
VERSION_MAIN = "v38.19 (Zombie Task Killer)"
VERSION_CONFIG = "v38.19 (Line-by-Line Regex)"
VERSION_PREFLIGHT = "v38.8 (DispatchEx)"
VERSION_FILE_READER = "v38.19 (Safe ListString)"
VERSION_DIFF_LOGIC = "v1.0 (Modular Compare Logic)"
VERSION_SERVER = "v38.16 (Fast Dialog Fix)"

CHANGE_HISTORY_LOG = r"""
*** Advanced Delta Tool - Change Log ***
v38.19 (Stability): main.py actively kills zombie tasks on port 8000 using Windows taskkill. config.py uses line-by-line evaluation for robust chapter ID extraction.
*** End of Change Log ***
"""

START_FILE_LEFT = ""
START_FILE_RIGHT = ""
DISPLAY_NAME_LEFT = ""
DISPLAY_NAME_RIGHT = ""

def extract_id(text):
    if not text: return None
    
    # FIX V38.19: Zeilen einzeln auswerten, damit [BILD]-Tags und Zeilenumbrüche die Regex nicht blockieren
    lines = text.split('\n')
    for line in lines:
        clean = re.sub(r'\[BILD:[^\]]+\]', '', line)
        clean = re.sub(r'\[P:\d+\]', '', clean)
        # Ersetzt versteckte Word-Tabs und Sonderzeichen durch Leerzeichen
        clean = re.sub(r'[\x00-\x1F\x7F-\x9F\xA0]', ' ', clean).strip()
        
        if not clean: continue
        
        # Aggressive Suche, die Kapitel 2, 2.1, 2.1.1 sofort als ID erkennt
        m = re.match(r'^(?:ID\s+\d+:|\[REQ-\d+\]|REQ\s+\d+:|Afo\.\s*\d+(?:\.\d+)*|\d+(?:\.\d+)*[a-zA-Z]?\.?)(?=\s|$|:|\-)', clean, re.IGNORECASE)
        if m:
            extracted = m.group(0).strip()
            extracted = re.sub(r'[\-\:]$', '', extracted).strip()
            return extracted
        
        # Sobald die erste echte Textzeile kein Kapitel ist, abbrechen, um Fehler zu vermeiden
        break
        
    return None

def escape_html(unsafe):
    if unsafe is None: return ""
    return html.escape(str(unsafe))
# ENDE
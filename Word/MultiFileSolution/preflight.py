# preflight.py
# ANFANG
# preflight.py (V38.8 Robust Preflight mit DispatchEx)
import sys
import config

PREFLIGHT_RESULTS = {
    "word_ready": False,
    "pywin32_missing": False,
    "word_installed": False,
    "user_message": "Preflight-Check noch nicht ausgeführt.",
    "priority_decision": ""
}

def run_preflight_check():
    """Prüft Abhängigkeiten (pywin32) und MS Word Verfügbarkeit."""
    global PREFLIGHT_RESULTS
    results = PREFLIGHT_RESULTS
    sys.stdout.write(f"--- ⚙️ Starte Delta Tool {config.APP_VERSION} Preflight-Check ---\n")
    
    # 1. Check Python Lib 'pywin32'
    pywin32_available = False
    try:
        import win32com.client
        pywin32_available = True
        sys.stdout.write("✅ Python 'pywin32' Bibliothek gefunden.\n")
    except ImportError:
        results["pywin32_missing"] = True
        sys.stdout.write("❌ Python 'pywin32' Bibliothek fehlt!\n")
    
    # 2. Check for Word using COM
    word_available = False
    if pywin32_available:
        import win32com.client
        try:
            # FIX V38.8: Nutze DispatchEx für den Preflight, um blockierte Zombie-Prozesse zu umgehen!
            word = win32com.client.DispatchEx("Word.Application")
            try:
                word.DisplayAlerts = 0
            except Exception: pass
            
            results["word_installed"] = True
            word_available = True
            sys.stdout.write("✅ Microsoft Word COM-Schnittstelle bereit.\n")
            
            # Word Instanz wieder schließen
            word.Quit()
        except Exception as e:
            sys.stdout.write(f"❌ Microsoft Word konnte nicht über COM angesprochen werden: {e}\n")
    
    # 3. Decision & Messaging
    if word_available:
        results["word_ready"] = True
        results["priority_decision"] = "Microsoft Word (COM Rendering)"
        results["user_message"] = r"<strong>✅ Preflight-Check:</strong> Microsoft Word wurde für Smart Rendering ausgewählt und ist bereit."
    elif results["pywin32_missing"]:
        results["user_message"] = r"<strong>⚠️ Preflight-Check:</strong> Microsoft Word Live-Sync ist deaktiviert. (Python-Bibliothek 'pywin32' fehlt!)."
    else:
        results["priority_decision"] = "XML Fallback"
        results["user_message"] = r"<strong>ℹ️ Preflight-Check:</strong> Microsoft Word blockiert. Smart Rendering und Live-Sync sind deaktiviert."
        
    sys.stdout.write("--- ✅ Preflight-Check abgeschlossen ---\n\n")
# ENDE
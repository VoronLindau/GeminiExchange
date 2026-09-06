# main.py
# ANFANG
# main.py (V38.19 - Zombie Task Killer)
import sys
import threading
import webbrowser
import subprocess
from http.server import HTTPServer
import config
import preflight
import server

def kill_zombie_on_port(port):
    """Sucht und zerstört rigoros jeden Prozess, der unseren Port blockiert."""
    try:
        # Führt Windows netstat aus, um die PID (Process ID) zu finden
        output = subprocess.check_output(f'netstat -ano | findstr :{port}', shell=True).decode()
        for line in output.strip().split('\n'):
            if 'LISTENING' in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid != '0':
                    sys.stdout.write(f"⚠️  Geister-Prozess (PID {pid}) auf Port {port} entdeckt. Führe Kill-Befehl aus...\n")
                    subprocess.call(f'taskkill /F /PID {pid}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def print_app_composition():
    sys.stdout.write("\n--- 🛠️  Applikations-Komposition (Wasserdicht) ---\n")
    sys.stdout.write(f"Zusammengesetzte finale Version: {config.APP_VERSION}\n")
    sys.stdout.write(f"  > Entry Point (main.py): {config.VERSION_MAIN}\n")
    sys.stdout.write(f"  > Konfiguration (config.py): {config.VERSION_CONFIG}\n")
    sys.stdout.write(f"  > Voraussetzungen (preflight.py): {config.VERSION_PREFLIGHT}\n")
    sys.stdout.write(f"  > Datei-Parser (file_reader.py): {config.VERSION_FILE_READER}\n")
    sys.stdout.write("---------------------------------------------------\n\n")

def start_application():
    print_app_composition()
    preflight.run_preflight_check()

    port = 8000
    # FIX V38.19: Töte alle Zombies auf Port 8000 bevor der Server startet!
    kill_zombie_on_port(port)
    
    server_address = ('', port)
    
    try:
        httpd = HTTPServer(server_address, server.DiffRequestHandler)
    except Exception as e:
        sys.stderr.write(f"❌ Fehler beim Starten des Servers auf Port {port}: {e}\n")
        sys.exit(1)

    url = f"http://localhost:{port}"

    sys.stdout.write(f"🚀 Starte Delta Tool Server auf {url} ...\n")
    sys.stdout.write("Zum Beenden des Tools: Terminal-Fenster schließen oder Strg+C im Terminal drücken.\n")

    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write("\n🛑 Server wurde durch Benutzer beendet.\n")
        httpd.server_close()
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"❌ Unerwarteter Server-Fehler: {e}\n")
        httpd.server_close()
        sys.exit(1)

if __name__ == '__main__':
    start_application()
# ENDE
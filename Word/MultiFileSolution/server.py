# server.py
# ANFANG
# server.py (V38.16 Fast Dialog Fix - Modular)
# TEIL 1 von 2
import os
import json
import zipfile
import tempfile
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import html
import collections
import config
import preflight
import file_reader
import diff_logic

# Globale Variable, damit Tkinter nur einmal startet (verhindert 30s Timeout)
_TK_ROOT = None

# ==========================================
# HILFSFUNKTION FÜR WORD-SYNC (V38.10 Robust)
# ==========================================
def jump_to_word_page(side, page_num):
    target_name = config.DISPLAY_NAME_LEFT if side == 'left' else config.DISPLAY_NAME_RIGHT
    fallback_path = config.START_FILE_LEFT if side == 'left' else config.START_FILE_RIGHT
    
    if not target_name: return False
        
    try:
        import win32com.client
        try:
            word = win32com.client.GetActiveObject("Word.Application")
        except Exception:
            word = win32com.client.DispatchEx("Word.Application")
            
        try: word.DisplayAlerts = 0
        except: pass
        
        try: 
            word.Visible = True 
        except Exception as e:
            print(f"WARNUNG: Sichtbarkeit beim Sync blockiert: {e}")
            
        doc = None
        for d in word.Documents:
            if target_name.lower() in d.Name.lower() or d.Name.lower() in target_name.lower():
                doc = d; break
                
        if not doc and fallback_path and os.path.exists(fallback_path):
            doc = word.Documents.Open(os.path.abspath(fallback_path), ReadOnly=True)
            
        if not doc: return False
            
        try: doc.Activate()
        except: pass
        
        try: word.Activate()
        except: pass
        
        target_range = doc.GoTo(1, 1, int(page_num))
        target_range.Select()
        word.ActiveWindow.ScrollIntoView(target_range)
        return True
    except Exception as e:
        print(f"WORD-BLOCKADE beim Scrollen: {e}")
        try:
            if fallback_path and os.path.exists(fallback_path):
                os.startfile(os.path.abspath(fallback_path))
        except: pass
        return False

# ==========================================
# REQUEST HANDLER KLASSE
# ==========================================
class DiffRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass 

    def do_POST(self):
        parsed_url = urlparse(self.path)
        if parsed_url.path == '/api/upload':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            filename = query.get('filename', [f'Unbekannte_Datei_{side}.docx'])[0]
            content_length = int(self.headers['Content-Length'])
            file_data = self.rfile.read(content_length)
            
            temp_dir = tempfile.gettempdir()
            save_path = os.path.join(temp_dir, f"delta_tmp_{side}.docx")
            with open(save_path, 'wb') as f: f.write(file_data)
                
            if side == 'left':
                config.START_FILE_LEFT = save_path
                config.DISPLAY_NAME_LEFT = filename
            elif side == 'right':
                config.START_FILE_RIGHT = save_path
                config.DISPLAY_NAME_RIGHT = filename
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/preflight_status':
            response_json = json.dumps(preflight.PREFLIGHT_RESULTS).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(response_json)
            return

        if parsed_url.path == '/api/browse_file':
            try:
                query = parse_qs(parsed_url.query)
                side = query.get('side', [''])[0]
                
                import tkinter as tk
                from tkinter import filedialog
                
                # FIX V38.16: Globale Tk-Instanz nutzen und nicht mehr zerstören
                global _TK_ROOT
                if _TK_ROOT is None:
                    _TK_ROOT = tk.Tk()
                    _TK_ROOT.withdraw()
                
                _TK_ROOT.attributes('-topmost', True)
                _TK_ROOT.lift()
                _TK_ROOT.focus_force()
                
                file_path = filedialog.askopenfilename(parent=_TK_ROOT, filetypes=[("Word Files", "*.docx")])
                
                # Fokus-Sperre aufheben, aber das Fenster bleibt im Hintergrund am Leben
                _TK_ROOT.attributes('-topmost', False)
                
                if file_path:
                    file_path = file_path.replace('\\', '/')
                    filename = os.path.basename(file_path)
                    if side == 'left':
                        config.START_FILE_LEFT = file_path
                        config.DISPLAY_NAME_LEFT = filename
                    else:
                        config.START_FILE_RIGHT = file_path
                        config.DISPLAY_NAME_RIGHT = filename
                        
                    response_json = json.dumps({"status": "ok", "path": file_path, "filename": filename}).encode('utf-8')
                else:
                    response_json = json.dumps({"status": "cancelled"}).encode('utf-8')
                    
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response_json)
            except Exception as e:
                error_json = json.dumps({"error": str(e)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(error_json)
            return

        if parsed_url.path == '/api/diff_data':
            try:
                ignore_breaks = parse_qs(parsed_url.query).get('ignore_breaks', ['1'])[0] == '1'
                
                if not config.START_FILE_LEFT or not config.START_FILE_RIGHT:
                     raise ValueError("Bitte wählen Sie zuerst beide Dateien aus.")
                
                info_l = file_reader.get_file_info(config.START_FILE_LEFT)
                info_r = file_reader.get_file_info(config.START_FILE_RIGHT)
                diff, stats = diff_logic.berechne_diff_daten(info_l['content'], info_r['content'], ignore_breaks)
                
                meta_l = os.path.getmtime(config.START_FILE_LEFT) if config.START_FILE_LEFT and os.path.exists(config.START_FILE_LEFT) else 0
                meta_r = os.path.getmtime(config.START_FILE_RIGHT) if config.START_FILE_RIGHT and os.path.exists(config.START_FILE_RIGHT) else 0
                
                metadata = {
                    "app_version": config.APP_VERSION,
                    "file_left": config.DISPLAY_NAME_LEFT,
                    "time_left": datetime.fromtimestamp(meta_l).strftime('%Y-%m-%d %H:%M:%S') if meta_l else "",
                    "file_right": config.DISPLAY_NAME_RIGHT,
                    "time_right": datetime.fromtimestamp(meta_r).strftime('%Y-%m-%d %H:%M:%S') if meta_r else ""
                }
                
                response_json = json.dumps({"diff": diff, "stats": stats, "metadata": metadata}).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response_json)
            except Exception as e:
                error_json = json.dumps({"error": str(e)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(error_json)
            return
            
        if parsed_url.path == '/api/jump':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            page = query.get('page', ['1'])[0]
            success = jump_to_word_page(side, page)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            return
            
        if parsed_url.path == '/media':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            file_path_in_zip = query.get('file', [''])[0]
            docx_path = config.START_FILE_LEFT if side == 'left' else config.START_FILE_RIGHT
            
            if not docx_path or not os.path.exists(docx_path):
                self.send_response(404); self.end_headers(); return

            try:
                with zipfile.ZipFile(docx_path, 'r') as z:
                    data = z.read(file_path_in_zip)
                    self.send_response(200)
                    ext = file_path_in_zip.lower().split('.')[-1]
                    mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif'}
                    self.send_header('Content-type', mime.get(ext, 'application/octet-stream'))
                    self.end_headers()
                    self.wfile.write(data)
            except Exception:
                self.send_response(404); self.end_headers()
            return

        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            html_content = self.get_html_template().replace("APP_VERSION", config.APP_VERSION)
            
            try:
                history_html = html.escape(config.CHANGE_HISTORY_LOG).replace("\n", "<br>")
                html_content = html_content.replace("CHANGE_HISTORY_LOG_DATA", history_html)
                html_content = html_content.replace("VERSION_MAIN_DATA", html.escape(config.VERSION_MAIN))
                html_content = html_content.replace("VERSION_CONFIG_DATA", html.escape(config.VERSION_CONFIG))
                html_content = html_content.replace("VERSION_PREFLIGHT_DATA", html.escape(config.VERSION_PREFLIGHT))
                html_content = html_content.replace("VERSION_FILE_READER_DATA", html.escape(config.VERSION_FILE_READER))
                html_content = html_content.replace("VERSION_DIFF_LOGIC_DATA", html.escape(config.VERSION_DIFF_LOGIC))
                html_content = html_content.replace("VERSION_SERVER_DATA", html.escape(config.VERSION_SERVER))
            except Exception: pass

            name_l = config.DISPLAY_NAME_LEFT if config.DISPLAY_NAME_LEFT else "Keine Datei (Links)"
            name_r = config.DISPLAY_NAME_RIGHT if config.DISPLAY_NAME_RIGHT else "Keine Datei (Rechts)"
            html_content = html_content.replace("NAME_LEFT_ESC", html.escape(name_l))
            html_content = html_content.replace("NAME_RIGHT_ESC", html.escape(name_r))
            
            self.wfile.write(html_content.encode('utf-8'))

    def get_html_template(self):
        return HTML_TEMPLATE
# --- HIER ENDET TEIL 1 ---
# server.py (Fortsetzung)
# TEIL 2 von 2


# ==========================================
# RIESIGES HTML/JS TEMPLATE (Start)
# ==========================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8"><title>Advanced Delta Tool</title>
    <style>
        :root { --bg-dark: #1e1e1e; --bg-panel: #252526; --text-main: #d4d4d4; }
        body { margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; background: var(--bg-dark); color: var(--text-main); overflow: hidden; }
        #header-container { display: flex; background: #333; border-bottom: 2px solid #444; position: relative; z-index: 100;}
        .pane-header { flex: 1; padding: 10px; display: flex; justify-content: space-between; align-items: center; }
        .pane-header.left { border-right: 1px solid #444; }
        .header-title { font-weight: bold; color: #9cdcfe; font-size: 15px; max-width: 350px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: #1e1e1e; padding: 4px 10px; border-radius: 4px; border: 1px solid #555; display: inline-flex; align-items: center; gap: 8px;}
        .browse-btn { background: #007acc; border: 1px solid #005f9e; color: white; padding: 4px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;}
        .browse-btn:hover { background: #005f9e; }
        .view-select { background: #007acc; border: 1px solid #005f9e; color: white; padding: 5px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; cursor: pointer; outline: none;}
        .word-btn { background: #107c41; margin-top: 5px; width: 100%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
        .review-btn { background: #8e44ad; margin-top: 5px; width: 48%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
        .center-panel { width: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: var(--bg-panel); padding: 5px 10px; font-size: 10px; color: #888; border-left: 1px solid #444; border-right: 1px solid #444; box-sizing: border-box;}
        
        .info-btn { background: transparent; border: 1px solid #555; color: #888; padding: 2px 6px; border-radius: 3px; font-size: 14px; cursor: pointer; display: flex; align-items: center; justify-content: center; position: absolute; top: 5px; right: 5px; z-index: 101;}
        .info-btn:hover { border-color: #9cdcfe; color: #9cdcfe; background: rgba(156,220,254,0.1);}

        #workspace { display: flex; flex: 1; overflow: hidden; position: relative; }
        .editor-container { flex: 1; overflow-y: auto; padding: 10px; font-size: 13px; line-height: 1.5; scroll-behavior: smooth; position: relative;}
        
        .editor-container.drag-over { border: 3px dashed #007acc !important; background-color: rgba(0, 122, 204, 0.1) !important; }
        .drag-overlay { display: none; position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.6); color: #007acc; font-size: 24px; font-weight: bold; align-items: center; justify-content: center; z-index: 100; pointer-events: none;}
        .editor-container.drag-over .drag-overlay { display: flex; }
        
        #svg-container { width: 100px; flex-shrink: 0; position: relative; background: var(--bg-panel); border-left: 1px solid #444; border-right: 1px solid #444; }
        svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
        
        .bucket-block { background-color: #252526; border: 1px solid #444; border-radius: 4px; margin-bottom: 12px; padding: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.2); transition: min-height 0.2s, box-shadow 0.5s;}
        .inner-line { padding: 2px 5px; margin-bottom: 3px; border-radius: 2px; min-height: 1.2em; word-wrap: break-word; font-family: 'Consolas', monospace;}
        
        .bg-insert { background-color: rgba(40, 167, 69, 0.2); border-left: 3px solid #28a745; }
        .bg-delete { background-color: rgba(220, 53, 69, 0.2); border-left: 3px solid #dc3545; text-decoration: line-through; opacity: 0.8; }
        .bg-replace { background-color: rgba(0, 123, 255, 0.2); border-left: 3px solid #007bff; }
        .bg-format { background-color: rgba(0, 123, 255, 0.08); border-left: 3px dashed #007bff; }
        .bg-equal { background-color: transparent; border-left: 3px solid #555; }
        .bg-empty { background-color: transparent; min-height: 1.2em; }
        
        .char-diff { background-color: rgba(0, 123, 255, 0.6); color: white; font-weight: bold; border-radius: 2px; padding: 0 2px; }
        
        .inline-img { max-width: 90%; max-height: 300px; border: 2px dashed #007acc; padding: 5px; margin: 5px 0; background: #2d2d2d; border-radius: 4px; display: block; box-sizing: border-box;}
        .img-changed { border: 3px solid #007bff; box-shadow: 0 0 8px rgba(0,123,255,0.6); }
        
        .jump-btn { background: #1e1e1e; color: #fff; border: 1px solid #fff; border-radius: 3px; font-size: 10px; cursor: pointer; padding: 3px 6px; margin-left: 10px;}
        .jump-btn:hover { background: #fff; color: #dc3545; }
        
        .review-widget { margin-top: 5px; padding: 5px; background: #1e1e1e; border: 1px solid #555; border-radius: 3px; display: flex; gap: 5px; }
        .review-widget select { background: #333; color: white; border: 1px solid #555; border-radius: 2px; font-size: 11px; padding: 2px; }
        .review-widget input { flex: 1; background: #333; color: white; border: 1px solid #555; border-radius: 2px; font-size: 11px; padding: 2px 5px; }
        
        #nav-buttons { position:fixed; bottom:20px; right:20px; z-index:1000; display:flex; gap:10px; }
        .nav-btn { font-weight:bold; color:white; border:none; padding:10px 15px; border-radius:4px; cursor:pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: background 0.2s;}
        .nav-btn:hover { filter: brightness(1.2); }
        
        .editor-container.view-delta .tag-equal { display: none !important; }
        
        /* FIX V38.20: Animierte CSS Fortschrittsanzeige */
        #loading-screen { 
            position:absolute; top:0; left:0; width: 100%; height: 100%; 
            background-color: rgba(30, 30, 30, 0.9); z-index: 2000; 
            display: flex; flex-direction: column; align-items: center; justify-content: center;
        }
        .loading-text { color: #9cdcfe; font-size: 20px; font-weight: bold; margin-bottom: 8px; font-family: 'Segoe UI', sans-serif;}
        .loading-sub { color: #888; font-size: 12px; margin-bottom: 20px; font-family: 'Segoe UI', sans-serif;}
        .progress-container { width: 350px; background: #333; border: 1px solid #555; border-radius: 6px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.5);}
        .progress-bar { 
            width: 100%; height: 14px; 
            background: repeating-linear-gradient(45deg, #007acc, #007acc 10px, #005f9e 10px, #005f9e 20px); 
            background-size: 28px 28px; 
            animation: move-stripes 1s linear infinite; 
        }
        @keyframes move-stripes { 0% { background-position: 0 0; } 100% { background-position: 28px 0; } }
        
        #preflight-status-panel { width: 100%; border-radius: 4px; padding: 8px; box-sizing: border-box; text-align: left; margin-bottom: 8px; font-size: 10px; line-height: 1.4; font-family: 'Segoe UI', sans-serif;}
        .preflight-ok { background-color: rgba(0, 122, 204, 0.1); border: 1px solid #007acc; color: #d4d4d4;}
        .preflight-ok strong { color: #007acc; }
        .preflight-warn { background-color: rgba(255, 152, 0, 0.1); border: 1px solid #ff9800; color: #d4d4d4; }
        .preflight-warn strong { color: #ff9800; }
        .preflight-warn code { background: rgba(255,255,255,0.1); padding: 1px 3px; border-radius: 2px;}

        .modal { display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.7); }
        .modal-content { background-color: #252526; margin: 10% auto; padding: 20px; border: 1px solid #444; border-radius: 8px; width: 600px; color: #d4d4d4; box-shadow: 0 5px 15px rgba(0,0,0,0.5); font-family: 'Segoe UI', sans-serif;}
        .close-modal { color: #888; float: right; font-size: 28px; font-weight: bold; cursor: pointer; line-height: 20px;}
        .close-modal:hover { color: #dc3545; }
        .modal-header { font-size: 18px; font-weight: bold; color: #9cdcfe; border-bottom: 1px solid #444; padding-bottom: 10px; margin-bottom: 15px;}
        .version-list { font-size: 12px; line-height: 1.6; font-family: 'Consolas', monospace; color: #888; margin-bottom: 15px; background: #1e1e1e; padding: 10px; border-radius: 4px; border: 1px solid #333;}
        .version-list strong { color: #d4d4d4; }
        .history-log { font-size: 11px; line-height: 1.5; font-family: 'Consolas', monospace; color: #d4d4d4; background: #1e1e1e; padding: 10px; border-radius: 4px; border: 1px solid #333; height: 250px; overflow-y: scroll; white-space: pre-wrap;}

        @media print { 
            #header-container, #svg-container, #nav-buttons, .review-widget, #preflight-status-panel, .info-btn, .modal { display: none !important; } 
            body, #workspace { overflow: visible !important; height: auto !important; } 
            .editor-container { overflow: visible !important; border: none; padding:0; width:48%; float:left; margin-right:2%;} 
            .bucket-block { page-break-inside: avoid; border: 1px solid #ccc;}
            .jump-btn { display: none !important; }
        }
    </style>
</head>
<body>
    <!-- FIX V38.20: Neuer Loading Screen mit Progress Bar -->
    <div id="loading-screen" style="display: flex;">
        <div class="loading-text" id="load-msg-main">⏳ Applikation wird initialisiert...</div>
        <div class="loading-sub" id="load-msg-sub">Bitte warten.</div>
        <div class="progress-container"><div class="progress-bar"></div></div>
    </div>

    <div id="info-modal" class="modal">
        <div class="modal-content">
            <span class="close-modal" onclick="closeInfoModal()">&times;</span>
            <div class="modal-header">Delta Tool - Info & Verlauf (V38.20 UI Update)</div>
            <div class="version-list">
                <strong>Conceptual Unified Base:</strong> APP_VERSION<br>
                <strong>Entry Point (main.py):</strong> VERSION_MAIN_DATA<br>
                <strong>Konfiguration (config.py):</strong> VERSION_CONFIG_DATA<br>
                <strong>Voraussetzungen (preflight.py):</strong> VERSION_PREFLIGHT_DATA<br>
                <strong>Datei-Parser (file_reader.py):</strong> VERSION_FILE_READER_DATA<br>
                <strong>Vergleichs-Logik (diff_logic.py):</strong> VERSION_DIFF_LOGIC_DATA<br>
                <strong>Web-Server (server.py):</strong> VERSION_SERVER_DATA
            </div>
            <div class="modal-header" style="font-size:14px; margin-top:15px; border:none; padding:0;">Change History:</div>
            <div class="history-log">CHANGE_HISTORY_LOG_DATA</div>
        </div>
    </div>

    <div id="header-container" style="visibility: hidden;">
        <button class="info-btn" title="Zeige Versionen und Change Log" onclick="showInfoModal()">📜</button>

        <div class="pane-header left">
            <div class="header-title">
                <span id="name-left" title="NAME_LEFT_ESC">📄 NAME_LEFT_ESC</span>
                <button class="browse-btn" onclick="browseFile('left')">📂 Suchen...</button>
            </div>
            <select id="view-left" class="view-select" onchange="changeView('left')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
        </div>
        
        <div class="center-panel">
            <div style="margin-bottom: 5px; font-weight:bold;">APP_VERSION</div>
            
            <div id="stats-panel" style="display:none; width: 100%; background: #1e1e1e; border-radius: 4px; padding: 6px; box-sizing: border-box; text-align: left; margin-bottom: 5px; border: 1px solid #444;">
                <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center; border-bottom:1px solid #444; padding-bottom:3px;"><b>Statistik (Kapitel/IDs)</b></div>
                <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                    <div style="width: 48%;"><u style="color:#9cdcfe">Links</u><br>Gleich: <span id="l-eq" style="float:right; font-weight:bold;">0</span><br>Geändert: <span id="l-rep" style="float:right; font-weight:bold;">0</span><br>Gelöscht: <span id="l-del" style="float:right; font-weight:bold;">0</span></div>
                    <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;"><u style="color:#9cdcfe">Rechts</u><br>Gleich: <span id="r-eq" style="float:right; font-weight:bold;">0</span><br>Geändert: <span id="r-rep" style="float:right; font-weight:bold;">0</span><br>Neu: <span id="r-ins" style="float:right; font-weight:bold;">0</span></div>
                </div>
                
                <div style="margin-top: 4px; padding-top: 4px; border-top: 1px solid #444; font-size: 10px; text-align: center; color: #ff9800; font-weight: bold;">
                    🖼️ Bilder geändert/neu: <span id="img-diffs">0</span>
                </div>
                
                <div style="margin-top: 6px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                    <label style="cursor: pointer; color: #d4d4d4; font-size: 10px; font-weight: bold;"><input type="checkbox" id="chk-ignore-breaks" checked onchange="reloadDiff()"> ⚙️ Umbrüche ignorieren</label>
                </div>
                
                <div style="margin-top: 4px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                    <b style="color: #8e44ad; font-size:10px;">JSON Review Spalte:</b><br>
                    <select id="review-side" onchange="renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'))" style="background:#333; color:white; border:1px solid #555; border-radius:2px; font-size:10px; width:100%; margin-top:2px;">
                        <option value="right">Rechts (Empfohlen)</option>
                        <option value="left">Links</option>
                        <option value="none">Ausblenden</option>
                    </select>
                </div>

                <div style="margin-top: 4px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                    <div id="preflight-status-panel">Lade Status...</div>
                </div>

                <div style="margin-top: 4px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                    <b style="color: #9cdcfe; font-size:10px;">MS Word Live-Sync</b><br>
                    <label id="lbl-sync-left" style="cursor:pointer; font-size:10px;"><input type="checkbox" id="sync-left" onchange="doLiveSync()"> Links</label> &nbsp;
                    <label id="lbl-sync-right" style="cursor:pointer; font-size:10px;"><input type="checkbox" id="sync-right" onchange="doLiveSync()"> Rechts</label>
                </div>
            </div>

            <div style="display: flex; justify-content: space-between; width: 100%;">
                <button class="review-btn" onclick="importJSONTrigger()">📂 Load</button>
                <button class="review-btn" onclick="exportJSON()">💾 Save</button>
            </div>
            <input type="file" id="json-upload" style="display:none;" accept=".json" onchange="importJSON(event)">
        </div>
        
        <div class="pane-header right">
            <div class="header-title">
                <span id="name-right" title="NAME_RIGHT_ESC">📄 NAME_RIGHT_ESC</span>
                <button class="browse-btn" onclick="browseFile('right')">📂 Suchen...</button>
            </div>
            <select id="view-right" class="view-select" onchange="changeView('right')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
        </div>
    </div>

    <div id="workspace" style="visibility: hidden;">
        <div id="left-editor" class="editor-container"></div>
        <div id="svg-container"><svg id="lines-svg"></svg></div>
        <div id="right-editor" class="editor-container"></div>
    </div>
    
    <div id="nav-buttons" style="visibility: hidden;">
        <button class="nav-btn" style="background:#ff9800;" onclick="jumpDelta(-1)">⬆ Vorheriges Delta</button>
        <button class="nav-btn" style="background:#007acc;" onclick="jumpDelta(1)">⬇ Nächstes Delta</button>
    </div>

    <script>
        window.addEventListener("dragover", function(e) { e.preventDefault(); }, false);
        window.addEventListener("drop", function(e) { e.preventDefault(); }, false);

        let diffData = []; let statsData = {}; let metaData = {};
        let syncTimer = null;
        let lastPageL = -1; let lastPageR = -1;
        let currentDeltaIdx = -1;
        let deltaElements = [];
        
        let reviewData = { schema_version: "1.0", app_version: "APP_VERSION", metadata: {}, reviews: {} };
        
        function showInfoModal() { document.getElementById('info-modal').style.display = 'block'; }
        function closeInfoModal() { document.getElementById('info-modal').style.display = 'none'; }
        window.onclick = function(event) { let modal = document.getElementById('info-modal'); if (event.target == modal) { modal.style.display = "none"; } }

        window.onload = function() { 
            checkPreflightStatus(); 
            document.getElementById('loading-screen').style.display = 'none';
            document.getElementById('header-container').style.visibility = 'visible';
            document.getElementById('workspace').style.visibility = 'visible';
            document.getElementById('nav-buttons').style.visibility = 'visible';
        };
        
        function browseFile(side) {
            document.getElementById('loading-screen').style.display = 'flex';
            document.getElementById('load-msg-main').textContent = "⏳ Öffne Datei-Dialog...";
            document.getElementById('load-msg-sub').textContent = "Warte auf Dateiauswahl (Fenster öffnet sich im Vordergrund).";
            
            fetch(`/api/browse_file?side=${side}`)
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'ok') {
                        safeSetText(side === 'left' ? 'name-left' : 'name-right', data.filename);
                        let nameEl = document.getElementById(side === 'left' ? 'name-left' : 'name-right');
                        if (nameEl) { nameEl.title = data.path; }
                        
                        const nameL = document.getElementById('name-left').textContent;
                        const nameR = document.getElementById('name-right').textContent;
                        if (!nameL.includes("Keine Datei") && !nameR.includes("Keine Datei")) {
                            reloadDiff();
                        } else {
                            document.getElementById('loading-screen').style.display = 'none';
                        }
                    } else {
                        document.getElementById('loading-screen').style.display = 'none';
                    }
                })
                .catch(err => {
                    document.getElementById('loading-screen').style.display = 'none';
                    alert("❌ Netzwerk-Fehler beim Datei-Dialog: " + err);
                });
        }

        function checkPreflightStatus() {
            fetch('/api/preflight_status?nocache=' + new Date().getTime())
                .then(res => res.json())
                .then(results => {
                    const panel = document.getElementById('preflight-status-panel');
                    if (panel) {
                        panel.innerHTML = results.user_message;
                        panel.className = results.pywin32_missing ? 'preflight-warn' : 'preflight-ok';
                    }
                }).catch(err => console.error("❌ Preflight Fetch Error: ", err));
        }

        function reloadDiff() {
            const ignore = document.getElementById('chk-ignore-breaks') ? document.getElementById('chk-ignore-breaks').checked : true;
            document.getElementById('loading-screen').style.display = 'flex';
            document.getElementById('load-msg-main').textContent = "⏳ Analysiere Diff-Schablonen...";
            document.getElementById('load-msg-sub').textContent = "MS Word COM-Schnittstelle arbeitet im Hintergrund. Bitte warten...";
            
            document.getElementById('workspace').style.visibility = 'hidden';
            document.getElementById('nav-buttons').style.visibility = 'hidden';
            
            fetch('/api/diff_data?ignore_breaks=' + (ignore ? '1' : '0')).then(res => res.json()).then(data => {
                if (data.error) { 
                    document.getElementById('load-msg-main').innerHTML = `<span style="color:#dc3545">❌ Backend-Fehler</span>`; 
                    document.getElementById('load-msg-sub').innerHTML = data.error; 
                    return; 
                }
                diffData = data.diff; statsData = data.stats; metaData = data.metadata;
                reviewData.metadata = metaData;
                
                document.getElementById('loading-screen').style.display = 'none';
                document.getElementById('header-container').style.visibility = 'visible';
                document.getElementById('workspace').style.visibility = 'visible';
                document.getElementById('nav-buttons').style.visibility = 'visible';
                
                safeSetText('name-left', metaData.file_left);
                safeSetText('name-right', metaData.file_right);
                
                document.getElementById('left-editor').innerHTML = '';
                document.getElementById('right-editor').innerHTML = '';
                
                renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'));
            }).catch(err => { 
                document.getElementById('load-msg-main').innerHTML = `<span style="color:#dc3545">❌ Netzwerk-Fehler</span>`; 
                document.getElementById('load-msg-sub').innerHTML = err; 
            });
        }

        function escapeHtml(unsafe) { return (unsafe || "").toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;"); }
        function updateReview(reqId, field, value) { if(!reviewData.reviews[reqId]) reviewData.reviews[reqId] = {status: "", comment: ""}; reviewData.reviews[reqId][field] = value; }
        
        function exportJSON() {
            reviewData.metadata.export_time = new Date().toISOString();
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(reviewData, null, 2));
            const dlAnchorElem = document.createElement('a');
            dlAnchorElem.setAttribute("href", dataStr);
            dlAnchorElem.setAttribute("download", "Delta_Review_Export.json");
            dlAnchorElem.click();
        }

        function importJSONTrigger() { document.getElementById('json-upload').click(); }
        function importJSON(event) {
            const file = event.target.files[0]; if(!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                try {
                    const parsed = JSON.parse(e.target.result);
                    if(parsed.schema_version === "1.0" || !parsed.schema_version) {
                        reviewData.reviews = parsed.reviews || {};
                        renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'));
                        alert("✅ JSON Review erfolgreich geladen!");
                    } else { alert("❌ JSON Format-Version wird nicht unterstützt."); }
                } catch(err) { alert("❌ Ungültige JSON Datei!"); }
                event.target.value = ""; 
            };
            reader.readAsText(file);
        }

        function buildReviewWidget(reqId) {
            const data = reviewData.reviews[reqId] || {status: "", comment: ""};
            const sAcc = data.status === "accepted" ? "selected" : "";
            const sNot = data.status === "not_accepted" ? "selected" : "";
            const sRef = data.status === "refinement" ? "selected" : "";
            const sInt = data.status === "internal" ? "selected" : "";
            
            return `
            <div class="review-widget">
                <select onchange="updateReview('${reqId}', 'status', this.value)">
                    <option value="">-- Status --</option>
                    <option value="accepted" ${sAcc}>✅ Accepted</option>
                    <option value="not_accepted" ${sNot}>❌ Not accepted</option>
                    <option value="refinement" ${sRef}>⚠️ Refinement needed</option>
                    <option value="internal" ${sInt}>💬 Internal clarification</option>
                </select>
                <input type="text" placeholder="Kommentar..." value="${escapeHtml(data.comment)}" onchange="updateReview('${reqId}', 'comment', this.value)" />
            </div>`;
        }

        const svgContainer = document.getElementById('svg-container');
        function jumpToPage(side, page) { fetch(`/api/jump?side=${side}&page=${page}`).then(res => res.json()).then(data => { if(!data.success) console.warn("MS Word Fernsteuerung blockiert."); }); }

        function getPage(eid) {
            let ed = document.getElementById(eid);
            let blocks = ed.getElementsByClassName('bucket-block');
            let curr = 1;
            let viewCenter = ed.scrollTop + (ed.clientHeight / 2);
            for(let b of blocks) {
                if(b.offsetTop <= viewCenter) { curr = parseInt(b.getAttribute('data-page') || curr); } 
                else { break; }
            }
            return curr;
        }

        function doLiveSync() {
            clearTimeout(syncTimer);
            syncTimer = setTimeout(() => {
                if(document.getElementById('sync-left').checked) { let p = getPage('left-editor'); if(p && p !== lastPageL) { lastPageL = p; jumpToPage('left', p); } }
                if(document.getElementById('sync-right').checked) { let p = getPage('right-editor'); if(p && p !== lastPageR) { lastPageR = p; jumpToPage('right', p); } }
            }, 800);
        }
        
        function jumpDelta(dir) {
            if(deltaElements.length === 0) { deltaElements = Array.from(document.getElementById('left-editor').querySelectorAll('.bucket-block:not(.tag-equal)')); }
            if(deltaElements.length === 0) return; 
            currentDeltaIdx += dir;
            if(currentDeltaIdx < 0) currentDeltaIdx = 0;
            if(currentDeltaIdx >= deltaElements.length) currentDeltaIdx = deltaElements.length - 1;
            const target = deltaElements[currentDeltaIdx];
            target.scrollIntoView({behavior: 'smooth', block: 'center'});
            target.style.boxShadow = "0 0 15px #ff9800";
            setTimeout(() => { target.style.boxShadow = "0 2px 4px rgba(0,0,0,0.2)"; }, 1500);
            doLiveSync();
        }

        function changeView(side) {
            const editor = document.getElementById(side + '-editor');
            const val = document.getElementById('view-' + side).value;
            editor.classList.remove('view-delta', 'view-equal');
            if (val !== 'all') editor.classList.add('view-' + val);
            deltaElements = []; currentDeltaIdx = -1;
            setTimeout(drawLines, 50); 
        }

        function safeSetText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
        
        function renderSpecialTags(htmlStr, side) {
            if (!htmlStr) return '';
            let res = htmlStr.replace(/\[BILD:(.*?)\|HASH:(.*?)\]/g, function(match, pathPart, hashPart) {
                let isChanged = hashPart.includes("char-diff");
                let path = pathPart.replace(/<[^>]*>?/gm, '').trim(); 
                let isComImage = path === "COM_IMAGE";
                
                if (isComImage) {
                    let badge = isChanged ? `<div style="background:#007bff; color:white; font-size:10px; padding:2px 5px; display:inline-block; border-radius:3px; margin-bottom:4px; font-weight:bold;">🔄 BILD GEÄNDERT</div><br>` : '';
                    return `<div style="margin-top:10px; margin-bottom:10px;">${badge}<div style="color:#888; font-style:italic; border:1px solid #555; padding:10px; border-radius:4px; text-align:center;">📷 [Bild-Inhalt via Word-Sync verfügbar]</div></div>`;
                }
                
                let badge = isChanged ? `<div style="background:#007bff; color:white; font-size:10px; padding:2px 5px; display:inline-block; border-radius:3px; margin-bottom:4px; font-weight:bold;">🔄 BILD GEÄNDERT</div><br>` : '';
                let imgClass = isChanged ? 'inline-img img-changed' : 'inline-img';
                return `<div style="margin-top:10px; margin-bottom:10px;">${badge}<img src="/media?side=${side}&file=${path}" class="${imgClass}" alt="Bild" onload="drawLines()" onerror="this.outerHTML='<div style=\\'color:red; border:1px solid red; padding:5px;\\'>Bild fehlt: ${path}</div>'"></div>`;
            });
            return res;
        }

        function renderEditors(leftEditor, rightEditor) {
            try {
                const reviewSide = document.getElementById('review-side').value;
                let imgDiffs = (statsData.img_rep || 0) + (statsData.img_ins || 0) + (statsData.img_del || 0);
                
                if (statsData.has_reqs || imgDiffs > 0) {
                    document.getElementById('stats-panel').style.display = 'block';
                    safeSetText('l-eq', statsData.l_eq); safeSetText('l-rep', statsData.l_rep); safeSetText('l-del', statsData.l_del);
                    safeSetText('r-eq', statsData.r_eq); safeSetText('r-rep', statsData.r_rep); safeSetText('r-ins', statsData.r_ins);
                    let imgDiffEl = document.getElementById('img-diffs');
                    if(imgDiffEl) imgDiffEl.textContent = imgDiffs;
                }

                leftEditor.innerHTML = ''; rightEditor.innerHTML = '';

                if(diffData && diffData.length > 0) {
                    diffData.forEach(block => {
                        const needsReview = block.tag !== 'equal' && block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)";
                        const reviewHTML = needsReview ? buildReviewWidget(block.req_id) : "";

                        const lDiv = document.createElement('div');
                        lDiv.id = `l-${block.id}`; lDiv.className = `bucket-block tag-${block.tag}`;
                        lDiv.setAttribute('data-page', block.page_l);
                        let btnL = `<button class='jump-btn' onclick='jumpToPage("left", ${block.page_l})'>🎯 Word S.${block.page_l}</button>`;
                        let headerL = block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>[${block.req_id}]</span>` : "";
                        let revL = (needsReview && reviewSide === 'left') ? reviewHTML : "";
                        let prefixL = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px;'>
                            <div style='display:flex; justify-content:space-between; align-items:center;'>${headerL}${btnL}</div>${revL}</div>`;
                        lDiv.innerHTML = prefixL + renderSpecialTags(block.left, 'left');
                        leftEditor.appendChild(lDiv);

                        const rDiv = document.createElement('div');
                        rDiv.id = `r-${block.id}`; rDiv.className = `bucket-block tag-${block.tag}`;
                        rDiv.setAttribute('data-page', block.page_r);
                        let btnR = `<button class='jump-btn' onclick='jumpToPage("right", ${block.page_r})'>🎯 Word S.${block.page_r}</button>`;
                        let headerR = block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>[${block.req_id}]</span>` : "";
                        let revR = (needsReview && reviewSide === 'right') ? reviewHTML : "";
                        let prefixR = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px;'>
                            <div style='display:flex; justify-content:space-between; align-items:center;'>${headerR}${btnR}</div>${revR}</div>`;
                        rDiv.innerHTML = prefixR + renderSpecialTags(block.right, 'right');
                        rightEditor.appendChild(rDiv);
                    });
                    
                    diffData.forEach(block => {
                        const lEl = document.getElementById(`l-${block.id}`);
                        const rEl = document.getElementById(`r-${block.id}`);
                        if(lEl && rEl) {
                            const maxH = Math.max(lEl.offsetHeight, rEl.offsetHeight);
                            lEl.style.minHeight = maxH + 'px';
                            rEl.style.minHeight = maxH + 'px';
                        }
                    });
                }
                
                setTimeout(drawLines, 300);
                deltaElements = []; currentDeltaIdx = -1;
                
            } catch(e) { alert("Fehler beim Rendern der Editoren: " + e); }
        }

        function drawLines() {
            try {
                const svg = document.getElementById('lines-svg');
                const leftEditor = document.getElementById('left-editor');
                const rightEditor = document.getElementById('right-editor');
                const container = document.getElementById('svg-container');
                
                if (!svg || !leftEditor || !rightEditor || !container) return;
                while (svg.firstChild) { svg.removeChild(svg.firstChild); }
                
                const svgWidth = container.clientWidth || 100;
                const lScroll = leftEditor.scrollTop;
                const rScroll = rightEditor.scrollTop;

                diffData.forEach(block => {
                    if (block.tag === 'equal') return; 
                    const lEl = document.getElementById('l-' + block.id);
                    const rEl = document.getElementById('r-' + block.id);
                    if (!lEl || !rEl || lEl.offsetParent === null || rEl.offsetParent === null) return;
                    
                    const lY = lEl.offsetTop + 18 - lScroll;
                    const rY = rEl.offsetTop + 18 - rScroll;
                    
                    let color = '#007bff'; let opacity = '0.8'; let strokeWidth = '2.5';
                    if (block.tag === 'insert') { color = '#28a745'; }
                    else if (block.tag === 'delete') { color = '#dc3545'; }
                    else if (block.tag === 'format') { color = '#007bff'; opacity = '0.6'; strokeWidth = '2'; }

                    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    path.setAttribute('d', `M 0 ${lY} C ${svgWidth/2} ${lY}, ${svgWidth/2} ${rY}, ${svgWidth} ${rY}`);
                    path.setAttribute('fill', 'none'); path.setAttribute('stroke', color);
                    path.setAttribute('stroke-width', strokeWidth); path.setAttribute('opacity', opacity);
                    if (block.tag === 'format') { path.setAttribute('stroke-dasharray', '6,6'); }
                    svg.appendChild(path);
                });
            } catch(e) {}
        }           

        let isSyncingLeft = false; let isSyncingRight = false;
        document.getElementById('left-editor')?.addEventListener('scroll', function() {
            if (!isSyncingLeft) {
                isSyncingRight = true;
                const ratio = this.scrollTop / (this.scrollHeight - this.clientHeight);
                const rEditor = document.getElementById('right-editor');
                rEditor.scrollTop = ratio * (rEditor.scrollHeight - rEditor.clientHeight);
                drawLines();
            }
            isSyncingLeft = false; doLiveSync();
        });
        document.getElementById('right-editor')?.addEventListener('scroll', function() {
            if (!isSyncingRight) {
                isSyncingLeft = true;
                const ratio = this.scrollTop / (this.scrollHeight - this.clientHeight);
                const lEditor = document.getElementById('left-editor');
                lEditor.scrollTop = ratio * (lEditor.scrollHeight - lEditor.clientHeight);
                drawLines();
            }
            isSyncingRight = false; doLiveSync();
        });

        window.addEventListener('resize', drawLines);
    </script>
</body>
</html>
""" # ENDE DES TEMPLATE-STRINGS
# HIER ENDET DATEI server.py (V38.20 DEFINITIV UND VOLLSTÄNDIG)
# ENDE
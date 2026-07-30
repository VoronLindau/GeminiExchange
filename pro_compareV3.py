import difflib
import webbrowser
import os
import json
import html
import csv
import sys
import tkinter as tk
from tkinter import filedialog
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- DOORS Next 7.0.2 Fix: Feldgrößen-Limit aufheben für riesige Rich-Text-Zellen ---
csv.field_size_limit(sys.maxsize)

# --- App Konfiguration ---
APP_VERSION = "v5.3"

def waehle_datei_dialog(titel):
    root = tk.Tk()
    root.withdraw() 
    root.attributes('-topmost', True)
    root.lift()
    root.focus_force()
    
    file_path = filedialog.askopenfilename(
        parent=root, title=titel,
        filetypes=[("Text/Code", "*.txt *.cfg *.py *.xml *.csv *.md *.ini *.gcode"), ("Alle", "*.*")]
    )
    root.destroy() 
    return file_path

def read_file_safe(file_path):
    encodings = ['utf-8-sig', 'cp1252', 'iso-8859-1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc, newline='') as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
            
    with open(file_path, 'r', encoding='utf-8', errors='replace', newline='') as f:
        return f.readlines()

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"path": "", "content": [], "siblings": []}
    
    content = read_file_safe(file_path)
        
    directory = os.path.dirname(file_path)
    valid_ext = ('.txt', '.ini', '.cfg', '.py', '.xml', '.csv', '.md', '.json', '.gcode')
    siblings = []
    try:
        for f_name in os.listdir(directory):
            if f_name.lower().endswith(valid_ext):
                siblings.append({
                    "name": f_name,
                    "path": os.path.join(directory, f_name).replace('\\', '/')
                })
    except Exception: pass
    
    siblings = sorted(siblings, key=lambda x: x['name'].lower())
    return {"path": file_path.replace('\\', '/'), "content": content, "siblings": siblings}

def get_inline_diff(lines_left, lines_right):
    left_res, right_res = [], []
    if len(lines_left) != len(lines_right):
        return [html.escape(l) for l in lines_left], [html.escape(l) for l in lines_right]

    for l, r in zip(lines_left, lines_right):
        sm = difflib.SequenceMatcher(None, l, r)
        out_l, out_r = "", ""
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            chunk_l = html.escape(l[i1:i2])
            chunk_r = html.escape(r[j1:j2])
            if tag == 'equal':
                out_l += chunk_l
                out_r += chunk_r
            else:
                if chunk_l: out_l += f"<span class='char-diff'>{chunk_l}</span>"
                if chunk_r: out_r += f"<span class='char-diff'>{chunk_r}</span>"
        left_res.append(out_l)
        right_res.append(out_r)
    return left_res, right_res

def parse_full_csv(lines, delimiter):
    if delimiter == '\\t': delimiter = '\t'
    reader = csv.reader(lines, delimiter=delimiter)
    parsed_rows = []
    prev_line_num = 0
    
    try:
        for row in reader:
            current_line_num = reader.line_num
            raw_lines = lines[prev_line_num : current_line_num]
            raw_text = "".join(raw_lines)
            parsed_rows.append( (raw_text, row) )
            prev_line_num = current_line_num
    except Exception as e:
        print(f"CSV Warnung (Fallback greift): {e}")
        pass
        
    return parsed_rows

def berechne_csv_diff(text1, text2, col_l, col_r, delimiter):
    parsed1 = parse_full_csv(text1, delimiter)
    parsed2 = parse_full_csv(text2, delimiter)
        
    matched_indices_2 = set()
    diff_data = []
    block_id = 0
    matches = {} 
    
    exact_map_2 = {}
    for j, (raw2, cols2) in enumerate(parsed2):
        key2 = cols2[col_r].strip() if col_r < len(cols2) else ""
        if key2 not in exact_map_2: exact_map_2[key2] = []
        exact_map_2[key2].append(j)
        
    for i, (raw1, cols1) in enumerate(parsed1):
        key1 = cols1[col_l].strip() if col_l < len(cols1) else ""
        if key1 in exact_map_2:
            for j in exact_map_2[key1]:
                if j not in matched_indices_2:
                    matches[i] = (j, 100.0)
                    matched_indices_2.add(j)
                    break
                    
    for i, (raw1, cols1) in enumerate(parsed1):
        if i in matches: continue
        key1 = cols1[col_l].strip() if col_l < len(cols1) else ""
        if not key1: continue 
        
        best_j = -1
        best_ratio = 0.0
        
        for j, (raw2, cols2) in enumerate(parsed2):
            if j in matched_indices_2: continue
            key2 = cols2[col_r].strip() if col_r < len(cols2) else ""
            if not key2: continue
            
            ratio = difflib.SequenceMatcher(None, key1, key2).ratio() * 100
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
                
        if best_j != -1 and best_ratio >= 60.0:
            matches[i] = (best_j, best_ratio)
            matched_indices_2.add(best_j)
            
    for i, (raw1, cols1) in enumerate(parsed1):
        if i in matches:
            j, key_ratio = matches[i]
            raw2, cols2 = parsed2[j]
            
            if key_ratio == 100.0:
                tag = 'equal'
                left_html = [html.escape(raw1)]
                right_html = [html.escape(raw2)]
            else:
                tag = 'replace'
                left_html, right_html = get_inline_diff([raw1], [raw2])
                
            diff_data.append({
                'id': block_id, 'tag': tag,
                'left': left_html, 'right': right_html,
                'raw_left': raw1.splitlines(keepends=True) if raw1 else [],
                'raw_right': raw2.splitlines(keepends=True) if raw2 else [],
                'ratio': round(key_ratio, 1) 
            })
        else:
            diff_data.append({
                'id': block_id, 'tag': 'delete',
                'left': [html.escape(raw1)], 'right': [],
                'raw_left': raw1.splitlines(keepends=True) if raw1 else [],
                'raw_right': [],
                'ratio': 0
            })
        block_id += 1
        
    for j, (raw2, cols2) in enumerate(parsed2):
        if j not in matched_indices_2:
            diff_data.append({
                'id': block_id, 'tag': 'insert',
                'left': [], 'right': [html.escape(raw2)],
                'raw_left': [], 
                'raw_right': raw2.splitlines(keepends=True) if raw2 else [],
                'ratio': 0
            })
            block_id += 1
            
    return diff_data

def berechne_diff_daten(text1, text2):
    sm = difflib.SequenceMatcher(None, text1, text2)
    opcodes = sm.get_opcodes()
    diff_data = []
    block_id = 0
    
    for tag, i1, i2, j1, j2 in opcodes:
        block_left = text1[i1:i2]
        block_right = text2[j1:j2]
        ratio = 0
        
        if tag == 'replace':
            str_left = "".join(block_left)
            str_right = "".join(block_right)
            ratio = round(difflib.SequenceMatcher(None, str_left, str_right).ratio() * 100, 1)
            left_html, right_html = get_inline_diff(block_left, block_right)
        else:
            left_html = [html.escape(l) for l in block_left]
            right_html = [html.escape(l) for l in block_right]
            
        diff_data.append({
            'id': block_id,
            'tag': tag,
            'left': left_html,
            'right': right_html,
            'raw_left': block_left,
            'raw_right': block_right,
            'ratio': ratio
        })
        block_id += 1
    return diff_data

class DiffRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass 

    def do_GET(self):
        global START_FILE_LEFT, START_FILE_RIGHT
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            info_l = get_file_info(START_FILE_LEFT)
            info_r = get_file_info(START_FILE_RIGHT)
            
            html_content = self.get_html_template().replace(
                "INITIAL_RAW_LEFT", json.dumps(info_l['content'])
            ).replace(
                "INITIAL_RAW_RIGHT", json.dumps(info_r['content'])
            ).replace(
                "INITIAL_FILES_LEFT", json.dumps(info_l['siblings'])
            ).replace(
                "INITIAL_FILES_RIGHT", json.dumps(info_r['siblings'])
            ).replace(
                "INITIAL_PATH_LEFT", info_l['path']
            ).replace(
                "INITIAL_PATH_RIGHT", info_r['path']
            ).replace(
                "APP_VERSION", APP_VERSION
            )
            self.wfile.write(html_content.encode('utf-8'))
            
        elif self.path.startswith('/api/select_file'):
            file_path = waehle_datei_dialog("Wähle eine neue Datei")
            info = get_file_info(file_path) if file_path else {"path": None}
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(info).encode('utf-8'))

    def do_POST(self):
        if self.path == '/api/read_file':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            info = get_file_info(data['path'])
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(info).encode('utf-8'))
            
        elif self.path == '/api/diff':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            
            if data.get('isCsv', False):
                col_l = max(0, int(data.get('colLeft', 1)) - 1)
                col_r = max(0, int(data.get('colRight', 1)) - 1)
                delim = data.get('delimiter', ';')
                if delim == '\\t': delim = '\t'
                diff_data = berechne_csv_diff(data['textLeft'], data['textRight'], col_l, col_r, delim)
            else:
                diff_data = berechne_diff_daten(data['textLeft'], data['textRight'])
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(diff_data).encode('utf-8'))

    def get_html_template(self):
        return """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="utf-8">
            <title>Advanced Delta Tool</title>
            <style>
                :root { --bg-dark: #1e1e1e; --bg-panel: #252526; --bg-header: #333333; --text-main: #d4d4d4; --accent: #007acc; --insert: rgba(40, 167, 69, 0.2); --border-insert: #28a745; --delete: rgba(220, 53, 69, 0.2); --border-delete: #dc3545; --replace: rgba(0, 123, 255, 0.2); --border-replace: #007bff; }
                body { margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, sans-serif; height: 100vh; display: flex; flex-direction: column; background-color: var(--bg-dark); color: var(--text-main); overflow: hidden; }
                #header-container { position: sticky; top: 0; z-index: 100; display: flex; flex-direction: column; background: var(--bg-header); box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
                .top-bar { display: flex; border-bottom: 2px solid #444; }
                
                #csv-toolbar { display: none; background: #004a7c; color: white; padding: 8px; text-align: center; font-size: 13px; font-weight: bold; border-bottom: 2px solid #005b99;}
                #csv-toolbar select { background: #fff; border: none; padding: 3px; border-radius: 3px; font-weight: bold; margin-right: 15px; outline: none; cursor: pointer; }
                #csv-toolbar input { width: 40px; text-align: center; background: #fff; border: none; padding: 3px; border-radius: 3px; font-weight: bold; margin: 0 5px;}
                #csv-toolbar button { background: #ff9800; color: #000; border: none; font-weight: bold; padding: 4px 15px; border-radius: 3px; cursor: pointer; margin-left: 15px;}
                
                .pane-header { flex: 1; padding: 10px 15px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
                .pane-header.left { border-right: 1px solid #444; }
                .file-controls { display: flex; gap: 10px; align-items: center; }
                .file-path { font-family: 'Consolas', monospace; font-size: 13px; color: #9cdcfe; padding: 6px; background: #1e1e1e; border: 1px dashed #555; border-radius: 4px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1;}
                .file-path:hover { background: #2a2d2e; border-color: var(--accent); }
                .dir-dropdown { background: #3c3c3c; color: white; border: 1px solid #555; padding: 5px; border-radius: 3px; max-width: 150px; outline: none; cursor: pointer; }
                .search-bar { display: flex; gap: 5px; }
                .search-bar input { flex: 1; padding: 4px 8px; background: #3c3c3c; border: 1px solid #555; color: white; border-radius: 3px; outline: none; min-width: 50px; }
                .search-bar button { background: #555; border: none; color: white; padding: 4px 10px; cursor: pointer; border-radius: 3px; }
                .search-stats { font-size: 12px; align-self: center; color: #aaa; min-width: 40px; text-align: right;}
                .delta-nav-panel { width: 120px; flex-shrink: 0; background: var(--bg-panel); display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 5px; border-left: 1px solid #444; border-right: 1px solid #444; padding: 5px 0; }
                .delta-nav-title { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
                .delta-nav-version { color: var(--accent); font-weight: bold; }
                .delta-nav-buttons button { background: #555; border: none; color: white; padding: 4px 12px; cursor: pointer; border-radius: 3px; font-size: 12px; }
                .delta-nav-stats { font-size: 13px; font-weight: bold; color: #fff; font-family: monospace; margin-top: 2px;}
                
                .filter-btn { flex: 1; background: #007acc; color: white; border: none; padding: 3px 0; font-size: 10px; border-radius: 3px; cursor: pointer; transition: background 0.2s;}
                .filter-btn:hover { background: #005b99; }
                .filter-btn.toggle-active { background-color: #dc3545 !important; border-color: #dc3545 !important; font-weight: bold;}

                #workspace { display: flex; flex: 1; overflow: hidden; position: relative; width: 100%; }
                .editor-container { flex: 1; overflow-y: auto; overflow-x: auto; font-family: 'Consolas', monospace; font-size: 13px; line-height: 1.5; padding: 10px 0; scroll-behavior: smooth; transition: background-color 0.2s; }
                .editor-container::-webkit-scrollbar { width: 12px; height: 12px; }
                .editor-container::-webkit-scrollbar-thumb { background: #555; border-radius: 6px; }
                .drag-over { background-color: rgba(0, 122, 204, 0.1) !important; box-shadow: inset 0 0 10px #007acc; }
                #svg-container { width: 120px; flex-shrink: 0; position: relative; background: var(--bg-panel); border-left: 1px solid #444; border-right: 1px solid #444; cursor: col-resize; }
                svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
                #summary-panel { width: 500px; flex-shrink: 0; background: #1e1e1e; border-left: 2px solid #555; display: flex; flex-direction: column; transition: width 0.3s; }
                .summary-header { background: #333; padding: 8px; text-align: center; font-size: 12px; font-weight: bold; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center;}
                
                #statistics-content { border-bottom: 2px solid #555; background: #252526; padding: 10px 15px; font-family: 'Segoe UI', Tahoma, sans-serif; font-size: 12px; }
                .stat-header { font-weight: bold; color: #9cdcfe; margin-top: 5px; margin-bottom: 8px; text-transform: uppercase; font-size: 11px; letter-spacing: 1px;}
                
                /* NEU v5.3: Klickbare Statistiken */
                .stat-row { display: flex; justify-content: space-between; padding-bottom: 2px;}
                .clickable-stat { cursor: pointer; border-radius: 3px; padding: 2px 4px; margin: 0 -4px 2px -4px; transition: all 0.2s; border: 1px solid transparent; }
                .clickable-stat:hover { background: #3c3c3c; border-color: #555; }
                .stat-num { font-family: monospace; font-size: 13px; font-weight: bold; }
                
                #summary-content { flex: 1; overflow-y: auto; overflow-x: hidden; }
                .summary-row { display: flex; border-bottom: 1px solid #333; cursor: pointer; transition: background-color 0.2s; }
                .summary-row:hover { background-color: #2a2d2e; }
                .summary-col { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 4px; font-family: 'Consolas', monospace; font-size: 11px; }
                .summary-col.left { border-right: none; }
                
                .summary-col-mid { width: 50px; flex-shrink: 0; text-align: center; font-size: 11px; font-weight: bold; background: #252526; color: #fff; display: flex; align-items: center; justify-content: center; border-right: 1px solid #444; border-left: 1px solid #444; }
                .tag-equal .summary-col-mid { color: #28a745; }
                .tag-replace .summary-col-mid { color: #007bff; }
                
                .code-block { padding: 2px 10px; white-space: pre; border-left: 3px solid transparent; border-right: 3px solid transparent; transition: background-color 0.3s; }
                
                .tag-equal { color: #d4d4d4; }
                .tag-insert { background-color: var(--insert); border-right-color: var(--border-insert); }
                .tag-delete { background-color: var(--delete); border-left-color: var(--border-delete); text-decoration: line-through; opacity: 0.7; }
                .tag-replace { background-color: var(--replace); border-left-color: var(--border-replace); border-right-color: var(--border-replace); }
                .char-diff { font-weight: bold; border-radius: 2px; padding: 0 1px; }
                .tag-delete .char-diff { background-color: rgba(220, 53, 69, 0.6); color: white; text-decoration: none; }
                .tag-insert .char-diff { background-color: rgba(40, 167, 69, 0.6); color: white; }
                .tag-replace .char-diff { background-color: rgba(0, 123, 255, 0.6); color: white; }
                .active-delta { outline: 2px solid #ff9800; background-color: rgba(255, 152, 0, 0.2) !important; z-index: 10; position: relative;}
                mark.search-hit { background-color: #ffeb3b; color: black; border-radius: 2px; padding: 0 2px; font-weight: bold; box-shadow: 0 0 4px #ffeb3b;}
                mark.active-hit { background-color: #ff9800; color: white; box-shadow: 0 0 6px #ff9800; outline: 1px solid #fff;}
                .percent-label { font-family: sans-serif; font-size: 10px; font-weight: bold; fill: #fff; text-anchor: middle; dominant-baseline: middle; }
                .label-bg { fill: #007bff; rx: 4; ry: 4; }
                .btn-excel { background-color: #217346; color: white; border: none; padding: 4px 8px; border-radius: 3px; cursor: pointer; font-size: 11px; font-weight: bold; display: flex; align-items: center; gap: 4px; transition: background-color 0.2s;}
                
                #loading-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.85); z-index: 9999; display: none; flex-direction: column; justify-content: center; align-items: center; color: white; font-family: 'Segoe UI', sans-serif;}
                .spinner { border: 6px solid #333; border-top: 6px solid var(--accent); border-radius: 50%; width: 60px; height: 60px; animation: spin 1s linear infinite; margin-bottom: 25px; }
                @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
                .loading-text { font-size: 24px; font-weight: bold; letter-spacing: 1px; }
                .loading-subtext { font-size: 14px; color: #aaa; margin-top: 10px; }
            </style>
        </head>
        <body>
            <div id="loading-overlay">
                <div class="spinner"></div>
                <div class="loading-text">Berechne Unterschiede...</div>
                <div class="loading-subtext">Die Daten werden analysiert. Das kann bei großen Dateien etwas dauern.</div>
            </div>

            <div id="header-container">
                <div class="top-bar">
                    <div class="pane-header left">
                        <div class="file-controls">
                            <div class="file-path" id="path-left" ondblclick="changeFile('left')" title="Doppelklick, um Datei lokal zu öffnen">INITIAL_PATH_LEFT</div>
                            <select id="dropdown-left" class="dir-dropdown" onchange="loadFileFromDropdown('left')"></select>
                        </div>
                        <div class="search-bar">
                            <input type="text" id="search-input-left" placeholder="Suchen..." onkeyup="if(event.key==='Enter') executeSearch('left')">
                            <button onclick="executeSearch('left')">🔍</button>
                            <button onclick="stepSearch('left', -1)">▲</button>
                            <button onclick="stepSearch('left', 1)">▼</button>
                            <span class="search-stats" id="stats-left" style="margin-left:5px">0/0</span>
                        </div>
                    </div>
                    
                    <div class="delta-nav-panel">
                        <div class="delta-nav-title">Deltas <span style="color:var(--accent)">APP_VERSION</span></div>
                        <div class="delta-nav-buttons">
                            <button onclick="stepDelta(-1)">▲</button>
                            <button onclick="stepDelta(1)">▼</button>
                        </div>
                        <div style="display: flex; gap: 4px; width: 90%; margin-top: 2px;">
                            <button id="toggle-deltas-btn" onclick="setFilter('deltas')" class="filter-btn">Deltas</button>
                            <button id="toggle-equals-btn" onclick="setFilter('equals')" class="filter-btn">Gleiche</button>
                        </div>
                        <!-- NEU v5.3: Panel wieder öffnen Button -->
                        <button onclick="toggleSummary()" class="filter-btn" style="width: 90%; margin-top: 4px; background: #444; border: 1px solid #555;" title="Statistik & Übersicht ein/ausblenden">📊 Panel</button>
                        <div class="delta-nav-stats" id="delta-stats-display" style="margin-top: 5px;">0/0</div>
                    </div>
                    
                    <div class="pane-header right">
                        <div class="file-controls">
                            <div class="file-path" id="path-right" ondblclick="changeFile('right')" title="Doppelklick, um Datei lokal zu öffnen">INITIAL_PATH_RIGHT</div>
                            <select id="dropdown-right" class="dir-dropdown" onchange="loadFileFromDropdown('right')"></select>
                        </div>
                        <div class="search-bar">
                            <input type="text" id="search-input-right" placeholder="Suchen..." onkeyup="if(event.key==='Enter') executeSearch('right')">
                            <button onclick="executeSearch('right')">🔍</button>
                            <button onclick="stepSearch('right', -1)">▲</button>
                            <button onclick="stepSearch('right', 1)">▼</button>
                            <span class="search-stats" id="stats-right" style="margin-left:5px">0/0</span>
                        </div>
                    </div>
                </div>
                
                <div id="csv-toolbar">
                    🚀 CSV-Modus: 
                    Trennzeichen 
                    <select id="csv-delimiter">
                        <option value=";">Semikolon (;)</option>
                        <option value=",">Komma (,)</option>
                        <option value="\\t">Tabulator</option>
                        <option value="|">Pipe (|)</option>
                    </select>
                    Vergleiche Spalte (Links) <input type="number" id="csv-col-left" value="1" min="1"> 
                    mit Spalte (Rechts) <input type="number" id="csv-col-right" value="1" min="1">
                    <button onclick="triggerDiffUpdate()">AKTUALISIEREN</button>
                </div>
            </div>

            <div id="workspace">
                <div id="left-editor" class="editor-container"></div>
                <div id="svg-container"><svg id="lines-svg"></svg></div>
                <div id="right-editor" class="editor-container"></div>
                
                <div id="summary-panel">
                    <div class="summary-header">
                        <span style="flex: 1; text-align: left; margin-top: 3px;">ÜBERSICHT & STATISTIK</span>
                        <div style="display: flex; gap: 10px;">
                            <button class="btn-excel" onclick="exportExcel()">📥 EXCEL</button>
                            <button onclick="toggleSummary()" style="background:none; border:none; color:#aaa; cursor:pointer; font-size: 14px;" title="Panel schließen">✖</button>
                        </div>
                    </div>
                    <div id="statistics-content"></div> 
                    <div id="summary-content"></div>
                </div>
            </div>

            <script>
                let diffData = []; 
                let rawLeft = INITIAL_RAW_LEFT;
                let rawRight = INITIAL_RAW_RIGHT;
                let filesLeft = INITIAL_FILES_LEFT;
                let filesRight = INITIAL_FILES_RIGHT;
                
                let deltaBlocks = [];
                let currentDeltaIndex = -1;
                let activeFilter = 'all'; // Filter State: 'all', 'deltas', 'equals', 'delete', 'insert', '100', '90', '80', '70', '60', 'low'
                let currentZoom = 13; 
                let isSummaryVisible = true;
                
                const leftEditor = document.getElementById('left-editor');
                const rightEditor = document.getElementById('right-editor');
                const svgContainer = document.getElementById('svg-container');
                const svg = document.getElementById('lines-svg');
                
                function toggleLoading(show) {
                    document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
                }

                function checkCsvMode() {
                    const pL = document.getElementById('path-left').textContent.toLowerCase().trim();
                    const pR = document.getElementById('path-right').textContent.toLowerCase().trim();
                    const tb = document.getElementById('csv-toolbar');
                    if (pL.endsWith('.csv') || pR.endsWith('.csv')) {
                        tb.style.display = 'block'; return true;
                    } else {
                        tb.style.display = 'none'; return false;
                    }
                }

                function showWaitingPrompt() {
                    leftEditor.innerHTML = '<div style="padding: 30px; color: #007acc; font-size: 18px; font-weight: bold; line-height: 1.5;">🚀 CSV-Dateien erkannt!<br><br><span style="color:#aaa; font-size: 14px; font-weight: normal;">Bitte wähle oben das Trennzeichen und die Spalten aus und klicke auf "AKTUALISIEREN".</span><br><br><span style="color:#888; font-size: 12px; font-weight: normal;">Tipp: Wenn du Export-Dateien aus DOORS Next nutzt, öffne sie am besten über einen Doppelklick auf den Dateipfad oben, statt per Drag&Drop. So werden alle DOORS-Sonderzeichen korrekt gelesen!</span></div>';
                    rightEditor.innerHTML = ''; svg.innerHTML = '';
                    document.getElementById('summary-content').innerHTML = '';
                    document.getElementById('statistics-content').innerHTML = '';
                    document.getElementById('delta-stats-display').textContent = '0/0';
                }

                function updateDropdown(side, siblings, currentPath) {
                    const select = document.getElementById(`dropdown-${side}`);
                    select.innerHTML = '<option value="">-- Im Ordner --</option>';
                    siblings.forEach(f => {
                        const opt = document.createElement('option');
                        opt.value = f.path; opt.textContent = f.name;
                        if (f.path === currentPath) opt.selected = true;
                        select.appendChild(opt);
                    });
                }

                function initDeltas() {
                    // Sammelt nur Deltas, die auch durch den aktuellen Filter SICHTBAR sind!
                    deltaBlocks = diffData.filter(b => shouldShow(b.tag, b.ratio));
                    currentDeltaIndex = -1;
                    document.getElementById('delta-stats-display').textContent = deltaBlocks.length > 0 ? `0/${deltaBlocks.length}` : "0/0";
                }

                function stepDeltaToId(targetId) {
                    const idx = deltaBlocks.findIndex(b => b.id === targetId);
                    if(idx !== -1) { currentDeltaIndex = idx - 1; stepDelta(1); }
                }

                function stepDelta(direction) {
                    if (deltaBlocks.length === 0) return;
                    if (currentDeltaIndex >= 0 && currentDeltaIndex < deltaBlocks.length) {
                        const oldId = deltaBlocks[currentDeltaIndex].id;
                        document.getElementById(`left-block-${oldId}`)?.classList.remove('active-delta');
                        document.getElementById(`right-block-${oldId}`)?.classList.remove('active-delta');
                    }
                    currentDeltaIndex += direction;
                    if (currentDeltaIndex >= deltaBlocks.length) currentDeltaIndex = 0;
                    if (currentDeltaIndex < 0) currentDeltaIndex = deltaBlocks.length - 1;
                    
                    const targetId = deltaBlocks[currentDeltaIndex].id;
                    const leftEl = document.getElementById(`left-block-${targetId}`);
                    const rightEl = document.getElementById(`right-block-${targetId}`);
                    
                    if (leftEl) leftEl.classList.add('active-delta');
                    if (rightEl) rightEl.classList.add('active-delta');
                    if (leftEl) leftEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    else if (rightEl) rightEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    document.getElementById('delta-stats-display').textContent = `${currentDeltaIndex + 1}/${deltaBlocks.length}`;
                }

                // --- NEU v5.3: Zentrales Filter-Management ---
                function setFilter(filterType) {
                    if (activeFilter === filterType) {
                        activeFilter = 'all'; // Klick auf aktiven Filter schaltet ihn aus
                    } else {
                        activeFilter = filterType;
                    }
                    updateStatistics(); // UI-Highlight in der Statistik aktualisieren
                    applyFilters();     // Blöcke ein/ausblenden
                }

                function shouldShow(tag, ratio) {
                    if (activeFilter === 'all') return true;
                    if (activeFilter === 'deltas') return tag !== 'equal';
                    if (activeFilter === 'equals' || activeFilter === '100') return tag === 'equal';
                    if (activeFilter === 'delete') return tag === 'delete';
                    if (activeFilter === 'insert') return tag === 'insert';

                    // Ab hier gelten Filter nur noch für Ähnlichkeits-Treffer
                    if (tag !== 'replace') return false;

                    if (activeFilter === '90') return ratio >= 90 && ratio < 100;
                    if (activeFilter === '80') return ratio >= 80 && ratio < 90;
                    if (activeFilter === '70') return ratio >= 70 && ratio < 80;
                    if (activeFilter === '60') return ratio >= 60 && ratio < 70;
                    if (activeFilter === 'low') return ratio < 60;

                    return true;
                }

                function applyFilters() {
                    document.getElementById('toggle-deltas-btn').classList.toggle('toggle-active', activeFilter === 'deltas');
                    document.getElementById('toggle-equals-btn').classList.toggle('toggle-active', activeFilter === 'equals');

                    document.querySelectorAll('.code-block').forEach(el => {
                        let tag = el.getAttribute('data-tag');
                        let ratio = parseFloat(el.getAttribute('data-ratio'));
                        el.style.display = shouldShow(tag, ratio) ? 'block' : 'none';
                    });

                    document.querySelectorAll('.summary-row').forEach(row => {
                        let tag = row.getAttribute('data-tag');
                        let ratio = parseFloat(row.getAttribute('data-ratio'));
                        row.style.display = shouldShow(tag, ratio) ? 'flex' : 'none';
                    });

                    initDeltas(); // Up/Down Pfeile passen sich dem neuen Filter an!

                    if (document.getElementById('search-input-left').value) executeSearch('left');
                    if (document.getElementById('search-input-right').value) executeSearch('right');
                    setTimeout(drawLines, 50); 
                }

                function toggleSummary() {
                    isSummaryVisible = !isSummaryVisible;
                    const panel = document.getElementById('summary-panel');
                    panel.style.width = isSummaryVisible ? '500px' : '0px';
                    panel.style.borderLeft = isSummaryVisible ? '2px solid #555' : 'none';
                    setTimeout(drawLines, 300);
                }

                function createStatRow(label, count, filterKey, color) {
                    let isActive = (activeFilter === filterKey);
                    let activeStyle = isActive ? 'background: #007acc; color: white; border-color: #4dc3ff;' : '';
                    return `<div class="stat-row clickable-stat" style="${activeStyle}" onclick="setFilter('${filterKey}')" title="Klicken, um diesen Datensatz zu filtern">
                                <span>${label}</span>
                                <span class="stat-num" style="color:${isActive ? 'white' : color}">${count}</span>
                            </div>`;
                }

                function updateStatistics() {
                    let statsL = { total: 0, unmatch: 0, exakt: 0, m90: 0, m80: 0, m70: 0, m60: 0, mLow: 0 };
                    let statsR = { total: 0, unmatch: 0, exakt: 0, m90: 0, m80: 0, m70: 0, m60: 0, mLow: 0 };

                    diffData.forEach(b => {
                        let linesL = b.raw_left ? b.raw_left.length : 0;
                        let linesR = b.raw_right ? b.raw_right.length : 0;
                        
                        statsL.total += linesL;
                        statsR.total += linesR;

                        if (b.tag === 'equal') {
                            statsL.exakt += linesL; statsR.exakt += linesR;
                        } else if (b.tag === 'delete') {
                            statsL.unmatch += linesL;
                        } else if (b.tag === 'insert') {
                            statsR.unmatch += linesR;
                        } else if (b.tag === 'replace') {
                            if (b.ratio >= 90) { statsL.m90 += linesL; statsR.m90 += linesR; }
                            else if (b.ratio >= 80) { statsL.m80 += linesL; statsR.m80 += linesR; }
                            else if (b.ratio >= 70) { statsL.m70 += linesL; statsR.m70 += linesR; }
                            else if (b.ratio >= 60) { statsL.m60 += linesL; statsR.m60 += linesR; }
                            else { statsL.mLow += linesL; statsR.mLow += linesR; }
                        }
                    });

                    let html = `
                        <div style="display: flex; gap: 15px;">
                            <div style="flex: 1; border-right: 1px solid #444; padding-right: 15px;">
                                <div class="stat-header">LINKS (Original)</div>
                                <div class="stat-row" style="margin-bottom:6px;"><span>Gesamtzeilen:</span> <span class="stat-num">${statsL.total}</span></div>
                                ${createStatRow('Ohne Partner:', statsL.unmatch, 'delete', '#dc3545')}
                                <div style="margin-top: 6px; border-top: 1px dashed #444; padding-top: 6px;"></div>
                                ${createStatRow('100% (Spalte gleich):', statsL.exakt, '100', '#d4d4d4')}
                                ${createStatRow('90% - 99%:', statsL.m90, '90', '#d4d4d4')}
                                ${createStatRow('80% - 89%:', statsL.m80, '80', '#d4d4d4')}
                                ${createStatRow('70% - 79%:', statsL.m70, '70', '#d4d4d4')}
                                ${createStatRow('60% - 69%:', statsL.m60, '60', '#d4d4d4')}
                                ${createStatRow('< 60%:', statsL.mLow, 'low', '#d4d4d4')}
                            </div>
                            <div style="flex: 1;">
                                <div class="stat-header">RECHTS (Geändert)</div>
                                <div class="stat-row" style="margin-bottom:6px;"><span>Gesamtzeilen:</span> <span class="stat-num">${statsR.total}</span></div>
                                ${createStatRow('Ohne Partner:', statsR.unmatch, 'insert', '#28a745')}
                                <div style="margin-top: 6px; border-top: 1px dashed #444; padding-top: 6px;"></div>
                                ${createStatRow('100% (Spalte gleich):', statsR.exakt, '100', '#d4d4d4')}
                                ${createStatRow('90% - 99%:', statsR.m90, '90', '#d4d4d4')}
                                ${createStatRow('80% - 89%:', statsR.m80, '80', '#d4d4d4')}
                                ${createStatRow('70% - 79%:', statsR.m70, '70', '#d4d4d4')}
                                ${createStatRow('60% - 69%:', statsR.m60, '60', '#d4d4d4')}
                                ${createStatRow('< 60%:', statsR.mLow, 'low', '#d4d4d4')}
                            </div>
                        </div>
                    `;
                    document.getElementById('statistics-content').innerHTML = html;
                }

                function exportExcel() {
                    const pathLeft = document.getElementById('path-left').textContent;
                    const pathRight = document.getElementById('path-right').textContent;
                    let htmlTable = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40"><head><meta charset="utf-8"><style>table { border-collapse: collapse; font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; } th { background-color: #333333; color: #ffffff; padding: 6px; text-align: left; border: 1px solid #777777; font-weight: bold;} td { border: 1px solid #cccccc; padding: 4px 6px; vertical-align: top; mso-number-format: "\\@"; }</style></head><body><table><tr><th>Original (Links):<br><span style="font-weight: normal; font-size: 10px;">${pathLeft}</span></th><th>Übereinstimmung</th><th>Geändert (Rechts):<br><span style="font-weight: normal; font-size: 10px;">${pathRight}</span></th></tr>`;

                    diffData.forEach(block => {
                        // Exportiert nur, was der Benutzer auch durch den Filter sieht
                        if (!shouldShow(block.tag, block.ratio)) return;
                        
                        let bgL = 'transparent', bgR = 'transparent', styleL = '', styleR = '';
                        let ratioTxt = '-';
                        
                        if (block.tag === 'delete') { 
                            bgL = '#f8d7da'; styleL = 'background-color: #dc3545; color: white; font-weight: bold; text-decoration: line-through;'; 
                        } 
                        else if (block.tag === 'insert') { 
                            bgR = '#d4edda'; styleR = 'background-color: #28a745; color: white; font-weight: bold;'; 
                        } 
                        else if (block.tag === 'replace') { 
                            bgL = bgR = '#cce5ff'; styleL = styleR = 'background-color: #007bff; color: white; font-weight: bold;'; 
                            ratioTxt = block.ratio + '%';
                        }
                        else if (block.tag === 'equal') {
                            ratioTxt = '100%';
                        }

                        let txtL = block.left.join('').replace(/\\r?\\n/g, '<br style="mso-data-placement:same-cell;">').replace(/<span class='char-diff'>/g, `<span style="${styleL}">`);
                        let txtR = block.right.join('').replace(/\\r?\\n/g, '<br style="mso-data-placement:same-cell;">').replace(/<span class='char-diff'>/g, `<span style="${styleR}">`);
                        
                        htmlTable += `<tr>
                            <td style="background-color: ${bgL};">${txtL || '&nbsp;'}</td>
                            <td style="text-align: center; font-weight: bold; vertical-align: middle;">${ratioTxt}</td>
                            <td style="background-color: ${bgR};">${txtR || '&nbsp;'}</td>
                        </tr>`;
                    });
                    htmlTable += `</table></body></html>`;
                    const blob = new Blob([htmlTable], { type: 'application/vnd.ms-excel' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url; a.download = 'Delta_Zusammenfassung.xls';
                    document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
                }

                function renderEditors() {
                    leftEditor.innerHTML = ''; rightEditor.innerHTML = '';
                    const summaryContent = document.getElementById('summary-content');
                    summaryContent.innerHTML = '';
                    
                    diffData.forEach(block => {
                        const leftDiv = document.createElement('div');
                        leftDiv.id = `left-block-${block.id}`; leftDiv.className = `code-block tag-${block.tag}`;
                        leftDiv.setAttribute('data-tag', block.tag); leftDiv.setAttribute('data-ratio', block.ratio);
                        leftDiv.innerHTML = block.left.length > 0 ? block.left.join('') : '\\n'.repeat(block.right.length);
                        leftEditor.appendChild(leftDiv);

                        const rightDiv = document.createElement('div');
                        rightDiv.id = `right-block-${block.id}`; rightDiv.className = `code-block tag-${block.tag}`;
                        rightDiv.setAttribute('data-tag', block.tag); rightDiv.setAttribute('data-ratio', block.ratio);
                        rightDiv.innerHTML = block.right.length > 0 ? block.right.join('') : '\\n'.repeat(block.left.length);
                        rightEditor.appendChild(rightDiv);
                        
                        const row = document.createElement('div');
                        row.className = `summary-row tag-${block.tag}`;
                        row.setAttribute('data-tag', block.tag); row.setAttribute('data-ratio', block.ratio);
                        row.onclick = () => stepDeltaToId(block.id);
                        
                        const sl = document.createElement('div'); sl.className = `summary-col left`; sl.innerHTML = block.left.length > 0 ? block.left.join('') : '&nbsp;';
                        
                        const smid = document.createElement('div'); smid.className = `summary-col-mid`; 
                        if (block.tag === 'equal') smid.textContent = '100%';
                        else if (block.tag === 'replace') smid.textContent = block.ratio + '%';
                        else smid.textContent = '-';
                        
                        const sr = document.createElement('div'); sr.className = `summary-col`; sr.innerHTML = block.right.length > 0 ? block.right.join('') : '&nbsp;';
                        
                        row.appendChild(sl); row.appendChild(smid); row.appendChild(sr); summaryContent.appendChild(row);
                    });
                    
                    updateStatistics();
                    applyFilters(); // Hier wird automatisch initDeltas() mit aufgerufen
                }

                function drawLines() {
                    svg.innerHTML = '';
                    const svgWidth = svgContainer.clientWidth;
                    const leftScroll = leftEditor.scrollTop; const rightScroll = rightEditor.scrollTop;

                    diffData.forEach(block => {
                        if (!shouldShow(block.tag, block.ratio) || block.tag === 'equal') return;
                        
                        const leftEl = document.getElementById(`left-block-${block.id}`);
                        const rightEl = document.getElementById(`right-block-${block.id}`);
                        if (!leftEl || !rightEl || leftEl.style.display === 'none') return;
                        
                        const leftY = leftEl.offsetTop + (leftEl.offsetHeight / 2) - leftScroll;
                        const rightY = rightEl.offsetTop + (rightEl.offsetHeight / 2) - rightScroll;

                        let color = '#007bff';
                        if (block.tag === 'insert') color = '#28a745';
                        if (block.tag === 'delete') color = '#dc3545';

                        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        const curve = `M 0 ${leftY} C ${svgWidth/2} ${leftY}, ${svgWidth/2} ${rightY}, ${svgWidth} ${rightY}`;
                        path.setAttribute('d', curve); path.setAttribute('fill', 'none'); path.setAttribute('stroke', color); path.setAttribute('stroke-width', '2'); path.setAttribute('opacity', '0.6');
                        svg.appendChild(path);

                        if (block.tag === 'replace') {
                            const midY = (leftY + rightY) / 2; const midX = svgWidth / 2;
                            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                            rect.setAttribute('x', midX - 20); rect.setAttribute('y', midY - 10); rect.setAttribute('width', '40'); rect.setAttribute('height', '20'); rect.setAttribute('class', 'label-bg');
                            svg.appendChild(rect);
                            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                            text.setAttribute('x', midX); text.setAttribute('y', midY + 1); text.setAttribute('class', 'percent-label'); text.textContent = `${block.ratio}%`;
                            svg.appendChild(text);
                        }
                    });
                }

                async function triggerDiffUpdate() {
                    toggleLoading(true); 
                    
                    const isCsv = checkCsvMode();
                    const payload = {
                        textLeft: rawLeft, 
                        textRight: rawRight,
                        isCsv: isCsv,
                        delimiter: document.getElementById('csv-delimiter').value,
                        colLeft: document.getElementById('csv-col-left').value,
                        colRight: document.getElementById('csv-col-right').value
                    };
                    
                    try {
                        const diffRes = await fetch('/api/diff', { method: 'POST', body: JSON.stringify(payload) });
                        diffData = await diffRes.json();
                        renderEditors();
                    } catch (e) {
                        console.error("Fehler beim Diff:", e);
                    } finally {
                        toggleLoading(false); 
                    }
                }

                async function loadFileFromDropdown(side) {
                    const select = document.getElementById(`dropdown-${side}`);
                    const path = select.value;
                    if(!path) return;
                    
                    const response = await fetch('/api/read_file', { method: 'POST', body: JSON.stringify({path: path}) });
                    const data = await response.json();
                    
                    document.getElementById(`path-${side}`).textContent = data.path;
                    if (side === 'left') rawLeft = data.content;
                    if (side === 'right') rawRight = data.content;
                    
                    if (checkCsvMode()) {
                        showWaitingPrompt();
                    } else {
                        triggerDiffUpdate();
                    }
                }

                async function changeFile(side) {
                    document.getElementById(`path-${side}`).textContent = "Lade Dateiauswahl...";
                    const response = await fetch('/api/select_file');
                    const data = await response.json();
                    if (data.path) {
                        document.getElementById(`path-${side}`).textContent = data.path;
                        updateDropdown(side, data.siblings, data.path);
                        
                        if (side === 'left') rawLeft = data.content;
                        if (side === 'right') rawRight = data.content;
                        
                        if (checkCsvMode()) {
                            showWaitingPrompt();
                        } else {
                            triggerDiffUpdate();
                        }
                    }
                }

                function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }
                ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => { leftEditor.addEventListener(evt, preventDefaults, false); rightEditor.addEventListener(evt, preventDefaults, false); });
                ['dragenter', 'dragover'].forEach(evt => { leftEditor.addEventListener(evt, () => leftEditor.classList.add('drag-over'), false); rightEditor.addEventListener(evt, () => rightEditor.classList.add('drag-over'), false); });
                ['dragleave', 'drop'].forEach(evt => { leftEditor.addEventListener(evt, () => leftEditor.classList.remove('drag-over'), false); rightEditor.addEventListener(evt, () => rightEditor.classList.remove('drag-over'), false); });
                leftEditor.addEventListener('drop', (e) => handleDrop(e, 'left'), false);
                rightEditor.addEventListener('drop', (e) => handleDrop(e, 'right'), false);

                function handleDrop(e, side) {
                    const file = e.dataTransfer.files[0];
                    if (!file) return;
                    const reader = new FileReader();
                    reader.onload = async function(event) {
                        let content = event.target.result.match(/.*(?:\\r\\n|\\r|\\n)|.+$/g) || [];
                        document.getElementById(`path-${side}`).textContent = `[Drag & Drop] ${file.name}`;
                        document.getElementById(`dropdown-${side}`).innerHTML = '<option>-- Datei gezogen --</option>';
                        
                        if (side === 'left') rawLeft = content;
                        if (side === 'right') rawRight = content;
                        
                        if (checkCsvMode()) {
                            showWaitingPrompt();
                        } else {
                            triggerDiffUpdate();
                        }
                    };
                    reader.readAsText(file);
                }

                let searchState = { left: { hits: [], currentIndex: -1 }, right: { hits: [], currentIndex: -1 } };
                function escapeRegExp(string) { return string.replace(/[.*+?^${}()|[\]\\\\]/g, '\\\\$&'); }
                function clearSearch(side) {
                    const editor = document.getElementById(`${side}-editor`);
                    const marks = Array.from(editor.querySelectorAll('mark.search-hit'));
                    marks.forEach(mark => { const parent = mark.parentNode; parent.replaceChild(document.createTextNode(mark.textContent), mark); parent.normalize(); });
                    searchState[side] = { hits: [], currentIndex: -1 }; document.getElementById(`stats-${side}`).textContent = "0/0";
                }
                function highlightNode(node, regex, hits) {
                    if (node.nodeType === 3) { 
                        let match = node.nodeValue.match(regex);
                        if (match) {
                            const mark = document.createElement('mark'); mark.className = 'search-hit';
                            const splitNode = node.splitText(match.index); const remainderNode = splitNode.splitText(match[0].length);
                            mark.appendChild(splitNode.cloneNode(true)); splitNode.parentNode.replaceChild(mark, splitNode);
                            hits.push(mark); highlightNode(remainderNode, regex, hits); 
                        }
                    } else if (node.nodeType === 1 && node.nodeName !== 'MARK') {
                        const children = Array.from(node.childNodes); children.forEach(child => highlightNode(child, regex, hits));
                    }
                }
                function executeSearch(side) {
                    clearSearch(side);
                    const query = document.getElementById(`search-input-${side}`).value; if (!query) return;
                    const editor = document.getElementById(`${side}-editor`); const regex = new RegExp(escapeRegExp(query), 'i');
                    editor.querySelectorAll('.code-block').forEach(block => {
                        if (block.style.opacity === '0' || block.style.display === 'none') return; 
                        highlightNode(block, regex, searchState[side].hits);
                    });
                    if (searchState[side].hits.length > 0) stepSearch(side, 1);
                    else document.getElementById(`stats-${side}`).textContent = "0/0";
                }
                function stepSearch(side, direction) {
                    const state = searchState[side]; if (state.hits.length === 0) return;
                    if (state.currentIndex >= 0 && state.currentIndex < state.hits.length) state.hits[state.currentIndex].classList.remove('active-hit');
                    state.currentIndex += direction;
                    if (state.currentIndex >= state.hits.length) state.currentIndex = 0;
                    if (state.currentIndex < 0) state.currentIndex = state.hits.length - 1;
                    const targetMark = state.hits[state.currentIndex]; targetMark.classList.add('active-hit');
                    targetMark.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    document.getElementById(`stats-${side}`).textContent = `${state.currentIndex + 1}/${state.hits.length}`;
                }

                window.addEventListener('wheel', (e) => {
                    if (e.ctrlKey) {
                        e.preventDefault(); 
                        if (e.deltaY > 0) currentZoom -= 1; else currentZoom += 1; 
                        if (currentZoom < 4) currentZoom = 4; 
                        leftEditor.style.fontSize = `${currentZoom}px`; rightEditor.style.fontSize = `${currentZoom}px`; drawLines(); 
                    }
                }, {passive: false});

                window.addEventListener('mousedown', (e) => {
                    if (e.ctrlKey && e.button === 1) { 
                        e.preventDefault(); currentZoom = 13; leftEditor.style.fontSize = `13px`; rightEditor.style.fontSize = `13px`; drawLines(); 
                    }
                });

                let isSyncingLeft = false; let isSyncingRight = false;
                leftEditor.addEventListener('scroll', function() { if (!isSyncingLeft) { isSyncingRight = true; rightEditor.scrollTop = (this.scrollTop / (this.scrollHeight - this.clientHeight)) * (rightEditor.scrollHeight - rightEditor.clientHeight); drawLines(); } isSyncingLeft = false; });
                rightEditor.addEventListener('scroll', function() { if (!isSyncingRight) { isSyncingLeft = true; leftEditor.scrollTop = (this.scrollTop / (this.scrollHeight - this.clientHeight)) * (leftEditor.scrollHeight - leftEditor.clientHeight); drawLines(); } isSyncingRight = false; });

                let isDragging = false;
                svgContainer.addEventListener('mousedown', () => { isDragging = true; document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none'; });
                document.addEventListener('mousemove', (e) => {
                    if (!isDragging) return;
                    const cr = document.getElementById('workspace').getBoundingClientRect(); const totalW = cr.width;
                    const lFlex = (e.clientX - cr.left - 60) / totalW; const rFlex = 1 - lFlex - (120 / totalW);
                    if (lFlex > 0.1 && rFlex > 0.1) { leftEditor.style.flex = lFlex; rightEditor.style.flex = rFlex; drawLines(); }
                });
                document.addEventListener('mouseup', () => { if (isDragging) { isDragging = false; document.body.style.cursor = 'default'; document.body.style.userSelect = 'auto'; } });

                window.onload = () => { 
                    updateDropdown('left', filesLeft, document.getElementById('path-left').textContent);
                    updateDropdown('right', filesRight, document.getElementById('path-right').textContent);
                    
                    if (checkCsvMode()) {
                        showWaitingPrompt();
                    } else {
                        triggerDiffUpdate(); 
                    }
                };
                window.addEventListener('resize', drawLines);
            </script>
        </body>
        </html>
        """

def start_app():
    global START_FILE_LEFT, START_FILE_RIGHT
    print(f"Starte Advanced Delta Tool {APP_VERSION}...")
    
    START_FILE_LEFT = waehle_datei_dialog("Wähle die LINKE Datei")
    if not START_FILE_LEFT: return
    START_FILE_RIGHT = waehle_datei_dialog("Wähle die RECHTE Datei")
    if not START_FILE_RIGHT: return
    
    server = HTTPServer(('localhost', 0), DiffRequestHandler)
    port = server.server_port 
    
    print(f"\nServer läuft auf http://localhost:{port}")
    webbrowser.open(f'http://localhost:{port}')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")
        server.server_close()

if __name__ == "__main__":
    start_app()
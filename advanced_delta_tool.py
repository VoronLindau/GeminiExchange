import os
import re
import json
import zipfile
import hashlib
import difflib
import tkinter as tk
from tkinter import filedialog
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading
import html
import tempfile
import collections
from urllib.parse import urlparse, parse_qs

APP_VERSION = "v20.0 (Media-Diff & Word Live-Sync Engine)"

START_FILE_LEFT = ""
START_FILE_RIGHT = ""
DISPLAY_NAME_LEFT = ""
DISPLAY_NAME_RIGHT = ""

# ==========================================
# MODUS 1: MICROSOFT WORD COM-STEUERUNG
# ==========================================
def jump_to_word_page(file_path, page_num):
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = True 
        
        abs_path = os.path.abspath(file_path)
        doc = None
        for d in word.Documents:
            if d.FullName.lower() == abs_path.lower():
                doc = d
                break
        if not doc:
            doc = word.Documents.Open(abs_path)
            
        doc.Activate()
        word.Activate()
        # wdGoToPage = 1, wdGoToAbsolute = 1
        word.Selection.GoTo(1, 1, int(page_num))
        return True
    except Exception as e:
        return False

# ==========================================
# MODUS 2: PURE PYTHON XML PARSER
# ==========================================
def get_docx_data(file_path):
    content = []
    objects = {}
    page_count = [1] 
    
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            rels = {}
            if 'word/_rels/document.xml.rels' in z.namelist():
                import xml.etree.ElementTree as ET
                rels_root = ET.fromstring(z.read('word/_rels/document.xml.rels'))
                for rel in rels_root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                    target = rel.get('Target')
                    if target:
                        if not target.startswith('word/'): target = 'word/' + target
                        rels[rel.get('Id')] = target

            for name in z.namelist():
                if name.startswith(('word/media/', 'word/embeddings/')):
                    objects[name] = hashlib.sha256(z.read(name)).hexdigest()

            if 'word/document.xml' in z.namelist():
                import xml.etree.ElementTree as ET
                doc_root = ET.fromstring(z.read('word/document.xml'))
                
                for p in doc_root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    para_text = ""
                    for node in p.iter():
                        if node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lastRenderedPageBreak' or \
                           (node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br' and node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type') == 'page'):
                            page_count[0] += 1
                            para_text += f"\n[SEITENUMBRUCH: {page_count[0]}]\n"
                        elif node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t' and node.text:
                            para_text += node.text
                        elif node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tab':
                            para_text += " " 
                        elif node.tag in ('{http://schemas.openxmlformats.org/drawingml/2006/main}blip', '{urn:schemas-microsoft-com:vml}imagedata'):
                            r_id = node.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed') or node.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                            if r_id and r_id in rels:
                                img_path = rels[r_id]
                                img_hash = objects.get(img_path, "NO_HASH")
                                para_text += f"\n[BILD: {img_path} | HASH: {img_hash}]\n"
                    
                    txt = para_text.strip()
                    if txt: content.append(txt)
                
    except Exception as e:
        print(f"Fehler beim XML-Parsing: {e}")
    return content, objects

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"path": "", "content": ["\n\n\n\n     ⬇ Bitte eine Office-Datei per Drag & Drop hier ablegen ⬇\n\n\n"], "objects": {}}
    
    if file_path.lower().endswith('.docx'):
        content, objects = get_docx_data(file_path)
    else:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = [l.strip() for l in f.readlines() if l.strip()]
        objects = {}
    return {"path": file_path.replace('\\', '/'), "content": content, "objects": objects}

def heal_text(lines):
    res = []
    last_major = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        m = re.match(r'^(\d+)(?:\.|$)', line)
        if m: last_major = m.group(1)
        
        if re.match(r'^\d+\.?$', line) and i+1 < len(lines) and re.match(r'^\.\d+', lines[i+1].strip()):
            merged = line + lines[i+1].strip()
            res.append(merged)
            m2 = re.match(r'^(\d+)', merged)
            if m2: last_major = m2.group(1)
            i += 2
            continue
            
        if re.match(r'^\.\d+', line) and last_major:
            res.append(last_major + line)
            i += 1
            continue
            
        res.append(line)
        i += 1
    return res

def extract_id(text):
    m = re.match(r'^\s*(?:ID\s+\d+:|\[REQ-\d+\]|REQ\s+\d+:|\d+\.\d+(?:\.\d+)*[a-zA-Z]?)(?:\s|$)', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    return None

def highlight_inline(str_l, str_r):
    if len(str_l) > 3000 or len(str_r) > 3000:
        return f"<span class='char-diff'>{html.escape(str_l)}</span>", f"<span class='char-diff'>{html.escape(str_r)}</span>"
        
    sm_inline = difflib.SequenceMatcher(None, str_l, str_r)
    left_out, right_out = "", ""
    for op_in, m1, m2, n1, n2 in sm_inline.get_opcodes():
        if op_in == 'equal':
            left_out += html.escape(str_l[m1:m2])
            right_out += html.escape(str_r[n1:n2])
        else:
            if m1 != m2: left_out += f"<span class='char-diff'>{html.escape(str_l[m1:m2])}</span>"
            if n1 != n2: right_out += f"<span class='char-diff'>{html.escape(str_r[n1:n2])}</span>"
    return left_out, right_out

def berechne_diff_daten(lines_left, lines_right):
    lines_left = heal_text(lines_left)
    lines_right = heal_text(lines_right)
    
    sm = difflib.SequenceMatcher(None, lines_left, lines_right)
    
    buckets = collections.OrderedDict()
    current_id = "HEADER (Deckblatt/Inhaltsverzeichnis)"
    buckets[current_id] = []
    
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for l, r in zip(lines_left[i1:i2], lines_right[j1:j2]):
                cid = extract_id(r) or extract_id(l)
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                buckets[current_id].append({'tag': 'equal', 'left': html.escape(l), 'right': html.escape(r)})
                
        elif op == 'replace':
            sub_l = lines_left[i1:i2]
            sub_r = lines_right[j1:j2]
            for k in range(max(len(sub_l), len(sub_r))):
                l = sub_l[k] if k < len(sub_l) else ""
                r = sub_r[k] if k < len(sub_r) else ""
                
                cid = extract_id(r) or extract_id(l)
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                
                if l and r:
                    l_out, r_out = highlight_inline(l, r)
                    buckets[current_id].append({'tag': 'replace', 'left': l_out, 'right': r_out})
                elif l:
                    buckets[current_id].append({'tag': 'delete', 'left': html.escape(l), 'right': ""})
                elif r:
                    buckets[current_id].append({'tag': 'insert', 'left': "", 'right': html.escape(r)})
                    
        elif op == 'delete':
            for l in lines_left[i1:i2]:
                cid = extract_id(l)
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                buckets[current_id].append({'tag': 'delete', 'left': html.escape(l), 'right': ""})
                
        elif op == 'insert':
            for r in lines_right[j1:j2]:
                cid = extract_id(r)
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                buckets[current_id].append({'tag': 'insert', 'left': "", 'right': html.escape(r)})

    left_ids = set()
    right_ids = set()
    img_diffs = 0
    
    for cid, items in buckets.items():
        if cid != "HEADER (Deckblatt/Inhaltsverzeichnis)":
            if any(i['left'] for i in items): left_ids.add(cid)
            if any(i['right'] for i in items): right_ids.add(cid)
            
        # Zähle veränderte Bilder in nicht-gleichen Blöcken
        for item in items:
            if item['tag'] != 'equal':
                img_l = len(re.findall(r'\[BILD:', item['left']))
                img_r = len(re.findall(r'\[BILD:', item['right']))
                img_diffs += max(img_l, img_r)
        
    stats = {
        "l_eq": 0, "l_rep": 0, "l_del": len(left_ids - right_ids), "l_tot": len(left_ids),
        "r_eq": 0, "r_rep": 0, "r_ins": len(right_ids - left_ids), "r_tot": len(right_ids),
        "img_diffs": img_diffs,
        "has_reqs": len(left_ids) > 0 or len(right_ids) > 0
    }
    
    intersect = left_ids & right_ids
    for cid in intersect:
        has_diff = any(i['tag'] != 'equal' and (i['left'] or i['right']) for i in buckets[cid])
        if not has_diff:
            stats['l_eq'] += 1; stats['r_eq'] += 1
        else:
            stats['l_rep'] += 1; stats['r_rep'] += 1

    diff_data = []
    block_id = 0
    for cid, items in buckets.items():
        if not items: continue
        left_htmls, right_htmls = [], []
        tag_set = set()
        
        prefix = f"<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px;'>[{cid}]</div>" if cid != "HEADER (Deckblatt/Inhaltsverzeichnis)" else ""
        
        for item in items:
            left_htmls.append(f"<div class='inner-line bg-{item['tag']}'>{item['left']}</div>" if item['left'] else "<div class='inner-line bg-empty'></div>")
            right_htmls.append(f"<div class='inner-line bg-{item['tag']}'>{item['right']}</div>" if item['right'] else "<div class='inner-line bg-empty'></div>")
            tag_set.add(item['tag'])
            
        overall_tag = 'equal' if tag_set == {'equal'} else 'replace'
        
        diff_data.append({
            'id': block_id,
            'req_id': cid,
            'tag': overall_tag,
            'left': prefix + "".join(left_htmls),
            'right': prefix + "".join(right_htmls)
        })
        block_id += 1

    return diff_data, stats

class DiffRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass 

    def do_POST(self):
        global START_FILE_LEFT, START_FILE_RIGHT, DISPLAY_NAME_LEFT, DISPLAY_NAME_RIGHT
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
                START_FILE_LEFT = save_path; DISPLAY_NAME_LEFT = filename
            elif side == 'right':
                START_FILE_RIGHT = save_path; DISPLAY_NAME_RIGHT = filename
                
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

    def do_GET(self):
        global START_FILE_LEFT, START_FILE_RIGHT, DISPLAY_NAME_LEFT, DISPLAY_NAME_RIGHT
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/diff_data':
            try:
                info_l = get_file_info(START_FILE_LEFT)
                info_r = get_file_info(START_FILE_RIGHT)
                diff, stats = berechne_diff_daten(info_l['content'], info_r['content'])
                self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({"diff": diff, "stats": stats}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return
            
        if parsed_url.path == '/api/jump':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            page = query.get('page', ['1'])[0]
            
            target_file = START_FILE_LEFT if side == 'left' else START_FILE_RIGHT
            success = jump_to_word_page(target_file, page)
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            return
            
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type', 'text/html; charset=utf-8'); self.end_headers()
            name_l = DISPLAY_NAME_LEFT if DISPLAY_NAME_LEFT else "Keine Datei (Links)"
            name_r = DISPLAY_NAME_RIGHT if DISPLAY_NAME_RIGHT else "Keine Datei (Rechts)"
            html_content = self.get_html_template().replace("APP_VERSION", APP_VERSION).replace("NAME_LEFT", name_l).replace("NAME_RIGHT", name_r)
            self.wfile.write(html_content.encode('utf-8'))

    def get_html_template(self):
        return """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="utf-8">
            <title>Advanced Delta Tool</title>
            <style>
                :root { --bg-dark: #1e1e1e; --bg-panel: #252526; --text-main: #d4d4d4; }
                body { margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; background: var(--bg-dark); color: var(--text-main); overflow: hidden; }
                #header-container { display: flex; background: #333; border-bottom: 2px solid #444; }
                .pane-header { flex: 1; padding: 10px; display: flex; justify-content: space-between; align-items: center; }
                .pane-header.left { border-right: 1px solid #444; }
                .header-title { font-weight: bold; color: #9cdcfe; font-size: 15px; max-width: 350px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: #1e1e1e; padding: 4px 10px; border-radius: 4px; border: 1px solid #555;}
                .view-select { background: #007acc; border: 1px solid #005f9e; color: white; padding: 5px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; cursor: pointer; outline: none;}
                .word-btn { background: #107c41; margin-top: 5px; width: 100%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
                .center-panel { width: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: var(--bg-panel); padding: 5px 10px; font-size: 10px; color: #888; border-left: 1px solid #444; border-right: 1px solid #444; box-sizing: border-box;}
                #workspace { display: flex; flex: 1; overflow: hidden; position: relative; }
                .editor-container { flex: 1; overflow-y: auto; padding: 10px; font-size: 13px; line-height: 1.5; scroll-behavior: smooth; position: relative;}
                .editor-container.drag-over { border: 3px dashed #007acc !important; background-color: rgba(0, 122, 204, 0.1) !important; }
                .drag-overlay { display: none; position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.6); color: #007acc; font-size: 24px; font-weight: bold; align-items: center; justify-content: center; z-index: 100; pointer-events: none;}
                .editor-container.drag-over .drag-overlay { display: flex; }
                #svg-container { width: 100px; flex-shrink: 0; position: relative; background: var(--bg-panel); border-left: 1px solid #444; border-right: 1px solid #444; }
                svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
                
                .bucket-block { background-color: #252526; border: 1px solid #444; border-radius: 4px; margin-bottom: 12px; padding: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.2);}
                .inner-line { padding: 2px 5px; margin-bottom: 3px; border-radius: 2px; min-height: 1.2em; word-wrap: break-word; font-family: 'Consolas', monospace;}
                
                .bg-insert { background-color: rgba(40, 167, 69, 0.2); border-left: 3px solid #28a745; }
                .bg-delete { background-color: rgba(220, 53, 69, 0.2); border-left: 3px solid #dc3545; text-decoration: line-through; opacity: 0.8; }
                .bg-replace { background-color: rgba(0, 123, 255, 0.2); border-left: 3px solid #007bff; }
                .bg-equal { background-color: transparent; border-left: 3px solid #555; }
                .bg-empty { background-color: transparent; min-height: 1.2em; }
                
                .char-diff { background-color: rgba(0, 123, 255, 0.6); color: white; font-weight: bold; border-radius: 2px; padding: 0 2px; }
                
                .page-break-line { border-top: 1px dashed #dc3545; margin: 15px 0; position: relative; width: 100%; }
                .page-break-line span { 
                    background: #dc3545; color: white; padding: 2px 6px; font-size: 11px; font-weight: bold; 
                    border-radius: 0 0 0 4px; position: absolute; right: 0; top: 0; display: flex; align-items: center; gap: 6px;
                }
                .jump-btn { background: #1e1e1e; color: #fff; border: 1px solid #fff; border-radius: 3px; font-size: 9px; cursor: pointer; padding: 2px 4px;}
                .jump-btn:hover { background: #fff; color: #dc3545; }
                
                .editor-container.view-delta .tag-equal { display: none !important; }
                .editor-container.view-equal .tag-replace, .editor-container.view-equal .tag-insert, .editor-container.view-equal .tag-delete { display: none !important; }
                
                #loading-screen { position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); color:#007acc; font-size:24px; font-weight:bold; z-index: 1000; text-align: center; }
            </style>
        </head>
        <body>
            <div id="loading-screen">⏳ Lade Semantic Engine...</div>

            <div id="header-container" style="visibility: hidden;">
                <div class="pane-header left">
                    <span class="header-title" title="NAME_LEFT">📄 NAME_LEFT</span>
                    <select id="view-left" class="view-select" onchange="changeView('left')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
                </div>
                
                <div class="center-panel">
                    <div style="margin-bottom: 5px; font-weight:bold;">APP_VERSION</div>
                    <div id="req-mode-badge" style="display:none; background:#28a745; color:white; padding:2px 4px; border-radius:3px; margin-bottom: 5px; font-weight:bold;">✅ SEMANTIC SYNC</div>
                    
                    <div id="stats-panel" style="display:none; width: 100%; background: #1e1e1e; border-radius: 4px; padding: 6px; box-sizing: border-box; text-align: left; margin-bottom: 5px; border: 1px solid #444;">
                        <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center; border-bottom:1px solid #444; padding-bottom:3px;"><b>Statistik</b></div>
                        <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                            <div style="width: 48%;">
                                <u style="color:#9cdcfe">Links</u><br>Gleich: <span id="l-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="l-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>Gelöscht: <span id="l-del" style="float:right; font-weight:bold; color:#dc3545;">0</span>
                            </div>
                            <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;">
                                <u style="color:#9cdcfe">Rechts</u><br>Gleich: <span id="r-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="r-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>Neu: <span id="r-ins" style="float:right; font-weight:bold; color:#28a745;">0</span>
                            </div>
                        </div>
                        <div style="border-top: 1px solid #444; margin-top: 4px; padding-top: 4px; text-align: center; font-size: 9px; font-weight: bold; color: #ff9800;">
                            Bilder geändert: <span id="img-diffs">0</span>
                        </div>
                    </div>

                    <div style="margin-top: 5px; text-align: center; font-size: 11px; background: #1e1e1e; border: 1px solid #444; padding: 4px; border-radius: 3px; width: 100%; box-sizing: border-box;">
                        <b style="color: #9cdcfe;">MS Word Live-Sync</b><br>
                        <label style="cursor:pointer;"><input type="checkbox" id="sync-left" onchange="doLiveSync()"> Links</label> &nbsp;
                        <label style="cursor:pointer;"><input type="checkbox" id="sync-right" onchange="doLiveSync()"> Rechts</label>
                    </div>

                    <button class="word-btn" onclick="window.print()">🖨️ PDF Report</button>
                </div>
                
                <div class="pane-header right">
                    <span class="header-title" title="NAME_RIGHT">📄 NAME_RIGHT</span>
                    <select id="view-right" class="view-select" onchange="changeView('right')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
                </div>
            </div>

            <div id="workspace" style="visibility: hidden;">
                <div id="left-editor" class="editor-container" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event, 'left')"></div>
                <div id="svg-container"><svg id="lines-svg"></svg></div>
                <div id="right-editor" class="editor-container" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event, 'right')"></div>
            </div>

            <script>
                let diffData = []; let statsData = {};
                let syncTimer = null;
                let lastPageL = -1; let lastPageR = -1;
                
                window.onload = function() {
                    fetch('/api/diff_data').then(res => res.json()).then(data => {
                        if (data.error) { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${data.error}</span>`; return; }
                        diffData = data.diff; statsData = data.stats;
                        document.getElementById('loading-screen').style.display = 'none';
                        document.getElementById('header-container').style.visibility = 'visible';
                        document.getElementById('workspace').style.visibility = 'visible';
                        renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'));
                    }).catch(err => { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Browser-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${err}</span>`; });
                };

                const svgContainer = document.getElementById('svg-container');

                function handleDragOver(e) { e.preventDefault(); e.currentTarget.classList.add('drag-over'); }
                function handleDragLeave(e) { e.preventDefault(); e.currentTarget.classList.remove('drag-over'); }
                async function handleDrop(e, side) {
                    e.preventDefault(); e.currentTarget.classList.remove('drag-over');
                    const file = e.dataTransfer.files[0];
                    if (!file) return;
                    e.currentTarget.querySelector('.drag-overlay').style.display = "flex";
                    try {
                        const arrayBuffer = await file.arrayBuffer();
                        const response = await fetch(`/api/upload?side=${side}&filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: arrayBuffer });
                        if (response.ok) window.location.reload(); 
                    } catch (error) { alert("Upload-Fehler"); }
                }

                function jumpToPage(side, page) {
                    fetch(`/api/jump?side=${side}&page=${page}`).then(res => res.json()).then(data => {
                        if(!data.success) console.warn("MS Word Fernsteuerung fehlgeschlagen.");
                    });
                }

                function getPage(eid) {
                    let ed = document.getElementById(eid);
                    let breaks = ed.getElementsByClassName('page-break-line');
                    let curr = 1;
                    let viewTop = ed.scrollTop;
                    for(let b of breaks) {
                        if(b.offsetTop <= viewTop + (ed.clientHeight/2)) {
                            curr = parseInt(b.getAttribute('data-page') || curr);
                        } else { break; }
                    }
                    return curr;
                }

                function doLiveSync() {
                    clearTimeout(syncTimer);
                    syncTimer = setTimeout(() => {
                        if(document.getElementById('sync-left').checked) {
                            let p = getPage('left-editor');
                            if(p && p !== lastPageL) { lastPageL = p; fetch(`/api/jump?side=left&page=${p}`); }
                        }
                        if(document.getElementById('sync-right').checked) {
                            let p = getPage('right-editor');
                            if(p && p !== lastPageR) { lastPageR = p; fetch(`/api/jump?side=right&page=${p}`); }
                        }
                    }, 800); // 800ms debounce
                }

                function changeView(side) {
                    const editor = document.getElementById(side + '-editor');
                    const val = document.getElementById('view-' + side).value;
                    editor.classList.remove('view-delta', 'view-equal');
                    if (val !== 'all') editor.classList.add('view-' + val);
                    setTimeout(drawLines, 50); 
                }

                function renderSpecialTags(htmlStr, side) {
                    let res = htmlStr.replace(/\\[BILD:\s*(.*?)\s*\|\s*HASH:.*?\\]/g, `<div style="border:1px solid #007acc; padding:4px; margin:4px 0; background:#2d2d2d; color:#9cdcfe; font-size:10px; border-radius:3px;">🖼️ BILD-OBJEKT [$1]</div>`);
                    res = res.replace(/\\[SEITENUMBRUCH:\s*(\d+)\\]/g, `<div class="page-break-line" data-page="$1"><span>Seite $1 <button class="jump-btn" onclick="jumpToPage('${side}', $1)">🎯 Word</button></span></div>`);
                    return res;
                }

                function renderEditors(leftEditor, rightEditor) {
                    if (statsData.has_reqs) {
                        document.getElementById('req-mode-badge').style.display = 'block';
                        document.getElementById('stats-panel').style.display = 'block';
                        document.getElementById('l-eq').textContent = statsData.l_eq;
                        document.getElementById('l-rep').textContent = statsData.l_rep;
                        document.getElementById('l-del').textContent = statsData.l_del;
                        document.getElementById('r-eq').textContent = statsData.r_eq;
                        document.getElementById('r-rep').textContent = statsData.r_rep;
                        document.getElementById('r-ins').textContent = statsData.r_ins;
                        document.getElementById('img-diffs').textContent = statsData.img_diffs;
                    }

                    diffData.forEach(block => {
                        const lDiv = document.createElement('div');
                        lDiv.id = `l-${block.id}`; lDiv.className = `bucket-block tag-${block.tag}`;
                        lDiv.innerHTML = renderSpecialTags(block.left, 'left') || '';
                        leftEditor.appendChild(lDiv);

                        const rDiv = document.createElement('div');
                        rDiv.id = `r-${block.id}`; rDiv.className = `bucket-block tag-${block.tag}`;
                        rDiv.innerHTML = renderSpecialTags(block.right, 'right') || '';
                        rightEditor.appendChild(rDiv);
                    });
                    
                    leftEditor.innerHTML += '<div class="drag-overlay">📥 HIER ABLEGEN</div>';
                    rightEditor.innerHTML += '<div class="drag-overlay">📥 HIER ABLEGEN</div>';
                    setTimeout(drawLines, 200);
                }

                function drawLines() {
                    const svg = document.getElementById('lines-svg');
                    const leftEditor = document.getElementById('left-editor');
                    const rightEditor = document.getElementById('right-editor');
                    if (!svg || !leftEditor || !rightEditor) return;
                    
                    svg.innerHTML = '';
                    const svgWidth = svgContainer.clientWidth;
                    const lScroll = leftEditor.scrollTop;
                    const rScroll = rightEditor.scrollTop;

                    diffData.forEach(block => {
                        const lEl = document.getElementById(`l-${block.id}`);
                        const rEl = document.getElementById(`r-${block.id}`);
                        if (!lEl || !rEl || lEl.offsetParent === null || rEl.offsetParent === null) return;
                        
                        const lY = lEl.offsetTop + (lEl.offsetHeight / 2) - lScroll;
                        const rY = rEl.offsetTop + (rEl.offsetHeight / 2) - rScroll;
                        
                        let color = block.tag === 'insert' ? '#28a745' : block.tag === 'delete' ? '#dc3545' : block.tag === 'equal' ? '#666666' : '#007bff';
                        let opacity = block.tag === 'equal' ? '0.3' : '0.6';
                        let strokeWidth = block.tag === 'equal' ? '1' : '2';

                        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        path.setAttribute('d', `M 0 ${lY} C ${svgWidth/2} ${lY}, ${svgWidth/2} ${rY}, ${svgWidth} ${rY}`);
                        path.setAttribute('fill', 'none'); path.setAttribute('stroke', color);
                        path.setAttribute('stroke-width', strokeWidth); path.setAttribute('opacity', opacity);
                        svg.appendChild(path);
                    });
                }

                let isSyncingLeft = false; let isSyncingRight = false;
                document.getElementById('left-editor')?.addEventListener('scroll', function() {
                    if (!isSyncingLeft) {
                        isSyncingRight = true;
                        document.getElementById('right-editor').scrollTop = this.scrollTop / (this.scrollHeight - this.clientHeight) * (document.getElementById('right-editor').scrollHeight - document.getElementById('right-editor').clientHeight);
                        drawLines();
                    }
                    isSyncingLeft = false;
                    doLiveSync();
                });
                document.getElementById('right-editor')?.addEventListener('scroll', function() {
                    if (!isSyncingRight) {
                        isSyncingLeft = true;
                        document.getElementById('left-editor').scrollTop = this.scrollTop / (this.scrollHeight - this.clientHeight) * (document.getElementById('left-editor').scrollHeight - document.getElementById('left-editor').clientHeight);
                        drawLines();
                    }
                    isSyncingRight = false;
                    doLiveSync();
                });

                window.addEventListener('resize', drawLines);
            </script>
        </body>
        </html>
        """

def start_fallback_server():
    server = HTTPServer(('localhost', 0), DiffRequestHandler)
    print(f"Tool laeuft. Oeffne Browser: http://localhost:{server.server_port}")
    webbrowser.open(f'http://localhost:{server.server_port}')
    server.serve_forever()

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    START_FILE_LEFT = filedialog.askopenfilename(title="Wähle LINKE Datei", filetypes=[("Word/Text", "*.docx *.txt *.md")])
    START_FILE_RIGHT = filedialog.askopenfilename(title="Wähle RECHTE Datei", filetypes=[("Word/Text", "*.docx *.txt *.md")])
    
    if START_FILE_LEFT: DISPLAY_NAME_LEFT = os.path.basename(START_FILE_LEFT)
    if START_FILE_RIGHT: DISPLAY_NAME_RIGHT = os.path.basename(START_FILE_RIGHT)
    
    server_thread = threading.Thread(target=start_fallback_server, daemon=True)
    server_thread.start()
    
    try: threading.Event().wait(1)
    except KeyboardInterrupt: pass
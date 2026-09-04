import os
import re
import json
import zipfile
import hashlib
import xml.etree.ElementTree as ET
import difflib
import tkinter as tk
from tkinter import filedialog
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading
import html
import tempfile
from urllib.parse import urlparse, parse_qs

APP_VERSION = "v16.0 (Semantic Anchor Engine)"

START_FILE_LEFT = ""
START_FILE_RIGHT = ""
DISPLAY_NAME_LEFT = ""
DISPLAY_NAME_RIGHT = ""

# ==========================================
# MODUS 1: MICROSOFT WORD COM-STEUERUNG
# ==========================================
def try_word_fusion(file_left, file_right):
    if not file_left or not file_right or not os.path.exists(file_left) or not os.path.exists(file_right):
        return False
    try:
        import win32com.client
    except ImportError:
        return False
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False
        doc1 = word.Documents.Open(os.path.abspath(file_left))
        doc2 = word.Documents.Open(os.path.abspath(file_right))
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, "FUSIONIERT_Vergleich.docx").replace('\\', '/')
        word.Application.CompareDocuments(
            doc1, doc2, 2, 1, True, True, True, True, True, True, True, True, True, True
        )
        fused_doc = word.ActiveDocument
        fused_doc.SaveAs(os.path.abspath(output_file))
        fused_doc.Close()
        doc1.Close(False)
        doc2.Close(False)
        word.Quit()
        os.startfile(os.path.abspath(output_file))
        return True
    except Exception:
        try:
            word.Quit()
        except:
            pass
        return False

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
        word.Selection.GoTo(1, 1, int(page_num))
        return True
    except Exception as e:
        return False

# ==========================================
# MODUS 2: SEMANTIC ANCHOR ENGINE
# ==========================================
def get_docx_data(file_path):
    content = ""
    objects = {}
    page_count = [1] 
    
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            rels = {}
            if 'word/_rels/document.xml.rels' in z.namelist():
                rels_root = ET.fromstring(z.read('word/_rels/document.xml.rels'))
                for rel in rels_root.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                    target = rel.get('Target')
                    if target:
                        if not target.startswith('word/'): target = 'word/' + target
                        rels[rel.get('Id')] = target

            for name in z.namelist():
                if name.startswith(('word/media/', 'word/embeddings/')):
                    objects[name] = hashlib.sha256(z.read(name)).hexdigest()

            def extract_p_data(p_node):
                para_text = ""
                for node in p_node.iter():
                    if node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}lastRenderedPageBreak':
                        page_count[0] += 1
                        para_text += f"\n[SEITENUMBRUCH: {page_count[0]}]\n"
                    elif node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br' and node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type') == 'page':
                        page_count[0] += 1
                        para_text += f"\n[SEITENUMBRUCH: {page_count[0]}]\n"
                    elif node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t':
                        if node.text: para_text += node.text
                    elif node.tag == '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tab':
                        para_text += " " # Zwingt Tabulatoren in Leerzeichen
                    elif node.tag in ('{http://schemas.openxmlformats.org/drawingml/2006/main}blip', '{urn:schemas-microsoft-com:vml}imagedata'):
                        r_id = node.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed') or node.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                        if r_id and r_id in rels:
                            img_path = rels[r_id]
                            img_hash = objects.get(img_path, "NO_HASH")
                            para_text += f"\n[BILD: {img_path} | HASH: {img_hash}]\n"
                return para_text

            if 'word/document.xml' in z.namelist():
                doc_root = ET.fromstring(z.read('word/document.xml'))
                # Lade den puren Textstrom mit Zeilenumbrüchen herunter
                for p in doc_root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'):
                    txt = extract_p_data(p).strip()
                    if txt: content += txt + "\n"
                
    except Exception as e:
        print(f"Fehler beim XML-Parsing: {e}")
    return content, objects

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"path": "", "content": "\n\n\n\n     ⬇ Bitte eine Office-Datei per Drag & Drop hier ablegen ⬇\n\n\n", "objects": {}}
    
    if file_path.lower().endswith('.docx'):
        content, objects = get_docx_data(file_path)
    else:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        objects = {}
    return {"path": file_path.replace('\\', '/'), "content": content, "objects": objects}

def heal_text(raw_text):
    """Heilt zerrissene IDs (z.B. '.1.9' wird zu '2.1.9') im Hintergrund."""
    lines = raw_text.split('\n')
    last_major = ""
    healed_lines = []
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped: 
            healed_lines.append(line)
            continue
            
        # Merke dir die letzte Hauptnummer (z.B. "2")
        m = re.match(r'^(\d+)(?:\.|$)', line_stripped)
        if m: last_major = m.group(1)
        
        # Repariere isolierte Sub-IDs (z.B. ".1.9")
        if re.match(r'^\.\d+', line_stripped) and last_major:
            line = re.sub(r'^\s*(\.\d+)', f"{last_major}\\1", line)
            
        healed_lines.append(line)
        
    return "\n".join(healed_lines)

def chunk_by_anchors(raw_text):
    """Der semantische Staubsauger: Trennt IDs vom Text und baut logische Eimer."""
    raw_text = heal_text(raw_text)
    
    # Erkennt Kapitel-IDs sicher (z.B. "2.1.9", "2.1.2a", "ID 45:")
    anchor_pattern = re.compile(r'(?:^|\n)\s*((?:ID\s+\d+:|\[REQ-\d+\]|REQ\s+\d+:|\d+\.\d+(?:\.\d+)*[a-zA-Z]?))\s*')
    
    chunks = []
    last_idx = 0
    current_id = "HEADER (Deckblatt/Inhaltsverzeichnis)"
    
    for m in anchor_pattern.finditer(raw_text):
        start = m.start()
        content = raw_text[last_idx:start].strip()
        if content or current_id != "HEADER (Deckblatt/Inhaltsverzeichnis)":
            chunks.append({'id': current_id, 'text': content})
        current_id = m.group(1).strip()
        last_idx = m.end()
        
    content = raw_text[last_idx:].strip()
    chunks.append({'id': current_id, 'text': content})
    
    # Füge zerrissene Textfragmente derselben ID wieder zusammen
    merged = {}
    for c in chunks:
        cid = c['id']
        if cid not in merged:
            merged[cid] = ""
        if c['text']:
            if merged[cid]: merged[cid] += "\n"
            merged[cid] += c['text']
            
    return [{'id': k, 'text': v.strip()} for k, v in merged.items()]

def diff_text_inline(text_l, text_r):
    """Word-Level Abgleich der Eimer-Inhalte für präzises Highlighting."""
    if text_l == text_r:
        return html.escape(text_l).replace('\n', '<br>'), html.escape(text_r).replace('\n', '<br>'), 'equal'
        
    tokens_l = re.findall(r'\S+|\s+', text_l)
    tokens_r = re.findall(r'\S+|\s+', text_r)
    sm = difflib.SequenceMatcher(None, tokens_l, tokens_r)
    
    left_html = ""
    right_html = ""
    
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        chunk_l = html.escape("".join(tokens_l[i1:i2]))
        chunk_r = html.escape("".join(tokens_r[j1:j2]))
        
        if op == 'equal':
            left_html += chunk_l
            right_html += chunk_r
        else:
            if chunk_l.strip(): left_html += f"<span class='char-diff'>{chunk_l}</span>"
            elif chunk_l: left_html += chunk_l 
            
            if chunk_r.strip(): right_html += f"<span class='char-diff'>{chunk_r}</span>"
            elif chunk_r: right_html += chunk_r
            
    return left_html.replace('\n', '<br>'), right_html.replace('\n', '<br>'), 'replace'

def berechne_diff_daten(raw_left, raw_right):
    chunks_left = chunk_by_anchors(raw_left)
    chunks_right = chunk_by_anchors(raw_right)
    
    left_map = {c['id']: c['text'] for c in chunks_left}
    right_map = {c['id']: c['text'] for c in chunks_right}
    
    left_ids = set(left_map.keys())
    right_ids = set(right_map.keys())
    
    # Rekonstruktion der Reihenfolge (Rechtes Dokument ist die saubere Schablone)
    ordered_ids = []
    seen = set()
    for c in chunks_right:
        if c['id'] not in seen:
            ordered_ids.append(c['id'])
            seen.add(c['id'])
    for c in chunks_left:
        if c['id'] not in seen:
            ordered_ids.append(c['id'])
            seen.add(c['id'])

    stats = {
        "l_eq": 0, "l_rep": 0, "l_del": 0, "l_tot": len(left_ids),
        "r_eq": 0, "r_rep": 0, "r_ins": 0, "r_tot": len(right_ids),
        "has_reqs": len(left_ids) > 0 or len(right_ids) > 0
    }

    diff_data = []
    block_id = 0
    
    # Abgleich der logischen Anker (Die Vogelperspektive)
    for cid in ordered_ids:
        text_l = left_map.get(cid, None)
        text_r = right_map.get(cid, None)
        
        prefix = f"<div style='color:#007acc; font-weight:bold; margin-bottom:4px; font-size:14px;'>[{cid}]</div>" if cid != "HEADER (Deckblatt/Inhaltsverzeichnis)" else ""
        
        if text_l is not None and text_r is not None:
            html_l, html_r, tag = diff_text_inline(text_l, text_r)
            if tag == 'equal':
                stats["l_eq"] += 1; stats["r_eq"] += 1
            else:
                stats["l_rep"] += 1; stats["r_rep"] += 1
            diff_data.append({
                'id': block_id, 'tag': tag, 'req_id': cid,
                'left': prefix + html_l, 'right': prefix + html_r
            })
        elif text_l is not None:
            stats["l_del"] += 1
            diff_data.append({
                'id': block_id, 'tag': 'delete', 'req_id': cid,
                'left': prefix + html.escape(text_l).replace('\n', '<br>'), 'right': ""
            })
        elif text_r is not None:
            stats["r_ins"] += 1
            diff_data.append({
                'id': block_id, 'tag': 'insert', 'req_id': cid,
                'left': "", 'right': prefix + html.escape(text_r).replace('\n', '<br>')
            })
        block_id += 1

    return diff_data, stats

def generate_word_report():
    if not START_FILE_LEFT or not START_FILE_RIGHT:
        return False
        
    info_l = get_file_info(START_FILE_LEFT)
    info_r = get_file_info(START_FILE_RIGHT)
    diff_data, stats = berechne_diff_daten(info_l['content'], info_r['content'])
            
    try:
        import win32com.client
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = True
        doc = word.Documents.Add()
        sel = word.Selection
        
        sel.Font.Size = 16
        sel.Font.Bold = True
        sel.TypeText("Delta-Protokoll: Semantic Anchor Bericht\n\n")
        
        sel.Font.Size = 11
        sel.Font.Bold = False
        sel.TypeText(f"Original-Datei: {DISPLAY_NAME_LEFT}\n")
        sel.TypeText(f"Geänderte Datei: {DISPLAY_NAME_RIGHT}\n\n")
        
        sel.Font.Bold = True
        sel.TypeText("Management Summary (Logische Kapitel-Blöcke):\n")
        sel.Font.Bold = False
        sel.TypeText(f"• Unverändert: {stats['l_eq']}\n")
        sel.TypeText(f"• Geändert: {stats['l_rep']}\n")
        sel.TypeText(f"• Neu: {stats['r_ins']}\n")
        sel.TypeText(f"• Gelöscht: {stats['l_del']}\n\n")
        
        sel.Font.Bold = True
        sel.TypeText("Detailliertes Änderungsprotokoll:\n\n")
        sel.Font.Bold = False
        
        has_diffs = False
        for b in diff_data:
            if b['tag'] == 'equal' or b['req_id'] == "HEADER (Deckblatt/Inhaltsverzeichnis)": continue
            has_diffs = True
            tag_de = {"insert": "NEU", "replace": "GEÄNDERT", "delete": "GELÖSCHT"}[b['tag']]
            sel.Font.Bold = True
            sel.TypeText(f"--- Kapitel/ID: {b['req_id']} [{tag_de}] ---\n")
            sel.Font.Bold = False
            
            if "[BILD:" in b['left'] or "[BILD:" in b['right']:
                sel.TypeText("-> Achtung: Enthält Grafik-/Medienänderungen.\n\n")
            else:
                clean_r = re.sub(r'<[^>]+>', '', b['right']).replace('<br>', '\n').strip()
                if clean_r: sel.TypeText(f"Neuer Inhalt:\n{clean_r}\n\n")
                
        if not has_diffs:
            sel.TypeText("Es wurden keine inhaltlichen Änderungen gefunden.\n")
            
        return True
    except Exception as e:
        print(f"Fehler bei Report-Generierung: {e}")
        return False

class DiffRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass 

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
            with open(save_path, 'wb') as f:
                f.write(file_data)
                
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
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"diff": diff, "stats": stats}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return
            
        if parsed_url.path == '/api/report':
            success = generate_word_report()
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
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
            
        if parsed_url.path == '/api/word_fuse':
            success = try_word_fusion(START_FILE_LEFT, START_FILE_RIGHT)
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            return
            
        if parsed_url.path == '/media':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            file_path_in_zip = query.get('file', [''])[0]
            
            docx_path = START_FILE_LEFT if side == 'left' else START_FILE_RIGHT
            try:
                with zipfile.ZipFile(docx_path, 'r') as z:
                    data = z.read(file_path_in_zip)
                    self.send_response(200)
                    ext = file_path_in_zip.lower().split('.')[-1]
                    content_types = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif'}
                    self.send_header('Content-type', content_types.get(ext, 'application/octet-stream'))
                    self.end_headers()
                    self.wfile.write(data)
            except Exception:
                self.send_response(404); self.end_headers()
            return
            
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type', 'text/html; charset=utf-8'); self.end_headers()
            
            name_l = DISPLAY_NAME_LEFT if DISPLAY_NAME_LEFT else "Keine Datei (Links)"
            name_r = DISPLAY_NAME_RIGHT if DISPLAY_NAME_RIGHT else "Keine Datei (Rechts)"
            
            html_content = self.get_html_template().replace(
                "APP_VERSION", APP_VERSION
            ).replace("NAME_LEFT", name_l).replace("NAME_RIGHT", name_r)
            
            self.wfile.write(html_content.encode('utf-8'))

    def get_html_template(self):
        return """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="utf-8">
            <title>Advanced Delta Tool</title>
            <style>
                :root {
                    --bg-dark: #1e1e1e; --bg-panel: #252526; --text-main: #d4d4d4;
                    --insert: rgba(40, 167, 69, 0.2); --delete: rgba(220, 53, 69, 0.2); --replace: rgba(0, 123, 255, 0.2);
                }
                body { margin: 0; padding: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; background: var(--bg-dark); color: var(--text-main); overflow: hidden; }
                
                #header-container { display: flex; background: #333; border-bottom: 2px solid #444; }
                .pane-header { flex: 1; padding: 10px; display: flex; justify-content: space-between; align-items: center; }
                .pane-header.left { border-right: 1px solid #444; }
                
                .header-title { font-weight: bold; color: #9cdcfe; font-size: 15px; max-width: 350px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: #1e1e1e; padding: 4px 10px; border-radius: 4px; border: 1px solid #555;}
                
                .view-select { background: #007acc; border: 1px solid #005f9e; color: white; padding: 5px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; cursor: pointer; outline: none;}
                .view-select:hover { background: #005f9e; }
                
                .word-btn { background: #107c41; margin-top: 5px; width: 100%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
                .report-btn { background: #005a9e; margin-top: 5px; width: 100%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
                
                .center-panel { width: 220px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: var(--bg-panel); padding: 5px 10px; font-size: 10px; color: #888; border-left: 1px solid #444; border-right: 1px solid #444; box-sizing: border-box;}
                
                #workspace { display: flex; flex: 1; overflow: hidden; position: relative; }
                .editor-container { flex: 1; overflow-y: auto; padding: 10px; font-family: 'Consolas', monospace; font-size: 13px; line-height: 1.5; scroll-behavior: smooth; position: relative;}
                
                .editor-container.drag-over { border: 3px dashed #007acc !important; background-color: rgba(0, 122, 204, 0.1) !important; }
                .drag-overlay { display: none; position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.6); color: #007acc; font-size: 24px; font-weight: bold; align-items: center; justify-content: center; z-index: 100; pointer-events: none;}
                .editor-container.drag-over .drag-overlay { display: flex; }
                
                #svg-container { width: 100px; flex-shrink: 0; position: relative; background: var(--bg-panel); border-left: 1px solid #444; border-right: 1px solid #444; }
                svg { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
                
                .code-block { padding: 10px; border-radius: 4px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #444;}
                .tag-insert { background-color: var(--insert); border-left: 4px solid #28a745; }
                .tag-delete { background-color: var(--delete); border-left: 4px solid #dc3545; }
                .tag-replace { background-color: var(--replace); border-left: 4px solid #007bff; }
                .tag-equal { background-color: transparent; border-left: 4px solid #555; }
                
                .char-diff { background-color: rgba(0, 123, 255, 0.6); color: white; font-weight: bold; border-radius: 2px; padding: 0 2px; }
                .inline-img { max-width: 90%; max-height: 300px; border: 2px dashed #007acc; padding: 5px; margin: 10px 0; background: #2d2d2d; border-radius: 4px; display: block; }
                
                .page-break-line { border-top: 1px dashed #dc3545; margin: 15px 0; position: relative; width: 100%; }
                .page-break-line span { 
                    background: #dc3545; color: white; padding: 2px 6px; font-size: 11px; font-weight: bold; 
                    border-radius: 0 0 0 4px; position: absolute; right: 0; top: 0; display: flex; align-items: center; gap: 6px;
                }
                .jump-btn {
                    background: #1e1e1e; color: #fff; border: 1px solid #fff; border-radius: 3px; 
                    font-size: 9px; cursor: pointer; padding: 2px 4px; transition: 0.2s;
                }
                .jump-btn:hover { background: #fff; color: #dc3545; }
                
                .editor-container.view-delta .tag-equal { display: none !important; }
                .editor-container.view-equal .tag-replace, 
                .editor-container.view-equal .tag-insert, 
                .editor-container.view-equal .tag-delete { display: none !important; }
                
                #loading-screen { position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); color:#007acc; font-size:24px; font-weight:bold; z-index: 1000; text-align: center; }
            </style>
        </head>
        <body>
            <div id="loading-screen">⏳ Analysiere semantische Anker... Bitte warten.</div>

            <div id="header-container" style="visibility: hidden;">
                <div class="pane-header left">
                    <span class="header-title" title="NAME_LEFT">📄 NAME_LEFT</span>
                    <select id="view-left" class="view-select" onchange="changeView('left')">
                        <option value="all">Ansicht: Alles</option>
                        <option value="delta">Ansicht: Nur Deltas</option>
                        <option value="equal">Ansicht: Nur Gleiche</option>
                    </select>
                </div>
                
                <div class="center-panel">
                    <div style="margin-bottom: 5px; font-weight:bold;">APP_VERSION</div>
                    <div id="req-mode-badge" style="display:none; background:#28a745; color:white; padding:2px 4px; border-radius:3px; margin-bottom: 5px; font-weight:bold;">✅ REQ MODE</div>
                    
                    <div id="stats-panel" style="display:none; width: 100%; background: #1e1e1e; border-radius: 4px; padding: 6px; box-sizing: border-box; text-align: left; margin-bottom: 5px; border: 1px solid #444;">
                        <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center; border-bottom:1px solid #444; padding-bottom:3px;"><b>Statistik (Kapitel-Blöcke)</b></div>
                        
                        <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                            <div style="width: 48%;">
                                <u style="color:#9cdcfe">Original (Links)</u><br>
                                Gleich: <span id="l-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="l-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>
                                Gelöscht: <span id="l-del" style="float:right; font-weight:bold; color:#dc3545;">0</span><br>
                                <div style="border-top: 1px solid #444; margin-top: 2px; padding-top: 2px;">
                                    <b>Total: <span id="l-tot" style="float:right;">0</span></b>
                                </div>
                            </div>
                            <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;">
                                <u style="color:#9cdcfe">Neu (Rechts)</u><br>
                                Gleich: <span id="r-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="r-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>
                                Neu: <span id="r-ins" style="float:right; font-weight:bold; color:#28a745;">0</span><br>
                                <div style="border-top: 1px solid #444; margin-top: 2px; padding-top: 2px;">
                                    <b>Total: <span id="r-tot" style="float:right;">0</span></b>
                                </div>
                            </div>
                        </div>
                        
                        <div style="margin-top: 6px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                            <label style="cursor: pointer; color: #d4d4d4;"><input type="checkbox" id="chk-equal-lines" onchange="drawLines()"> Gleiche Linien zeigen</label>
                        </div>
                    </div>

                    <button class="report-btn" onclick="triggerReport()" style="display:none;" id="btn-report">📊 Report (Word) erzeugen</button>
                    <button class="word-btn" onclick="triggerWordFusion()">🗎 In MS Word öffnen</button>
                </div>
                
                <div class="pane-header right">
                    <span class="header-title" title="NAME_RIGHT">📄 NAME_RIGHT</span>
                    <select id="view-right" class="view-select" onchange="changeView('right')">
                        <option value="all">Ansicht: Alles</option>
                        <option value="delta">Ansicht: Nur Deltas</option>
                        <option value="equal">Ansicht: Nur Gleiche</option>
                    </select>
                </div>
            </div>

            <div id="workspace" style="visibility: hidden;">
                <div id="left-editor" class="editor-container" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event, 'left')"></div>
                <div id="svg-container"><svg id="lines-svg"></svg></div>
                <div id="right-editor" class="editor-container" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event, 'right')"></div>
            </div>

            <script>
                let diffData = [];
                let statsData = {};
                
                window.onload = function() {
                    fetch('/api/diff_data')
                        .then(res => res.json())
                        .then(data => {
                            if (data.error) {
                                document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Fehler beim Einlesen:</span><br><br><span style="font-size:14px; color:#d4d4d4">${data.error}</span>`;
                                return;
                            }
                            diffData = data.diff;
                            statsData = data.stats;
                            
                            document.getElementById('loading-screen').style.display = 'none';
                            document.getElementById('header-container').style.visibility = 'visible';
                            document.getElementById('workspace').style.visibility = 'visible';
                            
                            const leftEditor = document.getElementById('left-editor');
                            const rightEditor = document.getElementById('right-editor');
                            renderEditors(leftEditor, rightEditor);
                        })
                        .catch(err => {
                            document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Browser-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${err}</span>`;
                        });
                };

                const svgContainer = document.getElementById('svg-container');

                function handleDragOver(e) { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add('drag-over'); }
                function handleDragLeave(e) { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove('drag-over'); }
                async function handleDrop(e, side) {
                    e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove('drag-over');
                    const file = e.dataTransfer.files[0];
                    if (!file) return;
                    const overlay = e.currentTarget.querySelector('.drag-overlay');
                    if(overlay) { overlay.textContent = "⚙️ LADE NEU..."; overlay.style.display = "flex"; }
                    try {
                        const arrayBuffer = await file.arrayBuffer();
                        const filename = encodeURIComponent(file.name);
                        const response = await fetch(`/api/upload?side=${side}&filename=${filename}`, { method: 'POST', body: arrayBuffer });
                        if (response.ok) window.location.reload(); 
                    } catch (error) { alert("Verbindungsfehler zum lokalen Server."); }
                }

                function triggerWordFusion() {
                    const btn = document.querySelector('.word-btn');
                    btn.textContent = "⏳ Starte Word..."; btn.style.background = "#ff9800";
                    fetch('/api/word_fuse').then(res => res.json()).then(data => {
                        if(!data.success) alert("MS Word Fusion fehlgeschlagen.");
                        btn.textContent = "🗎 In MS Word öffnen"; btn.style.background = "#107c41";
                    });
                }
                
                function triggerReport() {
                    const btn = document.getElementById('btn-report');
                    btn.textContent = "⏳ Generiere..."; btn.style.background = "#ff9800";
                    fetch('/api/report').then(res => res.json()).then(data => {
                        if(!data.success) alert("Konnte Word-Report nicht erstellen.");
                        btn.textContent = "📊 Report (Word) erzeugen"; btn.style.background = "#005a9e";
                    });
                }
                
                function jumpToPage(side, page) {
                    fetch(`/api/jump?side=${side}&page=${page}`).then(res => res.json()).then(data => {
                        if(!data.success) alert("Konnte Word nicht fernsteuern. Ist die Datei am Speicherort verfügbar?");
                    });
                }

                function changeView(side) {
                    const editor = document.getElementById(side + '-editor');
                    const val = document.getElementById('view-' + side).value;
                    
                    editor.classList.remove('view-delta', 'view-equal');
                    if (val !== 'all') {
                        editor.classList.add('view-' + val);
                    }
                    setTimeout(drawLines, 50); 
                }

                function renderSpecialTags(htmlStr, side) {
                    let res = htmlStr.replace(/\\[BILD:\s*(.*?)\s*\|\s*HASH:.*?\\]/g, `<img src="/media?side=${side}&file=$1" class="inline-img" alt="Bild ($1)" onload="drawLines()" onerror="this.outerHTML='<div style=\\'color:red; border:1px solid red; padding:5px;\\'>Fehlendes Bild: $1</div>'">`);
                    res = res.replace(/\\[SEITENUMBRUCH:\s*(\d+)\\]/g, `<div class="page-break-line"><span>Seite $1 <button class="jump-btn" onclick="jumpToPage('${side}', $1)" title="In MS Word direkt auf diese Seite springen">🎯 Word</button></span></div>`);
                    return res;
                }
                
                function updateStats() {
                    document.getElementById('l-eq').textContent = statsData.l_eq;
                    document.getElementById('l-rep').textContent = statsData.l_rep;
                    document.getElementById('l-del').textContent = statsData.l_del;
                    document.getElementById('l-tot').textContent = statsData.l_tot;

                    document.getElementById('r-eq').textContent = statsData.r_eq;
                    document.getElementById('r-rep').textContent = statsData.r_rep;
                    document.getElementById('r-ins').textContent = statsData.r_ins;
                    document.getElementById('r-tot').textContent = statsData.r_tot;
                }

                function renderEditors(leftEditor, rightEditor) {
                    if (statsData.has_reqs) {
                        document.getElementById('req-mode-badge').style.display = 'block';
                        document.getElementById('stats-panel').style.display = 'block';
                        document.getElementById('btn-report').style.display = 'block';
                        updateStats();
                    }

                    diffData.forEach(block => {
                        const lDiv = document.createElement('div');
                        lDiv.id = `l-${block.id}`; lDiv.className = `code-block tag-${block.tag}`;
                        lDiv.innerHTML = renderSpecialTags(block.left, 'left') || '<br>';
                        leftEditor.appendChild(lDiv);

                        const rDiv = document.createElement('div');
                        rDiv.id = `r-${block.id}`; rDiv.className = `code-block tag-${block.tag}`;
                        rDiv.innerHTML = renderSpecialTags(block.right, 'right') || '<br>';
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
                    
                    const chk = document.getElementById('chk-equal-lines');
                    const showEqual = chk ? chk.checked : false;

                    diffData.forEach(block => {
                        if (block.tag === 'equal' && !showEqual) return;
                        
                        const lEl = document.getElementById(`l-${block.id}`);
                        const rEl = document.getElementById(`r-${block.id}`);
                        
                        if (!lEl || !rEl) return;
                        if (lEl.offsetParent === null || rEl.offsetParent === null) return;
                        
                        const lY = lEl.offsetTop + (lEl.offsetHeight / 2) - lScroll;
                        const rY = rEl.offsetTop + (rEl.offsetHeight / 2) - rScroll;
                        
                        let color = '#007bff';
                        let opacity = '0.6';
                        let strokeWidth = '2';
                        
                        if (block.tag === 'insert') color = '#28a745';
                        if (block.tag === 'delete') color = '#dc3545';
                        
                        if (block.tag === 'equal') {
                            color = '#666666';
                            opacity = '0.3';
                            strokeWidth = '1';
                        }

                        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        path.setAttribute('d', `M 0 ${lY} C ${svgWidth/2} ${lY}, ${svgWidth/2} ${rY}, ${svgWidth} ${rY}`);
                        path.setAttribute('fill', 'none'); 
                        path.setAttribute('stroke', color);
                        path.setAttribute('stroke-width', strokeWidth); 
                        path.setAttribute('opacity', opacity);
                        svg.appendChild(path);
                    });
                }

                let isSyncingLeft = false; let isSyncingRight = false;
                document.getElementById('left-editor')?.addEventListener('scroll', function() {
                    if (!isSyncingLeft) {
                        isSyncingRight = true;
                        const re = document.getElementById('right-editor');
                        re.scrollTop = this.scrollTop / (this.scrollHeight - this.clientHeight) * (re.scrollHeight - re.clientHeight);
                        drawLines();
                    }
                    isSyncingLeft = false;
                });
                document.getElementById('right-editor')?.addEventListener('scroll', function() {
                    if (!isSyncingRight) {
                        isSyncingLeft = true;
                        const le = document.getElementById('left-editor');
                        le.scrollTop = this.scrollTop / (this.scrollHeight - this.clientHeight) * (le.scrollHeight - le.clientHeight);
                        drawLines();
                    }
                    isSyncingRight = false;
                });

                window.addEventListener('resize', drawLines);
            </script>
        </body>
        </html>
        """

def start_fallback_server():
    server = HTTPServer(('localhost', 0), DiffRequestHandler)
    port = server.server_port
    print(f"Tool laeuft. Oeffne Browser: http://localhost:{port}")
    webbrowser.open(f'http://localhost:{port}')
    server.serve_forever()

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    START_FILE_LEFT = filedialog.askopenfilename(title="Wähle LINKE Datei (oder Abbrechen für leeres Tool)", filetypes=[("Word/Text", "*.docx *.txt *.md")])
    START_FILE_RIGHT = filedialog.askopenfilename(title="Wähle RECHTE Datei (oder Abbrechen für leeres Tool)", filetypes=[("Word/Text", "*.docx *.txt *.md")])
    
    if START_FILE_LEFT: DISPLAY_NAME_LEFT = os.path.basename(START_FILE_LEFT)
    if START_FILE_RIGHT: DISPLAY_NAME_RIGHT = os.path.basename(START_FILE_RIGHT)
    
    server_thread = threading.Thread(target=start_fallback_server, daemon=True)
    server_thread.start()
    
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        pass
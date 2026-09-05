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
import collections
from urllib.parse import urlparse, parse_qs

APP_VERSION = "v33.0 (Smart Format & Invisible Breaks Engine)"

START_FILE_LEFT = ""
START_FILE_RIGHT = ""
DISPLAY_NAME_LEFT = ""
DISPLAY_NAME_RIGHT = ""

# ==========================================
# MS WORD COM-STEUERUNG (Smart Sync)
# ==========================================
def jump_to_word_page(side, page_num):
    target_name = DISPLAY_NAME_LEFT if side == 'left' else DISPLAY_NAME_RIGHT
    fallback_path = START_FILE_LEFT if side == 'left' else START_FILE_RIGHT
    
    if not target_name:
        return False
        
    try:
        import win32com.client
    except ImportError:
        print("FEHLER: 'pywin32' fehlt! Bitte 'pip install pywin32' ausführen.")
        return False
        
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = True 
        
        doc = None
        for d in word.Documents:
            if target_name.lower() in d.Name.lower() or d.Name.lower() in target_name.lower():
                doc = d
                break
                
        if not doc and fallback_path and os.path.exists(fallback_path):
            doc = word.Documents.Open(os.path.abspath(fallback_path))
            
        if not doc:
            return False
            
        doc.Activate()
        word.Activate()
        
        target_range = doc.GoTo(1, 1, int(page_num))
        target_range.Select()
        word.ActiveWindow.ScrollIntoView(target_range)
        
        print(f"-> Live-Sync: In '{doc.Name}' auf Seite {page_num} gescrollt!")
        return True
    except Exception as e:
        print(f"WORD-BLOCKADE beim Scrollen: {e}")
        return False

# ==========================================
# PURE PYTHON XML PARSER
# ==========================================
def get_docx_data(file_path):
    content = []
    page_count = [1]
    
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            rels = {}
            if 'word/_rels/document.xml.rels' in z.namelist():
                import xml.etree.ElementTree as ET
                rels_root = ET.fromstring(z.read('word/_rels/document.xml.rels'))
                for rel in rels_root.iter():
                    if rel.tag.endswith('}Relationship'):
                        r_id = rel.get('Id')
                        target = rel.get('Target')
                        if r_id and target:
                            if target.startswith('/word/'): target = target[1:]
                            elif not target.startswith('word/'): target = 'word/' + target
                            rels[r_id] = target

            objects = {}
            for name in z.namelist():
                if name.startswith(('word/media/', 'word/embeddings/')):
                    objects[name] = hashlib.sha256(z.read(name)).hexdigest()

            if 'word/document.xml' in z.namelist():
                import xml.etree.ElementTree as ET
                doc_root = ET.fromstring(z.read('word/document.xml'))
                
                for p in doc_root.iter():
                    if p.tag.endswith('}p'):
                        para_text = ""
                        for node in p.iter():
                            if node.tag.endswith('}lastRenderedPageBreak') or (node.tag.endswith('}br') and any(v == 'page' for k,v in node.attrib.items())):
                                page_count[0] += 1
                                para_text += f"\n[SEITENUMBRUCH:{page_count[0]}]\n"
                            elif node.tag.endswith('}t') and node.text:
                                para_text += node.text
                            elif node.tag.endswith('}tab'):
                                para_text += " " 
                            elif node.tag.endswith('}blip') or node.tag.endswith('}imagedata'):
                                r_id = None
                                for k, v in node.attrib.items():
                                    if k.endswith('}embed') or k.endswith('}id') or k == 'id':
                                        r_id = v
                                        break
                                if r_id and r_id in rels:
                                    img_path = rels[r_id]
                                    img_hash = objects.get(img_path, "NO_HASH")
                                    para_text += f"\n[BILD:{img_path}|HASH:{img_hash}]\n"
                        
                        txt = para_text.strip()
                        if txt:
                            for line in txt.split('\n'):
                                clean_line = line.strip()
                                if clean_line:
                                    content.append(f"[P:{page_count[0]}]{clean_line}")
                        
    except Exception as e:
        print(f"Fehler beim XML-Parsing: {e}")
    return content

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"path": "", "content": ["\n\n\n\n     ⬇ Bitte eine Office-Datei per Drag & Drop hier ablegen ⬇\n\n\n"]}
    if file_path.lower().endswith('.docx'):
        content = get_docx_data(file_path)
    else:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = [f"[P:1]{l.strip()}" for l in f.readlines() if l.strip()]
    return {"path": file_path.replace('\\', '/'), "content": content}

def heal_text(lines):
    res = []
    last_major = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        m_p = re.match(r'^(\[P:\d+\])(.*)', line)
        p_tag = m_p.group(1) if m_p else ""
        clean_line = m_p.group(2).strip() if m_p else line
            
        m = re.match(r'^(\d+)(?:\.|$)', clean_line)
        if m: last_major = m.group(1)
        
        if re.match(r'^\d+\.?$', clean_line) and i+1 < len(lines):
            next_m = re.match(r'^(\[P:\d+\])(.*)', lines[i+1].strip())
            next_clean = next_m.group(2).strip() if next_m else lines[i+1].strip()
            if re.match(r'^\.\d+', next_clean):
                merged = clean_line + next_clean
                res.append(p_tag + merged)
                m2 = re.match(r'^(\d+)', merged)
                if m2: last_major = m2.group(1)
                i += 2
                continue
            
        if re.match(r'^\.\d+', clean_line) and last_major:
            res.append(p_tag + last_major + clean_line)
            i += 1
            continue
            
        res.append(line)
        i += 1
    return res

def parse_line_obj(line):
    m = re.match(r'^(\[P:(\d+)\])(.*)', line)
    if m: return m.group(2), m.group(3).strip()
    return "1", line.strip()

def extract_id(text):
    m = re.match(r'^\s*(?:ID\s+\d+:|\[REQ-\d+\]|REQ\s+\d+:|\d+(?:\.\d+)*[a-zA-Z]?|\d+\.)(?:\s|$)', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    return None

def clean_text_for_diff(text):
    t = re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text)
    return re.sub(r'\s+', ' ', t).strip()

def remove_visual_breaks(text):
    t = re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text)
    return t.strip()

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

def berechne_diff_daten(lines_left, lines_right, ignore_breaks=True):
    lines_left = heal_text(lines_left)
    lines_right = heal_text(lines_right)
    
    objs_l = [{'page': p, 'text': t} for p, t in (parse_line_obj(l) for l in lines_left)]
    objs_r = [{'page': p, 'text': t} for p, t in (parse_line_obj(r) for r in lines_right)]
    
    clean_l = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_l]
    clean_r = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_r]

    sm = difflib.SequenceMatcher(None, clean_l, clean_r, autojunk=False)
    
    buckets = collections.OrderedDict()
    current_id = "HEADER (Deckblatt/Inhaltsverzeichnis)"
    buckets[current_id] = []
    
    stats = {"l_eq": 0, "l_rep": 0, "l_del": 0, "l_tot": 0, "r_eq": 0, "r_rep": 0, "r_ins": 0, "r_tot": 0, "img_eq": 0, "img_rep": 0, "img_del": 0, "img_ins": 0, "has_reqs": False}
    
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for o_l, o_r in zip(objs_l[i1:i2], objs_r[j1:j2]):
                stats['img_eq'] += len(re.findall(r'\[BILD:', o_l['text']))
                cid = extract_id(o_r['text']) or extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                    
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                
                if ignore_breaks and not disp_l and not disp_r:
                    continue # Block unsichtbar machen
                    
                buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': html.escape(disp_r), 'page_l': o_l['page'], 'page_r': o_r['page']})
                
        elif op == 'replace':
            sub_l = objs_l[i1:i2]
            sub_r = objs_r[j1:j2]
            for k in range(max(len(sub_l), len(sub_r))):
                o_l = sub_l[k] if k < len(sub_l) else {'page': '', 'text': ''}
                o_r = sub_r[k] if k < len(sub_r) else {'page': '', 'text': ''}
                
                c_l = clean_text_for_diff(o_l['text'])
                c_r = clean_text_for_diff(o_r['text'])
                
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                
                cid = extract_id(o_r['text']) or extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                
                if ignore_breaks and c_l == c_r:
                    if disp_l or disp_r:
                        buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': html.escape(disp_r), 'page_l': o_l['page'], 'page_r': o_r['page']})
                    continue

                if o_l['text'] and o_r['text']:
                    l_imgs = len(re.findall(r'\[BILD:', o_l['text']))
                    r_imgs = len(re.findall(r'\[BILD:', o_r['text']))
                    stats['img_rep'] += min(l_imgs, r_imgs)
                    if r_imgs > l_imgs: stats['img_ins'] += (r_imgs - l_imgs)
                    if l_imgs > r_imgs: stats['img_del'] += (l_imgs - r_imgs)
                    
                    l_out, r_out = highlight_inline(disp_l, disp_r)
                    
                    # Gestrichelte Linie für reine Format/Umruch-Änderungen!
                    current_tag = 'format' if (not ignore_breaks and c_l == c_r and disp_l != disp_r) else 'replace'
                    buckets[current_id].append({'tag': current_tag, 'left': l_out, 'right': r_out, 'page_l': o_l['page'], 'page_r': o_r['page']})
                elif o_l['text']:
                    if ignore_breaks and not c_l:
                        if disp_l: buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                    else:
                        stats['img_del'] += len(re.findall(r'\[BILD:', o_l['text']))
                        current_tag = 'format' if (not ignore_breaks and not c_l) else 'delete'
                        buckets[current_id].append({'tag': current_tag, 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                elif o_r['text']:
                    if ignore_breaks and not c_r:
                        if disp_r: buckets[current_id].append({'tag': 'equal', 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})
                    else:
                        stats['img_ins'] += len(re.findall(r'\[BILD:', o_r['text']))
                        current_tag = 'format' if (not ignore_breaks and not c_r) else 'insert'
                        buckets[current_id].append({'tag': current_tag, 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})
                    
        elif op == 'delete':
            for o_l in objs_l[i1:i2]:
                c_l = clean_text_for_diff(o_l['text'])
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                
                cid = extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                    
                if ignore_breaks and not c_l:
                    if disp_l: buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                else:
                    stats['img_del'] += len(re.findall(r'\[BILD:', o_l['text']))
                    current_tag = 'format' if (not ignore_breaks and not c_l) else 'delete'
                    buckets[current_id].append({'tag': current_tag, 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                
        elif op == 'insert':
            for o_r in objs_r[j1:j2]:
                c_r = clean_text_for_diff(o_r['text'])
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                
                cid = extract_id(o_r['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                    
                if ignore_breaks and not c_r:
                    if disp_r: buckets[current_id].append({'tag': 'equal', 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})
                else:
                    stats['img_ins'] += len(re.findall(r'\[BILD:', o_r['text']))
                    current_tag = 'format' if (not ignore_breaks and not c_r) else 'insert'
                    buckets[current_id].append({'tag': current_tag, 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})

    left_ids = set()
    right_ids = set()
    for cid, items in buckets.items():
        if cid == "HEADER (Deckblatt/Inhaltsverzeichnis)": continue
        if any(i['left'] for i in items): left_ids.add(cid)
        if any(i['right'] for i in items): right_ids.add(cid)
        
    stats["l_del"] = len(left_ids - right_ids); stats["l_tot"] = len(left_ids)
    stats["r_ins"] = len(right_ids - left_ids); stats["r_tot"] = len(right_ids)
    stats["has_reqs"] = len(left_ids) > 0 or len(right_ids) > 0
    
    intersect = left_ids & right_ids
    for cid in intersect:
        has_diff = any(i['tag'] != 'equal' and (i['left'] or i['right']) for i in buckets[cid])
        if not has_diff: stats['l_eq'] += 1; stats['r_eq'] += 1
        else: stats['l_rep'] += 1; stats['r_rep'] += 1

    diff_data = []
    block_id = 0
    for cid, items in buckets.items():
        if not items: continue
        
        left_htmls, right_htmls = [], []
        tag_set = set()
        
        page_l = next((i['page_l'] for i in items if i['page_l']), "1")
        page_r = next((i['page_r'] for i in items if i['page_r']), "1")
        
        for item in items:
            left_htmls.append(f"<div class='inner-line bg-{item['tag']}'>{item['left']}</div>" if item['left'] else "<div class='inner-line bg-empty'></div>")
            right_htmls.append(f"<div class='inner-line bg-{item['tag']}'>{item['right']}</div>" if item['right'] else "<div class='inner-line bg-empty'></div>")
            tag_set.add(item['tag'])
            
        overall_tag = 'equal'
        if 'replace' in tag_set or 'delete' in tag_set or 'insert' in tag_set: overall_tag = 'replace'
        elif 'format' in tag_set: overall_tag = 'format'
        
        diff_data.append({
            'id': block_id,
            'req_id': cid,
            'tag': overall_tag,
            'page_l': page_l,
            'page_r': page_r,
            'left': "".join(left_htmls),
            'right': "".join(right_htmls)
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
                
            if side == 'left': START_FILE_LEFT = save_path; DISPLAY_NAME_LEFT = filename
            elif side == 'right': START_FILE_RIGHT = save_path; DISPLAY_NAME_RIGHT = filename
                
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

    def do_GET(self):
        global START_FILE_LEFT, START_FILE_RIGHT, DISPLAY_NAME_LEFT, DISPLAY_NAME_RIGHT
        parsed_url = urlparse(self.path)
        
        if parsed_url.path == '/api/diff_data':
            try:
                ignore_breaks = parse_qs(parsed_url.query).get('ignore_breaks', ['1'])[0] == '1'
                info_l = get_file_info(START_FILE_LEFT)
                info_r = get_file_info(START_FILE_RIGHT)
                diff, stats = berechne_diff_daten(info_l['content'], info_r['content'], ignore_breaks)
                
                response_json = json.dumps({"diff": diff, "stats": stats}).encode('utf-8')
                self.send_response(200); self.send_header('Content-type', 'application/json')
                self.send_header('Content-Length', str(len(response_json))); self.end_headers()
                self.wfile.write(response_json)
            except Exception as e:
                error_json = json.dumps({"error": str(e)}).encode('utf-8')
                self.send_response(500); self.send_header('Content-type', 'application/json')
                self.send_header('Content-Length', str(len(error_json))); self.end_headers()
                self.wfile.write(error_json)
            return
            
        if parsed_url.path == '/api/jump':
            query = parse_qs(parsed_url.query)
            side = query.get('side', [''])[0]
            page = query.get('page', ['1'])[0]
            success = jump_to_word_page(side, page)
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
            html_content = self.get_html_template().replace("APP_VERSION", APP_VERSION).replace("NAME_LEFT", name_l).replace("NAME_RIGHT", name_r)
            self.wfile.write(html_content.encode('utf-8'))

    def get_html_template(self):
        return """
        <!DOCTYPE html>
        <html lang="de">
        <head>
            <meta charset="utf-8"><title>Advanced Delta Tool</title>
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
                
                .jump-btn { background: #1e1e1e; color: #fff; border: 1px solid #fff; border-radius: 3px; font-size: 10px; cursor: pointer; padding: 3px 6px;}
                .jump-btn:hover { background: #fff; color: #dc3545; }
                
                #nav-buttons { position:fixed; bottom:20px; right:20px; z-index:1000; display:flex; gap:10px; }
                .nav-btn { font-weight:bold; color:white; border:none; padding:10px 15px; border-radius:4px; cursor:pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: background 0.2s;}
                .nav-btn:hover { filter: brightness(1.2); }
                
                .editor-container.view-delta .tag-equal { display: none !important; }
                #loading-screen { position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); color:#007acc; font-size:24px; font-weight:bold; z-index: 1000; text-align: center; }
                
                @media print { 
                    #header-container, #svg-container, #nav-buttons { display: none !important; } 
                    body, #workspace { overflow: visible !important; height: auto !important; } 
                    .editor-container { overflow: visible !important; border: none; padding:0; width:48%; float:left; margin-right:2%;} 
                    .bucket-block { page-break-inside: avoid; border: 1px solid #ccc;}
                    .jump-btn { display: none !important; }
                }
            </style>
        </head>
        <body>
            <div id="loading-screen">⏳ Analysiere Diff-Schablonen... Bitte warten.</div>

            <div id="header-container" style="visibility: hidden;">
                <div class="pane-header left">
                    <span class="header-title" title="NAME_LEFT">📄 NAME_LEFT</span>
                    <select id="view-left" class="view-select" onchange="changeView('left')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
                </div>
                
                <div class="center-panel">
                    <div style="margin-bottom: 5px; font-weight:bold;">APP_VERSION</div>
                    <div id="req-mode-badge" style="display:none; background:#28a745; color:white; padding:2px 4px; border-radius:3px; margin-bottom: 5px; font-weight:bold;">✅ ALIGNED SYNC</div>
                    
                    <div id="stats-panel" style="display:none; width: 100%; background: #1e1e1e; border-radius: 4px; padding: 6px; box-sizing: border-box; text-align: left; margin-bottom: 5px; border: 1px solid #444;">
                        <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center; border-bottom:1px solid #444; padding-bottom:3px;"><b>Statistik (Kapitel/IDs)</b></div>
                        <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                            <div style="width: 48%;">
                                <u style="color:#9cdcfe">Links</u><br>Gleich: <span id="l-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="l-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>Gelöscht: <span id="l-del" style="float:right; font-weight:bold; color:#dc3545;">0</span><br>
                                <div style="border-top: 1px solid #444; margin-top: 2px; padding-top: 2px;">Total: <span id="l-tot" style="float:right;">0</span></div>
                            </div>
                            <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;">
                                <u style="color:#9cdcfe">Rechts</u><br>Gleich: <span id="r-eq" style="float:right; font-weight:bold; color:#888;">0</span><br>
                                Geändert: <span id="r-rep" style="float:right; font-weight:bold; color:#007bff;">0</span><br>Neu: <span id="r-ins" style="float:right; font-weight:bold; color:#28a745;">0</span><br>
                                <div style="border-top: 1px solid #444; margin-top: 2px; padding-top: 2px;">Total: <span id="r-tot" style="float:right;">0</span></div>
                            </div>
                        </div>
                        
                        <div style="border-top: 1px solid #444; margin-top: 6px; padding-top: 4px;">
                            <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center;"><b>Bilder / Medien</b></div>
                            <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                                <div style="width: 48%;">Geändert: <span id="img-rep" style="float:right; font-weight:bold; color:#007bff;">0</span></div>
                                <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;">Neu: <span id="img-ins" style="float:right; font-weight:bold; color:#28a745;">0</span></div>
                            </div>
                        </div>

                        <div style="margin-top: 6px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                            <label style="cursor: pointer; color: #d4d4d4; font-size: 10px; font-weight: bold;"><input type="checkbox" id="chk-ignore-breaks" checked onchange="reloadDiff()"> ⚙️ Umbrüche ignorieren</label>
                        </div>
                        <div style="margin-top: 4px; text-align: center; border-top: 1px solid #444; padding-top: 4px;">
                            <b style="color: #9cdcfe;">MS Word Live-Sync</b><br>
                            <label style="cursor:pointer;"><input type="checkbox" id="sync-left" onchange="doLiveSync()"> Links</label> &nbsp;
                            <label style="cursor:pointer;"><input type="checkbox" id="sync-right" onchange="doLiveSync()"> Rechts</label>
                        </div>
                    </div>

                    <button class="word-btn" onclick="window.print()">🖨️ PDF Report (Drucken)</button>
                </div>
                
                <div class="pane-header right">
                    <span class="header-title" title="NAME_RIGHT">📄 NAME_RIGHT</span>
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
                let diffData = []; let statsData = {};
                let syncTimer = null;
                let lastPageL = -1; let lastPageR = -1;
                let currentDeltaIdx = -1;
                let deltaElements = [];
                
                window.onload = function() { reloadDiff(); };
                
                function reloadDiff() {
                    const ignore = document.getElementById('chk-ignore-breaks') ? document.getElementById('chk-ignore-breaks').checked : true;
                    document.getElementById('loading-screen').style.display = 'block';
                    document.getElementById('workspace').style.visibility = 'hidden';
                    document.getElementById('nav-buttons').style.visibility = 'hidden';
                    
                    fetch('/api/diff_data?ignore_breaks=' + (ignore ? '1' : '0')).then(res => res.json()).then(data => {
                        if (data.error) { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Backend-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${data.error}</span>`; return; }
                        diffData = data.diff; statsData = data.stats;
                        
                        document.getElementById('loading-screen').style.display = 'none';
                        document.getElementById('header-container').style.visibility = 'visible';
                        document.getElementById('workspace').style.visibility = 'visible';
                        document.getElementById('nav-buttons').style.visibility = 'visible';
                        
                        document.getElementById('left-editor').innerHTML = '';
                        document.getElementById('right-editor').innerHTML = '';
                        
                        renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'));
                    }).catch(err => { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Netzwerk-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${err}</span>`; });
                }

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
                        if (response.ok) reloadDiff(); 
                    } catch (error) { alert("Upload-Fehler"); }
                }

                function jumpToPage(side, page) {
                    fetch(`/api/jump?side=${side}&page=${page}`).then(res => res.json()).then(data => {
                        if(!data.success) console.warn("MS Word Fernsteuerung blockiert. Siehe Terminal-Output.");
                    });
                }

                function getPage(eid) {
                    let ed = document.getElementById(eid);
                    let blocks = ed.getElementsByClassName('bucket-block');
                    let curr = 1;
                    let viewCenter = ed.scrollTop + (ed.clientHeight / 2);
                    for(let b of blocks) {
                        if(b.offsetTop <= viewCenter) {
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
                            if(p && p !== lastPageL) { lastPageL = p; jumpToPage('left', p); }
                        }
                        if(document.getElementById('sync-right').checked) {
                            let p = getPage('right-editor');
                            if(p && p !== lastPageR) { lastPageR = p; jumpToPage('right', p); }
                        }
                    }, 800);
                }
                
                function jumpDelta(dir) {
                    if(deltaElements.length === 0) {
                        deltaElements = Array.from(document.getElementById('left-editor').querySelectorAll('.bucket-block:not(.tag-equal)'));
                    }
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
                    
                    deltaElements = [];
                    currentDeltaIdx = -1;
                    
                    setTimeout(drawLines, 50); 
                }

                function safeSetText(id, text) {
                    const el = document.getElementById(id);
                    if (el) el.textContent = text;
                }
                
                function renderSpecialTags(htmlStr, side) {
                    if (!htmlStr) return '';
                    let res = htmlStr.replace(/\[BILD:(.*?)\|HASH:(.*?)\]/g, function(match, pathPart, hashPart) {
                        let isChanged = hashPart.includes("char-diff");
                        let path = pathPart.replace(/<[^>]*>?/gm, '').trim(); 
                        let badge = isChanged ? `<div style="background:#007bff; color:white; font-size:10px; padding:2px 5px; display:inline-block; border-radius:3px; margin-bottom:4px; font-weight:bold; box-shadow: 0 1px 3px rgba(0,0,0,0.5);">🔄 BILD GEÄNDERT</div><br>` : '';
                        let imgClass = isChanged ? 'inline-img img-changed' : 'inline-img';
                        return `<div style="margin-top:10px; margin-bottom:10px;">${badge}<img src="/media?side=${side}&file=${path}" class="${imgClass}" alt="Bild" onload="drawLines()" onerror="this.outerHTML='<div style=\\'color:red; border:1px solid red; padding:5px;\\'>Bild fehlt: ${path}</div>'"></div>`;
                    });
                    res = res.replace(/\[SEITENUMBRUCH:\s*(\d+)\]/g, `<div class="page-break-line" data-page="$1"><span>Seite $1</span></div>`);
                    return res;
                }

                function renderEditors(leftEditor, rightEditor) {
                    try {
                        if (statsData.has_reqs) {
                            const badge = document.getElementById('req-mode-badge');
                            const panel = document.getElementById('stats-panel');
                            if (badge) badge.style.display = 'block';
                            if (panel) panel.style.display = 'block';
                            
                            safeSetText('l-eq', statsData.l_eq); safeSetText('l-rep', statsData.l_rep);
                            safeSetText('l-del', statsData.l_del); safeSetText('l-tot', statsData.l_tot);
                            
                            safeSetText('r-eq', statsData.r_eq); safeSetText('r-rep', statsData.r_rep);
                            safeSetText('r-ins', statsData.r_ins); safeSetText('r-tot', statsData.r_tot);
                            
                            safeSetText('img-rep', statsData.img_rep); safeSetText('img-ins', statsData.img_ins);
                        }

                        if(diffData && diffData.length > 0) {
                            diffData.forEach(block => {
                                const lDiv = document.createElement('div');
                                lDiv.id = `l-${block.id}`; lDiv.className = `bucket-block tag-${block.tag}`;
                                lDiv.setAttribute('data-page', block.page_l);
                                
                                let btnL = `<button class='jump-btn' onclick='jumpToPage("left", ${block.page_l})'>🎯 Word S.${block.page_l}</button>`;
                                let headerL = block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>[${block.req_id}]</span>` : "";
                                let prefixL = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px; display:flex; justify-content:space-between; align-items:center;'>${headerL}${btnL}</div>`;
                                lDiv.innerHTML = prefixL + renderSpecialTags(block.left, 'left');
                                leftEditor.appendChild(lDiv);

                                const rDiv = document.createElement('div');
                                rDiv.id = `r-${block.id}`; rDiv.className = `bucket-block tag-${block.tag}`;
                                rDiv.setAttribute('data-page', block.page_r);
                                
                                let btnR = `<button class='jump-btn' onclick='jumpToPage("right", ${block.page_r})'>🎯 Word S.${block.page_r}</button>`;
                                let headerR = block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>[${block.req_id}]</span>` : "";
                                let prefixR = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px; display:flex; justify-content:space-between; align-items:center;'>${headerR}${btnR}</div>`;
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
                        
                        leftEditor.insertAdjacentHTML('beforeend', '<div class="drag-overlay">📥 HIER ABLEGEN</div>');
                        rightEditor.insertAdjacentHTML('beforeend', '<div class="drag-overlay">📥 HIER ABLEGEN</div>');
                        setTimeout(drawLines, 300);
                        
                        deltaElements = [];
                        currentDeltaIdx = -1;
                        
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
                        
                        const chkMaster = document.getElementById('chk-show-lines');
                        const showLines = chkMaster ? chkMaster.checked : true;
                        if (!showLines) return;
                        
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
                            
                            if (block.tag === 'format') {
                                path.setAttribute('stroke-dasharray', '6,6');
                            }
                            
                            svg.appendChild(path);
                        });
                    } catch(e) {}
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
    
    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt: 
        pass
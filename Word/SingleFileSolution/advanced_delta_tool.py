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
from datetime import datetime

APP_VERSION = "v36.0 (Semantic Header-Break Engine)"

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
    
    if not target_name: return False
        
    try: import win32com.client
    except ImportError: return False
        
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = True 
        doc = None
        for d in word.Documents:
            if target_name.lower() in d.Name.lower() or d.Name.lower() in target_name.lower():
                doc = d; break
                
        if not doc and fallback_path and os.path.exists(fallback_path):
            doc = word.Documents.Open(os.path.abspath(fallback_path))
            
        if not doc: return False
            
        doc.Activate(); word.Activate()
        target_range = doc.GoTo(1, 1, int(page_num))
        target_range.Select()
        word.ActiveWindow.ScrollIntoView(target_range)
        return True
    except Exception as e:
        print(f"WORD-BLOCKADE beim Scrollen: {e}")
        return False

# ==========================================
# PURE PYTHON XML PARSER (Mit Heading-Scanner)
# ==========================================
def get_docx_data(file_path):
    content = []; page_count = [1]
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            rels = {}
            if 'word/_rels/document.xml.rels' in z.namelist():
                import xml.etree.ElementTree as ET
                rels_root = ET.fromstring(z.read('word/_rels/document.xml.rels'))
                for rel in rels_root.iter():
                    if rel.tag.endswith('}Relationship'):
                        r_id = rel.get('Id'); target = rel.get('Target')
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
                        is_heading = False
                        for node in p.iter():
                            if node.tag.endswith('}pStyle'):
                                val = node.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                                if val and re.search(r'(?:heading|berschrift|title|titel)', val, re.IGNORECASE):
                                    is_heading = True
                                    
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
                                        r_id = v; break
                                if r_id and r_id in rels:
                                    img_path = rels[r_id]
                                    img_hash = objects.get(img_path, "NO_HASH")
                                    para_text += f"\n[BILD:{img_path}|HASH:{img_hash}]\n"
                        
                        txt = para_text.strip()
                        if txt:
                            for line in txt.split('\n'):
                                clean_line = line.strip()
                                if clean_line: 
                                    h_tag = "§H§" if is_heading else ""
                                    content.append(f"[P:{page_count[0]}]{h_tag}{clean_line}")
    except Exception as e: print(f"Fehler beim XML-Parsing: {e}")
    return content

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path): return {"path": "", "content": []}
    if file_path.lower().endswith('.docx'): content = get_docx_data(file_path)
    else:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = [f"[P:1]{l.strip()}" for l in f.readlines() if l.strip()]
    return {"path": file_path.replace('\\', '/'), "content": content}

def heal_text(lines):
    res = []; last_major = ""; i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line: i += 1; continue
        m_p = re.match(r'^(\[P:\d+\])(§H§)?(.*)', line)
        p_tag = m_p.group(1) if m_p else ""
        h_tag = "§H§" if m_p and m_p.group(2) else ""
        clean_line = m_p.group(3).strip() if m_p else line
            
        m = re.match(r'^(\d+)(?:\.|$)', clean_line)
        if m: last_major = m.group(1)
        
        if re.match(r'^\d+\.?$', clean_line) and i+1 < len(lines):
            next_m = re.match(r'^(\[P:\d+\])(§H§)?(.*)', lines[i+1].strip())
            next_clean = next_m.group(3).strip() if next_m else lines[i+1].strip()
            if re.match(r'^\.\d+', next_clean):
                merged = clean_line + next_clean
                res.append(p_tag + h_tag + merged)
                m2 = re.match(r'^(\d+)', merged)
                if m2: last_major = m2.group(1)
                i += 2; continue
            
        if re.match(r'^\.\d+', clean_line) and last_major:
            res.append(p_tag + h_tag + last_major + clean_line)
            i += 1; continue
            
        res.append(line); i += 1
    return res

def parse_line_obj(line):
    m = re.match(r'^(\[P:(\d+)\])(§H§)?(.*)', line)
    if m: return m.group(2), bool(m.group(3)), m.group(4).strip()
    return "1", line.startswith('§H§'), line.replace('§H§', '').strip()

def extract_id(text):
    m = re.match(r'^\s*(?:ID\s+\d+:|\[REQ-\d+\]|REQ\s+\d+:|\d+(?:\.\d+)*[a-zA-Z]?|\d+\.)(?:\s|$)', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    return None

def clean_text_for_diff(text):
    t = re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text)
    return re.sub(r'\s+', ' ', t).strip()

def remove_visual_breaks(text):
    return re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text).strip()

def highlight_inline(str_l, str_r):
    if len(str_l) > 3000 or len(str_r) > 3000:
        return f"<span class='char-diff'>{html.escape(str_l)}</span>", f"<span class='char-diff'>{html.escape(str_r)}</span>"
    sm_inline = difflib.SequenceMatcher(None, str_l, str_r)
    left_out, right_out = "", ""
    for op_in, m1, m2, n1, n2 in sm_inline.get_opcodes():
        if op_in == 'equal':
            left_out += html.escape(str_l[m1:m2]); right_out += html.escape(str_r[n1:n2])
        else:
            if m1 != m2: left_out += f"<span class='char-diff'>{html.escape(str_l[m1:m2])}</span>"
            if n1 != n2: right_out += f"<span class='char-diff'>{html.escape(str_r[n1:n2])}</span>"
    return left_out, right_out

def berechne_diff_daten(lines_left, lines_right, ignore_breaks=True):
    lines_left = heal_text(lines_left); lines_right = heal_text(lines_right)
    objs_l = [{'page': p, 'is_h': h, 'text': t} for p, h, t in (parse_line_obj(l) for l in lines_left)]
    objs_r = [{'page': p, 'is_h': h, 'text': t} for p, h, t in (parse_line_obj(r) for r in lines_right)]
    
    clean_l = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_l]
    clean_r = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_r]

    sm = difflib.SequenceMatcher(None, clean_l, clean_r, autojunk=False)
    buckets = collections.OrderedDict()
    current_id = "HEADER (Deckblatt/Inhaltsverzeichnis)"
    buckets[current_id] = []
    
    stats = {"l_eq": 0, "l_rep": 0, "l_del": 0, "l_tot": 0, "r_eq": 0, "r_rep": 0, "r_ins": 0, "r_tot": 0, "img_eq": 0, "img_rep": 0, "img_del": 0, "img_ins": 0, "has_reqs": False}
    
    def assign_bucket(o_l, o_r, cur_id):
        txt_l = o_l['text'] if o_l else ""
        txt_r = o_r['text'] if o_r else ""
        is_h = (o_l and o_l['is_h']) or (o_r and o_r['is_h'])
        cid = extract_id(txt_r) or extract_id(txt_l)
        
        if cid:
            if cid not in buckets: buckets[cid] = []
            return cid
        elif is_h:
            disp = (txt_r or txt_l)[:40]
            new_id = f"[{disp}]"
            while new_id in buckets: new_id += " " # Unsichtbare Spaces für Unique Dictionary Keys
            buckets[new_id] = []
            return new_id
        return cur_id

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for o_l, o_r in zip(objs_l[i1:i2], objs_r[j1:j2]):
                current_id = assign_bucket(o_l, o_r, current_id)
                stats['img_eq'] += len(re.findall(r'\[BILD:', o_l['text']))
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                if ignore_breaks and not disp_l and not disp_r: continue
                buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': html.escape(disp_r), 'page_l': o_l['page'], 'page_r': o_r['page']})
                
        elif op == 'replace':
            for k in range(max(len(objs_l[i1:i2]), len(objs_r[j1:j2]))):
                o_l = objs_l[i1:i2][k] if k < len(objs_l[i1:i2]) else None
                o_r = objs_r[j1:j2][k] if k < len(objs_r[j1:j2]) else None
                current_id = assign_bucket(o_l, o_r, current_id)
                
                txt_l = o_l['text'] if o_l else ""
                txt_r = o_r['text'] if o_r else ""
                c_l = clean_text_for_diff(txt_l); c_r = clean_text_for_diff(txt_r)
                disp_l = remove_visual_breaks(txt_l) if ignore_breaks else txt_l
                disp_r = remove_visual_breaks(txt_r) if ignore_breaks else txt_r
                page_l = o_l['page'] if o_l else ''
                page_r = o_r['page'] if o_r else ''
                
                if ignore_breaks and c_l == c_r:
                    if disp_l or disp_r: buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': html.escape(disp_r), 'page_l': page_l, 'page_r': page_r})
                    continue

                if txt_l and txt_r:
                    l_imgs = len(re.findall(r'\[BILD:', txt_l)); r_imgs = len(re.findall(r'\[BILD:', txt_r))
                    stats['img_rep'] += min(l_imgs, r_imgs)
                    if r_imgs > l_imgs: stats['img_ins'] += (r_imgs - l_imgs)
                    if l_imgs > r_imgs: stats['img_del'] += (l_imgs - r_imgs)
                    l_out, r_out = highlight_inline(disp_l, disp_r)
                    current_tag = 'format' if (not ignore_breaks and c_l == c_r and disp_l != disp_r) else 'replace'
                    buckets[current_id].append({'tag': current_tag, 'left': l_out, 'right': r_out, 'page_l': page_l, 'page_r': page_r})
                elif txt_l:
                    if ignore_breaks and not c_l:
                        if disp_l: buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': "", 'page_l': page_l, 'page_r': ''})
                    else:
                        stats['img_del'] += len(re.findall(r'\[BILD:', txt_l))
                        current_tag = 'format' if (not ignore_breaks and not c_l) else 'delete'
                        buckets[current_id].append({'tag': current_tag, 'left': html.escape(disp_l), 'right': "", 'page_l': page_l, 'page_r': ''})
                elif txt_r:
                    if ignore_breaks and not c_r:
                        if disp_r: buckets[current_id].append({'tag': 'equal', 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': page_r})
                    else:
                        stats['img_ins'] += len(re.findall(r'\[BILD:', txt_r))
                        current_tag = 'format' if (not ignore_breaks and not c_r) else 'insert'
                        buckets[current_id].append({'tag': current_tag, 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': page_r})
                    
        elif op == 'delete':
            for o_l in objs_l[i1:i2]:
                current_id = assign_bucket(o_l, None, current_id)
                txt_l = o_l['text']
                c_l = clean_text_for_diff(txt_l)
                disp_l = remove_visual_breaks(txt_l) if ignore_breaks else txt_l
                
                if ignore_breaks and not c_l:
                    if disp_l: buckets[current_id].append({'tag': 'equal', 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                else:
                    stats['img_del'] += len(re.findall(r'\[BILD:', txt_l))
                    current_tag = 'format' if (not ignore_breaks and not c_l) else 'delete'
                    buckets[current_id].append({'tag': current_tag, 'left': html.escape(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                
        elif op == 'insert':
            for o_r in objs_r[j1:j2]:
                current_id = assign_bucket(None, o_r, current_id)
                txt_r = o_r['text']
                c_r = clean_text_for_diff(txt_r)
                disp_r = remove_visual_breaks(txt_r) if ignore_breaks else txt_r
                
                if ignore_breaks and not c_r:
                    if disp_r: buckets[current_id].append({'tag': 'equal', 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})
                else:
                    stats['img_ins'] += len(re.findall(r'\[BILD:', txt_r))
                    current_tag = 'format' if (not ignore_breaks and not c_r) else 'insert'
                    buckets[current_id].append({'tag': current_tag, 'left': "", 'right': html.escape(disp_r), 'page_l': '', 'page_r': o_r['page']})

    left_ids = set(); right_ids = set()
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

    diff_data = []; block_id = 0
    for cid, items in buckets.items():
        if not items: continue
        left_htmls = []; right_htmls = []; tag_set = set()
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
            'id': block_id, 'req_id': cid, 'tag': overall_tag,
            'page_l': page_l, 'page_r': page_r,
            'left': "".join(left_htmls), 'right': "".join(right_htmls)
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
                
                meta_l = os.path.getmtime(START_FILE_LEFT) if START_FILE_LEFT and os.path.exists(START_FILE_LEFT) else 0
                meta_r = os.path.getmtime(START_FILE_RIGHT) if START_FILE_RIGHT and os.path.exists(START_FILE_RIGHT) else 0
                
                metadata = {
                    "app_version": APP_VERSION,
                    "file_left": DISPLAY_NAME_LEFT,
                    "time_left": datetime.fromtimestamp(meta_l).strftime('%Y-%m-%d %H:%M:%S') if meta_l else "",
                    "file_right": DISPLAY_NAME_RIGHT,
                    "time_right": datetime.fromtimestamp(meta_r).strftime('%Y-%m-%d %H:%M:%S') if meta_r else ""
                }
                
                response_json = json.dumps({"diff": diff, "stats": stats, "metadata": metadata}).encode('utf-8')
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
                .header-title { font-weight: bold; color: #9cdcfe; font-size: 15px; max-width: 250px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: #1e1e1e; padding: 4px 10px; border-radius: 4px; border: 1px solid #555;}
                
                .file-btn { background: #333; border: 1px solid #555; color: #d4d4d4; padding: 5px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
                .file-btn:hover { background: #555; color: #fff; }
                
                .view-select { background: #007acc; border: 1px solid #005f9e; color: white; padding: 5px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; cursor: pointer; outline: none;}
                .word-btn { background: #107c41; margin-top: 5px; width: 100%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
                .review-btn { background: #8e44ad; margin-top: 5px; width: 48%; border:none; color:white; padding:4px; font-size:11px; cursor:pointer; border-radius: 3px; font-weight:bold;}
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
                
                .jump-btn { background: #1e1e1e; color: #fff; border: 1px solid #fff; border-radius: 3px; font-size: 10px; cursor: pointer; padding: 3px 6px; margin-left: 10px;}
                .jump-btn:hover { background: #fff; color: #dc3545; }
                
                .review-widget { margin-top: 5px; padding: 5px; background: #1e1e1e; border: 1px solid #555; border-radius: 3px; display: flex; gap: 5px; }
                .review-widget select { background: #333; color: white; border: 1px solid #555; border-radius: 2px; font-size: 11px; padding: 2px; }
                .review-widget input { flex: 1; background: #333; color: white; border: 1px solid #555; border-radius: 2px; font-size: 11px; padding: 2px 5px; }
                
                #nav-buttons { position:fixed; bottom:20px; right:20px; z-index:1000; display:flex; gap:10px; }
                .nav-btn { font-weight:bold; color:white; border:none; padding:10px 15px; border-radius:4px; cursor:pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: background 0.2s;}
                .nav-btn:hover { filter: brightness(1.2); }
                
                .editor-container.view-delta .tag-equal { display: none !important; }
                #loading-screen { position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); color:#007acc; font-size:24px; font-weight:bold; z-index: 1000; text-align: center; }
                
                @media print { 
                    #header-container, #svg-container, #nav-buttons, .review-widget { display: none !important; } 
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
                    <span class="header-title" id="title-left" title="NAME_LEFT">📄 NAME_LEFT</span>
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <button class="file-btn" onclick="document.getElementById('file-left').click()">📂 Ändern</button>
                        <input type="file" id="file-left" style="display:none;" accept=".docx,.txt,.md" onchange="handleFileUpload(event, 'left')">
                        <select id="view-left" class="view-select" onchange="changeView('left')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
                    </div>
                </div>
                
                <div class="center-panel">
                    <div style="margin-bottom: 5px; font-weight:bold;">APP_VERSION</div>
                    
                    <div id="stats-panel" style="display:none; width: 100%; background: #1e1e1e; border-radius: 4px; padding: 6px; box-sizing: border-box; text-align: left; margin-bottom: 5px; border: 1px solid #444;">
                        <div style="color:#d4d4d4; font-size:11px; margin-bottom:4px; text-align:center; border-bottom:1px solid #444; padding-bottom:3px;"><b>Statistik (Kapitel/IDs)</b></div>
                        <div style="display:flex; justify-content: space-between; font-size: 9px; line-height: 1.4;">
                            <div style="width: 48%;"><u style="color:#9cdcfe">Links</u><br>Gleich: <span id="l-eq" style="float:right; font-weight:bold;">0</span><br>Geändert: <span id="l-rep" style="float:right; font-weight:bold;">0</span><br>Gelöscht: <span id="l-del" style="float:right; font-weight:bold;">0</span></div>
                            <div style="border-left: 1px solid #444; padding-left: 4px; width: 48%;"><u style="color:#9cdcfe">Rechts</u><br>Gleich: <span id="r-eq" style="float:right; font-weight:bold;">0</span><br>Geändert: <span id="r-rep" style="float:right; font-weight:bold;">0</span><br>Neu: <span id="r-ins" style="float:right; font-weight:bold;">0</span></div>
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
                            <b style="color: #9cdcfe; font-size:10px;">MS Word Live-Sync</b><br>
                            <label style="cursor:pointer; font-size:10px;"><input type="checkbox" id="sync-left" onchange="doLiveSync()"> Links</label> &nbsp;
                            <label style="cursor:pointer; font-size:10px;"><input type="checkbox" id="sync-right" onchange="doLiveSync()"> Rechts</label>
                        </div>
                    </div>

                    <div style="display: flex; justify-content: space-between; width: 100%;">
                        <button class="review-btn" onclick="importJSONTrigger()">📂 Load</button>
                        <button class="review-btn" onclick="exportJSON()">💾 Save</button>
                    </div>
                    <input type="file" id="json-upload" style="display:none;" accept=".json" onchange="importJSON(event)">
                </div>
                
                <div class="pane-header right">
                    <span class="header-title" id="title-right" title="NAME_RIGHT">📄 NAME_RIGHT</span>
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <button class="file-btn" onclick="document.getElementById('file-right').click()">📂 Ändern</button>
                        <input type="file" id="file-right" style="display:none;" accept=".docx,.txt,.md" onchange="handleFileUpload(event, 'right')">
                        <select id="view-right" class="view-select" onchange="changeView('right')"><option value="all">Ansicht: Alles</option><option value="delta">Nur Deltas</option><option value="equal">Nur Gleiche</option></select>
                    </div>
                </div>
            </div>

            <div id="workspace" style="visibility: hidden;">
                <div id="left-editor" class="editor-container" ondrop="handleDrop(event, 'left')"></div>
                <div id="svg-container"><svg id="lines-svg"></svg></div>
                <div id="right-editor" class="editor-container" ondrop="handleDrop(event, 'right')"></div>
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
                
                let reviewData = {
                    schema_version: "1.0",
                    app_version: "APP_VERSION",
                    metadata: {},
                    reviews: {}
                };
                
                window.onload = function() { reloadDiff(); };
                
                function reloadDiff() {
                    const ignore = document.getElementById('chk-ignore-breaks') ? document.getElementById('chk-ignore-breaks').checked : true;
                    document.getElementById('loading-screen').style.display = 'block';
                    document.getElementById('workspace').style.visibility = 'hidden';
                    document.getElementById('nav-buttons').style.visibility = 'hidden';
                    
                    fetch('/api/diff_data?ignore_breaks=' + (ignore ? '1' : '0')).then(res => res.json()).then(data => {
                        if (data.error) { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Backend-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${data.error}</span>`; return; }
                        diffData = data.diff; statsData = data.stats; metaData = data.metadata;
                        
                        reviewData.metadata = metaData;
                        
                        safeSetText('title-left', "📄 " + metaData.file_left);
                        document.getElementById('title-left').title = metaData.file_left;
                        safeSetText('title-right', "📄 " + metaData.file_right);
                        document.getElementById('title-right').title = metaData.file_right;
                        
                        document.getElementById('loading-screen').style.display = 'none';
                        document.getElementById('header-container').style.visibility = 'visible';
                        document.getElementById('workspace').style.visibility = 'visible';
                        document.getElementById('nav-buttons').style.visibility = 'visible';
                        
                        document.getElementById('left-editor').innerHTML = '';
                        document.getElementById('right-editor').innerHTML = '';
                        
                        renderEditors(document.getElementById('left-editor'), document.getElementById('right-editor'));
                    }).catch(err => { document.getElementById('loading-screen').innerHTML = `<span style="color:#dc3545">❌ Netzwerk-Fehler:</span><br><br><span style="font-size:14px; color:#d4d4d4">${err}</span>`; });
                }

                function escapeHtml(unsafe) {
                    return (unsafe || "").toString()
                        .replace(/&/g, "&amp;")
                        .replace(/</g, "&lt;")
                        .replace(/>/g, "&gt;")
                        .replace(/"/g, "&quot;")
                        .replace(/'/g, "&#039;");
                }

                function updateReview(reqId, field, value) {
                    if(!reviewData.reviews[reqId]) reviewData.reviews[reqId] = {status: "", comment: ""};
                    reviewData.reviews[reqId][field] = value;
                }

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
                    const file = event.target.files[0];
                    if(!file) return;
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

                async function uploadFileObj(file, side) {
                    document.getElementById('loading-screen').style.display = 'block';
                    document.getElementById('loading-screen').innerHTML = '⏳ Lade hoch...';
                    document.getElementById('workspace').style.visibility = 'hidden';
                    try {
                        const arrayBuffer = await file.arrayBuffer();
                        const response = await fetch(`/api/upload?side=${side}&filename=${encodeURIComponent(file.name)}`, { method: 'POST', body: arrayBuffer });
                        if (response.ok) reloadDiff(); 
                        else alert("Fehler vom Server beim Upload.");
                    } catch (error) { 
                        alert("Upload-Fehler: " + error); reloadDiff();
                    }
                }

                async function handleDrop(e, side) {
                    e.preventDefault(); 
                    if(e.currentTarget.classList) e.currentTarget.classList.remove('drag-over');
                    const file = e.dataTransfer.files[0];
                    if (!file) return;
                    await uploadFileObj(file, side);
                }

                async function handleFileUpload(e, side) {
                    const file = e.target.files[0];
                    if (!file) return;
                    await uploadFileObj(file, side);
                    e.target.value = ""; 
                }

                function jumpToPage(side, page) {
                    fetch(`/api/jump?side=${side}&page=${page}`).then(res => res.json()).then(data => {
                        if(!data.success) console.warn("MS Word Fernsteuerung blockiert.");
                    });
                }

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
                    deltaElements = []; currentDeltaIdx = -1;
                    setTimeout(drawLines, 50); 
                }

                function safeSetText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }
                
                function renderSpecialTags(htmlStr, side) {
                    if (!htmlStr) return '';
                    let res = htmlStr.replace(/\[BILD:(.*?)\|HASH:(.*?)\]/g, function(match, pathPart, hashPart) {
                        let isChanged = hashPart.includes("char-diff");
                        let path = pathPart.replace(/<[^>]*>?/gm, '').trim(); 
                        let badge = isChanged ? `<div style="background:#007bff; color:white; font-size:10px; padding:2px 5px; display:inline-block; border-radius:3px; margin-bottom:4px; font-weight:bold;">🔄 BILD GEÄNDERT</div><br>` : '';
                        let imgClass = isChanged ? 'inline-img img-changed' : 'inline-img';
                        return `<div style="margin-top:10px; margin-bottom:10px;">${badge}<img src="/media?side=${side}&file=${path}" class="${imgClass}" alt="Bild" onload="drawLines()" onerror="this.outerHTML='<div style=\\'color:red; border:1px solid red; padding:5px;\\'>Bild fehlt: ${path}</div>'"></div>`;
                    });
                    res = res.replace(/\[SEITENUMBRUCH:\s*(\d+)\]/g, ``);
                    return res;
                }

                function renderEditors(leftEditor, rightEditor) {
                    try {
                        const reviewSide = document.getElementById('review-side').value;
                        
                        if (statsData.has_reqs) {
                            document.getElementById('stats-panel').style.display = 'block';
                            safeSetText('l-eq', statsData.l_eq); safeSetText('l-rep', statsData.l_rep); safeSetText('l-del', statsData.l_del);
                            safeSetText('r-eq', statsData.r_eq); safeSetText('r-rep', statsData.r_rep); safeSetText('r-ins', statsData.r_ins);
                        }

                        leftEditor.innerHTML = ''; rightEditor.innerHTML = '';

                        if(diffData && diffData.length > 0) {
                            diffData.forEach(block => {
                                const needsReview = block.tag !== 'equal' && block.req_id !== "HEADER (Deckblatt/Inhaltsverzeichnis)";
                                const rawId = block.req_id;
                                const dispName = rawId.trim(); 
                                const reviewHTML = needsReview ? buildReviewWidget(rawId) : "";

                                const lDiv = document.createElement('div');
                                lDiv.id = `l-${block.id}`; lDiv.className = `bucket-block tag-${block.tag}`;
                                lDiv.setAttribute('data-page', block.page_l);
                                
                                let btnL = `<button class='jump-btn' onclick='jumpToPage("left", ${block.page_l})'>🎯 Word S.${block.page_l}</button>`;
                                let headerL = dispName !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>${dispName}</span>` : "";
                                let revL = (needsReview && reviewSide === 'left') ? reviewHTML : "";
                                let prefixL = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px;'>
                                    <div style='display:flex; justify-content:space-between; align-items:center;'>${headerL}${btnL}</div>
                                    ${revL}
                                </div>`;
                                lDiv.innerHTML = prefixL + renderSpecialTags(block.left, 'left');
                                leftEditor.appendChild(lDiv);

                                const rDiv = document.createElement('div');
                                rDiv.id = `r-${block.id}`; rDiv.className = `bucket-block tag-${block.tag}`;
                                rDiv.setAttribute('data-page', block.page_r);
                                
                                let btnR = `<button class='jump-btn' onclick='jumpToPage("right", ${block.page_r})'>🎯 Word S.${block.page_r}</button>`;
                                let headerR = dispName !== "HEADER (Deckblatt/Inhaltsverzeichnis)" ? `<span>${dispName}</span>` : "";
                                let revR = (needsReview && reviewSide === 'right') ? reviewHTML : "";
                                let prefixR = `<div style='color:#9cdcfe; font-weight:bold; margin-bottom:6px; font-size:14px; border-bottom:1px solid #444; padding-bottom:2px;'>
                                    <div style='display:flex; justify-content:space-between; align-items:center;'>${headerR}${btnR}</div>
                                    ${revR}
                                </div>`;
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
                        
                        leftEditor.insertAdjacentHTML('beforeend', '<div class="drag-overlay" ondragenter="handleDragOver(event)" ondragleave="handleDragLeave(event)">📥 HIER ABLEGEN</div>');
                        rightEditor.insertAdjacentHTML('beforeend', '<div class="drag-overlay" ondragenter="handleDragOver(event)" ondragleave="handleDragLeave(event)">📥 HIER ABLEGEN</div>');
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
                            
                            if (block.tag === 'format') { path.setAttribute('stroke-dasharray', '6,6'); }
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
                    isSyncingLeft = false; doLiveSync();
                });
                document.getElementById('right-editor')?.addEventListener('scroll', function() {
                    if (!isSyncingRight) {
                        isSyncingLeft = true;
                        document.getElementById('left-editor').scrollTop = this.scrollTop / (this.scrollHeight - this.clientHeight) * (document.getElementById('left-editor').scrollHeight - document.getElementById('left-editor').clientHeight);
                        drawLines();
                    }
                    isSyncingRight = false; doLiveSync();
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
        while True: threading.Event().wait(1)
    except KeyboardInterrupt: pass
# diff_logic.py
# ANFANG
import re
import difflib
import collections
import config

def parse_line_obj(line):
    """Zerlegt eine Zeile in Seitenzahl und Text."""
    m = re.match(r'^(\[P:(\d+)\])(.*)', line)
    if m:
        return m.group(2), m.group(3).strip()
    return "1", line.strip()

def heal_text(lines):
    """Repariert zerstückelte Kapitelnummern."""
    res = []; last_major = ""; i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line: i += 1; continue
        m_p = re.match(r'^(\[P:\d+\])(.*)', line)
        p_tag = m_p.group(1) if m_p else ""
        clean_line = m_p.group(2).strip() if m_p else line
            
        m = re.match(r'^(\d+)(?:\.|$)', clean_line)
        if m: last_major = m.group(1)
        
        # Verschmelzen von "2." und ".1" zu "2.1"
        if re.match(r'^\d+\.?$', clean_line) and i+1 < len(lines):
            next_m = re.match(r'^(\[P:\d+\])(.*)', lines[i+1].strip())
            next_clean = next_m.group(2).strip() if next_m else lines[i+1].strip()
            if re.match(r'^\.\d+', next_clean):
                merged = clean_line + next_clean
                res.append(p_tag + merged)
                m2 = re.match(r'^(\d+)', merged)
                if m2: last_major = m2.group(1)
                i += 2; continue
        
        # Anhängen von ".1" an "2" zu "2.1"
        if re.match(r'^\.\d+', clean_line) and last_major:
            res.append(p_tag + last_major + clean_line)
            i += 1; continue
            
        res.append(line); i += 1
    return res

def clean_text_for_diff(text):
    """Entfernt Umbrüche und normalisiert Leerzeichen für den Vergleich."""
    t = re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text)
    return re.sub(r'\s+', ' ', t).strip()

def remove_visual_breaks(text):
    """Entfernt visuelle Umbruch-Tags für die Anzeige."""
    return re.sub(r'\[SEITENUMBRUCH:\d+\]', '', text).strip()

def highlight_inline_diff(str_l, str_r):
    """Erzeugt Inline-Highlights für geänderte Zeichen."""
    # Schutz vor extrem langen Zeilen
    if len(str_l) > 2000 or len(str_r) > 2000:
        return f"<span class='char-diff'>{config.escape_html(str_l)}</span>", \
               f"<span class='char-diff'>{config.escape_html(str_r)}</span>"
               
    sm_inline = difflib.SequenceMatcher(None, str_l, str_r)
    left_out, right_out = "", ""
    for op_in, m1, m2, n1, n2 in sm_inline.get_opcodes():
        if op_in == 'equal':
            left_out += config.escape_html(str_l[m1:m2])
            right_out += config.escape_html(str_r[n1:n2])
        else:
            # Änderungen markieren
            if m1 != m2:
                left_out += f"<span class='char-diff'>{config.escape_html(str_l[m1:m2])}</span>"
            if n1 != n2:
                right_out += f"<span class='char-diff'>{config.escape_html(str_r[n1:n2])}</span>"
    return left_out, right_out

def berechne_diff_daten(lines_left, lines_right, ignore_breaks=True):
    """Führt den difflib Vergleich durch und bereitet Daten für UI auf."""
    
    # 1. Textreparatur & Zerlegung
    lines_left = heal_text(lines_left)
    lines_right = heal_text(lines_right)
    
    objs_l = [{'page': p, 'text': t} for p, t in (parse_line_obj(l) for l in lines_left)]
    objs_r = [{'page': p, 'text': t} for p, t in (parse_line_obj(r) for r in lines_right)]
    
    # 2. Reintext für Vergleich normalisieren
    clean_l = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_l]
    clean_r = [clean_text_for_diff(o['text']) if ignore_breaks else o['text'] for o in objs_r]

    # 3. difflib Vergleich
    sm = difflib.SequenceMatcher(None, clean_l, clean_r, autojunk=False)
    buckets = collections.OrderedDict()
    current_id = "HEADER (Deckblatt/Inhaltsverzeichnis)"
    buckets[current_id] = []
    
    # Statistik-Zähler
    stats = {"l_eq": 0, "l_rep": 0, "l_del": 0, "l_tot": 0, "r_eq": 0, "r_rep": 0, "r_ins": 0, "r_tot": 0, "img_eq": 0, "img_rep": 0, "img_del": 0, "img_ins": 0, "has_reqs": False}
    
    # 4. Opcodes durchlaufen und Buckets füllen
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            for o_l, o_r in zip(objs_l[i1:i2], objs_r[j1:j2]):
                stats['img_eq'] += len(re.findall(r'\[BILD:', o_l['text']))
                cid = config.extract_id(o_r['text']) or config.extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                
                if ignore_breaks and not disp_l and not disp_r: continue
                buckets[current_id].append({'tag': 'equal', 'left': config.escape_html(disp_l), 'right': config.escape_html(disp_r), 'page_l': o_l['page'], 'page_r': o_r['page']})
                
        elif op == 'replace':
            for k in range(max(len(objs_l[i1:i2]), len(objs_r[j1:j2]))):
                o_l = objs_l[i1:i2][k] if k < len(objs_l[i1:i2]) else {'page': '', 'text': ''}
                o_r = objs_r[j1:j2][k] if k < len(objs_r[j1:j2]) else {'page': '', 'text': ''}
                
                cid = config.extract_id(o_r['text']) or config.extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                
                c_l = clean_text_for_diff(o_l['text'])
                c_r = clean_text_for_diff(o_r['text'])
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']

                # Spezialfall: Nur Umbrüche haben sich geändert, Text ist gleich
                if ignore_breaks and c_l == c_r:
                    if disp_l or disp_r:
                        buckets[current_id].append({'tag': 'equal', 'left': config.escape_html(disp_l), 'right': config.escape_html(disp_r), 'page_l': o_l['page'], 'page_r': o_r['page']})
                    continue

                if o_l['text'] and o_r['text']:
                    # Echter Text- oder Bildersatz
                    l_imgs = len(re.findall(r'\[BILD:', o_l['text']))
                    r_imgs = len(re.findall(r'\[BILD:', o_r['text']))
                    stats['img_rep'] += min(l_imgs, r_imgs)
                    if r_imgs > l_imgs: stats['img_ins'] += (r_imgs - l_imgs)
                    if l_imgs > r_imgs: stats['img_del'] += (l_imgs - r_imgs)
                    
                    l_out, r_out = highlight_inline_diff(disp_l, disp_r)
                    current_tag = 'format' if (not ignore_breaks and c_l == c_r and disp_l != disp_r) else 'replace'
                    buckets[current_id].append({'tag': current_tag, 'left': l_out, 'right': r_out, 'page_l': o_l['page'], 'page_r': o_r['page']})
                elif o_l['text']:
                    # Zeile links gelöscht
                    stats['img_del'] += len(re.findall(r'\[BILD:', o_l['text']))
                    buckets[current_id].append({'tag': 'delete', 'left': config.escape_html(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                elif o_r['text']:
                    # Zeile rechts eingefügt
                    stats['img_ins'] += len(re.findall(r'\[BILD:', o_r['text']))
                    buckets[current_id].append({'tag': 'insert', 'left': "", 'right': config.escape_html(disp_r), 'page_l': '', 'page_r': o_r['page']})
                    
        elif op == 'delete':
            for o_l in objs_l[i1:i2]:
                stats['img_del'] += len(re.findall(r'\[BILD:', o_l['text']))
                cid = config.extract_id(o_l['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                disp_l = remove_visual_breaks(o_l['text']) if ignore_breaks else o_l['text']
                buckets[current_id].append({'tag': 'delete', 'left': config.escape_html(disp_l), 'right': "", 'page_l': o_l['page'], 'page_r': ''})
                
        elif op == 'insert':
            for o_r in objs_r[j1:j2]:
                stats['img_ins'] += len(re.findall(r'\[BILD:', o_r['text']))
                cid = config.extract_id(o_r['text'])
                if cid: 
                    current_id = cid
                    if current_id not in buckets: buckets[current_id] = []
                disp_r = remove_visual_breaks(o_r['text']) if ignore_breaks else o_r['text']
                buckets[current_id].append({'tag': 'insert', 'left': "", 'right': config.escape_html(disp_r), 'page_l': '', 'page_r': o_r['page']})

    # 5. Statistik berechnen (nach Kapitel-IDs)
    left_ids = set()
    right_ids = set()
    for cid, items in buckets.items():
        if cid == "HEADER (Deckblatt/Inhaltsverzeichnis)": continue
        if any(i['left'] for i in items): left_ids.add(cid)
        if any(i['right'] for i in items): right_ids.add(cid)
        
    stats["l_del"] = len(left_ids - right_ids)
    stats["l_tot"] = len(left_ids)
    stats["r_ins"] = len(right_ids - left_ids)
    stats["r_tot"] = len(right_ids)
    stats["has_reqs"] = len(left_ids) > 0 or len(right_ids) > 0
    
    intersect = left_ids & right_ids
    for cid in intersect:
        has_diff = any(i['tag'] != 'equal' and (i['left'] or i['right']) for i in buckets[cid])
        if not has_diff: stats['l_eq'] += 1; stats['r_eq'] += 1
        else: stats['l_rep'] += 1; stats['r_rep'] += 1

    # 6. Finale Datenstruktur für UI bauen (flache Liste)
    diff_data = []
    block_id = 0
    for cid, items in buckets.items():
        if not items: continue
        left_htmls = []
        right_htmls = []
        tag_set = set()
        
        # Bestimme Haupt-Seitenzahl für den gesamten Block
        page_l = next((i['page_l'] for i in items if i['page_l']), "1")
        page_r = next((i['page_r'] for i in items if i['page_r']), "1")
        
        for item in items:
            l_content = f"<div class='inner-line bg-{item['tag']}'>{item['left']}</div>" if item['left'] else "<div class='inner-line bg-empty'></div>"
            r_content = f"<div class='inner-line bg-{item['tag']}'>{item['right']}</div>" if item['right'] else "<div class='inner-line bg-empty'></div>"
            left_htmls.append(l_content)
            right_htmls.append(r_content)
            tag_set.add(item['tag']);
            
        # FIX (Zeile 217): Python-Kommentar statt JavaScript-Kommentar
        # Gesamt-Tag für Filterung
        overall_tag = 'equal'
        if 'replace' in tag_set or 'delete' in tag_set or 'insert' in tag_set:
            overall_tag = 'replace'
        elif 'format' in tag_set:
            overall_tag = 'format'
        
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
# ENDE
import difflib
import os
import html
import csv
import sys
import re
import math
from collections import Counter
import tkinter as tk
from tkinter import filedialog

# --- DOORS Next 7.0.2 Fix: Feldgrößen-Limit aufheben für riesige Rich-Text-Zellen ---
csv.field_size_limit(sys.maxsize)

# --- App Konfiguration ---
APP_VERSION = "v5.17"

# Globales Dictionary für den Fortschritt (wird in-place aktualisiert)
PROGRESS_STATE = {"status": "Bereit", "percent": 0}

def set_progress(status, percent):
    PROGRESS_STATE["status"] = status
    PROGRESS_STATE["percent"] = percent

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
    except Exception:
        pass
    
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
            parsed_rows.append((raw_text, row))
            prev_line_num = current_line_num
    except Exception as e:
        print(f"CSV Warnung (Fallback greift): {e}")
        
    return parsed_rows

def normalize_text(text, filters):
    if not text: return ""
    
    if 'strip_html' in filters:
        text = re.sub(r'<[^>]+>', '', text)
        
    if 'norm_typo' in filters:
        text = text.replace('„', '"').replace('“', '"').replace('”', '"')
        text = text.replace('‘', "'").replace('’', "'").replace('‚', "'")
        text = text.replace('–', '-').replace('—', '-')
        
    if 'norm_space' in filters:
        text = text.replace('\xa0', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
    else:
        text = text.strip()
        
    if 'ignore_case' in filters:
        text = text.lower()
        
    return text

# ==============================================================================
# NEU v5.17: OFFLINE INHALTS-ANALYSE (TF-IDF + N-Gramme + Containment)
# ==============================================================================
STOPWORDS_DE_EN = {
    "der", "die", "das", "ein", "eine", "einer", "eines", "einem", "einen",
    "und", "oder", "aber", "wenn", "falls", "weil", "dass", "als", "wie",
    "in", "im", "an", "am", "auf", "aus", "bei", "mit", "nach", "seit",
    "von", "vom", "zu", "zum", "zur", "für", "über", "unter", "durch",
    "ist", "sind", "war", "waren", "wird", "werden", "wurde", "wurden",
    "hat", "haben", "hatte", "hatten", "kann", "können", "muss", "müssen",
    "soll", "sollen", "darf", "dürfen", "nicht", "kein", "keine", "auch",
    "the", "and", "or", "if", "when", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "is", "are", "was", "were", "be", "been", "shall",
    "must", "should", "can", "will", "not", "no"
}

def extract_word_tokens(text):
    """Zerlegt Text in bereinigte Wörter (Zahlen, Einheiten & Fachbegriffe bleiben erhalten)."""
    words = re.findall(r'[a-zA-ZäöüÄÖÜß0-9_]+', text.lower())
    return [w for w in words if (len(w) > 1 or w.isdigit()) and w not in STOPWORDS_DE_EN]

def extract_char_trigrams(text):
    """Zerlegt Text in 3-Buchstaben-Häppchen, um deutsche Wortstämme/Komposita zu erkennen."""
    clean = re.sub(r'\s+', ' ', text.lower()).strip()
    if len(clean) < 3:
        return Counter([clean]) if clean else Counter()
    return Counter(clean[i:i+3] for i in range(len(clean) - 2))

def build_idf_weights(docs_tokens):
    """Berechnet das Gewicht jedes Wortes: Seltene Fachbegriffe hoch, häufige Wörter niedrig."""
    doc_count = len(docs_tokens)
    if doc_count == 0:
        return {}
    df = Counter()
    for tokens in docs_tokens:
        for t in set(tokens):
            df[t] += 1
    return {t: math.log(1.0 + (doc_count / (1.0 + freq))) for t, freq in df.items()}

def calc_content_similarity(tokens1, tokens2, trigrams1, trigrams2, idf):
    """Berechnet die inhaltliche Nähe (0.0 bis 59.9%) unabhängig vom Satzbau."""
    if not tokens1 and not tokens2:
        return 0.0

    # 1. TF-IDF gewichtete Kosinus-Ähnlichkeit der Wörter (Reihenfolge egal)
    c1, c2 = Counter(tokens1), Counter(tokens2)
    all_words = set(c1.keys()) | set(c2.keys())
    
    dot_word = sum(c1[w] * c2[w] * (idf.get(w, 1.0) ** 2) for w in all_words)
    norm1 = math.sqrt(sum((c1[w] * idf.get(w, 1.0)) ** 2 for w in c1))
    norm2 = math.sqrt(sum((c2[w] * idf.get(w, 1.0)) ** 2 for w in c2))
    cosine_word = (dot_word / (norm1 * norm2)) if (norm1 > 0 and norm2 > 0) else 0.0

    # 2. Containment-Score (Wurde ein kurzer Satz in einen langen Absatz eingebettet?)
    weight1 = sum(idf.get(w, 1.0) for w in set(c1.keys()))
    weight2 = sum(idf.get(w, 1.0) for w in set(c2.keys()))
    shared_weight = sum(idf.get(w, 1.0) for w in (set(c1.keys()) & set(c2.keys())))
    min_weight = min(weight1, weight2)
    containment = (shared_weight / min_weight) if min_weight > 0 else 0.0

    # 3. Trigramm-Ähnlichkeit (Erkennt Wortstämme wie 'Bremsanforderung' vs 'Bremsen')
    common_tri = sum((trigrams1 & trigrams2).values())
    total_tri = sum(trigrams1.values()) + sum(trigrams2.values())
    trigram_sim = (2.0 * common_tri / total_tri) if total_tri > 0 else 0.0

    # Kombinierter Inhalts-Score (skaliert auf Prozent, gedeckelt bei 59.9% für '< 60%' Kategorie)
    raw_score = (0.45 * cosine_word + 0.30 * containment + 0.25 * trigram_sim) * 100.0
    return min(59.9, round(raw_score, 1))

# ==============================================================================

def berechne_csv_diff(text1, text2, col_l, col_r, delimiter, filters):
    set_progress("Lese Original-Datei...", 5)
    parsed1 = parse_full_csv(text1, delimiter)
    
    set_progress("Lese Vergleichs-Datei...", 10)
    parsed2 = parse_full_csv(text2, delimiter)
        
    matched_indices_2 = set()
    diff_data = []
    block_id = 0
    matches = {}
    
    set_progress("Erkenne Duplikate...", 12)
    counts_l, counts_r = {}, {}
    
    norm_keys_1 = []
    for i, (raw1, cols1) in enumerate(parsed1):
        key1 = cols1[col_l] if col_l < len(cols1) else ""
        n_key1 = normalize_text(key1, filters)
        norm_keys_1.append(n_key1)
        if n_key1: counts_l[n_key1] = counts_l.get(n_key1, 0) + 1
        
    norm_keys_2 = []
    for j, (raw2, cols2) in enumerate(parsed2):
        key2 = cols2[col_r] if col_r < len(cols2) else ""
        n_key2 = normalize_text(key2, filters)
        norm_keys_2.append(n_key2)
        if n_key2: counts_r[n_key2] = counts_r.get(n_key2, 0) + 1
    
    set_progress("Indiziere Daten (Hash-Map)...", 15)
    exact_map_2 = {}
    for j, n_key2 in enumerate(norm_keys_2):
        if n_key2 not in exact_map_2: exact_map_2[n_key2] = []
        exact_map_2[n_key2].append(j)
        
    total_p1 = len(parsed1)
    
    # SCHRITT 1: Exakte 100% Treffer
    set_progress("Suche exakte Treffer...", 20)
    for i, n_key1 in enumerate(norm_keys_1):
        if n_key1 in exact_map_2:
            for j in exact_map_2[n_key1]:
                if j not in matched_indices_2:
                    matches[i] = (j, 100.0)
                    matched_indices_2.add(j)
                    break
                    
    # SCHRITT 2: Klassische Fuzzy-Suche (>= 60%)
    set_progress("Suche Ähnlichkeiten (Fuzzy >= 60%)...", 30)
    for i, n_key1 in enumerate(norm_keys_1):
        if total_p1 > 0 and i % max(1, total_p1 // 40) == 0:
            set_progress(f"Fuzzy-Analyse ({i}/{total_p1})...", 30 + int(35 * (i / total_p1)))
            
        if i in matches or not n_key1: continue 
        
        best_j = -1
        best_ratio = 0.0
        
        for j, n_key2 in enumerate(norm_keys_2):
            if j in matched_indices_2 or not n_key2: continue
            
            sm = difflib.SequenceMatcher(None, n_key1, n_key2)
            if sm.real_quick_ratio() * 100 < 60.0: continue
            if sm.quick_ratio() * 100 < 60.0: continue
            
            ratio = sm.ratio() * 100
            if ratio > best_ratio:
                best_ratio = ratio
                best_j = j
                
        if best_j != -1 and best_ratio >= 60.0:
            matches[i] = (best_j, best_ratio)
            matched_indices_2.add(best_j)

    # SCHRITT 3 (NEU v5.17 - Option A): Offline Inhalts-Analyse für verbleibende Waisen-Zeilen
    unmatched_l = [i for i in range(len(parsed1)) if i not in matches and norm_keys_1[i]]
    unmatched_r = [j for j in range(len(parsed2)) if j not in matched_indices_2 and norm_keys_2[j]]

    if unmatched_l and unmatched_r:
        set_progress(f"Starte Tiefen-Inhaltsanalyse ({len(unmatched_l)}x{len(unmatched_r)} Restzeilen)...", 68)
        
        # Berechne TF-IDF Wortgewichte über beide Dateien
        all_tokens_l = {i: extract_word_tokens(norm_keys_1[i]) for i in unmatched_l}
        all_tokens_r = {j: extract_word_tokens(norm_keys_2[j]) for j in unmatched_r}
        idf_weights = build_idf_weights(list(all_tokens_l.values()) + list(all_tokens_r.values()))
        
        trigrams_l = {i: extract_char_trigrams(norm_keys_1[i]) for i in unmatched_l}
        trigrams_r = {j: extract_char_trigrams(norm_keys_2[j]) for j in unmatched_r}
        
        candidate_pairs = []
        for idx_u, i in enumerate(unmatched_l):
            if len(unmatched_l) > 10 and idx_u % max(1, len(unmatched_l) // 10) == 0:
                set_progress(f"Inhalts-Vektorabgleich ({idx_u}/{len(unmatched_l)})...", 70 + int(15 * (idx_u / len(unmatched_l))))
            for j in unmatched_r:
                sim = calc_content_similarity(
                    all_tokens_l[i], all_tokens_r[j],
                    trigrams_l[i], trigrams_r[j],
                    idf_weights
                )
                # Schwellenwert: Ab 22% echter inhaltlicher Schlagwort/Stamm-Übereinstimmung
                if sim >= 22.0:
                    candidate_pairs.append((sim, i, j))
                    
        # Beste inhaltliche Treffer zuerst verheiraten (Best-First-Matching)
        candidate_pairs.sort(key=lambda x: x[0], reverse=True)
        for sim, i, j in candidate_pairs:
            if i not in matches and j not in matched_indices_2:
                matches[i] = (j, sim)
                matched_indices_2.add(j)

    # SCHRITT 4: HTML Zusammenbauen & Datensätze strikt mit 1 zählen
    set_progress("Baue HTML-Oberfläche...", 88)
    for i, (raw1, cols1) in enumerate(parsed1):
        norm_key1 = norm_keys_1[i]
        dup_left = bool(norm_key1 and counts_l.get(norm_key1, 0) > 1)
        
        if i in matches:
            j, key_ratio = matches[i]
            raw2, cols2 = parsed2[j]
            norm_key2 = norm_keys_2[j]
            dup_right = bool(norm_key2 and counts_r.get(norm_key2, 0) > 1)
            
            if key_ratio == 100.0:
                tag = 'equal'
                left_html = [html.escape(raw1)]
                right_html = [html.escape(raw2)]
            else:
                tag = 'replace'
                if len(raw1) > 5000 or len(raw2) > 5000:
                    left_html = [html.escape(raw1)]
                    right_html = [html.escape(raw2)]
                else:
                    left_html, right_html = get_inline_diff([raw1], [raw2])
                
            diff_data.append({
                'id': block_id, 'tag': tag,
                'left': left_html, 'right': right_html,
                'raw_left': raw1.splitlines(keepends=True) if raw1 else [],
                'raw_right': raw2.splitlines(keepends=True) if raw2 else [],
                'ratio': round(key_ratio, 1),
                'dup_left': dup_left,
                'dup_right': dup_right,
                'count_l': 1, 
                'count_r': 1
            })
        else:
            diff_data.append({
                'id': block_id, 'tag': 'delete',
                'left': [html.escape(raw1)], 'right': [],
                'raw_left': raw1.splitlines(keepends=True) if raw1 else [],
                'raw_right': [],
                'ratio': 0,
                'dup_left': dup_left,
                'dup_right': False,
                'count_l': 1, 
                'count_r': 0
            })
        block_id += 1
        
    set_progress("Erfasse neue Datensätze...", 95)
    for j, (raw2, cols2) in enumerate(parsed2):
        if j not in matched_indices_2:
            norm_key2 = norm_keys_2[j]
            dup_right = bool(norm_key2 and counts_r.get(norm_key2, 0) > 1)
            
            diff_data.append({
                'id': block_id, 'tag': 'insert',
                'left': [], 'right': [html.escape(raw2)],
                'raw_left': [], 
                'raw_right': raw2.splitlines(keepends=True) if raw2 else [],
                'ratio': 0,
                'dup_left': False,
                'dup_right': dup_right,
                'count_l': 0, 
                'count_r': 1
            })
            block_id += 1
            
    set_progress("Generiere Oberfläche...", 100)
    return diff_data

def berechne_diff_daten(text1, text2):
    set_progress("Initialisiere Textvergleich...", 5)
    
    counts_l, counts_r = {}, {}
    for l in text1:
        ls = l.strip()
        if ls: counts_l[ls] = counts_l.get(ls, 0) + 1
    for l in text2:
        ls = l.strip()
        if ls: counts_r[ls] = counts_r.get(ls, 0) + 1
    
    sm = difflib.SequenceMatcher(None, text1, text2)
    opcodes = sm.get_opcodes()
    diff_data = []
    block_id = 0
    total = len(opcodes)
    
    set_progress("Generiere Deltas...", 10)
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if total > 0 and idx % max(1, total // 50) == 0:
            set_progress(f"Berechne Blöcke ({idx}/{total})...", 10 + int(85 * (idx / total)))
            
        block_left = text1[i1:i2]
        block_right = text2[j1:j2]
        ratio = 0
        
        dup_left = any(counts_l.get(l.strip(), 0) > 1 for l in block_left if l.strip())
        dup_right = any(counts_r.get(l.strip(), 0) > 1 for l in block_right if l.strip())
        
        if tag == 'replace':
            str_left = "".join(block_left)
            str_right = "".join(block_right)
            ratio = round(difflib.SequenceMatcher(None, str_left, str_right).ratio() * 100, 1)
            
            if len(str_left) > 5000 or len(str_right) > 5000:
                left_html = [html.escape(l) for l in block_left]
                right_html = [html.escape(l) for l in block_right]
            else:
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
            'ratio': ratio,
            'dup_left': dup_left,
            'dup_right': dup_right,
            'count_l': len(block_left), 
            'count_r': len(block_right)
        })
        block_id += 1
        
    set_progress("Generiere Oberfläche...", 100)
    return diff_data
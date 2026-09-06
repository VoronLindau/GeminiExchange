# file_reader.py
# ANFANG
# file_reader.py (V38.19 Safe ListString Mapping)
import sys
import os
import zipfile
import hashlib
import config
import preflight

class DocxParserCOM:
    def __init__(self, file_path):
        self.file_path = file_path
        self.content = []
        
    def _extract_image_order(self):
        images = []
        try:
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(self.file_path, 'r') as z:
                rels = {}
                if 'word/_rels/document.xml.rels' in z.namelist():
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
                        try: objects[name] = hashlib.sha256(z.read(name)).hexdigest()
                        except: pass 
                if 'word/document.xml' in z.namelist():
                    doc_root = ET.fromstring(z.read('word/document.xml'))
                    for node in doc_root.iter():
                        if node.tag.endswith('}blip') or node.tag.endswith('}imagedata'):
                            r_id = None
                            for k, v in node.attrib.items():
                                if k.endswith('}embed') or k.endswith('}id') or k == 'id':
                                    r_id = v; break
                            if r_id and r_id in rels:
                                img_path = rels[r_id]
                                img_hash = objects.get(img_path, "NO_HASH")
                                images.append((img_path, img_hash))
        except Exception: pass
        return images

    def parse(self):
        word = None
        doc = None
        try:
            import win32com.client
            xml_images = self._extract_image_order()
            img_idx = 0
            
            sys.stdout.write(f"  > COM DispatchEx 'Word.Application' für: {os.path.basename(self.file_path)}...\n")
            word = win32com.client.DispatchEx("Word.Application")
            
            try: word.DisplayAlerts = 0
            except: pass

            try: word.Visible = False 
            except Exception as e_vis:
                sys.stdout.write(f"  ⚠️ WARNUNG: Word-Sichtbarkeit blockiert (COM: {e_vis}). Mache weiter...\n")
            
            sys.stdout.write(f"  > Öffne Dokument: {os.path.basename(self.file_path)}...\n")
            doc = word.Documents.Open(os.path.abspath(self.file_path), ReadOnly=True)
            
            count = 0
            total = doc.Paragraphs.Count
            for para in doc.Paragraphs:
                count += 1
                if count % 50 == 0: sys.stdout.write(f"\r    - Verarbeite Absatz {count}/{total}...")
                
                txt = para.Range.Text
                if txt is None: txt = ""
                image_tags = []
                
                try:
                    for ishape in para.Range.InlineShapes:
                        if img_idx < len(xml_images):
                            img_path, img_hash = xml_images[img_idx]
                            image_tags.append(f"\n[BILD:{img_path}|HASH:{img_hash}]\n")
                            img_idx += 1
                        else:
                            image_tags.append(f"\n[BILD:COM_IMAGE|HASH:fallback]\n")
                except: pass

                try:
                    shapes = para.Range.ShapeRange
                    for shape in shapes:
                        try:
                            if shape.TextFrame.HasText:
                                shape_txt = shape.TextFrame.TextRange.Text
                                shape_txt = shape_txt.replace('\r', ' ').replace('\x0b', ' ').replace('\x07', '').strip()
                                if shape_txt: txt = txt + " " + shape_txt
                        except: pass
                        
                        try:
                            if shape.Type == 13:
                                if img_idx < len(xml_images):
                                    img_path, img_hash = xml_images[img_idx]
                                    image_tags.append(f"\n[BILD:{img_path}|HASH:{img_hash}]\n")
                                    img_idx += 1
                                else:
                                    image_tags.append(f"\n[BILD:COM_IMAGE|HASH:fallback]\n")
                        except: pass
                except: pass

                txt = txt.replace('\x08', '').replace('\x01', '').replace('\r', '').replace('\x07', '').strip()
                
                # FIX V38.19: ListString Sicherung für Kapitelnummern
                try:
                    list_str = para.Range.ListFormat.ListString
                    if list_str and list_str.strip():
                        if not txt.startswith(list_str.strip()):
                            txt = f"{list_str.strip()} {txt}".strip()
                except: pass
                
                if not txt and not image_tags:
                    continue
                
                try: page_num = para.Range.Information(1)
                except: page_num = "1"
                
                para_content = txt
                if image_tags:
                    para_content = "".join(image_tags) + "\n" + txt
                
                if para_content.strip():
                    self.content.append(f"[P:{page_num}]{para_content.strip()}")
            
            sys.stdout.write(f"\r    ✅ Verarbeitet: {count}/{total} Absätze.            \n")
            
        except Exception as e:
            sys.stderr.write(f"❌ Fehler im COM DOCX Parser: {e}\n")
            self.content = [] 
            
        finally:
            try:
                if doc: doc.Close(0)
                if word: word.Quit()
            except: pass 
            
        return self.content

def get_docx_xml_data(file_path):
    content = []; page_count = [1]
    import xml.etree.ElementTree as ET
    import hashlib
    try:
        sys.stdout.write(f"  > XML-Fallback für: {os.path.basename(file_path)}...\n")
        with zipfile.ZipFile(file_path, 'r') as z:
            rels = {}
            if 'word/_rels/document.xml.rels' in z.namelist():
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
                    try: objects[name] = hashlib.sha256(z.read(name)).hexdigest()
                    except: pass 

            if 'word/document.xml' in z.namelist():
                doc_root = ET.fromstring(z.read('word/document.xml'))
                for p in doc_root.iter():
                    if p.tag.endswith('}p'):
                        para_text = ""
                        for node in p.iter():
                            if node.tag.endswith('}lastRenderedPageBreak') or \
                               (node.tag.endswith('}br') and any(v == 'page' for k,v in node.attrib.items())):
                                page_count[0] += 1
                                para_text += f"\n[SEITENUMBRUCH:{page_count[0]}]\n"
                            elif node.tag.endswith('}t') and node.text:
                                para_text += node.text
                            elif node.tag.endswith('}tab'):
                                para_text += " " 
                            elif node.tag.endswith('}blip') or node.tag.endswith('}id'):
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
                                if clean_line: content.append(f"[P:{page_count[0]}]{clean_line}")
    except Exception as e: sys.stderr.write(f"❌ Fehler beim XML-Parsing: {e}\n")
    return content

def get_file_info(file_path):
    if not file_path or not os.path.exists(file_path):
        return {"path": "", "content": []}
    normalized_path = file_path.replace('\\', '/')
    if file_path.lower().endswith('.docx'):
        if preflight.PREFLIGHT_RESULTS["word_ready"]:
            sys.stdout.write(f"--- 🛠️  Versuche COM Smart Rendering für: {os.path.basename(file_path)} ---\n")
            parser = DocxParserCOM(file_path)
            content = parser.parse()
            if content:
                sys.stdout.write("--- ✅ COM Smart Rendering erfolgreich ---\n\n")
                return {"path": normalized_path, "content": content}
        sys.stdout.write(f"--- 🛠️  Verwende XML-Fallback für: {os.path.basename(file_path)} ---\n")
        content = get_docx_xml_data(file_path)
        sys.stdout.write("--- ✅ XML-Fallback abgeschlossen ---\n\n")
        return {"path": normalized_path, "content": content}
    else:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = [f"[P:1]{l.strip()}" for l in f.readlines() if l.strip()]
        return {"path": normalized_path, "content": content}
# ENDE
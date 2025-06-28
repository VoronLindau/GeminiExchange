# -*- coding: utf-8 -*-
# ********************************************************************************************************************************
#
# Original-Code von Unknown, 14.Mai.2024
# Refaktoriert für bessere Modularität und Wiederverwendbarkeit
# Version 2: Modifiziert, um die Modul-ID anstelle des Namens zu verwenden, für mehr Zuverlässigkeit.
#
# Beschreibung:
# Dieses Skript ermöglicht es, ein neues Artefakt (z.B. eine Anforderung) in DOORS Next Generation zu erstellen
# und es anschließend in ein spezifisches Modul (identifiziert durch seine ID) einzubinden.
#
# ********************************************************************************************************************************

import logging
import os.path
import sys
import lxml.etree as ET
import argparse # Bessere Methode zur Verarbeitung von Kommandozeilenargumenten

# Importiere die benötigten ELM-Client-Module
import elmclient.server as elmserver
import elmclient.utils as utils
import elmclient.rdfxml as rdfxml

# Globale Variable für den Logger
logger = logging.getLogger(__name__)

# =================================================================================================
# HILFSFUNKTIONEN
# =================================================================================================
# (Hier stehen die unveränderten Hilfsfunktionen wie 'iterwalk')

def iterwalk(root, events=None, tags=None):
    """Incrementally walks XML structure (like iterparse but for an existing ElementTree structure)"""
    stack = [[root, list(root)]]
    tags = [] if tags is None else tags if type(tags) == list else [tags]
    events = events or ["start", "end"]
    def iterator():
        while stack:
            elnow, children = stack[-1]
            if children is None:
                if (not tags or elnow.tag in tags) and "start" in events:
                    yield ("start", elnow)
                stack[-1][1] = list(elnow)
            elif len(children) > 0:
                thischild = children.pop(0)
                stack.append([thischild, None])
            else:
                if len(stack) > 1 and (not tags or elnow.tag in tags) and "end" in events:
                    yield ("end", elnow)
                stack.pop()
    return iterator
    
# =================================================================================================
# MODULARE FUNKTIONEN
# =================================================================================================

def setup_logging(loglevel="INFO,OFF"):
    """Konfiguriert das Logging für das Skript."""
    levels = [utils.loglevels.get(l, -1) for l in loglevel.split(",", 1)]
    if len(levels) < 2:
        levels.append(None)
    if -1 in levels:
        raise ValueError(f'Logging level {loglevel} not valid.')
    utils.setup_logging(filelevel=levels[0], consolelevel=levels[1])
    logger.info("Logging initialisiert.")

def connect_to_elm(host, username, password, jts_context='jts', rm_context='rm4', caching=2):
    """
    Stellt eine Verbindung zum ELM-Server her und gibt das RM-Anwendungsobjekt zurück.
    """
    logger.info(f"Verbinde mit ELM-Server auf {host}...")
    elmserver.setupproxy(host)
    the_server = elmserver.JazzTeamServer(host, username, password, verifysslcerts=False, jtsappstring=f"jts:{jts_context}", appstring='rm4', cachingcontrol=caching)
    dn_app = the_server.find_app(f"rm:{rm_context}", ok_to_create=True)
    logger.info("Verbindung erfolgreich hergestellt.")
    return dn_app

def create_artifact_in_folder(component, artifact_type, artifact_title, folder_path):
    """
    Erstellt ein neues Artefakt in einem angegebenen Ordner.
    """
    logger.info(f"Erstelle Artefakt vom Typ '{artifact_type}' mit Titel '{artifact_title}' im Ordner '{folder_path}'...")
    the_folder = component.find_folder(folder_path)
    if the_folder is None:
        raise FileNotFoundError(f"Ordner '{folder_path}' nicht gefunden!")
    logger.info(f"Ordner-URL gefunden: {the_folder.folderuri}")
    factory_u, shapes = component.get_factory_uri("oslc_rm:Requirement", return_shapes=True)
    logger.info(f"Factory-URL: {factory_u}")
    the_shape_u = None
    for shape_u in shapes:
        shape_x = component.execute_get_rdf_xml(shape_u)
        shape_title = rdfxml.xmlrdf_get_resource_text(shape_x, ".//oslc:ResourceShape/dcterms:title")
        if shape_title == artifact_type:
            the_shape_u = shape_u
            logger.info(f"Passendes Shape '{shape_title}' gefunden: {the_shape_u}")
            break
    if the_shape_u is None:
        raise LookupError(f"Shape für den Artefakttyp '{artifact_type}' nicht gefunden!")
    xml_payload = f"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns:dc="http://purl.org/dc/terms/"
        xmlns:jazz_rm="http://jazz.net/ns/rm#"
        xmlns:oslc="http://open-services.net/ns/core#"
        xmlns:nav="http://jazz.net/ns/rm/navigation#">
      <rdf:Description rdf:about="">
        <rdf:type rdf:resource="http://open-services.net/ns/rm#Requirement"/>
        {'<rdf:type rdf:resource="https://hep.continental.com/ns/automotive/rm/ty/heading"/> <rdf:type rdf:resource="http://jazz.net/ns/rm#Text"/>' if artifact_type == "Heading" else ''}
        <dc:description rdf:parseType="Literal">Erstellt durch Python-Skript</dc:description>
        <jazz_rm:primaryText rdf:parseType="Literal">
            <div xmlns="http://www.w3.org/1999/xhtml"><p><span>{artifact_title}</span></p></div>
        </jazz_rm:primaryText>
        <dc:title rdf:parseType="Literal">{artifact_title}</dc:title>
        <oslc:instanceShape rdf:resource="{the_shape_u}"/>
        <nav:parent rdf:resource="{the_folder.folderuri}"/>
      </rdf:Description>
    </rdf:RDF>
    """
    thexml_x = ET.fromstring(xml_payload)
    response = component.execute_post_rdf_xml(factory_u, data=thexml_x, intent="Erstelle neues Artefakt")
    if response.status_code != 201:
        raise ConnectionError(f"POST-Anfrage zum Erstellen des Artefakts fehlgeschlagen! Status: {response.status_code}")
    the_artifact_u = response.headers.get('Location')
    the_artifact_x = component.execute_get_rdf_xml(the_artifact_u, intent="Hole ID des neuen Artefakts")
    the_id = rdfxml.xml_find_element(the_artifact_x, ".//dcterms:identifier").text
    logger.info(f"Artefakt erfolgreich erstellt! ID: {the_id}, URL: {the_artifact_u}")
    return the_artifact_u, the_id

def get_module_uri_by_id(component, module_id):
    """
    Findet die URI eines Moduls anhand seiner öffentlichen ID.

    Args:
        component (elmclient.apps.rm.Component): Das Komponentenobjekt.
        module_id (str): Die öffentliche ID des Moduls (z.B. "12345").

    Returns:
        str: Die eindeutige URI des Moduls.
    """
    logger.info(f"Suche nach Modul mit der ID '{module_id}'...")
    qcbase = component.get_query_capability_uri("oslc_rm:Requirement")
    # Suche nach einem Artefakt vom Typ 'Module', das die angegebene ID hat
    modules = component.execute_oslc_query(
        qcbase,
        whereterms=[
            ['dcterms:identifier', '=', f'"{module_id}"'], 
            ['rdf:type', '=', '<http://jazz.net/ns/rm#Module>']
        ],
        select=['*'],
        prefixes={rdfxml.RDF_DEFAULT_PREFIX["dcterms"]: 'dcterms'}
    )
    if len(modules) == 0:
        raise FileNotFoundError(f"Kein Modul mit der ID '{module_id}' gefunden.")
    if len(modules) > 1:
        # Dies sollte theoretisch nie passieren, da IDs einzigartig sein sollten.
        logger.warning(f"Mehr als ein Modul mit der ID '{module_id}' gefunden. Verwende das erste.")
    
    module_uri = list(modules.keys())[0]
    logger.info(f"Modul gefunden: {module_uri}")
    return module_uri


def bind_artifact_to_module_structure(component, module_uri, artifact_to_bind_uri):
    """Bindet ein vorhandenes Artefakt in die Struktur eines Moduls ein."""
    logger.info(f"Binde Artefakt {artifact_to_bind_uri} in Modul {module_uri} ein...")
    mod_x = component.execute_get_rdf_xml(module_uri, cacheable=False, intent="Hole Modul-Metadaten")
    structure_u = rdfxml.xmlrdf_get_resource_uri(mod_x, ".//rm_modules:structure")
    logger.info(f"Struktur-URL: {structure_u}")
    modstructure_x, etag = component.execute_get_rdf_xml(
        structure_u, 
        cacheable=False, 
        return_etag=True,
        intent="Hole Modulstruktur und ETag"
    )
    logger.info(f"ETag für die Struktur erhalten: {etag}")
    first_child_bindings = rdfxml.xml_find_elements(modstructure_x, 'rm_modules:Binding/rm_modules:childBindings')[0]
    new_binding_xml = ET.fromstring(
        f"""<rm_modules:Binding
                xmlns:rdf='{rdfxml.RDF_DEFAULT_PREFIX["rdf"]}'
                xmlns:oslc_config='{rdfxml.RDF_DEFAULT_PREFIX["oslc_config"]}'
                xmlns:rm_modules='{rdfxml.RDF_DEFAULT_PREFIX["rm_modules"]}'
                rdf:about="">
            <oslc_config:component rdf:resource="{component.project_uri}"/>
            <rm_modules:boundArtifact rdf:resource="{artifact_to_bind_uri}"/>
            <rm_modules:module rdf:resource="{module_uri}"/>
            <rm_modules:childBindings rdf:resource="http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"/>
        </rm_modules:Binding>"""
    )
    first_child_bindings.append(new_binding_xml)
    logger.info("XML-Struktur für das Binding vorbereitet.")
    response = component.execute_post_rdf_xml(
        structure_u, 
        data=modstructure_x, 
        put=True, 
        cacheable=False, 
        headers={'If-Match': etag}, 
        intent="Aktualisiere Modulstruktur"
    )
    logger.info(f"PUT-Antwort zum Aktualisieren der Struktur: {response.status_code}")
    if response.status_code not in [200, 201, 202]:
         raise ConnectionError(f"Update der Modulstruktur fehlgeschlagen! Status: {response.status_code}")
    location = response.headers.get('Location')
    if response.status_code == 202 and location:
        logger.info("Warte auf Abschluss des asynchronen Update-Jobs...")
        component.wait_for_tracker(location, interval=1.0, progressbar=True, msg="Struktur-Update")
    logger.info("Artefakt erfolgreich in Modulstruktur eingebunden.")


# =================================================================================================
# HAUPTPROGRAMM
# =================================================================================================

def main():
    """Hauptfunktion des Skripts."""
    parser = argparse.ArgumentParser(description='Erstellt ein DOORS NG Artefakt und bindet es in ein Modul ein.')
    parser.add_argument('artifact_type', help='Typ des Artefakts (z.B. "Requirement" oder "Heading").')
    parser.add_argument('artifact_title', help='Titel und primärer Text des Artefakts.')
    parser.add_argument('folder_path', help='Pfad zum Ordner, in dem das Artefakt erstellt wird (z.B. "ConsumerRatings artifacts").')
    parser.add_argument('project_name', help='Name des RM-Projekts.')
    parser.add_argument('component_name', help='Name der Komponente im Projekt.')
    parser.add_argument('config_name', help='Name der Konfiguration (Stream/Changeset).')
    # *** ÄNDERUNG HIER: Erwartet jetzt die ID statt des Namens ***
    parser.add_argument('module_id', help='Die öffentliche ID des Moduls (z.B. 12345), in das eingebunden wird.')
    parser.add_argument('username', help='Dein Benutzername.')
    parser.add_argument('password', help='Dein Passwort.')
    
    args = parser.parse_args()
    setup_logging()
    utils.log_commandline(os.path.basename(sys.argv[0]))

    try:
        jazzhost = 'https://tbd.de' # Bitte anpassen
        dn_app = connect_to_elm(jazzhost, args.username, args.password)
        project = dn_app.find_project(args.project_name)
        component = project.find_local_component(args.component_name)
        config_uri = component.get_local_config(args.config_name)
        component.set_local_config(config_uri)
        logger.info(f"Kontext gesetzt auf Projekt '{args.project_name}', Komponente '{args.component_name}', Konfiguration '{args.config_name}'.")

        new_artifact_uri, new_artifact_id = create_artifact_in_folder(
            component=component,
            artifact_type=args.artifact_type,
            artifact_title=args.artifact_title,
            folder_path=args.folder_path
        )

        # *** ÄNDERUNG HIER: Verwende die neue Funktion, um das Modul über die ID zu finden ***
        module_uri = get_module_uri_by_id(component, args.module_id)

        qcbase = component.get_query_capability_uri("oslc_rm:Requirement")
        artifacts_to_bind = component.execute_oslc_query(qcbase, whereterms=[['dcterms:identifier', '=', new_artifact_id]])
        if not artifacts_to_bind:
            raise FileNotFoundError(f"Das neu erstellte Artefakt mit ID {new_artifact_id} konnte nicht für das Binding gefunden werden.")
        
        artifact_to_bind_uri = list(artifacts_to_bind.keys())[0]

        bind_artifact_to_module_structure(
            component=component,
            module_uri=module_uri,
            artifact_to_bind_uri=artifact_to_bind_uri
        )
        print("\nSkript erfolgreich abgeschlossen!")
        print(f"Neues Artefakt '{new_artifact_id}' wurde erstellt und in das Modul mit der ID '{args.module_id}' eingebunden.")

    except (FileNotFoundError, LookupError, ConnectionError, ValueError) as e:
        logger.error(f"Ein Fehler ist aufgetreten: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("Ein unerwarteter Fehler ist aufgetreten:", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
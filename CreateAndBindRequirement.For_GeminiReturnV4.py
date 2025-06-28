# -*- coding: utf-8 -*-
# ********************************************************************************************************************************
#
# Create by Holger Jordan/Thomas Diepolder
# Date 14.Mai.2024
# Refaktoriert für bessere Modularität, Lesbarkeit und Wiederverwendbarkeit.
#
# Beschreibung:
# Dieses Skript erstellt ein Core-Artefakt in DOORS Next Generation und bindet es anschließend in ein Modul ein.
#
# ********************************************************************************************************************************

import logging
import os.path
import sys
import argparse
import time
import lxml.etree as ET

import elmclient.server as elmserver
import elmclient.utils as utils
import elmclient.rdfxml as rdfxml

logger = logging.getLogger(__name__)

# =================================================================================================
# MODULARE FUNKTIONEN
# =================================================================================================

def setup_logging(loglevel="INFO,OFF"):
    """Konfiguriert das Logging für das Skript."""
    levels = [utils.loglevels.get(l, -1) for l in loglevel.split(",", 1)]
    if len(levels) < 2:
        levels.append(None)
    if -1 in levels:
        raise ValueError(f'Logging level {loglevel} nicht gültig.')
    utils.setup_logging(filelevel=levels[0], consolelevel=levels[1])
    logger.info("Logging initialisiert.")

def connect_to_elm(host, username, password, jts_context='jts', rm_context='rm4', caching=2):
    """Stellt eine Verbindung zum ELM-Server her und gibt das RM-Anwendungsobjekt zurück."""
    logger.info(f"Verbinde mit ELM-Server auf {host}...")
    elmserver.setupproxy(host)
    server = elmserver.JazzTeamServer(host, username, password, verifysslcerts=False, jtsappstring=f"jts:{jts_context}", appstring='rm4', cachingcontrol=caching)
    dn_app = server.find_app(f"rm:{rm_context}", ok_to_create=True)
    logger.info("Verbindung erfolgreich hergestellt.")
    return dn_app

def create_artifact_in_folder(component, artifact_type, artifact_title, folder_path):
    """Erstellt ein neues Core-Artefakt in einem angegebenen Ordner."""
    logger.info(f"Erstelle Artefakt '{artifact_title}' vom Typ '{artifact_type}' im Ordner '{folder_path}'...")
    
    folder = component.find_folder(folder_path)
    if folder is None:
        raise FileNotFoundError(f"Ordner '{folder_path}' nicht gefunden!")
    logger.info(f"Ordner-URL gefunden: {folder.folderuri}")

    factory_uri, shapes = component.get_factory_uri("oslc_rm:Requirement", return_shapes=True)
    logger.info(f"Factory-URL: {factory_uri}")

    shape_uri = None
    for s_uri in shapes:
        shape_xml = component.execute_get_rdf_xml(s_uri)
        shape_title = rdfxml.xmlrdf_get_resource_text(shape_xml, ".//oslc:ResourceShape/dcterms:title")
        if shape_title == artifact_type:
            shape_uri = s_uri
            logger.info(f"Passendes Shape '{shape_title}' gefunden: {shape_uri}")
            break
    if shape_uri is None:
        raise LookupError(f"Shape für den Artefakttyp '{artifact_type}' nicht gefunden!")

    xml_payload = f"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        xmlns:dc="http://purl.org/dc/terms/" xmlns:jazz_rm="http://jazz.net/ns/rm#"
        xmlns:oslc="http://open-services.net/ns/core#" xmlns:nav="http://jazz.net/ns/rm/navigation#"
        xmlns:oslc_rm="http://open-services.net/ns/rm#">
      <rdf:Description rdf:about="">
        <rdf:type rdf:resource="http://open-services.net/ns/rm#Requirement"/>
        <dc:description rdf:parseType="Literal">Erstellt durch Python-Skript</dc:description>
        <jazz_rm:primaryText rdf:parseType="Literal">
            <div xmlns="http://www.w3.org/1999/xhtml"><p><span>{artifact_title}</span></p></div>
        </jazz_rm:primaryText>
        <dc:title rdf:parseType="Literal">{artifact_title}</dc:title>
        <oslc:instanceShape rdf:resource="{shape_uri}"/>
        <nav:parent rdf:resource="{folder.folderuri}"/>
      </rdf:Description>
    </rdf:RDF>"""
    
    response = component.execute_post_rdf_xml(factory_uri, data=ET.fromstring(xml_payload), intent="Erstelle Core-Artefakt")
    
    if response.status_code != 201:
        raise ConnectionError(f"POST-Anfrage fehlgeschlagen! Status: {response.status_code}")
    
    artifact_uri = response.headers.get('Location')
    artifact_xml = component.execute_get_rdf_xml(artifact_uri, intent="Hole ID des neuen Artefakts")
    artifact_id = rdfxml.xml_find_element(artifact_xml, ".//dcterms:identifier").text
    
    logger.info(f"Artefakt erfolgreich erstellt! ID: {artifact_id}, URL: {artifact_uri}")
    return artifact_uri, artifact_id

def find_module_by_name(component, module_name):
    """Findet ein Modul anhand seines Namens."""
    logger.info(f"Suche nach Modul '{module_name}'...")
    qc_base_uri = component.get_query_capability_uri("oslc_rm:Requirement")
    modules = component.execute_oslc_query(
        qc_base_uri,
        whereterms=[['dcterms:title', '=', f'"{module_name}"'], ['rdf:type', '=', '<http://jazz.net/ns/rm#Module>']],
    )
    if not modules:
        raise FileNotFoundError(f"Kein Modul mit dem Namen '{module_name}' gefunden.")
    if len(modules) > 1:
        logger.warning(f"Mehr als ein Modul mit dem Namen '{module_name}' gefunden. Verwende das erste.")
    
    module_uri = list(modules.keys())[0]
    logger.info(f"Modul gefunden: {module_uri}")
    return module_uri

def find_artifact_uri_by_id(component, artifact_id):
    """Findet die URI eines Artefakts anhand seiner öffentlichen ID."""
    logger.info(f"Suche nach Artefakt-URI für die ID '{artifact_id}'...")
    qc_base_uri = component.get_query_capability_uri("oslc_rm:Requirement")
    artifacts = component.execute_oslc_query(
        qc_base_uri,
        whereterms=[['dcterms:identifier', '=', f'"{artifact_id}"']],
        select=['*']
    )
    if not artifacts:
        raise FileNotFoundError(f"Kein Artefakt mit der ID '{artifact_id}' in dieser Konfiguration gefunden.")
    
    # Es kann mehrere Treffer geben (z.B. in verschiedenen Modulen), aber wir brauchen nur die URI des Core-Artefakts.
    # Wir nehmen an, der erste Treffer ist der richtige.
    artifact_uri = list(artifacts.keys())[0]
    logger.info(f"Artefakt-URI gefunden: {artifact_uri}")
    return artifact_uri

def bind_artifact_to_module(component, module_uri, artifact_to_bind_uri):
    """Bindet ein Artefakt in die Struktur eines Moduls ein."""
    logger.info(f"Binde Artefakt {artifact_to_bind_uri} in Modul {module_uri} ein...")

    mod_xml = component.execute_get_rdf_xml(module_uri, cacheable=False, intent="Hole Modul-Metadaten")
    structure_uri = rdfxml.xmlrdf_get_resource_uri(mod_xml, ".//rm_modules:structure")
    logger.info(f"Struktur-URL: {structure_uri}")

    structure_xml, etag = component.execute_get_rdf_xml(structure_uri, cacheable=False, return_etag=True, intent="Hole Modulstruktur und ETag")
    logger.info(f"ETag für die Struktur erhalten: {etag}")

    # ACHTUNG: Harte Annahme über die Einfügeposition. Dies ist eine potenzielle Schwachstelle für leere Module.
    insertion_point_xpath = 'rm_modules:Binding/rm_modules:childBindings/rm_modules:Binding/rm_modules:childBindings'
    insertion_point = rdfxml.xml_find_elements(structure_xml, insertion_point_xpath)
    
    if not insertion_point:
         raise ValueError(f"Konnte keine gültige Einfügeposition mit XPath '{insertion_point_xpath}' finden. Ist das Modul leer oder hat es eine andere Struktur?")

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
    insertion_point[0].append(new_binding_xml)

    response = component.execute_put_rdf_xml(
        structure_uri, 
        data=structure_xml, 
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
    parser.add_argument('artifact_type', help='Typ des Artefakts (z.B. "Anforderung").')
    parser.add_argument('artifact_title', help='Titel und primärer Text des Artefakts.')
    parser.add_argument('folder_path', help='Pfad zum Ordner, in dem das Artefakt erstellt wird.')
    parser.add_argument('project_name', help='Name des RM-Projekts.')
    parser.add_argument('component_name', help='Name der Komponente im Projekt.')
    parser.add_argument('config_name', help='Name der Konfiguration (Stream/Changeset).')
    parser.add_argument('module_name', help='Name des Moduls, in das das Artefakt eingebunden wird.')
    parser.add_argument('username', help='Dein Benutzername.')
    parser.add_argument('password', help='Dein Passwort.')
    
    args = parser.parse_args()

    setup_logging()
    utils.log_commandline(os.path.basename(sys.argv[0]))

    try:
        jazzhost = 'https://jazz.conti.de' # Später als Parameter oder aus Config-Datei
        dn_app = connect_to_elm(jazzhost, args.username, args.password)

        project = dn_app.find_project(args.project_name)
        component = project.find_local_component(args.component_name)
        config_uri = component.get_local_config(args.config_name)
        component.set_local_config(config_uri)
        logger.info(f"Kontext gesetzt: Projekt '{args.project_name}', Komponente '{args.component_name}', Konfiguration '{args.config_name}'.")

        # SCHRITT 1: Core-Artefakt erstellen
        new_artifact_uri, new_artifact_id = create_artifact_in_folder(
            component=component,
            artifact_type=args.artifact_type,
            artifact_title=args.artifact_title,
            folder_path=args.folder_path
        )

        # SCHRITT 2: Artefakt in Modul einbinden
        module_uri = find_module_by_name(component, args.module_name)
        
        # Die URI des gerade erstellten Artefakts kann direkt verwendet werden
        bind_artifact_to_module(
            component=component,
            module_uri=module_uri,
            artifact_to_bind_uri=new_artifact_uri
        )
        
        print("\nSkript erfolgreich abgeschlossen!")
        print(f"Neues Artefakt '{new_artifact_id}' wurde erstellt und in das Modul '{args.module_name}' eingebunden.")

    except (FileNotFoundError, LookupError, ConnectionError, ValueError) as e:
        logger.error(f"Ein Fehler ist aufgetreten: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("Ein unerwarteter Fehler ist aufgetreten:", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
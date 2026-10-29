def bnda_schema():
    def field(key, label, kind="text", required=True, **extra):
        return {"key": key, "label": label, "type": kind, "required": required, **extra}

    schema = {"sections": [
        {"title": "Identification", "fields": [
            field("type_structure", "Type de structure", "choice", options=["Agence", "Bureau", "Siège principal"]),
            field("code_agence", "Code d’agence ou de bureau"),
            field("date_audit", "Date de l’audit", "date"),
            field("heure_audit", "Heure de l’audit"),
            field("ville_region", "Ville et région"),
            field("quartier", "Quartier"),
            field("geolocalisation", "Géolocalisation", "gps"),
            field("responsable", "Nom et contact du responsable de la structure"),
            field("auditeur", "Nom et prénom de l’auditeur"),
            field("telephone_auditeur", "Numéro de téléphone de l’auditeur"),
        ]},
        {"title": "Infrastructure CCTV", "fields": [
            field("nombre_cameras", "Nombre total de caméras", "number"),
            field("marques_cameras", "Liste des marques de caméras du site"),
            field("photos_cameras", "Photos des caméras et de leurs étiquettes (10 à 150)", "photo", min_photos=10, max_photos=150),
            field("type_enregistrement", "Type d’enregistrement disponible sur le site"),
            field("photos_enregistreur", "Photos de l’enregistreur et de son étiquette (3 à 6)", "photo", min_photos=3, max_photos=6),
            field("slots_disque", "Nombre de slots disque disponibles sur l’enregistreur", "number"),
            field("photo_interieur", "Photo de l’intérieur de l’enregistreur", "photo", max_photos=1),
            field("stockage_externe", "Périphérique de stockage externe présent ?", "choice", options=["Oui", "Non"]),
            field("marque_stockage", "Si oui, marque du périphérique de stockage externe", required=False),
            field("zones_surveillees", "Zones déjà surveillées (couverture vidéo)"),
            field("zones_critiques", "Zones critiques hors du champ des caméras (ou aucune)"),
            field("photos_zones", "Vues d’ensemble des zones signalées (5 à 8)", "photo", min_photos=5, max_photos=8),
        ]},
        {"title": "Anomalies et réseau", "fields": [
            field("anomalies", "Anomalies et dysfonctionnements relevés (ou aucun)"),
            field("pieces", "Liste des pièces défectueuses identifiées (ou aucune)"),
            field("photos_pieces", "Photos des pièces défectueuses et des étiquettes disponibles (5 à 15)", "photo", min_photos=5, max_photos=15),
            field("bilan_reseau", "Bilan de l’état général du réseau et de ses accessoires"),
            field("etat_cables", "État des câbles FTP et coaxiaux"),
            field("photos_cables", "Photos des câbles du circuit", "photo", max_photos=15),
            field("routeurs_switchs", "Marques et numéros de série des routeurs et switchs de la baie informatique"),
            field("photos_baie", "Photos de la baie informatique (1 à 2)", "photo", min_photos=1, max_photos=2),
        ]},
        {"title": "Conclusion", "fields": [
            field("observation_globale", "Observation globale du site par le technicien"),
        ]},
    ]}
    labels = {
        "photos_cameras": "Photos des caméras et de leurs étiquettes (minimum 10)",
        "photos_enregistreur": "Photos de l’enregistreur et de son étiquette (minimum 3)",
        "photos_zones": "Vues d’ensemble des zones signalées (minimum 5)",
        "photos_pieces": "Photos des pièces défectueuses et des étiquettes disponibles (minimum 5)",
        "photos_baie": "Photos de la baie informatique (minimum 1)",
    }
    for section in schema["sections"]:
        for item in section["fields"]:
            if item["key"] == "heure_audit":
                item["type"] = "time"
            if item["type"] == "photo":
                item["max_photos"] = 150
                if item["key"] in labels:
                    item["label"] = labels[item["key"]]
    return schema

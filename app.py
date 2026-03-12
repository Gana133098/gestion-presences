# ===== IMPORTS =====
from flask import Flask, request, jsonify
import sqlite3
import os
from datetime import datetime 
from flask import render_template
import csv
from io import StringIO
from flask import Response
import pytz  # NOUVELLE LIGNE À AJOUTER


# ===== INITIALISATION FLASK =====
app = Flask(__name__)

# ===== CHEMIN DE LA BASE DE DONNÉES =====
# On récupère le dossier où se trouve app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# On construit le chemin vers la base SQLite
DB_PATH = os.path.join(BASE_DIR, "edtest.db")  # ⚠️ adapte le nom si besoin


# ===== FONCTION DE CONNEXION À LA DB =====
def get_db():
    """
    Ouvre une connexion vers la base SQLite
    """
    return sqlite3.connect(DB_PATH)


# ===== ROUTE TEST SERVEUR =====
@app.route("/")
def home():
    """
    Vérifie que Flask fonctionne
    """
    return "Serveur Flask OK"

@app.route("/test-db")
def test_db():
    """
    Vérifie que Flask voit bien les tables SQLite
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
    """)
    tables = cursor.fetchall()

    conn.close()
    return str(tables) 

@app.route("/api/badge-test")
def badge_test():
    return "badge route OK"


@app.route("/api/badge", methods=["POST"])
def badge():

    print("HEADERS:", request.headers)
    print("RAW DATA:", request.data)

    # 1️⃣ Lire l'UID
    data = request.get_json(force=True)

    if not data or "uid" not in data:
        return jsonify({"error": "UID manquant"}), 400

    uid = data["uid"]

    conn = get_db()
    cursor = conn.cursor()

    # 2️⃣ Trouver l'étudiant
    cursor.execute("""
        SELECT e.id, e.nom, e.prenom,
               g.id,
               fo.nom, fi.nom, g.nom
        FROM etudiants e
        JOIN groupes g ON e.groupe_id = g.id
        JOIN filieres fi ON g.filiere_id = fi.id
        JOIN formations fo ON fi.formation_id = fo.id
        WHERE e.uid_rfid = ?
    """, (uid,))
    
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"status": "INCONNU"})

    etudiant_id, nom, prenom, groupe_id, formation, filiere, groupe = row
    
    
    # requete SQL heure en cours
    # Ancien code à effacer :
    # now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Nouveau code :
    tz = pytz.timezone('Europe/Paris')
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    SELECT id, debut, fin, matiere,salle    
    FROM seances
    WHERE groupe_id = ?
      AND debut <= ?
      AND fin >= ?
    LIMIT 1
""", (groupe_id, now, now)) #modif1

    seance = cursor.fetchone()
    # si il ny a pas de seance en cours
    if not seance:
        conn.close()
        return jsonify({
        "status": "PAS_DE_COURS",
        "etudiant": {
            "nom": nom,
            "prenom": prenom,
            "groupe": groupe
        }
    })
    
    
    
    
    #Séance trouvée → calcul retard
    seance_id, debut, fin, matiere, salle= seance     #modif 

    heure_debut_dt = datetime.strptime(debut, "%Y-%m-%d %H:%M:%S")
    now_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")

    retard_minutes = (now_dt - heure_debut_dt).total_seconds() / 60

    #statut
    if retard_minutes <= 15:
        statut = "PRESENT"
    else:
        statut = "RETARD"

    # ===== 5️⃣ Vérifier si la présence existe déjà =====
    cursor.execute("""
    SELECT id
    FROM presences
    WHERE etudiant_id = ?
    AND seance_id = ?
    """, (etudiant_id, seance_id))

    presence_existante = cursor.fetchone()

    if presence_existante:
        conn.close()
        return jsonify({
        "status": "DEJA_BADGE",
        "etudiant": {
            "nom": nom,
            "prenom": prenom,
            "groupe": groupe
        }
    })
    
    
    # ===== 6️⃣ Insérer la présence =====
    cursor.execute("""
    INSERT INTO presences (etudiant_id, seance_id, timestamp_badge, etat)
    VALUES (?, ?, ?, ?)
    """, (etudiant_id,seance_id,
    now,               # timestamp du badge
    statut.lower()     # "present" ou "retard"
    ))

    conn.commit()
    conn.close()

    return jsonify({
    "status": "PRESENCE_ENREGISTREE",      # état global API
    "etat": statut.lower(),                # present | retard | hors_seance
    "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

    "etudiant": {
        "id": etudiant_id,
        "uid": uid,
        "nom": nom,
        "prenom": prenom,
        "formation": formation,
        "filiere": filiere,
        "groupe": groupe
    },

    "seance": {
        "id": seance_id,
        "matiere": matiere,
        "heure_debut": debut,
        "heure_fin": fin,
        "salle": salle
    },

    "presence": {
        "statut": statut.lower(),           # present / retard
        "retard_minutes": int(retard_minutes)
    }
    }), 200

@app.route("/prof")
def prof_page():
    return render_template("prof.html")



@app.route("/api/presences", methods=["GET"])
def api_presences():
    seance_id = request.args.get("seance_id")

    if not seance_id:
        return jsonify({"error": "seance_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # On part de la séance pour récupérer tous les étudiants du groupe,
    # puis on fait un LEFT JOIN sur les présences pour voir qui manque.
    cursor.execute("""
        SELECT 
            e.nom,
            e.prenom,
            g.nom AS groupe,
            COALESCE(p.etat, 'absent') AS statut,
            p.timestamp_badge,
            COALESCE(
                CASE 
                    WHEN p.etat = 'retard' THEN
                        CAST(
                            (julianday(p.timestamp_badge) - julianday(s.debut)) * 24 * 60
                            AS INTEGER
                        )
                    ELSE 0
                END,
                0
            ) AS retard_minutes
        FROM seances s
        JOIN etudiants e ON s.groupe_id = e.groupe_id
        JOIN groupes g ON e.groupe_id = g.id
        LEFT JOIN presences p ON p.etudiant_id = e.id AND p.seance_id = s.id
        WHERE s.id = ?
        ORDER BY p.timestamp_badge DESC, e.nom, e.prenom
    """, (seance_id,))

    rows = cursor.fetchall()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "nom": r[0],
            "prenom": r[1],
            "groupe": r[2],
            "statut": r[3],
            "timestamp_badge": r[4],
            "retard_minutes": r[5]
        })

    return jsonify(data)


#avoir la formation pour le frontend pour filtrer 
@app.route("/api/formations", methods=["GET"])
def api_formations():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM formations
        ORDER BY nom
    """)

    rows = cursor.fetchall()
    conn.close()

    formations = []
    for r in rows:
        formations.append({
            "id": r[0],
            "nom": r[1]
        })

    return jsonify(formations)


@app.route("/api/filieres", methods=["GET"])
def api_filieres():
    formation_id = request.args.get("formation_id")

    if not formation_id:
        return jsonify({"error": "formation_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM filieres
        WHERE formation_id = ?
        ORDER BY nom
    """, (formation_id,))

    rows = cursor.fetchall()
    conn.close()

    filieres = []
    for r in rows:
        filieres.append({
            "id": r[0],
            "nom": r[1]
        })

    return jsonify(filieres)

@app.route("/api/groupes", methods=["GET"])
def api_groupes():
    filiere_id = request.args.get("filiere_id")

    if not filiere_id:
        return jsonify({"error": "filiere_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM groupes
        WHERE filiere_id = ?
        ORDER BY nom
    """, (filiere_id,))

    rows = cursor.fetchall()
    conn.close()

    groupes = []
    for r in rows:
        groupes.append({
            "id": r[0],
            "nom": r[1]
        })

    return jsonify(groupes)

#seances d'un groupe
@app.route("/api/seance-en-cours", methods=["GET"])
def api_seance_en_cours():
    groupe_id = request.args.get("groupe_id")

    if not groupe_id:
        return jsonify({"error": "groupe_id manquant"}), 400

    # Ancien code à effacer : 
    # maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Nouveau code :
    tz = pytz.timezone('Europe/Paris')
    maintenant = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, matiere, debut, fin, salle
        FROM seances
        WHERE groupe_id = ?
          AND debut <= ?
          AND fin >= ?
        ORDER BY debut
        LIMIT 1
    """, (groupe_id, maintenant, maintenant))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({
            "status": "AUCUNE_SEANCE"
        })

    seance_id, matiere, debut, fin, salle = row

    return jsonify({
        "status": "SEANCE_EN_COURS",
        "seance": {
            "id": seance_id,
            "matiere": matiere,
            "debut": debut,
            "fin": fin,
            "salle": salle
        }
    }) 

#téléchargement CSV des présences d'une séance
@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    seance_id = request.args.get("seance_id")

    if not seance_id:
        return jsonify({"error": "seance_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 1. Récupérer les infos de la séance pour nommer le fichier
    cursor.execute("SELECT matiere, debut FROM seances WHERE id = ?", (seance_id,))
    seance_info = cursor.fetchone()
    
    if not seance_info:
        conn.close()
        return "Séance introuvable", 404
        
    matiere, debut = seance_info
    date_jour = debut[:10] # Garde juste YYYY-MM-DD

# 2. Récupérer TOUS les étudiants (Présents, Retards, Absents) + la Filière
    cursor.execute("""
        SELECT 
            e.nom,
            e.prenom,
            f.nom AS filiere, -- NOUVEAU : On sélectionne le nom de la filière
            g.nom AS groupe,
            COALESCE(p.etat, 'absent') AS statut,
            p.timestamp_badge,
            COALESCE(
                CASE 
                    WHEN p.etat = 'retard' THEN
                        CAST(
                            (julianday(p.timestamp_badge) - julianday(s.debut)) * 24 * 60
                            AS INTEGER
                        )
                    ELSE 0
                END,
                0
            ) AS retard_minutes
        FROM seances s
        JOIN etudiants e ON s.groupe_id = e.groupe_id
        JOIN groupes g ON e.groupe_id = g.id
        JOIN filieres f ON g.filiere_id = f.id  -- NOUVEAU : On fait le lien avec la table filieres
        LEFT JOIN presences p ON p.etudiant_id = e.id AND p.seance_id = s.id
        WHERE s.id = ?
        ORDER BY f.nom, g.nom, e.nom, e.prenom
    """, (seance_id,))

    rows = cursor.fetchall()
    conn.close()

    # 3. Générer le CSV en mémoire
    si = StringIO()
    cw = csv.writer(si, delimiter=';') 
    
    # NOUVEAU : Ajout de 'Filière' dans l'en-tête
    cw.writerow(['Nom', 'Prénom', 'Filière', 'Groupe', 'Statut', 'Heure de badge', 'Retard (min)'])
    
    # Remplissage des données
    for r in rows:
        nom, prenom, filiere, groupe, statut, heure, retard = r  # NOUVEAU : on dépaquète la filière
        heure_format = heure if heure else "—"
        cw.writerow([nom, prenom, filiere, groupe, statut, heure_format, retard])

    # 4. Renvoyer le texte comme un fichier téléchargeable
    # Le utf-8-sig est une astuce magique pour forcer Excel à lire les accents (é, à, etc.)
    return Response(
        si.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=presences_{matiere}_{date_jour}.csv"}
    )
# ===== LANCEMENT SERVEUR =====c
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

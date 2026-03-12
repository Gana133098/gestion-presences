# ===== IMPORTS =====
from flask import Flask, request, jsonify, render_template, Response
import os
from datetime import datetime
import csv
from io import StringIO
import pytz
import psycopg2
import psycopg2.extras

# ===== INITIALISATION FLASK =====
app = Flask(__name__)

# ===== CONNEXION DB =====
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)


# ===== ROUTE TEST SERVEUR =====
@app.route("/")
def home():
    return "Serveur Flask OK"

@app.route("/test-db")
def test_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
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

    data = request.get_json(force=True)

    if not data or "uid" not in data:
        return jsonify({"error": "UID manquant"}), 400

    uid = data["uid"]

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT e.id, e.nom, e.prenom,
               g.id,
               fo.nom, fi.nom, g.nom
        FROM etudiants e
        JOIN groupes g ON e.groupe_id = g.id
        JOIN filieres fi ON g.filiere_id = fi.id
        JOIN formations fo ON fi.formation_id = fo.id
        WHERE e.uid_rfid = %s
    """, (uid,))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"status": "INCONNU"})

    etudiant_id, nom, prenom, groupe_id, formation, filiere, groupe = row

    tz = pytz.timezone('Europe/Paris')
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        SELECT id, debut, fin, matiere, salle
        FROM seances
        WHERE groupe_id = %s
          AND debut <= %s
          AND fin >= %s
        LIMIT 1
    """, (groupe_id, now, now))

    seance = cursor.fetchone()

    if not seance:
        conn.close()
        return jsonify({
            "status": "PAS_DE_COURS",
            "etudiant": {"nom": nom, "prenom": prenom, "groupe": groupe}
        })

    seance_id, debut, fin, matiere, salle = seance

    debut_str = debut.strftime("%Y-%m-%d %H:%M:%S") if hasattr(debut, 'strftime') else debut
    heure_debut_dt = datetime.strptime(debut_str, "%Y-%m-%d %H:%M:%S")
    now_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")

    retard_minutes = (now_dt - heure_debut_dt).total_seconds() / 60

    statut = "PRESENT" if retard_minutes <= 15 else "RETARD"

    cursor.execute("""
        SELECT id FROM presences
        WHERE etudiant_id = %s AND seance_id = %s
    """, (etudiant_id, seance_id))

    presence_existante = cursor.fetchone()

    if presence_existante:
        conn.close()
        return jsonify({
            "status": "DEJA_BADGE",
            "etudiant": {"nom": nom, "prenom": prenom, "groupe": groupe}
        })

    cursor.execute("""
        INSERT INTO presences (etudiant_id, seance_id, timestamp_badge, etat)
        VALUES (%s, %s, %s, %s)
    """, (etudiant_id, seance_id, now, statut.lower()))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "PRESENCE_ENREGISTREE",
        "etat": statut.lower(),
        "horodatage": now,
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
            "heure_debut": debut_str,
            "heure_fin": fin.strftime("%Y-%m-%d %H:%M:%S") if hasattr(fin, 'strftime') else fin,
            "salle": salle
        },
        "presence": {
            "statut": statut.lower(),
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
                            EXTRACT(EPOCH FROM (p.timestamp_badge - s.debut)) / 60
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
        WHERE s.id = %s
        ORDER BY p.timestamp_badge DESC NULLS LAST, e.nom, e.prenom
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
            "timestamp_badge": r[4].strftime("%Y-%m-%d %H:%M:%S") if r[4] else None,
            "retard_minutes": r[5]
        })

    return jsonify(data)


@app.route("/api/formations", methods=["GET"])
def api_formations():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom FROM formations ORDER BY nom")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "nom": r[1]} for r in rows])


@app.route("/api/filieres", methods=["GET"])
def api_filieres():
    formation_id = request.args.get("formation_id")
    if not formation_id:
        return jsonify({"error": "formation_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom FROM filieres WHERE formation_id = %s ORDER BY nom", (formation_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "nom": r[1]} for r in rows])


@app.route("/api/groupes", methods=["GET"])
def api_groupes():
    filiere_id = request.args.get("filiere_id")
    if not filiere_id:
        return jsonify({"error": "filiere_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nom FROM groupes WHERE filiere_id = %s ORDER BY nom", (filiere_id,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "nom": r[1]} for r in rows])


@app.route("/api/seance-en-cours", methods=["GET"])
def api_seance_en_cours():
    groupe_id = request.args.get("groupe_id")
    if not groupe_id:
        return jsonify({"error": "groupe_id manquant"}), 400

    tz = pytz.timezone('Europe/Paris')
    maintenant = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, matiere, debut, fin, salle
        FROM seances
        WHERE groupe_id = %s
          AND debut <= %s
          AND fin >= %s
        ORDER BY debut
        LIMIT 1
    """, (groupe_id, maintenant, maintenant))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"status": "AUCUNE_SEANCE"})

    seance_id, matiere, debut, fin, salle = row

    return jsonify({
        "status": "SEANCE_EN_COURS",
        "seance": {
            "id": seance_id,
            "matiere": matiere,
            "debut": debut.strftime("%Y-%m-%d %H:%M:%S") if hasattr(debut, 'strftime') else debut,
            "fin": fin.strftime("%Y-%m-%d %H:%M:%S") if hasattr(fin, 'strftime') else fin,
            "salle": salle
        }
    })


@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    seance_id = request.args.get("seance_id")
    if not seance_id:
        return jsonify({"error": "seance_id manquant"}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT matiere, debut FROM seances WHERE id = %s", (seance_id,))
    seance_info = cursor.fetchone()

    if not seance_info:
        conn.close()
        return "Séance introuvable", 404

    matiere, debut = seance_info
    date_jour = debut.strftime("%Y-%m-%d") if hasattr(debut, 'strftime') else debut[:10]

    cursor.execute("""
        SELECT
            e.nom,
            e.prenom,
            f.nom AS filiere,
            g.nom AS groupe,
            COALESCE(p.etat, 'absent') AS statut,
            p.timestamp_badge,
            COALESCE(
                CASE
                    WHEN p.etat = 'retard' THEN
                        CAST(
                            EXTRACT(EPOCH FROM (p.timestamp_badge - s.debut)) / 60
                            AS INTEGER
                        )
                    ELSE 0
                END,
                0
            ) AS retard_minutes
        FROM seances s
        JOIN etudiants e ON s.groupe_id = e.groupe_id
        JOIN groupes g ON e.groupe_id = g.id
        JOIN filieres f ON g.filiere_id = f.id
        LEFT JOIN presences p ON p.etudiant_id = e.id AND p.seance_id = s.id
        WHERE s.id = %s
        ORDER BY f.nom, g.nom, e.nom, e.prenom
    """, (seance_id,))

    rows = cursor.fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si, delimiter=';')
    cw.writerow(['Nom', 'Prénom', 'Filière', 'Groupe', 'Statut', 'Heure de badge', 'Retard (min)'])

    for r in rows:
        nom, prenom, filiere, groupe, statut, heure, retard = r
        heure_format = heure.strftime("%Y-%m-%d %H:%M:%S") if heure else "—"
        cw.writerow([nom, prenom, filiere, groupe, statut, heure_format, retard])

    return Response(
        si.getvalue().encode('utf-8-sig'),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=presences_{matiere}_{date_jour}.csv"}
    )


# ===== LANCEMENT SERVEUR =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

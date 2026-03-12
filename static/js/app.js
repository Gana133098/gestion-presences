const tbody = document.querySelector("#table-presences tbody");
const emptyEl = document.querySelector("#empty");
const errorEl = document.querySelector("#error");
const lastUpdateEl = document.querySelector("#last-update");
const filterStatut = document.querySelector("#filter-statut");
const btnExportCsv = document.getElementById("btn-export-csv");
let currentSeanceId = null; // Pour retenir quelle séance télécharger
const selectFormation = document.getElementById("select-formation");
const selectFiliere = document.getElementById("select-filiere");
const selectGroupe = document.getElementById("select-groupe");

let currentGroupeId = null;
let currentPresencesData = []; // Stocker les données pour le filtrage local

document.addEventListener("DOMContentLoaded", () => {
  chargerFormations();
});

// ===== CHARGEMENT DES MENUS DÉROULANTS =====
function chargerFormations() {
  fetch("/api/formations")
    .then(res => res.json())
    .then(data => {
      selectFormation.innerHTML = '<option value="">-- Choisir --</option>';
      data.forEach(f => {
        const opt = document.createElement("option");
        opt.value = f.id;
        opt.textContent = f.nom;
        selectFormation.appendChild(opt);
      });
    });
}

selectFormation.addEventListener("change", () => {
  const formationId = selectFormation.value;

  selectFiliere.innerHTML = '<option value="">-- Choisir --</option>';
  selectGroupe.innerHTML = '<option value="">-- Choisir --</option>';
  selectFiliere.disabled = !formationId;
  selectGroupe.disabled = true;

  if (formationId) {
    fetch(`/api/filieres?formation_id=${formationId}`)
      .then(res => res.json())
      .then(data => {
        data.forEach(f => {
          const opt = document.createElement("option");
          opt.value = f.id;
          opt.textContent = f.nom;
          selectFiliere.appendChild(opt);
        });
      });
  }
});

selectFiliere.addEventListener("change", () => {
  const filiereId = selectFiliere.value;

  selectGroupe.innerHTML = '<option value="">-- Choisir --</option>';
  selectGroupe.disabled = !filiereId;

  if (filiereId) {
    fetch(`/api/groupes?filiere_id=${filiereId}`)
      .then(res => res.json())
      .then(data => {
        data.forEach(g => {
          const opt = document.createElement("option");
          opt.value = g.id;
          opt.textContent = g.nom;
          selectGroupe.appendChild(opt);
        });
      });
  }
});

// ===== CHANGEMENT DE GROUPE (Séance + Présences) =====
selectGroupe.addEventListener("change", () => {
  currentGroupeId = selectGroupe.value || null;

  if (!currentGroupeId) {
    viderSeance();
    viderPresences();
    return;
  }
  chargerSeanceEnCours(currentGroupeId);
});

function chargerSeanceEnCours(groupeId) {
  fetch(`/api/seance-en-cours?groupe_id=${groupeId}`)
    .then(res => res.json())
    .then(data => {
      if (data.status !== "SEANCE_EN_COURS") {
        viderSeance();
        viderPresences();
        return;
      }

      // MAJ des infos de la séance
      document.getElementById("seance-matiere").textContent = data.seance.matiere;
      document.getElementById("seance-salle").textContent = data.seance.salle || "—";
      document.getElementById("seance-debut").textContent = data.seance.debut;
      document.getElementById("seance-fin").textContent = data.seance.fin;
      // ... (code existant de mise à jour du texte HTML) ...
      
      currentSeanceId = data.seance.id; // On retient l'ID de la séance
      btnExportCsv.disabled = false;    // On active le bouton

      chargerPresences(data.seance.id);
      chargerPresences(data.seance.id);
    })
    .catch(() => {
      viderSeance();
      viderPresences();
    });
}

function chargerPresences(seanceId) {
  fetch(`/api/presences?seance_id=${seanceId}`)
    .then(res => res.json())
    .then(data => {
      currentPresencesData = data; // Sauvegarde pour le filtre statut
      renderPresences(data);
      updateLastUpdate(); // Mise à jour de l'heure ici !
    })
    .catch(() => {
      setError("Impossible de charger les présences.");
    });
}

// ===== AFFICHAGE ET FORMATAGE =====
function renderPresences(rows) {
  tbody.innerHTML = "";
  clearError();

  const filt = filterStatut.value;
  const filtered = (filt === "all") ? rows : rows.filter(r => r.statut === filt);

  if (filtered.length === 0) {
    emptyEl.classList.remove("hidden");
  } else {
    emptyEl.classList.add("hidden");
    
    filtered.forEach(p => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${p.nom ?? "—"}</td>
        <td>${p.prenom ?? "—"}</td>
        <td>${p.groupe ?? "—"}</td>
        <td><span class="badge ${p.statut}">${p.statut}</span></td>
        <td>${formatTime(p.timestamp_badge)}</td>
        <td>${p.retard_minutes ?? "—"}</td>
      `;
      tbody.appendChild(tr);
    });
  }
}

function updateLastUpdate() {
  const now = new Date();
  lastUpdateEl.textContent = `Dernière mise à jour: ${now.toLocaleTimeString()}`;
}

function formatTime(ts) {
  if (!ts) return "—";
  return ts.slice(11, 19); // Extrait juste l'heure HH:MM:SS
}

function viderSeance() {
  document.getElementById("seance-matiere").textContent = "—";
  document.getElementById("seance-matiere").textContent = "—";
  document.getElementById("seance-salle").textContent = "—";
  document.getElementById("seance-debut").textContent = "—";
  document.getElementById("seance-fin").textContent = "—";
  currentSeanceId = null;
  btnExportCsv.disabled = true;
}

function viderPresences() {
  tbody.innerHTML = "";
  emptyEl.classList.remove("hidden");
  currentPresencesData = [];
  lastUpdateEl.textContent = "Dernière mise à jour: —";
}

function setError(msg) {
  errorEl.textContent = msg;
  errorEl.classList.remove("hidden");
}

function clearError() {
  errorEl.textContent = "";
  errorEl.classList.add("hidden");
}

// ===== ÉVÉNEMENTS & AUTO-REFRESH =====
filterStatut.addEventListener("change", () => {
  renderPresences(currentPresencesData);
});

// Rafraîchissement automatique toutes les 10 secondes
setInterval(() => {
  if (currentGroupeId) {
    chargerSeanceEnCours(currentGroupeId);
  }
}, 10000); 

btnExportCsv.addEventListener("click", () => {
  if (currentSeanceId) {
    // Cette ligne redirige le navigateur vers notre route, ce qui lance le téléchargement !
    window.location.href = `/api/export-csv?seance_id=${currentSeanceId}`;
  }
});
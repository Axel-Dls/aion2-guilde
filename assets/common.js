/* Fonctions et constantes partagées par le classement et l'admin. */
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = n => n == null ? "–" : Number(n).toLocaleString("fr-FR");
  const norm = s => String(s || "").trim().replace(/\s+/g, " ").toLowerCase();

  // Classes du site officiel (anglais) → noms français
  const CLASS_FR = { Gladiator: "Gladiateur", Templar: "Templier", Cleric: "Clerc", Chanter: "Aède",
    Assassin: "Assassin", Ranger: "Ranger", Sorcerer: "Sorcier", Spiritmaster: "Spiritualiste" };

  // Rôles et classes qui les composent (même découpage que le tableau de suivi de la guilde)
  const ROLES = [
    { name: "Tank", color: "var(--tank)", classes: ["Gladiateur", "Templier"] },
    { name: "Heal", color: "var(--heal)", classes: ["Clerc"] },
    { name: "Aède", color: "var(--aede)", classes: ["Aède"] },
    { name: "DPS", color: "var(--dps)", classes: ["Assassin", "Ranger", "Sorcier", "Spiritualiste"] },
  ];
  const RANKS = ["Chef", "Officier", "Membre"];

  // Signalements produits par scripts/update.py (data/db.json → run.issues)
  const ISSUE = {
    not_found: { label: "Introuvable", bad: true },
    unknown_server: { label: "Serveur inconnu", bad: true },
    error: { label: "Échec de lecture", bad: true },
    left_guild: { label: "Hors légion", bad: false },
    gs_drop: { label: "GS en baisse", bad: false },
  };

  // Serveurs EU et leur identifiant sur le site officiel
  const SERVER_ID = { Siel: 1301, Nezekan: 1302, Vaizel: 1303, Kaisinel: 1304, Yustiel: 1305, Ariel: 1306, Fregion: 1307,
    Meslamtaeda: 1308, Hithanya: 1309, Israphel: 2301, Zikel: 2302, Triniel: 2303, Lumiel: 2304, Marchutan: 2305,
    Azphel: 2306, Ereshkigal: 2307, Beritra: 2308, Nemon: 2309 };

  const OFFICIAL = "https://aion2.plaync.com/en-us/characters";
  // Fiche officielle d'un perso suivi, ou recherche par pseudo à défaut
  function profileUrl(m, region = "eu") {
    if (m.serverId && m.characterId) return `${OFFICIAL}/${m.serverId}/${m.characterId}?region=${encodeURIComponent(m.region || region)}`;
    const q = new URLSearchParams({ keyword: m.name, region: m.region || region });
    const sid = m.serverId || SERVER_ID[m.server];
    if (sid) q.set("serverId", sid);
    return `${OFFICIAL}/index?${q}`;
  }

  // Dépôt GitHub déduit de l'adresse du site (utilisateur.github.io/depot)
  const host = location.hostname.match(/^([^.]+)\.github\.io$/);
  const REPO = {
    owner: host ? host[1] : "Axel-Dls",
    name: (host && location.pathname.split("/").filter(Boolean)[0]) || "aion2-guilde",
  };
  REPO.url = `https://github.com/${REPO.owner}/${REPO.name}`;

  // « il y a 3 h », « il y a 2 jours »
  function ago(iso) {
    const h = (Date.now() - new Date(iso)) / 36e5;
    if (h < 1) return "il y a moins d'une heure";
    if (h < 48) return `il y a ${Math.round(h)} h`;
    return `il y a ${Math.round(h / 24)} jours`;
  }
  const dateTime = iso => new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });

  // Valeur de `field` environ `days` jours avant le dernier relevé (ou le plus ancien connu)
  function valueDaysAgo(history, days, field) {
    const pts = (history || []).filter(p => p[field] != null);
    if (pts.length < 2) return null;
    const target = new Date(pts[pts.length - 1].d);
    target.setDate(target.getDate() - days);
    let ref = pts[0];
    for (const p of pts) if (new Date(p.d) <= target) ref = p;
    return ref === pts[pts.length - 1] ? null : ref[field];
  }

  // Charge data/db.json et ajoute à chaque membre : classe en français, progressions 7 j, signalements
  async function loadDb() {
    const db = await fetch("data/db.json?t=" + Date.now(), { cache: "no-store" }).then(r => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
    const issues = {};
    (db.run?.issues || []).forEach(i => (issues[norm(i.name)] ||= []).push(i));
    db.members = (db.members || []).map(m => {
      const gs0 = valueDaysAgo(m.history, 7, "il"), cp0 = valueDaysAgo(m.history, 7, "cp");
      return { ...m,
        classFr: CLASS_FR[m.className] || m.className || "",
        d7: gs0 != null && m.itemLevel != null ? m.itemLevel - gs0 : null,
        cp7: cp0 != null && m.cp != null ? m.cp - cp0 : null,
        issues: issues[norm(m.name)] || [] };
    });
    return db;
  }

  const roleBadge = r => /^(chef|officier)$/i.test(r || "") ? `<span class="role ${r.toLowerCase()}">${esc(r)}</span>` : "";
  const flags = (issues, only) => issues.filter(i => !only || only.includes(i.type))
    .map(i => `<span class="flag ${ISSUE[i.type]?.bad ? "bad" : ""}" title="${esc(i.detail)}">${esc(ISSUE[i.type]?.label || i.type)}</span>`).join("");

  function toast(text) {
    let el = $("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
    el.textContent = text; el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => el.hidden = true, 2600);
  }

  window.G = { $, esc, fmt, norm, CLASS_FR, ROLES, RANKS, ISSUE, SERVER_ID, REPO, profileUrl, ago, dateTime,
    valueDaysAgo, loadDb, roleBadge, flags, toast };
})();

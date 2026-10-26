/* Fonctions et constantes partagées par le classement et l'admin.
   Nécessite supabase-js (chargé avant ce fichier). */
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = n => n == null ? "–" : Number(n).toLocaleString("fr-FR");
  const norm = s => String(s || "").trim().replace(/\s+/g, " ").toLowerCase();

  // Classes du site officiel (anglais) → noms français
  const CLASS_FR = { Gladiator: "Gladiateur", Templar: "Templier", Cleric: "Clerc", Chanter: "Aède",
    Assassin: "Assassin", Ranger: "Ranger", Sorcerer: "Sorcier", Spiritmaster: "Spiritualiste", Elementalist: "Spiritualiste" };

  // Rôles et classes qui les composent (même découpage que le tableau de suivi de la guilde)
  const ROLES = [
    { name: "Tank", color: "var(--tank)", classes: ["Gladiateur", "Templier"] },
    { name: "Heal", color: "var(--heal)", classes: ["Clerc"] },
    { name: "Aède", color: "var(--aede)", classes: ["Aède"] },
    { name: "DPS", color: "var(--dps)", classes: ["Assassin", "Ranger", "Sorcier", "Spiritualiste"] },
  ];
  const RANKS = ["Chef", "Officier", "Membre"];

  // Signalements produits par scripts/update.py (table passages → signalements)
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

  // ------------------------------------------------------------ Supabase
  // Adresse et clé publique du projet : faites pour être visibles. Ce que chacun
  // peut lire ou modifier est contrôlé par la base elle-même (supabase/schema.sql).
  const SUPABASE_URL = "https://cvsrncwbferhkwsfajzf.supabase.co";
  const SUPABASE_KEY = "sb_publishable_4XN-7vWD291wAAWeywuLMg_ZJ55B4Qc";
  const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {
    auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  const ROLE_LABEL = { admin: "Admin", gerant: "Gérant", lecteur: "Lecteur" };
  // Restes de l'ancien site (clé GitHub et clé du mot de passe) : effacés de l'appareil
  try { ["aion2-guilde-token", "aion2-guilde-site-key"].forEach(k => { localStorage.removeItem(k); sessionStorage.removeItem(k); }); } catch {}
  let ME = null;  // { discord_id, role, nom, avatar }

  // Lève l'erreur renvoyée par Supabase, sinon renvoie les données
  const ok = ({ data, error }) => { if (error) throw error; return data; };
  // Toutes les lignes d'une requête, par pages de 1000 (limite de Supabase)
  async function fetchAll(query) {
    const out = [];
    for (let from = 0; ; from += 1000) {
      const rows = ok(await query().range(from, from + 999));
      out.push(...rows);
      if (rows.length < 1000) return out;
    }
  }

  const DISCORD_ICON = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.3 4.4A19.6 19.6 0 0 0 15.4 3l-.6 1.3a18 18 0 0 0-5.6 0L8.6 3a19.6 19.6 0 0 0-4.9 1.5C.6 9.1-.3 13.6.1 18.1a19.8 19.8 0 0 0 6 3l1.3-2.1a12.8 12.8 0 0 1-2-1l.5-.4a14 14 0 0 0 12.2 0l.5.4c-.6.4-1.3.7-2 1l1.3 2.1a19.7 19.7 0 0 0 6-3c.5-5.2-.8-9.7-3.6-13.7zM8 15.3c-1.2 0-2.2-1.1-2.2-2.4S6.8 10.5 8 10.5s2.2 1.1 2.2 2.4-1 2.4-2.2 2.4zm8 0c-1.2 0-2.2-1.1-2.2-2.4s1-2.4 2.2-2.4 2.2 1.1 2.2 2.4-1 2.4-2.2 2.4z"/></svg>';

  // Écran plein page tant que la personne n'est pas connectée ou autorisée
  function gate(html) {
    document.documentElement.classList.add("locked");
    const g = document.createElement("div");
    g.className = "gate";
    g.innerHTML = `<div class="gate-card">${html}</div>`;
    document.body.append(g);
    g.querySelector("[data-login]")?.addEventListener("click", async e => {
      e.target.disabled = true;
      const { error } = await sb.auth.signInWithOAuth({ provider: "discord", options: { redirectTo: location.origin + location.pathname } });
      if (error) { e.target.disabled = false; g.querySelector(".gate-err").textContent = "Connexion impossible : " + error.message; }
    });
    g.querySelector("[data-logout]")?.addEventListener("click", logout);
    return new Promise(() => {});  // la page attend : la connexion recharge le site
  }

  // Connexion obligatoire. Résout avec le compte une fois autorisé ; sinon affiche l'écran adapté.
  // need : rôles acceptés pour cette page (par défaut, tous les comptes autorisés).
  async function auth(need = ["admin", "gerant", "lecteur"]) {
    const { data: { session } } = await sb.auth.getSession();
    if (new URLSearchParams(location.search).has("code")) history.replaceState(null, "", location.pathname);
    if (!session) {
      return gate(`<p class="eyebrow">Accès réservé</p><h1>Ivalys</h1>
        <p class="muted">Ce site est réservé à la guilde. Connecte-toi avec ton compte Discord pour continuer.</p>
        <button class="discord" type="button" data-login>${DISCORD_ICON} Se connecter avec Discord</button>
        <p class="gate-err" role="alert"></p>`);
    }
    ME = ok(await sb.rpc("mon_acces"));
    const who = `<div class="gate-who">${ME.avatar ? `<img src="${esc(ME.avatar)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
      <div><strong>${esc(ME.nom || "Compte Discord")}</strong><small>ID ${esc(ME.discord_id || "?")}</small></div></div>`;
    if (!ME.role) {
      return gate(`<p class="eyebrow">Accès en attente</p><h1>Ivalys</h1>${who}
        <p class="muted">Ton compte n'a pas encore accès au site. Ta demande est enregistrée : un administrateur doit l'accepter.</p>
        <button type="button" data-logout>Se déconnecter</button>
        ${!ME.premier_admin ? "" : `<details><summary>Tu es l'administrateur du site ?</summary>
          Pour te donner l'accès la première fois, colle cette ligne dans Supabase → SQL Editor :
          <code>insert into public.acces (discord_id, pseudo, role) values ('${esc(ME.discord_id)}', '${esc((ME.nom || "Admin").replace(/'/g, ""))}', 'admin');</code>
          puis recharge cette page.</details>`}`);
    }
    if (!need.includes(ME.role)) {
      return gate(`<p class="eyebrow">Accès limité</p><h1>Ivalys</h1>${who}
        <p class="muted">Cette page est réservée aux gérants de la guilde.</p>
        <a class="btn primary" href="./" style="justify-content:center">Retour au classement</a>`);
    }
    return ME;
  }
  async function logout() {
    await sb.auth.signOut();
    location.href = location.pathname;
  }
  const lock = logout;
  const isProtected = () => true;

  // Ligne de la table membres → format utilisé par les pages
  const toMember = (r, hist = []) => ({
    id: r.id, key: r.cle, name: r.pseudo, server: r.serveur, role: r.statut, main: r.main || "", on: r.suivi,
    aliases: r.anciens_noms || [], className: r.classe, level: r.niveau, cp: r.cp, itemLevel: r.gs, legion: r.legion,
    image: r.image, characterId: r.character_id, serverId: r.server_id, region: r.region, status: r.etat,
    lastOk: r.dernier_ok, lastSeen: r.derniere_connexion, history: hist,
  });

  // Charge les données et ajoute à chaque membre : classe en français, progressions 7 j, signalements.
  // db.members : persos suivis ; db.all : tous les persos (suivis et en attente).
  async function loadDb() {
    const since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
    const [reglages, rows, last, releves] = await Promise.all([
      sb.from("reglages").select("cle,valeur").then(ok),
      fetchAll(() => sb.from("membres").select("*").order("id")),
      sb.from("passages").select("*").not("fin", "is", null).order("debut", { ascending: false }).limit(1).then(ok),
      fetchAll(() => sb.from("releves").select("membre_id,jour,gs,cp").gte("jour", since).order("jour").order("membre_id")),
    ]);
    const cfg = Object.fromEntries(reglages.map(r => [r.cle, r.valeur]));
    const hist = {};
    releves.forEach(p => (hist[p.membre_id] ||= []).push({ d: p.jour, cp: p.cp, il: p.gs }));
    const run = last[0];
    const db = {
      guild: cfg.guilde || "", region: cfg.region || "eu",
      updatedAt: run?.fin || null,
      counts: run ? { ok: run.ok, total: run.total } : null,
      run: run ? { at: run.fin, issues: run.signalements || [], source: run.declencheur } : { issues: [] },
    };
    const issues = {};
    db.run.issues.forEach(i => (issues[norm(i.name)] ||= []).push(i));
    db.all = rows.map(r => {
      const m = toMember(r, hist[r.id] || []);
      const gs0 = valueDaysAgo(m.history, 7, "il"), cp0 = valueDaysAgo(m.history, 7, "cp");
      return { ...m,
        classFr: CLASS_FR[m.className] || m.className || "",
        d7: gs0 != null && m.itemLevel != null ? m.itemLevel - gs0 : null,
        cp7: cp0 != null && m.cp != null ? m.cp - cp0 : null,
        issues: m.on ? issues[norm(m.name)] || [] : [] };
    });
    db.members = db.all.filter(m => m.on);
    // Alts : rattachés à leur main s'il est suivi, sinon traités comme des persos principaux
    const byName = Object.fromEntries(db.members.map(m => [norm(m.name), m]));
    db.members.forEach(m => { m.alts = []; });
    db.members.forEach(m => {
      const main = m.main && byName[norm(m.main)];
      m.isAlt = !!main && main !== m;
      if (m.isAlt) { m.mainName = main.name; main.alts.push(m); }
    });
    db.mains = db.members.filter(m => !m.isAlt);
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
    valueDaysAgo, loadDb, roleBadge, flags, toast, lock, logout, isProtected, sb, ok, fetchAll, auth, ROLE_LABEL,
    me: () => ME };
})();

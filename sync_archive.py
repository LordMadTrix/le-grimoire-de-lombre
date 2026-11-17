import html
import json
import os
import re
import subprocess
import unicodedata
import urllib.parse
import internetarchive as ia

ROOT = os.path.dirname(os.path.abspath(__file__))

ITEMS = {
    "episodes": {
        "identifier": "le-grimoire-de-lombre-episodes-video",
        "folder": "Episodes",
        "ext": ".mp4",
    },
    "audios": {
        "identifier": "le-grimoire-de-lombre-audios",
        "folder": "Audios",
        "ext": ".mp3",
    },
    "personnages": {
        "identifier": "le-grimoire-de-lombre-personnages",
        "folder": "Personnages",
        "ext": ".mp4",
    },
}

CHRONICLES_ITEM_ID = "le-grimoire-de-lombre-chroniques"

CHARACTER_NOTES = {
    "Armione": "L'Elfe Exilée — maîtresse des arcanes et des runes.",
    "Brandir": "Pourfendeur de Crânes — guerrier nain à la grande hache (La Guerre de la Bière).",
    "Lagherta": "Veille sur Vous — prêtresse lumineuse et protectrice du groupe.",
    "Lysandre": "Le Pieux — compagnon sombre et résolu, gardien de l'anneau.",
    "Persephonix": "Libre et Fière — ensorceleuse des flammes et des vents.",
}


def to_ascii_filename(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def sync_folder(cfg: dict) -> list[str]:
    ident = cfg["identifier"]
    folder = os.path.join(ROOT, cfg["folder"])
    ext = cfg["ext"].lower()
    if not os.path.isdir(folder):
        return []

    item = ia.get_item(ident)
    existing = {
        f["name"]
        for f in item.files
        if f.get("source") == "original" and f["name"].lower().endswith(ext)
    }

    local_files = sorted(
        f for f in os.listdir(folder) if f.lower().endswith(ext)
    )

    to_upload = {}
    for fname in local_files:
        remote_name = to_ascii_filename(fname)
        if remote_name not in existing and fname not in existing:
            to_upload[remote_name] = os.path.join(folder, fname)

    if to_upload:
        print(f"[{ident}] Envoi de {len(to_upload)} nouveau(x) fichier(s)...")
        ia.upload(ident, files=to_upload, verbose=True, verify=True, retries=3)
        existing.update(to_upload.keys())
    else:
        print(f"[{ident}] Tout est déjà à jour ({len(existing)} fichiers).")

    return sorted(existing)


def sync_texts_archive() -> None:
    files_to_sync = {}
    for sub in ["Histoires", "Chroniques", "Codex"]:
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if fname.lower().endswith((".txt", ".json")):
                remote = f"{sub}_{to_ascii_filename(fname)}"
                files_to_sync[remote] = os.path.join(d, fname)
    poster = os.path.join(ROOT, "Affiche - Le Grimoire de l'Ombre.jpg")
    if os.path.isfile(poster):
        files_to_sync["Affiche - Le Grimoire de l'Ombre.jpg"] = poster

    if not files_to_sync:
        return

    item = ia.get_item(CHRONICLES_ITEM_ID)
    if not item.exists:
        print(f"[{CHRONICLES_ITEM_ID}] Création de l'archive textes...")
        ia.upload(
            CHRONICLES_ITEM_ID,
            files=files_to_sync,
            metadata={
                "title": "Le Grimoire de l'Ombre - Histoires, Chroniques & Codex (JDR)",
                "mediatype": "texts",
                "collection": "opensource",
                "creator": "retromad",
                "language": "fre",
                "subject": ["JDR", "Jeu de rôle", "RPG", "Le Grimoire de l'Ombre", "Lore"],
                "description": (
                    "Archive des récits de personnages, chroniques de parties et codex "
                    "de la campagne JDR « Le Grimoire de l'Ombre »."
                ),
            },
            verbose=True,
            verify=True,
            retries=3,
        )
    else:
        print(f"[{CHRONICLES_ITEM_ID}] Synchronisation des textes...")
        ia.upload(CHRONICLES_ITEM_ID, files=files_to_sync, verbose=False, verify=True, retries=3)


def archive_url(ident: str, filename: str) -> str:
    return f"https://archive.org/download/{ident}/{urllib.parse.quote(filename)}"


def char_note_for(filename: str) -> str:
    for prefix, note in CHARACTER_NOTES.items():
        if filename.lower().startswith(prefix.lower()):
            return note
    return "Vidéo de présentation du personnage."


def format_paragraphs_html(raw: str) -> str:
    blocks = []
    for chunk in raw.strip().split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk == "---":
            blocks.append("<hr>")
        elif chunk.startswith("### "):
            blocks.append(f"<h4>{html.escape(chunk[4:])}</h4>")
        else:
            escaped = html.escape(chunk).replace("\n", "<br>")
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            blocks.append(f"<p>{escaped}</p>")
    return "".join(blocks)


def collect_books() -> tuple[list[dict], dict[str, dict]]:
    books = []
    by_key = {}

    chron_dir = os.path.join(ROOT, "Chroniques")
    if os.path.isdir(chron_dir):
        for fname in sorted(f for f in os.listdir(chron_dir) if f.lower().endswith(".txt")):
            with open(os.path.join(chron_dir, fname), encoding="utf-8") as fh:
                lines = fh.read().strip().splitlines()
            if not lines:
                continue
            title = lines[0].strip()
            body_html = format_paragraphs_html("\n".join(lines[1:]))
            entry = {
                "id": f"chron-{fname[:2]}",
                "kind": "Chronique",
                "title": title,
                "html": body_html,
                "prefix": fname[:2],
            }
            books.append(entry)
            by_key[f"chron:{fname[:2]}"] = entry

    stories_dir = os.path.join(ROOT, "Histoires")
    if os.path.isdir(stories_dir):
        for prefix in CHARACTER_NOTES:
            path = os.path.join(stories_dir, f"{prefix}.txt")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    raw = fh.read().strip()
                if not raw:
                    continue
                entry = {
                    "id": f"char-{prefix.lower()}",
                    "kind": "Personnage",
                    "title": prefix if prefix != "Persephonix" else "Perséphonix",
                    "html": format_paragraphs_html(raw),
                    "prefix": prefix.lower(),
                }
                books.append(entry)
                by_key[f"char:{prefix.lower()}"] = entry

    return books, by_key


def build_codex_html() -> str:
    codex_path = os.path.join(ROOT, "Codex", "codex.json")
    if not os.path.isfile(codex_path):
        return "<p>Aucun codex disponible.</p>"
    with open(codex_path, encoding="utf-8") as fh:
        data = json.load(fh)

    sections = [
        ("pnj", "Personnages Non-Joueurs (PNJ)"),
        ("lieux", "Lieux"),
        ("objets", "Objets & Trésors"),
        ("quetes", "Quêtes Actives"),
    ]
    out = []
    for key, label in sections:
        items = data.get(key, [])
        if not items:
            continue
        cards = []
        for it in items:
            nom = html.escape(it.get("nom", ""))
            role = html.escape(it.get("role") or it.get("statut") or "")
            note = html.escape(it.get("note", ""))
            badge = f'<span class="badge">{role}</span>' if role else ""
            cards.append(
                f"""          <article class="card">
            <div>
              <h3>{nom} {badge}</h3>
              <p>{note}</p>
            </div>
          </article>"""
            )
        out.append(
            f"""        <div class="codex-group">
          <h3>{label}</h3>
          <div class="grid">
{chr(10).join(cards)}
          </div>
        </div>"""
        )
    return "\n".join(out)


def build_index(episodes: list[str], audios: list[str], characters: list[str]) -> None:
    books, books_by_key = collect_books()

    audio_by_prefix = {f[:2]: f for f in audios if len(f) >= 2 and f[:2].isdigit()}

    ep_cards = []
    for f in episodes:
        prefix = f[:2] if len(f) >= 2 and f[:2].isdigit() else ""
        title = html.escape(os.path.splitext(f)[0])
        v_url = archive_url(ITEMS["episodes"]["identifier"], f)
        a_file = audio_by_prefix.get(prefix)
        a_html = ""
        if a_file:
            a_url = archive_url(ITEMS["audios"]["identifier"], a_file)
            a_html = f"""          <div class="linked-audio">
            <span class="mini-label">Audio associé :</span>
            <audio controls preload="metadata" src="{a_url}"></audio>
          </div>"""

        chron_book = books_by_key.get(f"chron:{prefix}")
        reader_btn = ""
        if chron_book:
            reader_btn = f'<button type="button" class="btn-inline" data-open-book="{chron_book["id"]}">Ouvrir la chronique dans la liseuse</button>'

        ep_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{title}</h3>
            <p>Épisode vidéo de la campagne.</p>
          </div>
          <video controls preload="metadata" playsinline src="{v_url}"></video>
{a_html}
          <div class="card-actions">
            {reader_btn}
            <a href="{v_url}" target="_blank" rel="noopener">Télécharger (.mp4)</a>
          </div>
        </article>"""
        )

    playlist_tracks = []
    audio_cards = []
    for i, f in enumerate(audios):
        title = os.path.splitext(f)[0]
        url = archive_url(ITEMS["audios"]["identifier"], f)
        playlist_tracks.append({"title": title, "url": url})
        audio_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{html.escape(title)}</h3>
            <p>Récit / session audio MP3.</p>
          </div>
          <audio controls preload="metadata" src="{url}"></audio>
          <div class="card-actions">
            <button type="button" class="btn-inline" data-play-track="{i}">Lire dans la playlist</button>
            <a href="{url}" target="_blank" rel="noopener">Télécharger (.mp3)</a>
          </div>
        </article>"""
        )

    char_cards = []
    for f in characters:
        title = html.escape(os.path.splitext(f)[0])
        note = html.escape(char_note_for(f))
        v_url = archive_url(ITEMS["personnages"]["identifier"], f)

        matched_book = None
        for prefix in CHARACTER_NOTES:
            if f.lower().startswith(prefix.lower()):
                matched_book = books_by_key.get(f"char:{prefix.lower()}")
                break

        story_btn = ""
        if matched_book:
            story_btn = f'<button type="button" class="btn-inline" data-open-book="{matched_book["id"]}">Lire dans la liseuse</button>'

        char_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{title}</h3>
            <p>{note}</p>
          </div>
          <video controls preload="metadata" playsinline src="{v_url}"></video>
          <div class="card-actions">
            {story_btn}
            <a href="{v_url}" target="_blank" rel="noopener">Télécharger (.mp4)</a>
          </div>
        </article>"""
        )

    chron_cards = []
    for b in books:
        if b["kind"] != "Chronique":
            continue
        chron_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{html.escape(b["title"])}</h3>
            <p>Compte-rendu complet de la session.</p>
          </div>
          <div class="card-actions">
            <button type="button" class="btn-inline" data-open-book="{b["id"]}">Ouvrir dans la liseuse</button>
          </div>
        </article>"""
        )

    books_json = json.dumps(books, ensure_ascii=False)
    tracks_json = json.dumps(playlist_tracks, ensure_ascii=False)
    codex_html = build_codex_html()

    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>Le Grimoire de l'Ombre — Portail JDR</title>
  <style>
    :root {{
      --bg-light: #f5f1ea;
      --bg-dark: #111015;
      --surface-light: #ffffff;
      --surface-dark: #1b1922;
      --border-light: #ddd4c6;
      --border-dark: #2f2a3d;
      --text-light: #1e1b24;
      --text-dark: #ede9e0;
      --muted-light: #60586d;
      --muted-dark: #a69eb5;
      --accent-light: #6d3fb5;
      --accent-dark: #c49a52;
      --accent-text-light: #ffffff;
      --accent-text-dark: #151218;

      --bg: var(--bg-light);
      --surface: var(--surface-light);
      --border: var(--border-light);
      --text: var(--text-light);
      --muted: var(--muted-light);
      --accent: var(--accent-light);
      --accent-text: var(--accent-text-light);

      color-scheme: light dark;
      accent-color: var(--accent);
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: var(--bg-dark);
        --surface: var(--surface-dark);
        --border: var(--border-dark);
        --text: var(--text-dark);
        --muted: var(--muted-dark);
        --accent: var(--accent-dark);
        --accent-text: var(--accent-text-dark);
      }}
    }}

    @supports (color: light-dark(white, black)) {{
      :root {{
        --bg: light-dark(var(--bg-light), var(--bg-dark));
        --surface: light-dark(var(--surface-light), var(--surface-dark));
        --border: light-dark(var(--border-light), var(--border-dark));
        --text: light-dark(var(--text-light), var(--text-dark));
        --muted: light-dark(var(--muted-light), var(--muted-dark));
        --accent: light-dark(var(--accent-light), var(--accent-dark));
        --accent-text: light-dark(var(--accent-text-light), var(--accent-text-dark));
      }}
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
    }}

    .wrap {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 2rem 1.25rem 4rem;
    }}

    .hero {{
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: 2rem;
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.5rem;
      margin-bottom: 1.75rem;
    }}

    @media (max-width: 680px) {{
      .hero {{ grid-template-columns: 1fr; text-align: center; }}
      .hero img {{ max-width: 220px; margin: 0 auto; }}
    }}

    .hero img {{
      width: 100%;
      border-radius: 10px;
      border: 1px solid var(--border);
      display: block;
    }}

    h1 {{
      margin: 0 0 0.5rem;
      font-size: clamp(1.7rem, 3vw, 2.3rem);
      letter-spacing: 0.02em;
    }}

    .subtitle {{
      margin: 0 0 1.25rem;
      color: var(--muted);
    }}

    .btn-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.65rem;
    }}

    @media (max-width: 680px) {{
      .btn-row {{ justify-content: center; }}
    }}

    .btn, .btn-inline {{
      display: inline-block;
      padding: 0.5rem 0.95rem;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      font-size: 0.9rem;
      border: 1px solid var(--border);
      color: var(--text);
      background: var(--bg);
      cursor: pointer;
      font-family: inherit;
    }}

    .btn.primary, .btn-inline.primary {{
      background: var(--accent);
      color: var(--accent-text);
      border-color: transparent;
    }}

    .btn:hover, .btn-inline:hover {{ opacity: 0.88; }}

    .tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
      margin-bottom: 1.75rem;
    }}

    .tab-btn {{
      padding: 0.55rem 1rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      font-weight: 600;
      font-size: 0.92rem;
      cursor: pointer;
      font-family: inherit;
    }}

    .tab-btn[aria-selected="true"] {{
      background: var(--accent);
      color: var(--accent-text);
      border-color: transparent;
    }}

    .tabpanel[hidden] {{ display: none; }}

    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin: 0 0 1rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.45rem;
    }}

    .section-head h2 {{
      margin: 0;
      font-size: 1.35rem;
    }}

    .section-head a {{
      color: var(--accent);
      text-decoration: none;
      font-size: 0.92rem;
      font-weight: 600;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
      gap: 1.15rem;
      margin-bottom: 2rem;
    }}

    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.1rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 0.75rem;
    }}

    .card h3 {{
      margin: 0 0 0.25rem;
      font-size: 1.05rem;
    }}

    .card p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.9rem;
    }}

    .badge {{
      display: inline-block;
      font-size: 0.75rem;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--accent);
      vertical-align: middle;
      margin-left: 0.35rem;
    }}

    video, audio {{
      width: 100%;
      border-radius: 8px;
      background: #000;
    }}

    audio {{ background: transparent; }}

    .linked-audio {{
      border-top: 1px solid var(--border);
      padding-top: 0.5rem;
    }}

    .mini-label {{
      display: block;
      font-size: 0.8rem;
      color: var(--muted);
      margin-bottom: 0.25rem;
    }}

    .card-actions {{
      display: flex;
      gap: 0.65rem;
      flex-wrap: wrap;
      align-items: center;
    }}

    .card-actions a {{
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
    }}

    .card-actions a:hover {{ text-decoration: underline; }}

    .playlist-bar {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem 1.2rem;
      margin-bottom: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.65rem;
    }}

    .playlist-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .codex-group {{ margin-bottom: 1.75rem; }}
    .codex-group > h3 {{
      margin: 0 0 0.75rem;
      color: var(--accent);
      font-size: 1.15rem;
    }}

    dialog:modal {{
      width: min(760px, 94vw);
      max-height: 88vh;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 0;
      background: var(--surface);
      color: var(--text);
      overscroll-behavior: contain;
    }}

    dialog::backdrop {{
      background: rgba(0, 0, 0, 0.65);
      backdrop-filter: blur(3px);
      overflow: hidden;
      overscroll-behavior: contain;
    }}

    .reader-head {{
      position: sticky;
      top: 0;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0.85rem 1.15rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
      z-index: 2;
    }}

    .reader-controls {{
      display: flex;
      gap: 0.4rem;
      align-items: center;
      flex-wrap: wrap;
    }}

    .reader-body {{
      padding: 1.5rem clamp(1rem, 4vw, 2.25rem) 2rem;
      font-family: Georgia, "Times New Roman", serif;
      font-size: var(--reader-size, 1.08rem);
      line-height: 1.75;
    }}

    .reader-body h4 {{
      color: var(--accent);
      margin: 1.4rem 0 0.5rem;
      font-family: system-ui, -apple-system, sans-serif;
    }}

    .reader-body hr {{
      border: 0;
      border-top: 1px solid var(--border);
      margin: 1.25rem 0;
    }}

    .reader-foot {{
      position: sticky;
      bottom: 0;
      background: var(--surface);
      border-top: 1px solid var(--border);
      padding: 0.7rem 1.15rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
    }}

    footer {{
      text-align: center;
      color: var(--muted);
      font-size: 0.85rem;
      margin-top: 3rem;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <header class="hero">
      <img
        src="Affiche%20-%20Le%20Grimoire%20de%20l'Ombre.jpg"
        onerror="this.onerror=null;this.src='https://archive.org/download/le-grimoire-de-lombre-episodes-video/Affiche%20-%20Le%20Grimoire%20de%20l%27Ombre.jpg';"
        alt="Affiche du groupe de JDR Le Grimoire de l'Ombre">
      <div>
        <h1>Le Grimoire de l'Ombre</h1>
        <p class="subtitle">
          Portail officiel de notre campagne de Jeu de Rôle — chroniques, vidéos, audios, fiches personnages et codex.
        </p>
        <div class="btn-row">
          <button type="button" class="btn primary" id="openGrimoireBtn">Ouvrir la Liseuse (Grimoire)</button>
          <a class="btn" href="https://archive.org/details/@retromad/" target="_blank" rel="noopener">Archive.org (@retromad)</a>
        </div>
      </div>
    </header>

    <nav class="tabs" role="tablist" aria-label="Sections du portail">
      <button class="tab-btn" role="tab" aria-selected="true" aria-controls="panel-chroniques" id="tab-chroniques">Chroniques &amp; Épisodes</button>
      <button class="tab-btn" role="tab" aria-selected="false" aria-controls="panel-personnages" id="tab-personnages">Personnages</button>
      <button class="tab-btn" role="tab" aria-selected="false" aria-controls="panel-codex" id="tab-codex">Codex</button>
      <button class="tab-btn" role="tab" aria-selected="false" aria-controls="panel-audios" id="tab-audios">Playlist Audio</button>
    </nav>

    <section id="panel-chroniques" class="tabpanel" role="tabpanel" aria-labelledby="tab-chroniques">
      <div class="section-head">
        <h2>Chroniques des Parties</h2>
        <a href="https://archive.org/details/{CHRONICLES_ITEM_ID}" target="_blank" rel="noopener">Archive textes →</a>
      </div>
      <div class="grid">
{chr(10).join(chron_cards)}
      </div>

      <div class="section-head">
        <h2>Épisodes Vidéo &amp; Audios liés</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-episodes-video" target="_blank" rel="noopener">Archive vidéos →</a>
      </div>
      <div class="grid">
{chr(10).join(ep_cards)}
      </div>
    </section>

    <section id="panel-personnages" class="tabpanel" role="tabpanel" aria-labelledby="tab-personnages" hidden>
      <div class="section-head">
        <h2>Personnages du Groupe</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-personnages" target="_blank" rel="noopener">Archive personnages →</a>
      </div>
      <div class="grid">
{chr(10).join(char_cards)}
      </div>
    </section>

    <section id="panel-codex" class="tabpanel" role="tabpanel" aria-labelledby="tab-codex" hidden>
      <div class="section-head">
        <h2>Codex de la Campagne</h2>
      </div>
{codex_html}
    </section>

    <section id="panel-audios" class="tabpanel" role="tabpanel" aria-labelledby="tab-audios" hidden>
      <div class="section-head">
        <h2>Récits &amp; Sessions Audio</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-audios" target="_blank" rel="noopener">Archive audios →</a>
      </div>
      <div class="playlist-bar">
        <div class="playlist-top">
          <strong id="playlistNow">Prêt à lire la playlist complète</strong>
          <button type="button" class="btn primary" id="playAllBtn">Lire tout en continu</button>
        </div>
        <audio id="playlistPlayer" controls preload="metadata"></audio>
      </div>
      <div class="grid">
{chr(10).join(audio_cards)}
      </div>
    </section>

    <footer>
      Le Grimoire de l'Ombre — Médias &amp; textes archivés sur Internet Archive (<a href="https://archive.org/details/@retromad/" target="_blank" rel="noopener">@retromad</a>)
    </footer>
  </main>

  <dialog id="readerDialog" closedby="any" aria-labelledby="readerTitle">
    <div class="reader-head">
      <strong id="readerTitle">Liseuse</strong>
      <div class="reader-controls">
        <button type="button" class="btn-inline" id="fontDecBtn" aria-label="Réduire le texte">A-</button>
        <button type="button" class="btn-inline" id="fontIncBtn" aria-label="Agrandir le texte">A+</button>
        <button type="button" class="btn-inline" id="closeReaderBtn">Fermer</button>
      </div>
    </div>
    <article class="reader-body" id="readerBody"></article>
    <div class="reader-foot">
      <button type="button" class="btn-inline" id="prevBookBtn">← Précédent</button>
      <span id="readerCounter" class="mini-label"></span>
      <button type="button" class="btn-inline" id="nextBookBtn">Suivant →</button>
    </div>
  </dialog>

  <script>
    const BOOKS = {books_json};
    const TRACKS = {tracks_json};

    // Onglets accessibles
    const tabBtns = document.querySelectorAll('.tab-btn');
    const panels = document.querySelectorAll('.tabpanel');
    tabBtns.forEach((btn) => {{
      btn.addEventListener('click', () => {{
        tabBtns.forEach((b) => b.setAttribute('aria-selected', 'false'));
        panels.forEach((p) => p.hidden = true);
        btn.setAttribute('aria-selected', 'true');
        document.getElementById(btn.getAttribute('aria-controls')).hidden = false;
      }});
    }});

    // Liseuse (Dialog modal)
    const dialog = document.getElementById('readerDialog');
    const readerTitle = document.getElementById('readerTitle');
    const readerBody = document.getElementById('readerBody');
    const readerCounter = document.getElementById('readerCounter');
    const prevBtn = document.getElementById('prevBookBtn');
    const nextBtn = document.getElementById('nextBookBtn');
    let currentBookIdx = 0;
    let fontSize = 1.08;

    function renderBook(idx) {{
      if (!BOOKS.length) return;
      currentBookIdx = (idx + BOOKS.length) % BOOKS.length;
      const b = BOOKS[currentBookIdx];
      readerTitle.textContent = `${{b.kind}} — ${{b.title}}`;
      readerBody.innerHTML = b.html;
      readerBody.scrollTop = 0;
      dialog.scrollTop = 0;
      readerCounter.textContent = `${{currentBookIdx + 1}} / ${{BOOKS.length}}`;
    }}

    function openBookById(id) {{
      const idx = BOOKS.findIndex((b) => b.id === id);
      renderBook(idx >= 0 ? idx : 0);
      dialog.showModal();
    }}

    document.getElementById('openGrimoireBtn').addEventListener('click', () => openBookById(BOOKS[0]?.id));
    document.querySelectorAll('[data-open-book]').forEach((btn) => {{
      btn.addEventListener('click', () => openBookById(btn.dataset.openBook));
    }});
    document.getElementById('closeReaderBtn').addEventListener('click', () => dialog.close());
    prevBtn.addEventListener('click', () => renderBook(currentBookIdx - 1));
    nextBtn.addEventListener('click', () => renderBook(currentBookIdx + 1));

    document.getElementById('fontIncBtn').addEventListener('click', () => {{
      fontSize = Math.min(1.5, +(fontSize + 0.1).toFixed(2));
      readerBody.style.setProperty('--reader-size', `${{fontSize}}rem`);
    }});
    document.getElementById('fontDecBtn').addEventListener('click', () => {{
      fontSize = Math.max(0.85, +(fontSize - 0.1).toFixed(2));
      readerBody.style.setProperty('--reader-size', `${{fontSize}}rem`);
    }});

    // Fallback light-dismiss pour Safari sans closedby
    if (!('closedBy' in HTMLDialogElement.prototype)) {{
      dialog.addEventListener('click', (event) => {{
        if (event.target !== dialog) return;
        const rect = dialog.getBoundingClientRect();
        const inside = (
          rect.top <= event.clientY && event.clientY <= rect.top + rect.height &&
          rect.left <= event.clientX && event.clientX <= rect.left + rect.width
        );
        if (!inside) dialog.close();
      }});
    }}

    // Playlist audio continue
    const playlistPlayer = document.getElementById('playlistPlayer');
    const playlistNow = document.getElementById('playlistNow');
    let currentTrackIdx = 0;

    function playTrack(idx) {{
      if (!TRACKS.length) return;
      currentTrackIdx = idx % TRACKS.length;
      const t = TRACKS[currentTrackIdx];
      playlistPlayer.src = t.url;
      playlistNow.textContent = `Lecture : ${{t.title}} (${{currentTrackIdx + 1}}/${{TRACKS.length}})`;
      playlistPlayer.play().catch(() => {{}});
    }}

    document.getElementById('playAllBtn').addEventListener('click', () => playTrack(0));
    document.querySelectorAll('[data-play-track]').forEach((btn) => {{
      btn.addEventListener('click', () => playTrack(Number(btn.dataset.playTrack)));
    }});
    playlistPlayer.addEventListener('ended', () => {{
      if (currentTrackIdx + 1 < TRACKS.length) {{
        playTrack(currentTrackIdx + 1);
      }}
    }});
  </script>
</body>
</html>
"""
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    print("index.html mis à jour.")


def git_push_if_repo() -> None:
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        return
    status = subprocess.run(
        ["git", "-C", ROOT, "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if not status.stdout.strip():
        print("Aucun changement Git à publier.")
        return
    subprocess.run(
        [
            "git", "-C", ROOT, "add",
            "index.html", "Affiche - Le Grimoire de l'Ombre.jpg",
            "sync_archive.py", "Lancer_Sync_Archive.bat", ".gitignore",
            "Histoires", "Chroniques", "Codex",
        ],
        check=False,
    )
    subprocess.run(["git", "-C", ROOT, "commit", "-m", "Mise a jour portail Le Grimoire de l'Ombre"], check=False)
    subprocess.run(["git", "-C", ROOT, "push"], check=False)
    print("Site web mis à jour sur GitHub Pages !")


if __name__ == "__main__":
    episodes = sync_folder(ITEMS["episodes"])
    audios = sync_folder(ITEMS["audios"])
    characters = sync_folder(ITEMS["personnages"])
    sync_texts_archive()
    build_index(episodes, audios, characters)
    git_push_if_repo()

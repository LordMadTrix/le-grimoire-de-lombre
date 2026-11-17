import html
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


def sync_folder(key: str, cfg: dict) -> list[str]:
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


def archive_url(ident: str, filename: str) -> str:
    return f"https://archive.org/download/{ident}/{urllib.parse.quote(filename)}"


def char_note_for(filename: str) -> str:
    for prefix, note in CHARACTER_NOTES.items():
        if filename.lower().startswith(prefix.lower()):
            return note
    return "Vidéo de présentation du personnage."


def load_story_html(filename: str) -> str:
    stories_dir = os.path.join(ROOT, "Histoires")
    if not os.path.isdir(stories_dir):
        return ""
    matched_path = None
    for prefix in CHARACTER_NOTES:
        if filename.lower().startswith(prefix.lower()):
            candidate = os.path.join(stories_dir, f"{prefix}.txt")
            if os.path.isfile(candidate):
                matched_path = candidate
                break
    if not matched_path:
        return ""
    with open(matched_path, encoding="utf-8") as fh:
        raw = fh.read().strip()
    if not raw:
        return ""
    blocks = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk == "---":
            blocks.append("<hr>")
        else:
            escaped = html.escape(chunk).replace("\n", "<br>")
            escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            blocks.append(f"<p>{escaped}</p>")
    return (
        '          <details class="story">\n'
        "            <summary>Lire son histoire</summary>\n"
        f'            <div class="story-body">{"".join(blocks)}</div>\n'
        "          </details>"
    )


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


def load_chronicles_html() -> str:
    chron_dir = os.path.join(ROOT, "Chroniques")
    if not os.path.isdir(chron_dir):
        return ""
    files = sorted(f for f in os.listdir(chron_dir) if f.lower().endswith(".txt"))
    if not files:
        return ""
    cards = []
    for fname in files:
        with open(os.path.join(chron_dir, fname), encoding="utf-8") as fh:
            lines = fh.read().strip().splitlines()
        if not lines:
            continue
        heading = html.escape(lines[0].strip())
        body = format_paragraphs_html("\n".join(lines[1:]))
        cards.append(
            f"""        <article class="card chronicle-card">
          <h3>{heading}</h3>
          <details class="story" open>
            <summary>Lire le compte-rendu</summary>
            <div class="story-body">{body}</div>
          </details>
        </article>"""
        )
    if not cards:
        return ""
    return f"""    <section id="chroniques">
      <div class="section-head">
        <h2>Chroniques des Parties</h2>
      </div>
      <div class="chronicles-list">
{chr(10).join(cards)}
      </div>
    </section>"""


def build_index(episodes: list[str], audios: list[str], characters: list[str]) -> None:
    ep_cards = []
    for f in episodes:
        title = html.escape(os.path.splitext(f)[0])
        url = archive_url(ITEMS["episodes"]["identifier"], f)
        ep_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{title}</h3>
            <p>Épisode vidéo de la campagne.</p>
          </div>
          <video controls preload="metadata" playsinline src="{url}"></video>
          <div class="card-actions">
            <a href="{url}" target="_blank" rel="noopener">Télécharger (.mp4)</a>
          </div>
        </article>"""
        )

    audio_cards = []
    for f in audios:
        title = html.escape(os.path.splitext(f)[0])
        url = archive_url(ITEMS["audios"]["identifier"], f)
        audio_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{title}</h3>
            <p>Récit / session audio MP3.</p>
          </div>
          <audio controls preload="metadata" src="{url}"></audio>
          <div class="card-actions">
            <a href="{url}" target="_blank" rel="noopener">Télécharger (.mp3)</a>
          </div>
        </article>"""
        )

    char_cards = []
    for f in characters:
        title = html.escape(os.path.splitext(f)[0])
        note = html.escape(char_note_for(f))
        story_html = load_story_html(f)
        url = archive_url(ITEMS["personnages"]["identifier"], f)
        char_cards.append(
            f"""        <article class="card">
          <div>
            <h3>{title}</h3>
            <p>{note}</p>
          </div>
          <video controls preload="metadata" playsinline src="{url}"></video>
{story_html}
          <div class="card-actions">
            <a href="{url}" target="_blank" rel="noopener">Télécharger (.mp4)</a>
          </div>
        </article>"""
        )

    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>Le Grimoire de l'Ombre — Archive JDR</title>
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
      grid-template-columns: 240px 1fr;
      gap: 2rem;
      align-items: center;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.5rem;
      margin-bottom: 2.5rem;
    }}

    @media (max-width: 680px) {{
      .hero {{ grid-template-columns: 1fr; text-align: center; }}
      .hero img {{ max-width: 240px; margin: 0 auto; }}
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

    .btn {{
      display: inline-block;
      padding: 0.55rem 1rem;
      border-radius: 8px;
      text-decoration: none;
      font-weight: 600;
      font-size: 0.92rem;
      border: 1px solid var(--border);
      color: var(--text);
      background: var(--bg);
    }}

    .btn.primary {{
      background: var(--accent);
      color: var(--accent-text);
      border-color: transparent;
    }}

    .btn:hover {{ opacity: 0.88; }}

    section {{ margin-bottom: 2.75rem; }}

    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 1rem;
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
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1.15rem;
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

    video, audio {{
      width: 100%;
      border-radius: 8px;
      background: #000;
    }}

    audio {{
      background: transparent;
    }}

    .card-actions {{
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .card-actions a {{
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent);
      text-decoration: none;
    }}

    .card-actions a:hover {{ text-decoration: underline; }}

    details.story {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.75rem;
      background: var(--bg);
    }}

    details.story summary {{
      cursor: pointer;
      font-weight: 600;
      font-size: 0.9rem;
      color: var(--accent);
    }}

    .story-body {{
      margin-top: 0.65rem;
      max-height: 320px;
      overflow-y: auto;
      padding-right: 0.35rem;
      font-size: 0.9rem;
    }}

    .story-body p {{
      color: var(--text);
      margin: 0 0 0.65rem;
    }}

    .story-body hr {{
      border: 0;
      border-top: 1px solid var(--border);
      margin: 0.75rem 0;
    }}

    .story-body h4 {{
      margin: 0.9rem 0 0.4rem;
      font-size: 0.98rem;
      color: var(--accent);
    }}

    .chronicles-list {{
      display: grid;
      gap: 1.15rem;
    }}

    .chronicle-card .story-body {{
      max-height: none;
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
          Portail officiel de notre campagne de Jeu de Rôle — vidéos des épisodes, récits audio et présentations des personnages, hébergés sur Internet Archive.
        </p>
        <div class="btn-row">
          <a class="btn primary" href="https://archive.org/details/@retromad/" target="_blank" rel="noopener">Profil Archive.org (@retromad)</a>
          <a class="btn" href="#episodes">Épisodes Vidéo</a>
          <a class="btn" href="#audios">Audios</a>
          <a class="btn" href="#personnages">Personnages</a>
          <a class="btn" href="#chroniques">Chroniques</a>
        </div>
      </div>
    </header>

{load_chronicles_html()}

    <section id="episodes">
      <div class="section-head">
        <h2>Épisodes Vidéo</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-episodes-video" target="_blank" rel="noopener">Voir l'item sur Archive.org →</a>
      </div>
      <div class="grid">
{chr(10).join(ep_cards)}
      </div>
    </section>

    <section id="audios">
      <div class="section-head">
        <h2>Récits &amp; Sessions Audio</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-audios" target="_blank" rel="noopener">Voir l'item sur Archive.org →</a>
      </div>
      <div class="grid">
{chr(10).join(audio_cards)}
      </div>
    </section>

    <section id="personnages">
      <div class="section-head">
        <h2>Personnages du Groupe</h2>
        <a href="https://archive.org/details/le-grimoire-de-lombre-personnages" target="_blank" rel="noopener">Voir l'item sur Archive.org →</a>
      </div>
      <div class="grid">
{chr(10).join(char_cards)}
      </div>
    </section>

    <footer>
      Le Grimoire de l'Ombre — Médias hébergés sur Internet Archive (<a href="https://archive.org/details/@retromad/" target="_blank" rel="noopener">@retromad</a>)
    </footer>
  </main>
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
    subprocess.run(["git", "-C", ROOT, "add", "index.html", "Affiche - Le Grimoire de l'Ombre.jpg", "sync_archive.py", "Lancer_Sync_Archive.bat", ".gitignore", "Histoires", "Chroniques"], check=False)
    subprocess.run(["git", "-C", ROOT, "commit", "-m", "Mise a jour archive Le Grimoire de l'Ombre"], check=False)
    subprocess.run(["git", "-C", ROOT, "push"], check=False)
    print("Site web mis à jour sur GitHub Pages !")


if __name__ == "__main__":
    episodes = sync_folder("episodes", ITEMS["episodes"])
    audios = sync_folder("audios", ITEMS["audios"])
    characters = sync_folder("personnages", ITEMS["personnages"])
    build_index(episodes, audios, characters)
    git_push_if_repo()

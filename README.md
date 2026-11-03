# BaseStatGuessr

A Pokémon base-stat guessing game.

- **Build the Spread:** you're given a Pokémon and its Base Stat Total. Share the points across six sliders. Every point you're off costs one point, from 100 per round.
- **Whose Spread?:** you're given six raw base stats. Name the Pokémon in 4 guesses or fewer. Each miss gives a clue: generation, then type, then a blurred sprite.
- **Length:** 5 rounds, or Infinite with 3 lives (score 0 in a round and you lose one).

The site itself is static, so GitHub Pages hosts it. Ranked Infinite runs and the leaderboard use a small free Cloudflare server in `worker/` (see below).

## Repo layout

```
index.html            the game
data/game-data.js     generated: Pokémon, stats, filters (scrambled)
data/sprites.js       generated: blurred + full sprites (scrambled)
tools/build.py        rebuilds the two data files
tools/stat-report.md  generated: where your fangame files differ from PokéAPI
tools/fangame/        YOUR files go here (git-ignored, never uploaded)
worker/               the leaderboard server (Cloudflare Worker + D1 database)
worker/src/data.js    generated: the server's copy of the Pokémon data
```

## Put it on GitHub Pages

1. Create a new public repo on GitHub (e.g. `basestatguessr`).
2. Upload everything in this folder **except** `tools/fangame/` (the `.gitignore` already skips it if you use git).
3. In the repo, go to **Settings → Pages**, set **Source** to *Deploy from a branch*, choose `main` and `/ (root)`, then save.
4. After a minute, the game is live at `https://<your-username>.github.io/basestatguessr/`.

## Updating the data from PokéAPI

The data files shipped here were built from your fangame files only. To switch to official PokéAPI stats (and whenever a new game changes stats):

1. Install Python 3 and Pillow: `pip install pillow`
2. Copy your files into place:
   - your PBS files (`pokemon.txt`, `pokemon_forms.txt`, `pokemon_base_1_Gen_9_Pack.txt`, `pokemon_forms_Gen_9_Pack.txt`) → `tools/fangame/PBS/`
   - your `Graphics/Pokemon/Front` folder → `tools/fangame/Front/`
3. From the repo folder, run:
   ```
   python tools/build.py --refresh
   ```
   This downloads PokéAPI's data tables (cached in `tools/.cache/`), then writes `data/game-data.js`, `data/sprites.js` and `tools/stat-report.md`.
4. Read `tools/stat-report.md`, then upload the two new `data/` files to GitHub.

How the data is combined:

- **The Pokémon list comes from your PBS files**, because every entry needs a sprite from your Front folder. Fakémon sprites and any Pokémon without a PBS entry are ignored.
- **Stats and types come from PokéAPI** whenever it has a matching Pokémon or form.
- **Anything PokéAPI doesn't have yet** (e.g. very new Megas) keeps the stats from your PBS files.
- The report lists every stat where your files and PokéAPI disagree. Treat it as a checklist for Iolite & Amethyst: either they're deliberate changes, or they're mistakes to fix.

Other options: `--offline` skips PokéAPI entirely; `--pbs DIR` and `--sprites DIR` point at different folders.

## The leaderboard server (Cloudflare)

Infinite runs with every generation and filter included are **ranked**. For those, the server picks each Pokémon, marks every guess and keeps the score itself, so nobody can post a made-up score. Everything else (5-round games, custom filters) runs in the browser as before.

Until you set it up, the leaderboard is saved on each player's own device.

### One-time setup (Windows)

1. Make a free account at [dash.cloudflare.com](https://dash.cloudflare.com/sign-up).
2. Install **Node.js** (the LTS version) from [nodejs.org](https://nodejs.org/).
3. Open Command Prompt in the `worker` folder:
   ```
   cd "C:\Users\Vena\Documents\folders\basestatguessr\worker"
   ```
4. Log in to Cloudflare (a browser window opens; click Allow):
   ```
   npx wrangler login
   ```
5. Create the database:
   ```
   npx wrangler d1 create basestatguessr
   ```
   It prints a `database_id`. Open `worker\wrangler.toml` in a text editor and paste it over `PASTE-YOUR-DATABASE-ID-HERE`. (If wrangler offers to add it to your config for you, say yes, and check the binding is called `DB`.)
6. In the same file, replace `YOUR-USERNAME` in `ALLOWED_ORIGINS` with your GitHub username, so only your site can use the server.
7. Create the tables:
   ```
   npx wrangler d1 execute basestatguessr --remote --file=schema.sql
   ```
   (Databases created before November 2026 also need `update-2.sql` run the same way, once.)
8. Put the server online:
   ```
   npx wrangler deploy
   ```
   It prints an address like `https://basestatguessr-api.yourname.workers.dev`. Open it in a browser: you should see `{"ok":true,...}`.
9. In `index.html`, find `const API_URL='';` near the top of the script and put that address between the quotes. Upload `index.html` to GitHub.

The Infinite option on the menu now says "ranked with everything included", and the leaderboard shows everyone's scores.

### Removing leaderboard entries (admin)

1. Pick an admin password (at least 16 characters) and give it to the server. In the `worker` folder:
   ```
   npx wrangler secret put ADMIN_TOKEN
   ```
   Type the password when asked. It's stored by Cloudflare, not in any file.
2. Go to your site with `#admin` on the end, e.g. `https://vena-cava.github.io/basestatguessr/#admin`, and log in with that password.
3. Tick entries and choose **Remove selected** (e.g. test runs), or **Remove all** to clear a mode's board when the rules change. Removed entries are hidden, not deleted, and **Restore selected** brings them back.

### Ranked round timer

Ranked rounds have a time limit, kept by the server so refreshing doesn't reset it. It's 60 seconds unless you add `ROUND_SECONDS = "45"` (or any number) under `[vars]` in `wrangler.toml` and redeploy.

### After every data rebuild

`tools/build.py` also rewrites `worker/src/data.js`. After uploading the new `data/` files to GitHub, run `npx wrangler deploy` in the `worker` folder again, so the server and the site use the same Pokémon.

### Free plan limits

Cloudflare's free Workers and D1 plans allow roughly 100,000 requests and 100,000 database writes a day. Each guess is one of each, so that's thousands of runs a day before it matters.

## About cheating

- **Ranked runs:** scores can't be faked. The server picks the Pokémon, so players can't re-roll for easy ones. It checks every guess, counts each guess once, and only accepts a leaderboard entry for a run it watched end.
- **What it can't stop:** someone looking up stats in another tab (Bulbapedia has them all). A time limit per round in ranked runs would make that much harder.
- **Casual games:** answers and sharp sprites are scrambled in the data files, so inspect element doesn't give them away at a glance.

---

Fan-made game. Pokémon and all related names are trademarks of Nintendo, Game Freak and The Pokémon Company. Stats data from [PokéAPI](https://pokeapi.co/).

# BaseStatGuessr

A Pokémon base-stat guessing game.

- **Build the Spread:** you're given a Pokémon and its Base Stat Total. Share the points across six sliders. Every point you're off costs one point, from 100 per round.
- **Whose Spread?:** you're given six raw base stats. Name the Pokémon in 4 guesses or fewer. Each miss gives a clue: generation, then type, then a blurred sprite.

It's a plain static site (no server), so GitHub Pages can host it as-is.

## Repo layout

```
index.html            the game
data/game-data.js     generated: Pokémon, stats, filters (scrambled)
data/sprites.js       generated: blurred + full sprites (scrambled)
tools/build.py        rebuilds the two data files
tools/stat-report.md  generated: where your fangame files differ from PokéAPI
tools/fangame/        YOUR files go here (git-ignored, never uploaded)
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

## About cheating

The answers and sharp sprites are scrambled in the data files and only decoded when a round ends, so inspect element and view-source don't give the answer away. Someone who knows JavaScript could still dig it out. Making the game fully cheat-proof needs a small server that only sends the answer after a guess. A daily mode would need that server anyway.

---

Fan-made game. Pokémon and all related names are trademarks of Nintendo, Game Freak and The Pokémon Company. Stats data from [PokéAPI](https://pokeapi.co/).

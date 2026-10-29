# Boox vesti

Sopstveni RSS feed za e-ink čitač: opinioni sažeti pojedinačno (teza, argumenti, zaključak, ton) i vesti u digestu grupisanom po događaju. Sažetke pravi DeepSeek, a GitHub Actions ga pokreće 3× dnevno i objavljuje na GitHub Pages.

- `feed.xml`: sve, `opinioni.xml`: samo opinioni, `vesti.xml`: samo digest
- `originali.xml`: isti opinioni, za KOReader sa `download_full_article=true` (skida ceo original)
- `index.html`: ista sadržina kao jedna strana za e-ink browser

Izvori i podešavanja su u `sources.yaml`.

Lokalno pokretanje (Docker, ključ iz `~/.claude-kp.env`):

```bash
./pokreni.sh --max 1
```

Na GitHub-u treba secret `DEEPSEEK_API_KEY` i Pages iz grane `gh-pages`.

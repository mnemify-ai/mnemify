# Sample workspace

The "Explore a sample map" preview in the app (`frontend/web/public/demo/`) is a
real harvest + compile of a fictional company, exported to static files. This
folder holds the source corpus and the scripts that rebuild it.

**The story.** Maya Chen is CTO of Stencil, a consumer fintech. Over six months
(Mar to Oct 2026) she runs an ACH pipeline rebuild after an outage, an ETF
investing launch, a Series B, SOC 2 Type II, a second incident and a VP Eng
search. `story_bible.yaml` holds the people, dates and numbers, and
`corpus_plan.md` lists every document. Everything is made up.

**The corpus** lives **outside the repo**, by default in a `sample-corpus/` folder
next to the checkout (or wherever `MNEMIFY_SAMPLE_CORPUS` points). Only the slim
export in `frontend/web/public/demo` is committed. The corpus is about 200 markdown
files with YAML frontmatter, laid out by the source they pretend to come from:

| Folder | Harvested as | How |
|---|---|---|
| `notion/<Root>/` | Notion pages (`_index.md` = top-level page) | `fixture_plugin.FixtureNotion` through the real harvester |
| `confluence/<SPACE>/` | Confluence pages in ENG / PLAT / SEC | `fixture_plugin.FixtureConfluence` |
| `obsidian/Maya/` | An Obsidian vault (wikilinks, tags, daily notes) | the real `obsidian` plugin |
| `notes/` | A local notes folder | the real `localfiles` plugin |
| `late/…` | Docs harvested *after* the compile | gives "what changed" something to show |

## Rebuild

```bash
scripts/sample-data/build.sh            # fresh scratch home under $TMPDIR
scripts/sample-data/build.sh ~/mnemify-sample   # or pick one (kept afterwards)
```

It needs the `claude` CLI signed in (every LLM step runs on your Claude
subscription) and downloads the on-device embedding model on first use. Expect
roughly an hour. `SAMPLE_AI_MODE=anthropic` uses `ANTHROPIC_API_KEY` from
`<scratch>/.env` instead.

**Never point `MNEMIFY_HOME` at the repo's `backend/`.** Its `.mnemify` holds a
developer's real harvested data. `seed.py` and `build.sh` both refuse to run
there, and they unset `MNEMIFY_ENV_FILE` / `MNEMIFY_YAML_FILE`, which would
otherwise override the scratch home.

Steps, if you need to rerun one by hand (each reads `MNEMIFY_HOME`):

1. `lint_corpus.py`: frontmatter, dates, Notion parents, wikilinks.
2. `seed.py`: harvest the four sources.
3. Compile: `uv run mnemify terrain build --ai-mode claude --embedding-model bge-small-en-v1.5`.
4. `mnemify up --port 8790`, then `record_ask.py` (questions in `questions.yaml`).
5. `curate.py`: saves a few answers to region memory and writes AI briefs.
   `condense_answers.py` then shortens the replayed answers to about 60%. The
   citation markers are kept; it checks there are no new ones and that the
   length is on target.
6. `seed.py --late`, then `snapshot.py`: GET every endpoint the sample shows.
7. `export.py`, then `validate.py`: write `public/demo/` and check it.

A recompile changes every region and tag id, so steps 3 to 7 always rerun
together. `export.py` strips local paths and `validate.py` fails if any remain.

**What ships.** `export.py` keeps the app light (`slim.py`):
- the whole map, plus every document as a listing;
- full text only for the documents the answers, todos and saved memory cite (the
  rest open as a summary preview);
- a curated set of about 18 todos;
- capped workspace lists;
- deduplicated chat citations.

That comes to about 1.3 MB.

**Safety.** Every script runs `sample_guard.py`:
- the home needs a `.mnemify-sample` sentinel, which seed.py writes into a new or
  empty directory;
- it refuses Mnemify's default home and anything inside the repo;
- it accepts only a localhost server.

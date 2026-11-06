# Examples

Everything in this folder was produced on **fictional sites** that we built for the purpose. No real site, brand,
person, address or identifier appears anywhere in this repository.

| Folder | What it is |
|---|---|
| `community-site/` | A full audit, outside + inside (read-only, through a fake WordPress REST API), of a fictional photo-editing community site, **in French**. `report.md` and `action-plan.md` are what the skill wrote, unedited. `demo_site.py` is the site itself, so you can serve it and run the same audit. |
| `fix-session/` | The agent applying a plan on a small fictional business site served locally, with the log. It predates the rule that allows one GO at a time, so the log shows grouped GOs that the tracker now refuses (the folder's README says so). |
| `benchmark/` | Raw run figures (time, turns, cost) and the machine-readable files of the fix session. |

Why fictional sites: a report about a real site lists that site's weaknesses, and publishing even an anonymized one
lets a reader recognize the site from its measurements. `Cercle Pixel` is an invented name; any resemblance to a real
business is a coincidence.

The community-site audit ran on `http://127.0.0.1`, so HTTPS, HSTS, PageSpeed Insights and field data were not
measurable and the report says so. Its figures come from one run, on one machine: treat them as an illustration of the
format and of the evidence, not as a benchmark.

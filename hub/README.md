# The IvoryOS Hub entries for plr-ivoryos

The Hub lists each liquid handler as a module (`modules`), version by version (`module_versions`),
with the instruments it yields beside its own (`module_parts`: `star_pipettes`, `flex_left`, ...)
and the Labware panel as a plugin (`plugins`). Each carries the steps IvoryOS shows, its schema.
This folder makes those entries for a release from what IvoryOS itself reads, so the Hub's steps
are exactly a deck's.

| File | What it is |
| :--- | :--- |
| `deck.json` | an IvoryOS NextGen deck with every liquid handler, simulated, and the Labware plugin: a smoke test, and the source of the schemas |
| `hub_entries.py` | turns IvoryOS's schema dump into the two files below |
| `schemas-<version>.json` | each class's schema, by class name |
| `update-<version>.sql` | one transaction updating the Hub; it reads the schemas from a temporary table `_schemas` |

## For a release

The Hub's rows install by version, so publish the release to PyPI first.

```bash
pip install -e . ivoryos-edge
python -m ivoryos_edge --deck hub/deck.json --data-dir /tmp/plr-hub   # writes ivoryos_schema.json; stop it once up
python hub/hub_entries.py /tmp/plr-hub/ivoryos_schema.json
```

Commit both files, then in the Hub's database, with the commit's id:

```sql
select net.http_get('https://raw.githubusercontent.com/ivoryos-ai/IvoryOS-PyLabRobot-Integration/<commit>/hub/schemas-<version>.json');
-- a moment later, in one session:
create temp table _schemas as select content::jsonb as s from net._http_response where id = <the id above> and status_code = 200;
-- then the contents of update-<version>.sql
```

The SQL checks `_schemas` holds the schemas before changing anything, and is one transaction.

# Read-only public review

The standalone demo publishes selected archived summaries. It never opens the
owner Workspace, private history, drafts, provider credentials or a Target.
It performs zero new model calls and zero new native campaigns.

## Preview or export

```bash
python3 -m reqlox_demo.public_demo --serve 8766
# Open http://127.0.0.1:8766/demo/
python3 -m reqlox_demo.public_demo --output-dir /absolute/new/demo-export
python3 -m http.server 8767 --bind 127.0.0.1 --directory /absolute/new/demo-export
# Open http://127.0.0.1:8767/public-demo.html
```

The export is four static files. Existing nonempty destinations, symlink inputs,
changed archive hashes and copied Target ledger drift are rejected. There is no
upload, API proxy, model client, source retrieval or experiment command in this
interface. Navigation is represented in the URL fragment; reloading restores
the selected record and stage without a private server draft.

## Publication boundary

`reqlox_demo/public_demo.py` selects seven fixed record identities from the
committed curated archive and explicitly projects safe fields. Unknown fields,
private record identities, raw evidence references with local locations,
provider responses and Workspace state are not exported. Source summary and
record hashes bind the retained summaries; they do not authenticate natural
truth or reconstruct missing historical raw evidence. The missing mistaken-launch
observations remain unknown.

The copied Target scope remains **15/15 campaigns, 62/120 seconds, zero remaining
campaigns**. Earlier library demonstrations have separate historical scopes.
The lock example is one generated candidate, two known libraries and twelve
dependent conditions, not twelve independent successful repairs. The integrated
caller is finite composed-call validation, not service-wide qualification.
Temppath keeps four atomic bindings HELD and no repair or repair re-injection.

## Hosted route separation

The gateway implementation adds anonymous GET/HEAD access to these exact paths:

| Route | Static object |
| --- | --- |
| `/demo/`, `/demo/public-demo.html` | `public-demo.html` |
| `/demo/public-demo.js` | `public-demo.js` |
| `/demo/public-demo.css` | `public-demo.css` |
| `/demo/public-demo.json` | `public-demo.json` |

`/demo` redirects to `/demo/`. Other `/demo/` paths return 404. Public write
methods return 405 before any upstream fetch. Owner pages and `/api/*` retain
Basic authentication and origin checks. The public routes fetch fixed GCS
objects without forwarding browser credentials and never proxy the VM API.
The local reproduction server also exposes `/demo/`; its other paths retain
their existing loopback-only boundary.

The asset bucket is intentionally public, independently of owner authentication.
Everything put there must be approved for anonymous reading. Release archives
and private state belong in their existing separate private locations.
The asset exporter does not inject the owner page's VM input-storage notice into
the static demo. The package includes all four assets, with JSON generated from
the curated data at export time.

The CI deployment gate checks anonymous asset hashes, private API rejection,
unknown public paths and write rejection on the staged revision before traffic
promotion, then repeats these reads on the configured origin. This describes
the implementation; see the dated delivery record for what was actually deployed.
The hosted entry is [the read-only review](https://reqlox.yukimurata0421.dev/demo/).
Verify its live behavior against the latest successful Actions deployment;
source checks alone do not establish that a revision is installed.

## Maintenance and costs

The operator owns the existing VM/gateway, release promotion, availability and
cost review. Static review does not require the private VM API, although the
Cloud Run gateway and GCS can still incur request, compute and transfer costs.
The gateway bounds simultaneous upstream requests to eight and public responses
to 1 MiB; these are resource bounds, not a financial cap or distributed abuse
protection. Do not claim anonymous access is cost-free.

Before publishing a URL, inspect the complete generated directory and manifest,
scan it for secrets and private locations, verify the route denial checks and
open the UI in a fresh browser. Retain the previous assets/revision for rollback.
Do not weaken owner authentication, republish raw state, change secret versions
or change repository visibility as part of this workflow.

A desired maintenance period through 2026-12-01 still needs an identified
operator and an agreed cost ceiling. No uptime promise, paid monitoring or
notification route is created by this change. Keep a submitted commit/tag and
its verified deployment identity separate from later development. Confirm the
applicable competition's current rules and account dashboard before submission;
deployment alone does not prove Google Cloud AI usage or competition acceptance.

See [Architecture](architecture.md), [Results](results.md),
[Review follow-up](review-follow-up-20261015.md), and
[Continuous deployment](continuous-deployment.md).

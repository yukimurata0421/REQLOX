# Review follow-up: 2026-10-15

This register distinguishes source fixes, observed delivery, unresolved evidence
and decisions that require the owner. It does not turn all 47 review items into
implementation defects. Video production changes are development-only. This register captures the
source-only checkpoint at 19:34 JST, before its subsequent deployment request.
Pending delivery statements below describe that checkpoint; consult the latest
Actions run and runtime identity for later delivery observations.

The verified delivery checkpoint is main `6fb68ff9`,
[Actions run 38708891481](https://github.com/yukimurata0421/REQLOX/actions/runs/38708891481),
GCP runtime release `dd622727e1f33a78b6d763ec6d13c2b830bb4c1dfa3f50c0dfb994644cc84c2b`,
and gateway revision `reqlox-web-gateway-00006-laj`. The new read-only demo in the
working tree is a later source change, not part of that deployed release.

| Review items | Disposition and remaining gate |
| --- | --- |
| 01–02 | Fresh read-only verification confirms the tested main commit and installed runtime. Python 3.11 and 3.14 each ran 691 tests with 29 native skips; build and automatic GCP deployment succeeded. Preserve the earlier failed CI run separately. |
| 03 | Competition GitHub App linkage is not confirmed by repository identity or Actions. Check the submission dashboard. |
| 04–05 | A separate anonymous static review surface is implemented and locally verified. Current deployed owner UI still requires its existing login. Submit an actually deployed and browser-verified review URL; do not distribute the owner password. |
| 06 | Cloud hosting and a loaded judge credential do not prove actual qualifying AI usage. Match a retained successful provider exchange to the required Cloud AI service and explain its role. No new provider call is authorized here. |
| 07 | No completed uploaded video or submitted architecture/project fields were observed. The development-only revised shooting kit and the architecture documentation are preparation. |
| 08 | Retain a submitted revision and verify hosting for the required period. Operator, cost ceiling and submission dashboard remain owner decisions. No maintenance guarantee is inferred from auto-stop being disabled. |
| 09 | The static review is a presentation surface. The existing VM/gateway execution deployment and any qualifying AI usage need separate evidence. |
| 10 | Recorded narration duration remains unknown until a real audio recording is measured. The revised kit includes scene budgets and an offline timing check. |
| 11–18 | Revised development-only script spends more time navigating records, explains model versus deterministic responsibilities, human approval, isolation and budgets, and visibly labels saved-result viewing. |
| 19 | The owned fictional report stays labeled synthetic. Natural incident knowledge transfer remains unproven. |
| 20 | Explicitly identify one generated candidate on two known libraries with twelve dependent conditions. This is not twelve independent repairs. |
| 21–22 | HELD 4, temppath repair not performed, UNKNOWN evidence gaps and the later composed caller are prominent in the new review interface and revised video. |
| 23–29 | Added a fixed static export and anonymous exact-route GET/HEAD allowlist. Owner authentication and private APIs stay separate. Write and route-escape checks precede upstream access. Deployment of these new routes remains pending. |
| 30 | Public asset-bucket access is intentional and separate from owner auth. Only the audited asset allowlist may be uploaded. Private releases/state remain private. |
| 31–32 | The dedicated projection and `/demo/` surface separate data and access paths. This uses the existing gateway; it creates no new service or authority. |
| 33 | Fixed export/response bounds and bounded concurrency are implemented. A monetary ceiling, abuse controls and ongoing inspection ownership remain operational decisions. No load test was performed. |
| 34–38 | Source added value, unused-OSS generalization, probability calibration, human-effort/cost savings and general latency distributions remain unproven. No new experiments or measurements were started. |
| 39 | Preserve 15/15 campaigns and 62/120 seconds. The campaign count closes the scope despite unspent time. No reset or implicit extension. |
| 40 | The 472-test, 58.70% statement/44.30% branch report remains a historical snapshot. The dated CI record supplies the later 691-test results and configured-runtime statement 63.92% / branch 49.64% (then excluding System IR). The new policy includes System IR and retains the earlier denominator as historical. Whole-runtime coverage and per-critical-file gates must be reported separately. |
| 41 | No independent host/OS/kernel or production-system qualification was added. |
| 42–43 | Corrected reviewer and public-scope pages to distinguish historical local checks, observed cloud delivery and pending changes. |
| 44 | Both repository remotes remain private. Anonymous code browsing is not claimed; changing visibility requires a separate decision. |
| 45 | Read-only review links method, implementation entry points, outcomes, Source identity and evidence limits. Architecture/tests are documented. Full source browsing still needs repository access. |
| 46 | Japanese shooting/narration materials remain only in development. Public UI and technical docs are English. A finished English video is not supplied or claimed. |
| 47 | Added a maintenance/cost runbook. The owner and a numeric cost limit are still required for a sustained availability commitment. |

Missing historical raw evidence remains missing. Static presentation,
deterministic replay, unit tests, deployment and actual repair observations are
different evidence gates. None establishes generalization, calibration or
external Source benefit.

See [Read-only review](read-only-demo.md) and the dated
[delivery checkpoint](../publication/ci-delivery-20261015.json).

## Remediation verification

The [source validation record](../publication/review-remediation-validation.json)
records 699 discovered tests with 29 native skips, zero failures/errors and no
real execution attempts. Runtime coverage now includes System IR: statement
64.70%, branch 50.45%. All critical-file gates pass separately. The local browser
checked all seven records, five stages, URL restoration, mobile layout and the
standalone static export. These checks did not deploy the working tree, create
a commit, run a native campaign or call a model.

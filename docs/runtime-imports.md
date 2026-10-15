# Runtime imports and archived verification

The installed runtime lives in `reqlox_core`. Internal modules use relative
imports; CLI, API, UI and tests use qualified package imports. Calling
`reqlox.inventory()` or `reqlox.source_conditions()` does not add a runtime
directory to `sys.path`. An unrelated flat module such as `workflow_effort`
cannot replace a package sibling.

Direct script entry points retain a small `__main__` bootstrap for compatibility.
Isolated workers use a fixed package mount and interpreter entry point. Target
and pinned dependency paths are introduced only inside their worker boundary.
These explicit execution boundaries do not establish a new native qualification;
changes to worker packaging still need a separately authorized retained harness.

The CLI's historical method audit checks the saved source hashes before loading
any verifier. Current relative-import snapshots load in a dedicated temporary
package. Older flat snapshots use a finder limited to their verified source
bytes and require an unused module namespace. Both forms remove their temporary
module entries afterward and leave `sys.path` unchanged. This loader is for
trusted retained verifier code, not arbitrary input code or a security sandbox.
The aggregate Target audit continues to hash archived Python without importing it.
Missing historical raw evidence remains missing; import compatibility cannot
reconstruct it.

Run the static checks without importing test or Target modules:

```bash
python3 -B scripts/check_imports.py
python3 -B scripts/native_test_inventory.py > native-test-inventory.json
```

The native inventory lists every discovered test source file, its hash, defined
test methods, unconditional holds, fixture entry points and direct boundary
calls. It checks that the offline guard precedes runtime imports and reports
native decorators that an environment switch could re-enable. Defined methods
and unittest's collected cases can differ because of inheritance. A static
boundary-call count is not a campaign count or proof of dynamic call safety.

The [offline suite](testing.md) complements this inventory with mocked dispatch,
identity and budget refusal tests. The archived native cases remain held even
when an opt-in environment variable is set. Moving one into an executable
harness requires separate authorization, inherited limits and persistent raw
receipts; ordinary test discovery cannot grant that authority.

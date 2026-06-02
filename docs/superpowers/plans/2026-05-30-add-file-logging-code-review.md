# add-file-logging Code Review

## Summary

Total: 7 findings — 0 Critical, 1 High, 2 Medium, 4 Low

Rounds executed: 3 (9 subagent passes total)

## Findings

### Critical

None.

### High

[H-001] (68) — Manual GUI verification was replaced by subprocess proxy evidence

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 5 Step 2 lines 307-325, Task 5 Step 3 lines 327-334, Task 5 Step 5 lines 349-356, Task 6 Step 1 lines 397-400, Grill-Me Pass 3 line 482

Location: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:76`, `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:80`, `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:81`, `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:83`, `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:98`, `openspec/changes/add-file-logging/tasks.md:18`

Reproduced in: R1-Pass1, R1-Pass2, R1-Pass3, R2-Pass1, R2-Pass2, R2-Pass3, R3-Pass1, R3-Pass2, R3-Pass3

Detail: The plan says the human operator runs the Task 5 manual checklist before Task 6, including dev GUI launch (`python -m app.ui.main_window`), Settings/local plaintext key entry, opening a document, forcing Detect Spells failure, restarting the app, and inspecting the real log file for 3.1, 3.2, and 3.4. The report instead records subprocess proxies for 3.1-3.4 and only records operator GUI/manual confirmation for 3.3 and 3.5, while `tasks.md` marks all verification tasks complete. This overstates sign-off against the plan.

### Medium

[M-001] (45) — Automated audit table no longer preserves manual-pending status for 3.3 and 3.5

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 4 Step 2 lines 282-284

Location: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:38`

Reproduced in: R2-Pass2

Detail: Task 4 Step 2 instructs the report to set 3.1, 3.2, and 3.4 to PASS with new test names, while keeping 3.3 and 3.5 as `PARTIAL (manual pending)`. The current Automated Audit table marks 3.3 and 3.5 as PASS and cites operator manual checks in the automated table, blurring the plan's automated/manual separation.

[M-002] (42) — Non-Windows skip path fails before skip decorators can run

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 0 Step 1 lines 42-57, Task 2 Step 1 line 143, Grill-Me Pass 2 non-Windows CI decision

Location: `app/utils/logging_setup.py:4`, `tests/test_logging_setup.py:13`

Reproduced in: R1-Pass3

Detail: The plan allows lock/claim tests to skip outside Windows, but `app.utils.logging_setup` imports `msvcrt` at module import time and `tests/test_logging_setup.py` imports that module before any `@unittest.skipUnless(sys.platform == "win32", ...)` decorators apply. On non-Windows, collection fails with `ModuleNotFoundError` instead of producing the planned skips.

### Low

[L-001] (24) — Open Logs Folder evidence omits the required `error.log` visibility check

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 5 Step 6 lines 358-365

Location: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:84`

Reproduced in: R1-Pass1

Detail: The plan requires confirming Explorer opens the logs directory and that `error.log` is visible in that folder. The report records that Explorer opened `%APPDATA%\SpellScribe\logs`, but it does not record the required `error.log` visibility confirmation.

[L-002] (23) — Required final/manual commit steps are still deferred or incomplete

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 5 Step 8 lines 383-388, Task 6 Step 3 lines 427-430

Location: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:94`, `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md:427`

Reproduced in: R2-Pass1, R3-Pass2

Detail: Earlier commit steps explicitly say the operator may defer git commits, but Task 5 Step 8 and Task 6 Step 3 are written as required commit steps. The verification report notes Task 5 Step 8 was intentionally deferred, and the plan still shows Task 6 Step 3 unchecked.

[L-003] (21) — Verification report cites a proxy script that is not present

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Task 5 Step 7 lines 367-381

Location: `docs/superpowers/plans/2026-05-29-add-file-logging-verification-report.md:86`

Reproduced in: R3-Pass1

Detail: The report cites `scripts/task5_manual_verification_proxy.py` as passing evidence for 3.1-3.4, but `rg --files scripts` returned no script files. Even if proxy evidence were acceptable, the cited evidence is not reproducible from the current workspace.

[L-004] (18) — UTC timestamp behavior is asserted only by timestamp shape

Plan ref: `docs/superpowers/plans/2026-05-29-add-file-logging-verification.md` Design Guardrail line 29, Task 5 Step 2 lines 317-321

Location: `tests/test_logging_setup.py:263`, `tests/test_ui_main_window.py:578`

Reproduced in: R2-Pass3

Detail: The tests assert the log timestamp format, thread name, logger name, level, and message, but they do not assert that the timestamp uses UTC rather than local time. The implementation currently uses `time.gmtime`, so this is a verification gap rather than a known behavior bug.

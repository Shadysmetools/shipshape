# Bug log (failing-then-passing proof)

Every fix gets a regression test that is RED before the fix and GREEN after. Push the test-only commit first (red build), then the fix (green build). Report each build as "N tests, M failed" from the build log, not the badge.

| # | Bug | Impact | Test (file::name) | Before build (N tests, M failed) | After build (N tests, M failed) | Commit(s) |
|---|---|---|---|---|---|---|
| 1 | <what was wrong> | <who it hurt> | tests/test_x.py::test_y | 120 tests, 1 failed | 121 tests, 0 failed | <test sha>, <fix sha> |

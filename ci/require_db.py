"""Pytest plugin for CI: a database test that skips is a failure.

backend/tests/platform skips itself when no Postgres is reachable, which keeps
the suite usable offline. In CI that same skip would turn a broken database
service into a green build, so CI loads this plugin:

    python -m pytest -p ci.require_db

and the run fails if any platform test skipped, or if none ran at all.
Nothing else in the suite is affected; this file is not a conftest and is only
active when named with -p.
"""

import pytest

PLATFORM = "backend/tests/platform/"

_ran = 0
_skipped = []


def pytest_runtest_logreport(report):
    global _ran
    if not report.nodeid.startswith(PLATFORM):
        return
    if report.skipped:
        # A skip raised in setup (the `database` fixture) is reported there.
        reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        _skipped.append((report.nodeid, reason))
    elif report.when == "call":
        _ran += 1


def pytest_terminal_summary(terminalreporter):
    if _skipped:
        terminalreporter.section("require_db: platform tests skipped", red=True)
        for nodeid, reason in _skipped[:20]:
            terminalreporter.write_line("SKIPPED %s: %s" % (nodeid, reason))
        if len(_skipped) > 20:
            terminalreporter.write_line("... and %d more" % (len(_skipped) - 20))
    elif _ran == 0:
        terminalreporter.section("require_db: no platform tests ran", red=True)
    else:
        terminalreporter.write_line("require_db: %d platform tests ran against Postgres" % _ran)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _skipped or _ran == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED

import datetime as dt
import unittest
from unittest import mock

from bridge import health as h

N = lambda *a: dt.datetime(2026, 11, 2, *a)
SCHED = {"Hour": 22, "Minute": 0}


class Health(unittest.TestCase):
    def test_parse_exit(self):
        self.assertEqual(h.parse_exit("\tlast exit code = 0\n"), 0)
        self.assertEqual(h.parse_exit("last exit code = 78"), 78)
        self.assertIsNone(h.parse_exit("\tlast exit code = (never exited)"))
        self.assertIsNone(h.parse_exit(""))

    def test_parse_state(self):
        self.assertEqual(h.parse_state("\tstate = not running\n"), "not running")
        self.assertEqual(h.parse_state("\tstate = running\n"), "running")

    def test_nonzero_exit(self):
        self.assertEqual(h.judge(3, "not running", False, SCHED, N(22), N(22, 30)), (False, "exit 3"))

    def test_missed_after_grace(self):
        # 00:30 next day: slot before (now-2h) is 22:00 on the 2nd; last run was the day before
        now = dt.datetime(2026, 11, 3, 0, 30)
        ok, d = h.judge(0, "not running", False, SCHED, N(6), now)
        self.assertEqual((ok, d), (False, "missed 22:00 run"))

    def test_not_missed_within_grace(self):
        ok, _ = h.judge(0, "not running", False, SCHED, dt.datetime(2026, 11, 1, 22), N(23))
        self.assertTrue(ok)

    def test_ran_ok(self):
        ok, _ = h.judge(0, "not running", False, SCHED, N(22, 1), dt.datetime(2026, 11, 3, 0, 30))
        self.assertTrue(ok)

    def test_no_logs_after_grace(self):
        self.assertFalse(h.judge(None, None, False, SCHED, None, dt.datetime(2026, 11, 3, 1))[0])

    def test_keepalive(self):
        self.assertTrue(h.judge(None, "running", True, None, None, N(1))[0])
        self.assertFalse(h.judge(None, "not running", True, None, None, N(1))[0])

    def test_not_loaded_and_errors(self):
        with mock.patch.object(h, "_print", return_value=(113, "")):
            r = h.health(N(12))
            self.assertTrue(r and all(j["detail"] == "not loaded" and not j["ok"] for j in r))
        with mock.patch.object(h, "_print", side_effect=OSError):
            self.assertTrue(all(not j["ok"] for j in h.health(N(12))))


if __name__ == "__main__":
    unittest.main()


class WatchPathsJob(unittest.TestCase):
    """aos-library: no schedule, not KeepAlive. Never ran or last exit 0 is fine; non-zero is not."""
    def test_never_ran_or_exit_zero_ok(self):
        self.assertTrue(h.judge(None, "not running", False, None, None, N(12))[0])
        self.assertTrue(h.judge(0, "not running", False, None, N(11), N(12))[0])

    def test_nonzero_fails(self):
        self.assertEqual(h.judge(1, "not running", False, None, N(11), N(12)), (False, "exit 1"))

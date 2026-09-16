"""Event spine tests."""
import unittest

from orca.core.events import Bus, EKind, Recorder


class TestBus(unittest.TestCase):
    def test_subscribers_see_every_event_in_order(self):
        bus = Bus()
        seen = []
        bus.subscribe(lambda e: seen.append(e.kind))
        bus.subscribe(lambda e: seen.append(e.kind))
        bus.emit(EKind.turn_start)
        bus.emit(EKind.text, text="hi")
        self.assertEqual(seen, [EKind.turn_start, EKind.turn_start,
                                EKind.text, EKind.text])

    def test_emit_returns_the_event(self):
        bus = Bus()
        event = bus.emit(EKind.tool_start, tool="bash", summary="ls")
        self.assertEqual(event.kind, EKind.tool_start)
        self.assertEqual(event.data["tool"], "bash")

    def test_recorder_filters_by_kind(self):
        rec = Recorder()
        bus = Bus()
        bus.subscribe(rec)
        bus.emit(EKind.text, text="a")
        bus.emit(EKind.error, message="b")
        self.assertEqual([e.kind for e in rec.of(EKind.error)], [EKind.error])
        self.assertEqual(rec.events[1].data["message"], "b")


if __name__ == "__main__":
    unittest.main()

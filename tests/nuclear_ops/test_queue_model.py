import tempfile
import unittest
from pathlib import Path

from qudi.logic.nuclear_ops.queue_model import ExperimentQueue, QueueStatus

from .helpers import experiment_spec


class ExperimentQueueTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "queue.h5"
        self.queue = ExperimentQueue.create(self.path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_sequential_transitions_are_persisted(self):
        first = self.queue.enqueue(experiment_spec("first"))
        second = self.queue.enqueue(experiment_spec("second"))

        claimed = self.queue.claim_next()
        self.assertEqual(claimed.item_id, first.item_id)
        self.queue.mark_running(first.item_id, run_file="first.h5")
        self.queue.mark_completed(first.item_id, run_file="first.h5")

        claimed = self.queue.claim_next()
        self.assertEqual(claimed.item_id, second.item_id)

        reopened = ExperimentQueue.open(self.path)
        self.assertEqual(reopened.get(first.item_id).status, QueueStatus.COMPLETED)
        self.assertEqual(reopened.get(second.item_id).status, QueueStatus.PREPARING)

    def test_queue_pause_prevents_claiming(self):
        self.queue.enqueue(experiment_spec())
        self.queue.set_paused(True)
        self.assertIsNone(self.queue.claim_next())
        self.queue.set_paused(False)
        self.assertIsNotNone(self.queue.claim_next())

    def test_only_pending_items_can_be_moved_or_removed(self):
        first = self.queue.enqueue(experiment_spec("first"))
        second = self.queue.enqueue(experiment_spec("second"))
        self.queue.move_pending(second.item_id, 0)
        self.assertEqual(self.queue.items[0].item_id, second.item_id)
        active = self.queue.claim_next()

        with self.assertRaisesRegex(ValueError, "pending"):
            self.queue.remove_pending(active.item_id)
        removed = self.queue.remove_pending(first.item_id)
        self.assertEqual(removed.item_id, first.item_id)

    def test_interrupted_run_is_marked_failed(self):
        item = self.queue.enqueue(experiment_spec())
        self.queue.claim_next()
        self.queue.mark_running(item.item_id, run_file="partial.h5")

        reopened = ExperimentQueue.open(self.path)
        recovered = reopened.recover_incomplete(requeue=False)

        self.assertEqual(len(recovered), 1)
        self.assertEqual(reopened.get(item.item_id).status, QueueStatus.FAILED)
        self.assertIn("stopped", reopened.get(item.item_id).error)

    def test_interrupted_run_can_be_explicitly_requeued(self):
        item = self.queue.enqueue(experiment_spec())
        self.queue.claim_next()

        reopened = ExperimentQueue.open(self.path)
        reopened.recover_incomplete(requeue=True)

        self.assertEqual(reopened.get(item.item_id).status, QueueStatus.PENDING)
        self.assertEqual(reopened.claim_next().item_id, item.item_id)

    def test_stop_on_failure_policy(self):
        queue_path = Path(self.temporary_directory.name) / "stop_queue.h5"
        queue = ExperimentQueue.create(queue_path, continue_on_failure=False)
        first = queue.enqueue(experiment_spec("first"))
        queue.enqueue(experiment_spec("second"))
        queue.claim_next()
        queue.mark_failed(first.item_id, "test failure")

        self.assertIsNone(queue.claim_next())


if __name__ == "__main__":
    unittest.main()

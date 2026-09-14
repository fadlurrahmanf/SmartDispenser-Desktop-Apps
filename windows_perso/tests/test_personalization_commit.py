import unittest

from app import PersoApp


class _Value:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class _Button:
    def __init__(self):
        self.options = {}

    def configure(self, **options):
        self.options.update(options)


class _Cursor:
    def __init__(self, fetch_results):
        self.fetch_results = list(fetch_results)
        self.executed = []
        self.rowcount = 0

    def execute(self, sql, parameters=()):
        self.executed.append((sql, parameters))
        self.rowcount = 1 if sql.startswith("UPDATE personalization_runs") else 0

    def fetchone(self):
        return self.fetch_results.pop(0)

    def close(self):
        pass


class _Database:
    def __init__(self, fetch_results):
        self.cursor_instance = _Cursor(fetch_results)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class PersonalizationCommitTests(unittest.TestCase):
    def test_session_gate_repeatedly_clears_stale_reader_modes(self):
        events = []

        class Dummy:
            recover_session_open_reader_mode = PersoApp.recover_session_open_reader_mode
            dashboard_ready = False
            startup_phase = "session_open"
            last_session_open = False
            session_gate_recovery_after = None

            def send(self, command, **parameters):
                events.append(("send", command))

            def after(self, delay, callback):
                events.append(("after", delay, callback.__name__))
                return "timer-1"

        app = Dummy()
        PersoApp.recover_session_open_reader_mode(app)

        self.assertEqual(
            events[:3],
            [("send", "card_test_stop"), ("send", "owner_lookup_stop"), ("send", "status_request")],
        )
        self.assertEqual(events[3], ("after", 900, "recover_session_open_reader_mode"))
        self.assertEqual(app.session_gate_recovery_after, "timer-1")

    def test_database_reservation_is_committed_as_pending_before_card_write(self):
        database = _Database([None, None])

        class Dummy:
            active_run_id = "run-1"
            active_run_customer_id = 7
            active_card_reference = 24
            active_run_card_session = 88
            selected_customer_card_status = _Value()

        app = Dummy()
        app.database = database
        result = PersoApp.reserve_personalization_ownership(app)

        self.assertTrue(result)
        self.assertEqual(database.commits, 1)
        self.assertEqual(database.rollbacks, 0)
        statements = [sql for sql, _ in database.cursor_instance.executed]
        pending_index = next(i for i, sql in enumerate(statements) if "INSERT INTO customer_cards" in sql and "'pending_write'" in sql)
        run_index = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE personalization_runs"))
        self.assertLess(pending_index, run_index)
        self.assertEqual(Dummy.selected_customer_card_status.value, "Card: RESERVED · CARD-00000018")

    def test_commit_arms_database_and_ui_before_sending(self):
        events = []

        class Dummy:
            wallet_slot_action = "confirm"
            active_run_id = "run-1"
            active_run_customer_id = 7
            selected_customer_id = 7
            active_card_reference = 24
            technical_reset_token = 11
            wallet_slot_button = _Button()
            debug_status = _Value()

            def refresh_selected_customer_card_status(self):
                return False

            def reserve_personalization_ownership(self):
                events.append(("database_reservation", self.wallet_slot_action))
                return True

            def reset_personalization_process(self):
                events.append(("reset",))

            def set_personalization_process_step(self, step, passed):
                events.append(("step", step, passed))

            def send(self, command, **parameters):
                events.append(("send", command, parameters, self.wallet_slot_action))

            def after(self, delay, callback):
                events.append(("after", delay))

        app = Dummy()
        result = PersoApp.begin_personalization_commit(app)

        self.assertTrue(result)
        self.assertEqual(app.wallet_slot_action, "writing")
        self.assertEqual(app.personalization_active_step, 1)
        self.assertEqual(app.wallet_slot_button.options["state"], "disabled")
        self.assertEqual(events[0], ("database_reservation", "confirm"))
        self.assertIn(("step", 1, True), events)
        self.assertIn(("send", "perso_commit", {"card_reference": 24}, "writing"), events)

    def test_commit_never_sends_when_database_reservation_fails(self):
        events = []

        class Dummy:
            wallet_slot_action = "confirm"
            active_run_id = "run-1"
            active_run_customer_id = 7
            selected_customer_id = 7
            active_card_reference = 24

            def refresh_selected_customer_card_status(self):
                return False

            def reserve_personalization_ownership(self):
                events.append("database_failed")
                return False

            def send(self, command, **parameters):
                events.append("card_write_sent")

        result = PersoApp.begin_personalization_commit(Dummy())

        self.assertFalse(result)
        self.assertEqual(events, ["database_failed"])

    def test_remove_arms_board_review_before_removing(self):
        events = []

        class Dummy:
            last_session_open = True
            debug_card_present = True
            wallet_slot_state = "already_used"
            wallet_slot_action = ""
            debug_status = _Value()
            debug_last_event = _Value()

            def send(self, command, **parameters):
                events.append(("send", command, parameters))

            def after(self, delay, callback):
                events.append(("after", delay))

        app = Dummy()
        PersoApp.begin_remove_personalization(app)

        self.assertEqual(app.wallet_slot_action, "remove_arming")
        self.assertEqual(app.remove_request_token, 1)
        self.assertEqual(events[0], ("send", "perso_arm", {}))
        self.assertIn(("after", 6500), events)


if __name__ == "__main__":
    unittest.main()

import unittest

from perso_core import ProtocolError, PersoSimulator, decode_frames, decode_frames_resilient, encode_frame, encode_stm32_compact_commit, is_perso_ready, request


class FrameTests(unittest.TestCase):
    def test_stm32_compact_commit_carries_uint32_reference(self):
        self.assertEqual(encode_stm32_compact_commit(0x1234ABCD), b"!P1234ABCD\n")

    def test_request_can_carry_compact_card_reference(self):
        self.assertEqual(
            request("perso_commit", card_reference=0x12345678),
            {"v": 1, "type": "perso_commit", "card_reference": 0x12345678},
        )

    def test_round_trip(self):
        buffer = bytearray(encode_frame(request("status_request")))
        self.assertEqual(decode_frames(buffer)[0]["type"], "status_request")
        self.assertFalse(buffer)

    def test_rejects_invalid_length(self):
        with self.assertRaises(ProtocolError):
            decode_frames(bytearray(b"\x01\x01{}"))

    def test_rejects_wrong_protocol_version(self):
        with self.assertRaises(ProtocolError):
            decode_frames(bytearray(encode_frame({"v": 99, "type": "status_request"})))

    def test_accepts_only_explicit_perso_handshake(self):
        self.assertTrue(is_perso_ready({"v": 1, "profile": "smartdispenser_perso", "card_format": "compact_v1", "type": "status", "code": "perso_ready"}))
        self.assertFalse(is_perso_ready({"v": 1, "profile": "smartdispenser_perso", "type": "status", "code": "perso_ready"}))
        self.assertFalse(is_perso_ready({"v": 1, "type": "status", "code": "ready"}))
        self.assertFalse(is_perso_ready({"v": 1, "profile": "smartdispenser_topup", "type": "status", "code": "perso_ready"}))

    def test_resilient_decoder_skips_esp_boot_text(self):
        response = {"v": 1, "profile": "smartdispenser_perso", "card_format": "compact_v1", "type": "status", "code": "perso_ready"}
        buffer = bytearray(b"ets Jul 29 2019\r\n")
        buffer.extend(encode_frame(response))
        self.assertEqual(decode_frames_resilient(buffer), [response])
        self.assertFalse(buffer)


class SimulationTests(unittest.TestCase):
    def test_perso_requires_session_and_blank_card(self):
        sim = PersoSimulator()
        self.assertEqual(sim.send(request("perso_arm"))[0]["type"], "error")
        sim.send(request("register_master_begin"))
        sim.present_card()
        sim.send(request("register_master_commit"))
        sim.send(request("perso_arm"))
        events = sim.present_card("blank")
        self.assertEqual(events[-1]["code"], "blank")
        self.assertEqual(sim.send(request("perso_commit"))[-1]["code"], "perso_success")

    def test_session_lock_requires_a_new_master_session(self):
        sim = PersoSimulator(master_registered=True, session_open=True)
        event = sim.send(request("session_lock"))[0]
        self.assertEqual(event["code"], "session_locked")
        self.assertFalse(event["session_open"])
        self.assertEqual(sim.send(request("perso_arm"))[0]["code"], "command_not_allowed")

    def test_technical_scan_requires_open_session_and_card(self):
        sim = PersoSimulator(master_registered=True, session_open=True)
        self.assertEqual(sim.send(request("technical_scan"))[0]["type"], "error")
        sim.present_card("blank")
        self.assertEqual(sim.send(request("technical_scan"))[0]["code"], "scan_started")

    def test_rejects_existing_card(self):
        sim = PersoSimulator(master_registered=True, session_open=True)
        sim.send(request("perso_arm"))
        events = sim.present_card("already_personalized")
        self.assertEqual(events[-1]["code"], "already_personalized")
        self.assertEqual(sim.send(request("perso_commit"))[0]["type"], "error")

    def test_remove_personalization_preserves_wallet_state(self):
        sim = PersoSimulator(master_registered=True, session_open=True)
        sim.send(request("perso_arm"))
        sim.present_card("already_personalized")
        events = sim.send(request("perso_remove"))
        self.assertEqual(
            [event["code"] for event in events],
            ["remove_metadata", "verify_removed", "perso_removed"],
        )
        self.assertEqual(events[-1]["card_reference"], 297)
        self.assertEqual(sim.precheck, "legacy_personalized")

    def test_full_perso_flow_has_all_verification_steps(self):
        sim = PersoSimulator()
        sim.send(request("register_master_begin"))
        sim.present_card("master_candidate")
        self.assertEqual(sim.send(request("register_master_commit"))[-1]["code"], "master_registered")
        sim.remove_card()
        sim.send(request("perso_arm"))
        sim.present_card("blank")
        events = sim.send(request("perso_commit"))
        self.assertEqual(
            [event["code"] for event in events],
            ["start", "write_protection", "write_wallet", "verify_wallet", "perso_success"],
        )

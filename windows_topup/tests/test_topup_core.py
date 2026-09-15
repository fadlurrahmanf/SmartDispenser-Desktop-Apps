import unittest
import tempfile
import json
import topup_core
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from topup_core import (MySqlStore, ProtocolError, SerialReaderAdapter, SimulationReader, TopupError, Wallet, backup_mysql,
                        canonical_card_reference, decode_frame, encode_frame, hash_pin)
from app_perso_style import TopupConsole, topup_candidate_ports


class FakeSerial:
 def __init__(self,lines): self.lines=list(lines);self.timeout=.25;self.is_open=True;self.written=b""
 def reset_input_buffer(self): pass
 def write(self,value): self.written=value
 def flush(self): pass
 def readline(self): return self.lines.pop(0) if self.lines else b""


class TopupCoreTest(unittest.TestCase):
 def test_port_discovery_tries_every_non_bluetooth_com_with_usb_first(self):
  ports=[
   SimpleNamespace(device="COM8",description="Standard Serial over Bluetooth link",hwid="BTHENUM\\x"),
   SimpleNamespace(device="COM7",description="Legacy communications port",hwid="ACPI\\PNP0501"),
   SimpleNamespace(device="COM12",description="USB Serial Device",hwid="USB VID:PID=1234:5678"),
   SimpleNamespace(device="COM3",description="USB-SERIAL CH340",hwid="USB VID:PID=1A86:7523"),
  ]
  self.assertEqual([port.device for port in topup_candidate_ports(ports)],["COM12","COM3","COM7"])
 def test_port_discovery_skips_wrong_bridge_and_accepts_expected_response(self):
  ports=[
   SimpleNamespace(device="COM4",description="USB Serial Device",hwid="USB one"),
   SimpleNamespace(device="COM5",description="USB Serial Device",hwid="USB two"),
  ]
  instances=[]
  class Candidate:
   def __init__(self,port): self.port=port;self.closed=False;instances.append(self)
   def connect(self):
    if self.port=="COM4": raise TopupError("Bridge alat Topup tidak sesuai")
   def close(self): self.closed=True
  with patch("serial.tools.list_ports.comports",return_value=ports),patch("app_perso_style.SerialReaderAdapter",side_effect=Candidate):
   reader,port=TopupConsole._find_topup_board()
  self.assertEqual((reader.port,port),("COM5","COM5"))
  self.assertTrue(instances[0].closed)
 def test_frame_round_trip(self):
  self.assertEqual(decode_frame(encode_frame({"v": 1, "type": "hello"}))["type"], "hello")
  with self.assertRaises(ProtocolError): decode_frame(b"\x00\x02{}")
 def test_simulation_idempotent_mutation(self):
  reader=SimulationReader(); reader.present(balance=20); reader.unlock_master()
  first=reader.mutate("operation-1", "balance_adjust", 10); again=reader.mutate("operation-1", "balance_adjust", 10)
  self.assertEqual(first.balance,30); self.assertEqual(again.balance,30); self.assertEqual(first.card_reference,"CARD-00000001")
 def test_card_reference_is_canonical_and_not_a_uid_token(self):
  self.assertEqual(canonical_card_reference("a1b2c3d4"),"CARD-A1B2C3D4")
  with self.assertRaises(ProtocolError): canonical_card_reference("SIM-CARD-01")
 def test_bridge_wallet_uses_verified_card_reference(self):
  adapter=SerialReaderAdapter("COM3")
  adapter.serial=FakeSerial([b"RES R OK reference=0000001F balance=20 active=1 schedule=1 used=0 reserved=0 legacy=0 revision=2\r\n"])
  wallet=adapter.read_wallet()
  self.assertEqual(wallet.card_reference,"CARD-0000001F")
 def test_simulation_refuses_over_limit(self):
  reader=SimulationReader(); reader.present(balance=100); reader.unlock_master()
  with self.assertRaises(TopupError): reader.mutate("operation-2", "balance_adjust", 10)
 def test_pin_hash_is_repeatable_with_same_salt(self):
  salt,digest=hash_pin("123456"); self.assertEqual(digest,hash_pin("123456",salt)[1])
 def test_backup_does_not_put_password_in_command(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary); executable=root/"mysqldump.exe"; executable.write_bytes(b"")
   secret="do-not-display-this-password"
   config={"mysqldump":str(executable),"host":"127.0.0.1","port":3306,"app_user":"sd_topup_app","app_password":secret}
   with patch("topup_core.APP_DIR",root),patch("topup_core.subprocess.run",return_value=SimpleNamespace(returncode=0)) as runner:
    backup_mysql(config)
   command=runner.call_args.args[0]
   self.assertNotIn(secret," ".join(command))
   self.assertEqual(runner.call_args.kwargs["env"]["MYSQL_PWD"],secret)
 def test_bridge_request_ignores_startup_banner(self):
  adapter=SerialReaderAdapter("COM3");request_id="operation-1"
  adapter.serial=FakeSerial([b"TOPUP BRIDGE V1 READY\r\n",b"noise\r\n",b"RES H OK bridge=topup-v1\r\n"])
  result=adapter._request("hello",{"operation_id":request_id},.2)
  self.assertEqual(result["bridge"],"topup-v1")
 def test_master_enrollment_uses_perso_style_state_machine(self):
  adapter=SerialReaderAdapter("COM3")
  adapter.serial=FakeSerial([
   b"RES E OK state=waiting\r\n",
   b"RES Q OK state=holding\r\n",
   b"RES Q OK state=ready\r\n",
   b"RES C OK master=enrolled\r\n",
  ])
  with patch("topup_core.time.sleep",return_value=None): adapter.enroll_master()
  self.assertTrue(adapter.master_unlocked)
 def test_master_enrollment_exposes_perso_style_stages(self):
  adapter=SerialReaderAdapter("COM3")
  adapter.serial=FakeSerial([
   b"RES E OK state=waiting\r\n",
   b"RES Q OK state=holding\r\n",
   b"RES C OK master=enrolled\r\n",
  ])
  self.assertEqual(adapter.begin_master_enrollment()["state"],"waiting")
  self.assertEqual(adapter.master_enrollment_status()["state"],"holding")
  self.assertEqual(adapter.commit_master_enrollment()["master"],"enrolled")
  self.assertTrue(adapter.master_unlocked)
 def test_session_lock_uses_compact_bridge_command(self):
  adapter=SerialReaderAdapter("COM3")
  adapter.master_unlocked=True
  adapter.serial=FakeSerial([b"RES L OK master=locked\r\n"])
  adapter.lock_session()
  self.assertFalse(adapter.master_unlocked)
 def test_card_test_uses_dedicated_presence_protocol(self):
  adapter=SerialReaderAdapter("COM3")
  adapter.serial=FakeSerial([
   b"RES Y OK state=ready present=0 detections=0\r\n",
   b"RES T OK state=active present=1 detections=1\r\n",
   b"RES Z OK state=stopped\r\n",
  ])
  self.assertEqual(adapter.start_card_test()["state"],"ready")
  self.assertTrue(adapter.card_test_status())
  self.assertEqual(adapter.stop_card_test()["state"],"stopped")
 def test_async_card_events_are_separate_from_command_responses(self):
  adapter=SerialReaderAdapter("COM3")
  adapter._dispatch_line("EVT card detected")
  self.assertEqual(adapter.next_event(),{"scope":"card","state":"detected"})
  adapter._dispatch_line("EVT card_test removed")
  self.assertEqual(adapter.next_event(),{"scope":"card_test","state":"removed"})
 def test_async_master_session_event_is_available_to_startup_ui(self):
  adapter=SerialReaderAdapter("COM3")
  adapter._dispatch_line("EVT master session_opened")
  self.assertEqual(adapter.next_event(),{"scope":"master","state":"session_opened"})
 def test_quota_overview_normalizes_database_rows_for_three_schedules(self):
  class Cursor:
   def __init__(self): self.sqls=[]
   def execute(self,sql,*args): self.sqls.append(sql)
   def fetchall(self):
    return [
      {"schedule":0,"card_count":2,"available_liter":12,"used_liter":1,"reserved_liter":0,"last_seen_at":None},
      {"schedule":1,"card_count":3,"available_liter":60,"used_liter":15,"reserved_liter":5,"last_seen_at":None},
      {"schedule":3,"card_count":1,"available_liter":20,"used_liter":10,"reserved_liter":0,"last_seen_at":None},
     ]
   def fetchone(self): return {"config_value":"120"}
   def close(self): pass
  class Database:
   def __init__(self): self.cursor_value=Cursor()
   def cursor(self,dictionary=False): return self.cursor_value
   def close(self): pass
  database=Database();store=MySqlStore({})
  with patch.object(store,"_connect",return_value=database): result=store.quota_overview()
  self.assertTrue(any("FROM card_wallet_state" in sql for sql in database.cursor_value.sqls))
  self.assertTrue(any("FROM app_config" in sql and "CURRENT_DATE" in sql for sql in database.cursor_value.sqls))
  self.assertEqual([row["label"] for row in result["schedules"]],["Pagi","Siang","Sore"])
  self.assertEqual(result["available_liter"],80)
  self.assertEqual(result["used_liter"],25)
  self.assertEqual(result["card_count"],4)
  self.assertEqual(result["unscheduled_cards"],2)
  self.assertEqual(result["quota_limit_liter"],120)
  self.assertEqual(result["allocated_liter"],92)
  self.assertEqual(result["remaining_liter"],28)
  self.assertEqual([row["distributed_liter"] for row in result["schedules"]],[60,0,20])
 def test_schema_contains_database_backed_wallet_snapshot(self):
  schema=Path(__file__).resolve().parents[1].joinpath("schema.sql").read_text(encoding="utf-8")
  self.assertIn("CREATE TABLE IF NOT EXISTS card_wallet_state",schema)
  self.assertIn("idx_wallet_state_active_schedule",schema)
  self.assertIn("CREATE TABLE IF NOT EXISTS app_config",schema)
 def test_distribution_quota_is_saved_for_current_date(self):
  store=MySqlStore({})
  cursor=MagicMock();database=MagicMock();database.cursor.return_value=cursor
  with patch.object(store,"quota_overview",return_value={"distributed_today_liter":100}),patch.object(store,"_connect",return_value=database):self.assertEqual(store.set_distribution_quota("250"),250)
  self.assertIn("INSERT INTO app_config",cursor.execute.call_args.args[0])
  self.assertIn("CURRENT_DATE",cursor.execute.call_args.args[0])
  self.assertEqual(cursor.execute.call_args.args[1],("250",))
 def test_distribution_quota_rejects_invalid_value(self):
  store=MySqlStore({})
  for value in (None,"",0,-1,1000000):
   with self.subTest(value=value),self.assertRaises(TopupError):store.set_distribution_quota(value)
 def test_distribution_quota_cannot_be_lower_than_today_distribution(self):
  store=MySqlStore({})
  with patch.object(store,"quota_overview",return_value={"distributed_today_liter":40}):
   with self.assertRaisesRegex(TopupError,"40 L yang sudah didistribusikan"):
    store.set_distribution_quota(30)
 def test_saved_config_protects_app_password_and_operator_pin(self):
  with tempfile.TemporaryDirectory() as directory:
   def fake_dpapi(value,protect,machine=False):return b"protected:"+value if protect else value.removeprefix(b"protected:")
   config={"host":"127.0.0.1","port":3306,"admin_user":"root","admin_password":"not-saved","app_user":"sd_topup_app","app_password":"app-secret","operator_pin":"202610"}
   with patch.object(topup_core,"APP_DIR",Path(directory)),patch.object(topup_core,"MACHINE_CONFIG_PATH",Path(directory,"missing-machine-config.json")),patch.object(topup_core,"_dpapi",side_effect=fake_dpapi):
    topup_core.save_config(config)
    raw=json.loads(Path(directory,"config.json").read_text(encoding="utf-8"))
    self.assertNotIn("admin_password",raw);self.assertNotIn("app_password",raw);self.assertNotIn("operator_pin",raw)
    loaded=topup_core.load_config()
   self.assertEqual(loaded["app_password"],"app-secret")
   self.assertEqual(loaded["operator_pin"],"202610")
 def test_machine_config_is_preferred_over_stale_user_config(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);machine=root/"machine.json";user_dir=root/"user";user_dir.mkdir()
   machine.write_text(json.dumps({"host":"127.0.0.1","port":3306,"admin_user":"root","app_user":"sd_topup_app","scope":"machine","app_secret":"bWFjaGluZQ==","operator_pin_secret":"cGlu"}),encoding="utf-8")
   (user_dir/"config.json").write_text(json.dumps({"host":"stale","port":3306,"app_user":"stale","app_secret":"c3RhbGU="}),encoding="utf-8")
   with patch.object(topup_core,"MACHINE_CONFIG_PATH",machine),patch.object(topup_core,"APP_DIR",user_dir),patch.object(topup_core,"_dpapi",side_effect=lambda value,protect,machine=False:value):
    loaded=topup_core.load_config()
   self.assertEqual(loaded["app_user"],"sd_topup_app")
   self.assertEqual(loaded["app_password"],"machine")
   self.assertEqual(loaded["operator_pin"],"pin")
 def test_positive_topup_cannot_exceed_distribution_quota(self):
  store=MySqlStore({})
  overview={"quota_configured":True,"allocated_liter":95,"quota_limit_liter":100}
  with patch.object(store,"quota_overview",return_value=overview):
   with self.assertRaisesRegex(TopupError,"melebihi batas 100 L"):
    store.validate_distribution_quota(Wallet("CARD-00000001",20,True,1),"balance_adjust",10)
 def test_reduction_does_not_require_distribution_quota(self):
  store=MySqlStore({})
  with patch.object(store,"quota_overview") as overview:
   store.validate_distribution_quota(Wallet("CARD-00000001",20,True,1),"balance_adjust",-10)
  overview.assert_not_called()
 def test_customer_card_removal_clears_wallet_and_returns_home(self):
  calls=[]
  app=SimpleNamespace(wallet=object(),current_customer={"unused":True},current_page="topup",status=SimpleNamespace(set=lambda value:calls.append(("status",value))),_render_wallet=lambda:calls.append(("render",None)),show_page=lambda page:calls.append(("page",page)))
  TopupConsole._customer_card_removed(app)
  self.assertIsNone(app.wallet);self.assertIsNone(app.current_customer)
  self.assertIn(("page","dashboard"),calls)
 def test_card_test_start_retries_a_dropped_ack_four_times(self):
  adapter=SerialReaderAdapter("COM3")
  timeout=TopupError("Respons Topup Board tidak diterima")
  with patch.object(adapter,"_request",side_effect=[timeout,timeout,timeout,{"state":"ready"}]) as request:
   self.assertEqual(adapter.start_card_test()["state"],"ready")
  self.assertEqual(request.call_count,4)
 def test_customer_watch_start_retries_a_dropped_ack_four_times(self):
  adapter=SerialReaderAdapter("COM3")
  timeout=TopupError("Respons Topup Board tidak diterima")
  with patch.object(adapter,"_request",side_effect=[timeout,timeout,timeout,{"state":"ready"}]) as request:
   self.assertEqual(adapter.start_card_watch()["state"],"ready")
  self.assertEqual(request.call_count,4)
 def test_simulation_card_test_is_presence_only(self):
  reader=SimulationReader();reader.start_card_test()
  self.assertFalse(reader.card_test_status())
  reader.present();self.assertTrue(reader.card_test_status())
  reader.stop_card_test()
  with self.assertRaises(TopupError): reader.card_test_status()
 def test_test_card_status_fallback_updates_a_missed_event(self):
  calls=[]
  app=SimpleNamespace(card_test_polling=True,card_test_active=True,card_test_present=False,
   _card_test_event=lambda present:calls.append(("present",present)),
   _schedule_card_test_poll=lambda delay:calls.append(("poll",delay)))
  TopupConsole._card_test_status_result(app,True,None)
  self.assertFalse(app.card_test_polling)
  self.assertEqual(calls,[("present",True),("poll",50)])
 def test_customer_fallback_read_records_wallet_in_database(self):
  wallet=SimulationReader();wallet.present(reference="0000001F")
  current=wallet.read_wallet();calls=[]
  app=SimpleNamespace(reader=SimpleNamespace(read_wallet=lambda:current),operator_id=7,
   store=SimpleNamespace(sync_wallet_state=lambda value:calls.append(("sync",value.card_reference)),
    audit=lambda operator,event,reference,detail:calls.append(("audit",operator,event,reference))))
  result=TopupConsole._read_customer_wallet(app)
  self.assertEqual(result.card_reference,"CARD-0000001F")
  self.assertEqual(calls,[('sync','CARD-0000001F'),('audit',7,'wallet_read','CARD-0000001F')])
 def test_customer_absence_fallback_returns_from_topup_to_overview(self):
  calls=[]
  app=SimpleNamespace(customer_watch_polling=True,customer_watch_active=True,wallet=object(),
   _customer_card_removed=lambda:calls.append("removed"),
   _schedule_customer_watch=lambda delay=350:calls.append(("poll",delay)))
  TopupConsole._customer_watch_result(app,None,TopupError("card absent"))
  self.assertFalse(app.customer_watch_polling)
  self.assertEqual(calls,["removed"])
 def test_customer_presence_probe_does_not_duplicate_database_audit(self):
  reader=SimulationReader();current=reader.present(reference="00000020")
  app=SimpleNamespace(reader=SimpleNamespace(read_wallet=lambda:current),operator_id=7,
   store=SimpleNamespace(sync_wallet_state=lambda value:self.fail("unexpected sync"),
    audit=lambda *args:self.fail("unexpected audit")))
  self.assertEqual(TopupConsole._read_customer_wallet(app,record=False).card_reference,"CARD-00000020")
 def test_customer_watch_uses_direct_read_when_event_ack_is_missing(self):
  calls=[]
  app=SimpleNamespace(customer_watch_polling=True,customer_watch_active=True,
   customer_watch_started=False,customer_watch_probe_due=99.0,
   status=SimpleNamespace(set=lambda value:calls.append(("status",value))),
   _schedule_customer_watch=lambda delay:calls.append(("poll",delay)))
  TopupConsole._customer_watch_started(app,TopupError("Respons Topup Board tidak diterima"))
  self.assertFalse(app.customer_watch_polling)
  self.assertTrue(app.customer_watch_started)
  self.assertEqual(app.customer_watch_probe_due,0.0)
  self.assertEqual(calls[-1],("poll",80))

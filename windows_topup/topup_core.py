"""Domain EXE Topup: MySQL lokal, simulasi, dan bridge COM tingkat tinggi."""
from __future__ import annotations
import base64, ctypes, hashlib, json, os, queue, secrets, struct, subprocess, sys, threading, time, uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_FRAME=4096
APP_DIR=Path(os.environ.get("LOCALAPPDATA",Path.home()))/"SmartDispenserTopup"
PROVISION_FILE="topup.provisioning.json"

class TopupError(RuntimeError): pass
class ProtocolError(ValueError): pass
@dataclass(frozen=True)
class Wallet:
 card_reference:str; balance:int; active:bool; schedule:int=0; used_today:int=0; reserved:int=0; legacy:bool=False; revision:int=0

def canonical_card_reference(value:Any)->str:
 raw=str(value).strip().upper()
 if raw.startswith("CARD-"): raw=raw[5:]
 if len(raw)!=8 or any(ch not in "0123456789ABCDEF" for ch in raw):
  raise ProtocolError("Card Reference tidak sah")
 return f"CARD-{raw}"
# STM32 bridge tidak memakai UUID untuk keamanan; ID hanya mencocokkan respons.
# Delapan digit cukup dan menjaga request tetap pendek seperti command compact Perso.
def new_request_id(): return secrets.token_hex(4)
def encode_frame(message:dict[str,Any])->bytes:
 data=json.dumps(message,separators=(",",":"),ensure_ascii=True).encode();
 if not data or len(data)>MAX_FRAME: raise ProtocolError("frame tidak sah")
 return struct.pack(">H",len(data))+data
def decode_frame(frame:bytes)->dict[str,Any]:
 if len(frame)<3: raise ProtocolError("frame terlalu pendek")
 size=struct.unpack(">H",frame[:2])[0]
 if size!=len(frame)-2 or size>MAX_FRAME: raise ProtocolError("panjang frame tidak sah")
 value=json.loads(frame[2:].decode())
 if not isinstance(value,dict) or value.get("v")!=1: raise ProtocolError("versi bridge tidak sah")
 return value
def hash_pin(pin:str,salt:bytes|None=None):
 salt=salt or secrets.token_bytes(16); return salt,hashlib.pbkdf2_hmac("sha256",pin.encode(),salt,250000)
def wallet_from_dict(v:dict[str,Any])->Wallet:
 reference=v.get("card_reference",v.get("reference"))
 return Wallet(canonical_card_reference(reference),int(v["balance"]),bool(v["active"]),int(v.get("schedule",0)),int(v.get("used_today",0)),int(v.get("reserved",0)),bool(v.get("legacy",False)),int(v.get("revision",0)))

class _DataBlob(ctypes.Structure):
 _fields_=[("cbData",ctypes.c_ulong),("pbData",ctypes.POINTER(ctypes.c_byte))]
def _dpapi(value:bytes,protect:bool)->bytes:
 if os.name!="nt": raise TopupError("Penyimpanan kredensial hanya didukung pada Windows")
 raw=ctypes.create_string_buffer(value); source=_DataBlob(len(value),ctypes.cast(raw,ctypes.POINTER(ctypes.c_byte))); target=_DataBlob()
 crypt32=ctypes.windll.crypt32; kernel32=ctypes.windll.kernel32
 if protect: ok=crypt32.CryptProtectData(ctypes.byref(source),"SmartDispenser Topup",None,None,None,0,ctypes.byref(target))
 else: ok=crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,0,ctypes.byref(target))
 if not ok: raise TopupError("Windows gagal melindungi konfigurasi")
 try: return ctypes.string_at(target.pbData,target.cbData)
 finally: kernel32.LocalFree(target.pbData)
def save_config(config:dict[str,Any]):
 APP_DIR.mkdir(parents=True,exist_ok=True); public={k:v for k,v in config.items() if k not in ("admin_password","app_password","operator_pin")}; public["app_secret"]=base64.b64encode(_dpapi(config["app_password"].encode(),True)).decode()
 if config.get("operator_pin") is not None:public["operator_pin_secret"]=base64.b64encode(_dpapi(str(config["operator_pin"]).encode(),True)).decode()
 (APP_DIR/"config.json").write_text(json.dumps(public),encoding="utf-8")
def load_config()->dict[str,Any]|None:
 path=APP_DIR/"config.json"
 if not path.exists(): return None
 raw=json.loads(path.read_text(encoding="utf-8")); raw["app_password"]=_dpapi(base64.b64decode(raw.pop("app_secret")),False).decode()
 if "operator_pin_secret" in raw:raw["operator_pin"]=_dpapi(base64.b64decode(raw.pop("operator_pin_secret")),False).decode()
 return raw
def load_provisioning_config()->dict[str,Any]:
 base=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
 path=base/PROVISION_FILE
 if not path.exists(): raise TopupError(f"File konfigurasi tidak ditemukan: {PROVISION_FILE}")
 raw=json.loads(path.read_text(encoding="utf-8"))
 required=("host","port","admin_user","admin_password","operator_pin")
 if any(key not in raw for key in required): raise TopupError(f"Isi {PROVISION_FILE} tidak lengkap")
 if len(str(raw["operator_pin"]))<6: raise TopupError("PIN operator pada file konfigurasi minimal 6 digit")
 return raw

class SimulationReader:
 def __init__(self): self.wallet=None; self.master_unlocked=False; self.done={}; self.card_test_active=False; self.card_watch_active=False; self._events=queue.Queue()
 def enroll_master(self): self.master_unlocked=True
 def lock_session(self): self.master_unlocked=False
 def unlock_master(self): self.master_unlocked=True
 def present(self,reference="CARD-00000001",balance=20):
  self.wallet=Wallet(canonical_card_reference(reference),balance,True,schedule=1,revision=1);self._events.put({"scope":"card_test" if self.card_test_active else "card","state":"detected"});return self.wallet
 def remove(self):
  if self.wallet:self.wallet=None;self._events.put({"scope":"card_test" if self.card_test_active else "card","state":"removed"})
 def next_event(self):
  try:return self._events.get_nowait()
  except queue.Empty:return None
 def clear_events(self):
  while self.next_event() is not None:pass
 def read_wallet(self):
  if not self.wallet: raise TopupError("Tidak ada kartu")
  return self.wallet
 def start_card_test(self):
  self.card_test_active=True
  if self.wallet:self._events.put({"scope":"card_test","state":"detected"})
 def card_test_status(self):
  if not self.card_test_active: raise TopupError("Card Test belum dimulai")
  return self.wallet is not None
 def stop_card_test(self): self.card_test_active=False
 def start_card_watch(self):
  self.card_watch_active=True
  if self.wallet:self._events.put({"scope":"card","state":"detected"})
 def stop_card_watch(self):self.card_watch_active=False
 def mutate(self,request_id,action,value=None):
  if request_id in self.done:return self.done[request_id]
  if not self.master_unlocked or not self.wallet: raise TopupError("Master atau kartu belum siap")
  w=self.wallet
  if action=="balance_adjust":
   total=w.balance+int(value)
   if int(value) not in (-30,-20,-10,10,20,30) or not 0<=total<=100: raise TopupError("Nominal atau saldo tidak sah")
   w=Wallet(w.card_reference,total,w.active,w.schedule,w.used_today,w.reserved,w.legacy,w.revision+1)
  elif action=="set_active": w=Wallet(w.card_reference,w.balance,bool(value),w.schedule,w.used_today,w.reserved,w.legacy,w.revision+1)
  elif action=="set_schedule":
   if value not in (1,2,3): raise TopupError("Jadwal tidak sah")
   w=Wallet(w.card_reference,w.balance,w.active,int(value),w.used_today,w.reserved,w.legacy,w.revision+1)
  elif action=="upgrade": w=Wallet(w.card_reference,w.balance,w.active,0,0,0,False,w.revision+1)
  elif action=="release_reserved":
   if not w.reserved: raise TopupError("Tidak ada cadangan")
   w=Wallet(w.card_reference,w.balance+w.reserved,w.active,w.schedule,w.used_today,0,False,w.revision+1)
  else: raise TopupError("Aksi tidak didukung")
  self.wallet=self.done[request_id]=w; return w

class SerialReaderAdapter:
 def __init__(self,port,baudrate=115200):
  self.port,self.baudrate,self.serial,self.master_unlocked,self._request_lock=port,baudrate,None,False,threading.Lock()
  self._responses=queue.Queue();self._events=queue.Queue();self._rx_stop=threading.Event();self._rx_thread=None
 def connect(self):
  try: import serial
  except ImportError as e: raise TopupError("pyserial belum diinstal") from e
  # Samakan dengan transport Perso: DTR/RTS harus sudah LOW sebelum port
  # dibuka. Default pyserial dapat menahan/reset board melalui CH340 sehingga
  # byte masuk ke USART tetapi loop firmware tidak sempat membalas.
  self.serial=serial.Serial()
  self.serial.port=self.port;self.serial.baudrate=self.baudrate
  self.serial.timeout=.25;self.serial.write_timeout=2
  self.serial.dtr=False;self.serial.rts=False
  self.serial.open()
  self._rx_stop.clear();self._rx_thread=threading.Thread(target=self._receive_loop,daemon=True);self._rx_thread.start()
  # CH340 may reset or expose the board's startup banner when COM opens.
  # Give firmware time to finish setup; _request then ignores unrelated lines.
  time.sleep(.25)
  if self._request("hello",{},4).get("bridge")!="topup-v1": raise TopupError("Bridge alat Topup tidak sesuai")
  # Sama seperti startup Perso: setiap koneksi aplikasi mengunci sesi lama.
  # Master harus diangkat lalu ditempel lagi sebelum workspace dibuka.
  self.lock_session()
 def close(self):
  self._rx_stop.set()
  if self.serial:self.serial.close()
  if self._rx_thread and self._rx_thread.is_alive():self._rx_thread.join(timeout=.6)
  self._rx_thread=None
  self.serial=None;self.master_unlocked=False
 def _receive_loop(self):
  while not self._rx_stop.is_set():
   try:line=self.serial.readline().decode("ascii","replace").strip() if self.serial else ""
   except Exception:
    if not self._rx_stop.is_set():time.sleep(.05)
    continue
   if line:self._dispatch_line(line)
 def _dispatch_line(self,line):
  parts=line.split()
  if len(parts)>=3 and parts[0]=="EVT":
   self._events.put({"scope":parts[1].lower(),"state":parts[2].lower()});return
  if len(parts)>=3 and parts[0]=="RES":self._responses.put(parts)
 def next_event(self):
  try:return self._events.get_nowait()
  except queue.Empty:return None
 def clear_events(self):
  while self.next_event() is not None:pass
 def _clear_responses(self):
  try:
   while True:self._responses.get_nowait()
  except queue.Empty:pass
 def _request(self,kind,fields,timeout_seconds=3):
  with self._request_lock:return self._request_unlocked(kind,fields,timeout_seconds)
 def _request_unlocked(self,kind,fields,timeout_seconds=3):
  if not self.serial or not self.serial.is_open: raise TopupError("COM belum tersambung")
  fields=dict(fields);operation_id=str(fields.pop("operation_id",new_request_id()));request_id=(operation_id[:1] or "0"); value=fields.get("value")
  compact={"hello":"H","lock":"L","unlock":"U","enroll_begin":"E","enroll_status":"Q","enroll_commit":"C","read":"R","test_start":"Y","test_status":"T","test_stop":"Z","watch_start":"J","watch_stop":"K"}
  compact_code=compact.get(kind.lower()) if value is None else None
  if compact_code: request_id=compact_code;command=f"!{compact_code}".encode("ascii")
  else: command=(f"#REQ {request_id} {kind.upper()}"+(f" {int(value)}" if value is not None else "")+"\n").encode("ascii")
  self._clear_responses()
  self.serial.write(b"!");self.serial.flush();time.sleep(.02)
  # Sama seperti compact-commit Perso: CH340 -> STM32 pada board ini dapat
  # membuang byte dari burst panjang. Kirim terukur agar satu baris utuh.
  for byte in command:
   self.serial.write(bytes((byte,)));self.serial.flush();time.sleep(.02)
  deadline=time.monotonic()+timeout_seconds
  while time.monotonic()<deadline:
   remaining=max(.01,deadline-time.monotonic())
   try:
    if self._rx_thread and self._rx_thread.is_alive():parts=self._responses.get(timeout=min(.25,remaining))
    else:
     line=self.serial.readline().decode("ascii","replace").strip();parts=line.split()
   except queue.Empty:continue
   if len(parts)<3 or parts[0]!="RES" or parts[1]!=request_id:continue
   if parts[2]!="OK":raise TopupError(" ".join(parts[3:]).replace("_"," ") or "Bridge menolak")
   data={}
   for item in parts[3:]:
    if "=" in item:key,val=item.split("=",1);data[key]=val
   return data
  raise TopupError("Respons Topup Board tidak diterima")
 def lock_session(self): self._request("lock",{});self.master_unlocked=False
 def unlock_master(self): self._request("unlock",{});self.master_unlocked=True
 def begin_master_enrollment(self): return self._request("enroll_begin",{})
 def master_enrollment_status(self): return self._request("enroll_status",{})
 def commit_master_enrollment(self):
  result=self._request("enroll_commit",{});self.master_unlocked=True;return result
 def enroll_master(self):
  self.begin_master_enrollment()
  deadline=time.monotonic()+18
  while time.monotonic()<deadline:
   state=self.master_enrollment_status().get("state")
   if state=="registered": return
   if state=="ready":
    self.commit_master_enrollment()
    return
   time.sleep(.3)
  raise TopupError("Master card harus ditempel terus selama 10 detik")
 def read_wallet(self):
  data=self._request("read",{}); return Wallet(canonical_card_reference(data["reference"]),int(data["balance"]),data["active"]=="1",int(data["schedule"]),int(data["used"]),int(data["reserved"]),data["legacy"]=="1",int(data["revision"]))
 def start_card_test(self):
  # Perso mengulang handshake Test Card maksimal empat kali bila ACK UART
  # terlewat. Terapkan batas yang sama pada bridge request-response Topup.
  last_error=None
  for _ in range(4):
   try:return self._request("test_start",{},.7)
   except TopupError as error:
    last_error=error
    if str(error)!="Respons Topup Board tidak diterima":raise
  raise last_error or TopupError("Board tidak mengonfirmasi mode Test Card")
 def card_test_status(self): return self._request("test_status",{}).get("present")=="1"
 def stop_card_test(self): return self._request("test_stop",{})
 def start_card_watch(self):
  # WATCH_START bersifat idempotent. Seperti Test Card, ulangi handshake bila
  # ACK singkat hilang di jalur UART/CH340; firmware mungkin sudah mengaktifkan
  # mode watch meskipun respons pertamanya tidak sampai ke aplikasi.
  last_error=None
  for _ in range(4):
   try:return self._request("watch_start",{},.7)
   except TopupError as error:
    last_error=error
    if str(error)!="Respons Topup Board tidak diterima":raise
  raise last_error or TopupError("Board tidak mengonfirmasi pemantauan kartu")
 def stop_card_watch(self):return self._request("watch_stop",{})
 def mutate(self,request_id,action,value=None):
  commands={"balance_adjust":"adjust","set_active":"active","set_schedule":"schedule","upgrade":"upgrade","release_reserved":"release"}
  data=self._request(commands[action],{"value":value,"operation_id":request_id})
  return Wallet(canonical_card_reference(data["reference"]),int(data["balance"]),data["active"]=="1",int(data["schedule"]),int(data["used"]),int(data["reserved"]),data["legacy"]=="1",int(data["revision"]))

class MySqlStore:
 def __init__(self,config): self.config=config
 @staticmethod
 def _driver():
  try: import mysql.connector as mysql
  except ImportError as e: raise TopupError("mysql-connector-python belum diinstal") from e
  return mysql
 def _connect(self,admin=False):
  c=self.config;return self._driver().connect(host=c["host"],port=int(c["port"]),user=c["admin_user"] if admin else c["app_user"],password=c["admin_password"] if admin else c["app_password"],database=None if admin else "smartdispenser_topup",autocommit=True)
 def ensure_schema(self):
  db=self._connect(True);cur=db.cursor()
  try:
   cur.execute("USE smartdispenser_topup")
   for sql in Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";"):
    if sql.strip():cur.execute(sql)
  finally:cur.close();db.close()
 @classmethod
 def provision(cls,c,pin):
  if len(pin)<6: raise TopupError("PIN minimal 6 digit")
  store=cls(c);db=store._connect(True);cur=db.cursor()
  try:
   cur.execute("CREATE DATABASE IF NOT EXISTS smartdispenser_topup CHARACTER SET utf8mb4")
   if c["app_user"]!="sd_topup_app": raise TopupError("Nama akun aplikasi tidak sah")
   for host in ("localhost","127.0.0.1"):
    cur.execute(f"CREATE USER IF NOT EXISTS `sd_topup_app`@'{host}' IDENTIFIED BY %s",(c["app_password"],))
    cur.execute(f"ALTER USER `sd_topup_app`@'{host}' IDENTIFIED BY %s",(c["app_password"],))
    cur.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON smartdispenser_topup.* TO `sd_topup_app`@'{host}'")
   cur.execute("FLUSH PRIVILEGES")
  finally:cur.close();db.close()
  # Skema dibuat oleh admin; akun aplikasi sengaja tidak diberi hak DDL.
  db=store._connect(True);cur=db.cursor()
  try:
   cur.execute("USE smartdispenser_topup")
   for sql in Path(__file__).with_name("schema.sql").read_text(encoding="utf-8").split(";"):
    if sql.strip():cur.execute(sql)
   salt,digest=hash_pin(pin)
   cur.execute("INSERT INTO operators(username,pin_salt,pin_hash,enabled) VALUES('admin',%s,%s,1) ON DUPLICATE KEY UPDATE pin_salt=VALUES(pin_salt),pin_hash=VALUES(pin_hash),enabled=1",(salt,digest))
  finally:cur.close();db.close()
  return store
 def login(self,pin):
  db=self._connect();cur=db.cursor(dictionary=True)
  try:
   cur.execute("SELECT * FROM operators WHERE username='admin' AND enabled=1");row=cur.fetchone()
   if not row or hash_pin(pin,bytes(row["pin_salt"]))[1]!=bytes(row["pin_hash"]):raise TopupError("PIN tidak benar")
   return int(row["id"])
  finally:cur.close();db.close()
 def audit(self,operator,event,card_reference,detail):
  db=self._connect();cur=db.cursor()
  try:cur.execute("INSERT INTO audit_events(operator_id,event_type,card_token,detail) VALUES(%s,%s,%s,%s)",(operator,event,canonical_card_reference(card_reference),detail[:255]))
  finally:cur.close();db.close()
 def sync_wallet_state(self,wallet):
  db=self._connect();cur=db.cursor()
  try:
   cur.execute("INSERT INTO card_wallet_state(card_token,balance,active,schedule,used_today,reserved,revision) VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE balance=VALUES(balance),active=VALUES(active),schedule=VALUES(schedule),used_today=VALUES(used_today),reserved=VALUES(reserved),revision=VALUES(revision),last_seen_at=CURRENT_TIMESTAMP",(canonical_card_reference(wallet.card_reference),wallet.balance,1 if wallet.active else 0,wallet.schedule,wallet.used_today,wallet.reserved,wallet.revision))
  finally:cur.close();db.close()
 def quota_overview(self):
  db=self._connect();cur=db.cursor(dictionary=True)
  try:
   cur.execute("SELECT schedule,COUNT(*) AS card_count,COALESCE(SUM(balance),0) AS available_liter,COALESCE(SUM(used_today),0) AS used_liter,COALESCE(SUM(reserved),0) AS reserved_liter,MAX(last_seen_at) AS last_seen_at FROM card_wallet_state WHERE active=1 GROUP BY schedule ORDER BY schedule")
   rows=cur.fetchall()
   cur.execute("SELECT config_value FROM app_config WHERE config_key=CONCAT('maximum_distribution_quota_',DATE_FORMAT(CURRENT_DATE,'%Y-%m-%d'))")
   quota_row=cur.fetchone()
  finally:cur.close();db.close()
  try: quota_limit_liter=max(0,int(quota_row["config_value"] if isinstance(quota_row,dict) else quota_row[0])) if quota_row else 0
  except (TypeError,ValueError,KeyError,IndexError): quota_limit_liter=0
  by_schedule={int(row["schedule"]):row for row in rows}
  names={1:"Pagi",2:"Siang",3:"Sore"}
  schedules=[]
  for value in (1,2,3):
   row=by_schedule.get(value,{})
   schedules.append({
    "schedule":value,"label":names[value],"card_count":int(row.get("card_count",0) or 0),
     "available_liter":int(row.get("available_liter",0) or 0),"used_liter":int(row.get("used_liter",0) or 0),
     "reserved_liter":int(row.get("reserved_liter",0) or 0),
     "distributed_liter":int(row.get("available_liter",0) or 0),
   })
  unscheduled_cards=sum(int(row.get("card_count",0) or 0) for key,row in by_schedule.items() if key not in names)
  distributed_today_liter=sum(int(row.get("available_liter",0) or 0) for row in rows)
  return {
   "schedules":schedules,
   "available_liter":sum(item["available_liter"] for item in schedules),
   "used_liter":sum(item["used_liter"] for item in schedules),
   "reserved_liter":sum(item["reserved_liter"] for item in schedules),
    "card_count":sum(item["card_count"] for item in schedules),
    "unscheduled_cards":unscheduled_cards,
    "quota_limit_liter":quota_limit_liter,
    "quota_configured":quota_limit_liter>0,
    "allocated_liter":distributed_today_liter,
    "distributed_today_liter":distributed_today_liter,
    "remaining_liter":max(0,quota_limit_liter-distributed_today_liter) if quota_limit_liter>0 else 0,
    "over_limit":quota_limit_liter>0 and distributed_today_liter>quota_limit_liter,
   }
 def set_distribution_quota(self,value):
  try: liters=int(str(value).strip())
  except (TypeError,ValueError): raise TopupError("Maksimal kuota harus berupa angka liter")
  if liters<=0: raise TopupError("Maksimal kuota harus lebih dari 0 liter")
  if liters>999999: raise TopupError("Maksimal kuota tidak boleh melebihi 999999 liter")
  distributed=int(self.quota_overview()["distributed_today_liter"])
  if liters<distributed: raise TopupError(f"Maksimal kuota tidak boleh lebih kecil dari {distributed} L yang sudah didistribusikan hari ini")
  db=self._connect();cur=db.cursor()
  try:cur.execute("INSERT INTO app_config(config_key,config_value) VALUES(CONCAT('maximum_distribution_quota_',DATE_FORMAT(CURRENT_DATE,'%Y-%m-%d')),%s) ON DUPLICATE KEY UPDATE config_value=VALUES(config_value)",(str(liters),))
  finally:cur.close();db.close()
  return liters
 def validate_distribution_quota(self,before,action,value):
  if action not in ("balance_adjust","set_active"): return
  increase=0
  if action=="balance_adjust" and before.active and int(value)>0:increase=int(value)
  elif action=="set_active" and bool(value) and not before.active:increase=max(0,int(before.balance))
  if increase<=0:return
  overview=self.quota_overview()
  if not overview["quota_configured"]: raise TopupError("Atur maksimal kuota distribusi di Overview sebelum menambah kuota")
  projected=int(overview["allocated_liter"])+increase
  if projected>int(overview["quota_limit_liter"]):
   raise TopupError(f"Penambahan ditolak: alokasi akan menjadi {projected} L, melebihi batas {overview['quota_limit_liter']} L")
 def transaction(self,operator,request_id,action,before,after,value=None):
  schedule_names={1:"morning",2:"afternoon",3:"evening"}
  detail=f"schedule={schedule_names.get(int(value),'unknown')}" if action=="set_schedule" and value is not None else None
  db=self._connect();cur=db.cursor()
  try:
   cur.execute("INSERT INTO transactions(request_id,card_token,operator_id,action,amount_liter,balance_before,balance_after,outcome,detail) VALUES(%s,%s,%s,%s,%s,%s,%s,'success',%s)",(request_id,before.card_reference,operator,action,after.balance-before.balance,before.balance,after.balance,detail))
   cur.execute("INSERT INTO card_wallet_state(card_token,balance,active,schedule,used_today,reserved,revision) VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE balance=VALUES(balance),active=VALUES(active),schedule=VALUES(schedule),used_today=VALUES(used_today),reserved=VALUES(reserved),revision=VALUES(revision),last_seen_at=CURRENT_TIMESTAMP",(canonical_card_reference(after.card_reference),after.balance,1 if after.active else 0,after.schedule,after.used_today,after.reserved,after.revision))
  finally:cur.close();db.close()
 def setting(self,key):
  db=self._connect();cur=db.cursor()
  try: cur.execute("SELECT config_value FROM app_config WHERE config_key=%s",(key,)); row=cur.fetchone(); return row[0] if row else None
  finally:cur.close();db.close()
 def set_setting(self,key,value):
  db=self._connect();cur=db.cursor()
  try: cur.execute("INSERT INTO app_config(config_key,config_value) VALUES(%s,%s) ON DUPLICATE KEY UPDATE config_value=VALUES(config_value)",(key,value))
  finally:cur.close();db.close()
 def history(self,query=""):
  db=self._connect();cur=db.cursor(dictionary=True)
  try:
   value=f"%{query.strip()}%"
   cur.execute("SELECT t.created_at,CASE WHEN t.detail IS NULL THEN t.action ELSE CONCAT(t.action,' (',t.detail,')') END AS action,t.amount_liter,t.balance_before,t.balance_after,t.card_token AS card_reference FROM transactions t WHERE t.card_token LIKE %s OR t.action LIKE %s OR COALESCE(t.detail,'') LIKE %s OR DATE_FORMAT(t.created_at,'%Y-%m-%d') LIKE %s ORDER BY t.id DESC LIMIT 100",(value,value,value,value))
   return cur.fetchall()
  finally:cur.close();db.close()
 def recent_audit(self,limit=6):
  db=self._connect();cur=db.cursor(dictionary=True)
  try: cur.execute("SELECT created_at,event_type,detail FROM audit_events ORDER BY id DESC LIMIT %s",(limit,)); return cur.fetchall()
  finally:cur.close();db.close()

def backup_mysql(c):
 exe=Path(c.get("mysqldump",r"C:\xampp\mysql\bin\mysqldump.exe"))
 if not exe.exists():raise TopupError("mysqldump XAMPP tidak ditemukan")
 folder=APP_DIR/"backup";folder.mkdir(parents=True,exist_ok=True);out=folder/f"topup_{datetime.now():%Y%m%d_%H%M%S}.sql"
 command=[
  str(exe),"--protocol=tcp","--single-transaction","--skip-lock-tables","--quick",
  "--default-character-set=utf8mb4","-h",c["host"],"-P",str(c["port"]),
  "-u",c["app_user"],"smartdispenser_topup",
 ]
 environment=os.environ.copy();environment["MYSQL_PWD"]=c["app_password"]
 flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
 with out.open("wb") as f:
  result=subprocess.run(command,check=False,stdout=f,stderr=subprocess.PIPE,env=environment,creationflags=flags)
 if result.returncode:
  out.unlink(missing_ok=True)
  raise TopupError("Backup Database gagal. Periksa koneksi dan konfigurasi MySQL XAMPP.")
 for old in sorted(folder.glob("*.sql"))[:-30]:old.unlink()
 return out

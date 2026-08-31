from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import shutil
import urllib.parse
import urllib.request
import json
import time
import unicodedata
from contextlib import closing, asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("PH_DB_PATH", str(BASE_DIR / "ph_estetica.db")))
UPLOAD_DIR = Path(os.getenv("PH_UPLOAD_DIR", str(BASE_DIR / "uploads")))
BACKUP_DIR = Path(os.getenv("PH_BACKUP_DIR", str(BASE_DIR / "backups")))
UPLOAD_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

WHATSAPP_NUMBER = "5538997238317"
WHATSAPP_DISPLAY = "(38) 99723-8317"
BUSINESS_NAME = "PH ESTÉTICA & DETAIL"

@asynccontextmanager
async def lifespan(_app):
    init_db()
    create_daily_backup()
    yield


app = FastAPI(title=BUSINESS_NAME, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("PH_SESSION_SECRET", "DEV-ONLY-CHANGE-ME-" + "ph-estetica"),
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

_last_backup_day = None

@app.middleware("http")
async def ensure_daily_backup(request: Request, call_next):
    global _last_backup_day
    today_key = date.today().isoformat()
    if _last_backup_day != today_key and DB_PATH.exists():
        create_daily_backup()
        _last_backup_day = today_key
    return await call_next(request)

STATUS_LABELS = {
    "scheduled": "AGENDADO",
    "received": "VEÍCULO RECEBIDO",
    "preparation": "PREPARAÇÃO",
    "washing": "LAVAGEM INICIADA",
    "detailing": "LIMPEZA INTERNA / DETALHAMENTO",
    "finishing": "FINALIZAÇÃO",
    "inspection": "INSPEÇÃO",
    "ready": "PRONTO PARA RETIRADA",
    "completed": "FINALIZADO",
    "cancelled": "CANCELADO",
}

KANBAN = [
    ("scheduled", "AGENDADOS"),
    ("received", "RECEBIDOS"),
    ("washing", "EM LAVAGEM"),
    ("detailing", "DETALHAMENTO"),
    ("finishing", "FINALIZAÇÃO"),
    ("ready", "PRONTOS"),
]

PAYMENT_LABELS = {
    "card": "Cartão",
    "cash": "Dinheiro",
    "pix": "PIX",
}

DEFAULT_COMPANY_SETTINGS = {
    "whatsapp_number": WHATSAPP_NUMBER,
    "home_eyebrow": "CENTRAL DIGITAL DE CUIDADOS AUTOMOTIVOS",
    "home_headline": "Mais que uma lavagem. Um cuidado completo.",
    "home_subtitle": "Agende em poucos passos, conte como o veículo está e acompanhe tudo com uma experiência mais profissional para carros e motos.",
    "home_gallery_title": "Resultados e cuidados da PH",
    "home_hero_image_url": "https://images.unsplash.com/photo-1746593934498-b335e4e04845?auto=format&fit=crop&w=1800&q=82",
    "home_car_image_url": "https://images.unsplash.com/photo-1761312834150-4beefff097a7?auto=format&fit=crop&w=1600&q=82",
    "home_moto_image_url": "https://images.unsplash.com/photo-1759825045061-ac853e131f60?auto=format&fit=crop&w=1600&q=82",
    "home_detail_image_url": "https://images.unsplash.com/photo-1732357417676-9c4c14cd23c7?auto=format&fit=crop&w=1600&q=82",
    "home_moto_detail_image_url": "https://images.unsplash.com/photo-1774427052795-f73aa5338815?auto=format&fit=crop&w=1600&q=82",
    "instagram": "",
    "cancel_min_hours": "2",
    "reschedule_min_hours": "2",
    "backup_retention_days": "30",
    "wa_msg_scheduled": "Olá, {cliente}! Seu agendamento #{agendamento} na PH ESTÉTICA & DETAIL está confirmado para o veículo {veiculo}. Serviço: {servico}. Data: {data} às {horario}.",
    "wa_msg_received": "Olá, {cliente}! O veículo {veiculo} já está com a gente na PH ESTÉTICA & DETAIL. Em breve iniciaremos os cuidados. ✨",
    "wa_msg_preparation": "Olá, {cliente}! O veículo {veiculo} está em preparação para o atendimento na PH ESTÉTICA & DETAIL.",
    "wa_msg_washing": "Olá, {cliente}! Iniciamos a lavagem do veículo {veiculo} na PH ESTÉTICA & DETAIL.",
    "wa_msg_detailing": "Olá, {cliente}! O veículo {veiculo} está na etapa de detalhamento na PH ESTÉTICA & DETAIL.",
    "wa_msg_finishing": "Olá, {cliente}! Estamos finalizando os cuidados com o veículo {veiculo} na PH ESTÉTICA & DETAIL.",
    "wa_msg_inspection": "Olá, {cliente}! O veículo {veiculo} está na inspeção final na PH ESTÉTICA & DETAIL.",
    "wa_msg_ready": "Olá, {cliente}! ✨ O veículo {veiculo} está pronto para retirada na PH ESTÉTICA & DETAIL. Agradecemos pela confiança!",
    "wa_msg_completed": "Olá, {cliente}! O atendimento do veículo {veiculo} foi finalizado. Obrigado por confiar na PH ESTÉTICA & DETAIL! ✨",
    "wa_msg_cancelled": "Olá, {cliente}! O agendamento #{agendamento} do veículo {veiculo} foi cancelado. Se precisar, estamos à disposição pelo WhatsApp.",
    "wa_msg_payment_pending": "Olá, {cliente}! Tudo bem? 😊 Passando para lembrar que o pagamento do atendimento #{agendamento}, referente ao veículo {veiculo}, no valor de {valor}, ainda consta como pendente em nosso sistema. Forma de pagamento combinada: {forma_pagamento}. Se você já realizou o pagamento, pode desconsiderar esta mensagem. Qualquer dúvida, estamos à disposição. — {empresa}",
}

HOME_IMAGE_SLOTS = {
    "hero": ("home_hero_image_url", "Banner principal"),
    "car": ("home_car_image_url", "Seção de carros"),
    "moto": ("home_moto_image_url", "Seção de motos"),
    "detail": ("home_detail_image_url", "Detalhe automotivo"),
    "moto_detail": ("home_moto_detail_image_url", "Detalhe de moto"),
}


FIPE_V2_BASE = "https://fipe.parallelum.com.br/api/v2"
FIPE_VEHICLE_TYPES = {"car": "cars", "moto": "motorcycles"}

# Snapshot das marcas FIPE pesquisadas em 30/08/2026. Os modelos são sincronizados
# diretamente da API e salvos localmente no banco para busca rápida/offline depois da primeira carga.
FIPE_BRANDS_2026_08 = {
    "car": [
        ("1","Acura"),("2","Agrale"),("3","Alfa Romeo"),("4","AM Gen"),("5","Asia Motors"),("189","ASTON MARTIN"),("6","Audi"),("207","Baby"),("7","BMW"),("8","BRM"),("123","Bugre"),("238","BYD"),("236","CAB Motors"),("10","Cadillac"),("265","Caoa Changan"),("245","Caoa Chery"),("161","Caoa Chery/Chery"),("11","CBT Jipe"),("136","CHANA"),("182","CHANGAN"),("12","Chrysler"),("13","Citroën"),("14","Cross Lander"),("241","D2D Motors"),("15","Daewoo"),("16","Daihatsu"),("263","Denza"),("246","DFSK"),("17","Dodge"),("147","EFFA"),("18","Engesa"),("19","Envemo"),("20","Ferrari"),("249","FEVER"),("21","Fiat"),("149","Fibravan"),("22","Ford"),("190","FOTON"),("170","Fyber"),("254","GAC"),("199","GEELY"),("23","GM - Chevrolet"),("153","GREAT WALL"),("24","Gurgel"),("240","GWM"),("152","HAFEI"),("214","HITECH ELECTRIC"),("25","Honda"),("26","Hyundai"),("27","Isuzu"),("208","IVECO"),("177","JAC"),("251","Jaecoo"),("28","Jaguar"),("29","Jeep"),("264","Jetour"),("154","JINBEI"),("30","JPX"),("31","Kia Motors"),("32","Lada"),("171","LAMBORGHINI"),("33","Land Rover"),("260","Leapmotor"),("34","Lexus"),("168","LIFAN"),("127","LOBINI"),("35","Lotus"),("140","Mahindra"),("36","Maserati"),("37","Matra"),("38","Mazda"),("211","Mclaren"),("39","Mercedes-Benz"),("40","Mercury"),("167","MG"),("156","MINI"),("41","Mitsubishi"),("42","Miura"),("250","NETA"),("43","Nissan"),("252","Omoda"),("44","Peugeot"),("45","Plymouth"),("46","Pontiac"),("47","Porsche"),("185","RAM"),("186","RELY"),("48","Renault"),("195","Rolls-Royce"),("49","Rover"),("50","Saab"),("51","Saturn"),("52","Seat"),("247","SERES"),("183","SHINERAY"),("157","smart"),("125","SSANGYONG"),("54","Subaru"),("55","Suzuki"),("165","TAC"),("56","Toyota"),("57","Troller"),("58","Volvo"),("59","VW - VolksWagen"),("163","Wake"),("120","Walk"),("253","ZEEKR")
    ],
    "moto": [
        ("60","ADLY"),("61","AGRALE"),("131","AMAZONAS"),("62","APRILIA"),("63","ATALA"),("216","AVELLOZ"),("64","BAJAJ"),("205","BEE"),("162","Benelli"),("65","BETA"),("66","BIMOTA"),("67","BMW"),("68","BRANDY"),("130","BRAVA"),("150","BRP"),("117","BUELL"),("155","BUENO"),("212","BULL"),("69","byCristo"),("70","CAGIVA"),("71","CALOI"),("266","CFMOTO"),("72","DAELIM"),("145","DAFRA"),("137","DAYANG"),("142","DAYUN"),("73","DERBI"),("74","DUCATI"),("75","EMME"),("248","FEVER"),("132","FOX"),("209","FUSCO MOTOSEGURA"),("128","FYM"),("143","GARINNI"),("76","GAS GAS"),("133","GREEN"),("138","HAOBAO"),("203","HAOJUE"),("77","HARLEY-DAVIDSON"),("78","HARTFORD"),("79","HERO"),("261","Hisun"),("80","HONDA"),("81","HUSABERG"),("82","HUSQVARNA"),("202","INDIAN"),("158","IROS"),("141","JIAPENG VOLCANO"),("174","JOHNNYPAG"),("151","JONNY"),("129","KAHENA"),("118","KASINSKI"),("85","KAWASAKI"),("87","KTM"),("204","KYMCO"),("159","LANDUM"),("88","L'AQUILA"),("89","LAVRALE"),("139","LERIVO"),("258","LEVA"),("178","LIFAN"),("148","Lon-V"),("175","MAGRÃO TRICICLOS"),("146","Malaguti"),("126","MIZA"),("259","Mobílli"),("90","MOTO GUZZI"),("201","MOTOCAR"),("255","MOTOMORINI"),("200","MOTORINO"),("160","MRX"),("91","MV AGUSTA"),("92","MVK"),("239","NIU"),("93","ORCA"),("164","PEGASSI"),("94","PEUGEOT"),("95","PIAGGIO"),("210","POLARIS"),("173","REGAL RAPTOR"),("198","RIGUETE"),("192","Royal Enfield"),("96","SANYANG"),("262","SBM"),("134","SHINERAY"),("97","SIAMOTO"),("98","SUNDOWN"),("237","SUPER SOCO"),("99","SUZUKI"),("267","SWM"),("176","TARGOS"),("187","TIGER"),("119","TRAXX"),("100","TRIUMPH"),("244","Ventane Motors"),("180","VENTO"),("256","VESPA"),("215","VOLTZ"),("243","WATTS"),("135","WUYANG"),("101","YAMAHA"),("242","ZONTES")
    ]
}

BRAND_CANONICAL = {
    "GM - CHEVROLET": "Chevrolet",
    "VW - VOLKSWAGEN": "Volkswagen",
    "KIA MOTORS": "Kia",
    "CAOA CHERY/CHERY": "Caoa Chery",
}

BRAND_COMMON_ALIASES = {
    "Volkswagen": ["VW", "Volks", "Volks Wagen"],
    "Chevrolet": ["GM", "Chevy"],
    "Mercedes-Benz": ["Mercedes", "Mercedes Benz"],
    "Harley-Davidson": ["Harley", "Harley Davidson"],
    "Royal Enfield": ["Royal"],
    "Caoa Chery": ["Chery"],
}

CAR_BODY_SUFFIXES = {
    "plus","cross","sedan","hatchback","sportback","avant","variant","weekend","sw","touring",
    "grandtour","grand","tour","picasso","cactus","aircross","lounge","pallas","fastback","cabrio",
    "cabriolet","coupe","coupé","spider","roadster","countryman","clubman","oroch","evoque","velar",
    "van","wagon","estate","shooting","pickup","pick-up"
}

CAR_TRIM_TOKENS = {
    "comfortline","highline","trendline","extreme","ultimate","premier","lt","ltz","rs","ex","exl","exr",
    "lx","lxs","touring","xei","altis","gli","srx","hse","se","sel","titanium","limited","platinum",
    "exclusive","intense","iconic","outsider","zen","life","drive","precision","volcano","ranch","endurance",
    "freedom","impetus","audace","abarth","trekking","like","attractive","essence","adventure","way","mille",
    "elx","hlx","sx","sxt","style","advance","elite","signature","prestige","active","allure","griffe",
    "feel","shine","live","origins","first","edition","launch","connect","pepper","selection","seleção",
    "route","city","prime","rock","motion","imotion","i-motion","comfor","comfort","hig","high","gl","gls",
    "gti","gts","cl","cli","track","sense","joy","activ","effect","diamond","evolution","vision","working",
    "hard","advantage","executive","sport","black","country","z71","r-line","rline","blue","bluemotion"
}

MOTO_TRIM_TOKENS = {
    "abs","dlx","es","ex","ks","esd","esdi","esi","esdd","flex","flexone","mix","sport","rally","adventure",
    "edition","special","anniversary","black","dct","e-clutch","eclutch","te","fm","tm","quadriciclo","ouro",
    "cargo","start","fan","titan","s","sp","std","limited","touring","premium"
}

ENGINE_STOP_RE = re.compile(r"^(?:\d+[.,]\d+|\d{1,2}v|\d+p|tdi|tsi|tfsi|turbo|tb|flex|diesel|gasolina|aut\.?|mec\.?|cvt|awd|rwd|fwd|4x4|4x2|hybrid|hibrido|híbrido|phev|electric|el[eé]trico)$", re.I)


def normalize_search(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def canonical_brand_name(raw: str) -> str:
    clean = re.sub(r"\s+", " ", (raw or "").strip())
    mapped = BRAND_CANONICAL.get(clean.upper())
    if mapped:
        return mapped
    preserve = {"BMW","BYD","BRM","DFSK","EFFA","FOTON","GAC","GEELY","GWM","JAC","JPX","MG","MINI","NETA","RAM","RELY","SERES","TAC","ZEEKR","ADLY","BRP","CFMOTO","FYM","HERO","KTM","KYMCO","MRX","MVK","NIU","ORCA","SBM","SWM"}
    if clean.upper() in preserve:
        return clean.upper()
    if clean.isupper() and len(clean) > 4:
        return " ".join(part.capitalize() if part not in {"GAS","GAS"} else part.title() for part in clean.split())
    return clean


def _pretty_model_token(token: str) -> str:
    if not token:
        return token
    if any(ch.isdigit() for ch in token):
        return token.upper() if len(token) <= 8 else token
    if token.upper() in {"CB","CBR","CBX","CG","CRF","NC","NX","NXR","PCX","SH","TRX","VFR","VT","VTX","XL","XLR","XLX","XR","XRE","MT","YZF","YBR","XTZ","GS","GSX","GSX-R","DL","DR","KTM","BMW","ABS","RR","RS"}:
        return token.upper()
    return token.capitalize() if token.isupper() else token


def _pretty_model(candidate: str) -> str:
    return " ".join(_pretty_model_token(t) for t in re.sub(r"\s+", " ", candidate.strip()).split())


def generic_model_name(vehicle_type: str, brand: str, raw: str) -> str:
    original = re.sub(r"\s+", " ", (raw or "").replace("\n", " ")).strip(" -/")
    upper = original.upper()
    if vehicle_type == "moto":
        # Regras de famílias que a FIPE fragmenta por acabamento, mas que para estética são o mesmo modelo.
        if re.match(r"^(?:C\s*100\s+)?BIZ\b", upper): return "Biz"
        if re.match(r"^POP\b", upper): return "Pop"
        m=re.match(r"^CG\s+(\d{3})\b", upper)
        if m: return f"CG {m.group(1)}"
        m=re.match(r"^NXR\s+(\d{3})\s+BROS\b", upper)
        if m: return f"Bros {m.group(1)}"
        m=re.match(r"^SAHARA\s+(\d{3})\b", upper)
        if m: return f"Sahara {m.group(1)}"
        m=re.match(r"^XRE\s+(\d{3})\b", upper)
        if m: return f"XRE {m.group(1)}"
        m=re.match(r"^PCX\s+(\d{3})\b", upper)
        if m: return f"PCX {m.group(1)}"
        m=re.match(r"^(CB\s+300F)\b", upper)
        if m: return "CB 300F"
        m=re.match(r"^(CB\s+500[FX])\b", upper)
        if m: return m.group(1)
        m=re.match(r"^(CBR\s+500R)\b", upper)
        if m: return m.group(1)
        m=re.match(r"^(NC\s+\d{3}X)\b", upper)
        if m: return m.group(1)
        m=re.match(r"^(XR\s+\d{3}L?\s+TORNADO)\b", upper)
        if m: return _pretty_model(m.group(1))
        m=re.match(r"^(CBX?\s+\d{3}\s+TWISTER)\b", upper)
        if m: return _pretty_model(m.group(1))
        m=re.match(r"^(CRF\s+\d{4}L\s+AFRICA\s+TWIN)\b", upper)
        if m: return _pretty_model(m.group(1))
        # Para as demais motos, removemos acabamento e itens técnicos no fim, mantendo série/cilindrada/letra.
        segment=re.split(r"\s*/\s*", original)[0].strip()
        tokens=segment.split()
        kept=[]
        for tok in tokens:
            key=normalize_search(tok)
            if kept and (key in MOTO_TRIM_TOKENS or ENGINE_STOP_RE.match(tok)):
                break
            kept.append(tok)
            if len(kept) >= 5:
                break
        while len(kept)>1 and normalize_search(kept[-1]) in MOTO_TRIM_TOKENS:
            kept.pop()
        return _pretty_model(" ".join(kept) or original)

    # Carros: o nome FIPE normalmente começa pela família e depois traz versão/motor.
    tokens=original.replace("/", " / ").split()
    kept=[]
    for tok in tokens:
        key=normalize_search(tok)
        if tok == "/":
            break
        if kept and (ENGINE_STOP_RE.match(tok) or key in CAR_TRIM_TOKENS or re.search(r"\d+[.,]\d+", tok)):
            break
        kept.append(tok)
        if len(kept) >= 5:
            break
    while len(kept)>1 and normalize_search(kept[-1]) in CAR_TRIM_TOKENS:
        kept.pop()
    candidate=" ".join(kept) or original
    return _pretty_model(candidate)


def _collapse_car_candidates(raw_items):
    first_pass=[generic_model_name("car", "", x["name"]) for x in raw_items]
    single={normalize_search(x) for x in first_pass if len(x.split())==1}
    result=[]
    for item,candidate in zip(raw_items, first_pass):
        parts=candidate.split()
        if len(parts)>1 and normalize_search(parts[0]) in single:
            suffix=normalize_search(" ".join(parts[1:]))
            # Se o complemento descreve carroceria/família, mantemos separado (Onix Plus, Corolla Cross etc.).
            if not any(tok in CAR_BODY_SUFFIXES for tok in suffix.split()):
                candidate=parts[0]
        result.append((item,candidate))
    return result


def suggested_car_category(name: str) -> str:
    s=normalize_search(name)
    large_words=("hilux","ranger","s10","amarok","toro","sw4","trailblazer","commander","compass","renegade","creta","tucson","sportage","sorento","santa fe","pajero","outlander","eclipse cross","rav4","corolla cross","hr v","cr v","tracker","equinox","territory","bronco","edge","taos","tiguan","t cross","nivus","kicks","frontier","pathfinder","x trail","duster","captur","koleos","oroch","2008","3008","5008","aircross","c4 cactus","c5 aircross","pulse","fastback","strada","saveiro","montana","master","ducato","sprinter","transit","daily")
    return "car_large" if any(w in s for w in large_words) else "car_small"


def _fetch_fipe_json(url: str, timeout: int = 20):
    last_error=None
    for attempt in range(3):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":"PH-Estetica-Detail/1.0","Accept":"application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error=exc
            if attempt < 2:
                time.sleep(0.7 * (attempt + 1))
    raise RuntimeError(f"Falha ao consultar catálogo FIPE: {last_error}")


def seed_vehicle_catalog_brands(conn):
    for vehicle_type, items in FIPE_BRANDS_2026_08.items():
        for source_code, source_name in items:
            name=canonical_brand_name(source_name)
            row=conn.execute("SELECT id FROM vehicle_brands_catalog WHERE vehicle_type=? AND name=? COLLATE NOCASE", (vehicle_type,name)).fetchone()
            if row:
                brand_id=row["id"]
                conn.execute("UPDATE vehicle_brands_catalog SET search_text=? WHERE id=?", (normalize_search(name),brand_id))
            else:
                cur=conn.execute("INSERT INTO vehicle_brands_catalog(vehicle_type,name,search_text,active,synced_at) VALUES (?,?,?,?,?)", (vehicle_type,name,normalize_search(name),1,now_iso()))
                brand_id=cur.lastrowid
            conn.execute("INSERT OR IGNORE INTO vehicle_brand_sources(brand_id,source_code,source_name) VALUES (?,?,?)", (brand_id,str(source_code),source_name))
            aliases={source_name,name,*BRAND_COMMON_ALIASES.get(name,[])}
            for alias in aliases:
                conn.execute("INSERT OR IGNORE INTO vehicle_brand_aliases(brand_id,alias,search_text) VALUES (?,?,?)", (brand_id,alias,normalize_search(alias)))
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('vehicle_catalog_brands_seeded','2026-08-30')")


def sync_vehicle_brands_from_fipe(conn, vehicle_type: str):
    api_type=FIPE_VEHICLE_TYPES[vehicle_type]
    data=_fetch_fipe_json(f"{FIPE_V2_BASE}/{api_type}/brands")
    items=[]
    for b in data if isinstance(data,list) else []:
        code=str(b.get("code") or b.get("codigo") or "")
        raw=str(b.get("name") or b.get("nome") or "").strip()
        if code and raw: items.append((code,raw))
    if not items:
        raise RuntimeError("A FIPE não retornou marcas.")
    # usa a mesma rotina, mas sem depender do snapshot
    for source_code, source_name in items:
        name=canonical_brand_name(source_name)
        row=conn.execute("SELECT id FROM vehicle_brands_catalog WHERE vehicle_type=? AND name=? COLLATE NOCASE", (vehicle_type,name)).fetchone()
        if row: brand_id=row["id"]
        else:
            brand_id=conn.execute("INSERT INTO vehicle_brands_catalog(vehicle_type,name,search_text,active,synced_at) VALUES (?,?,?,?,?)", (vehicle_type,name,normalize_search(name),1,now_iso())).lastrowid
        conn.execute("UPDATE vehicle_brands_catalog SET search_text=?, synced_at=? WHERE id=?", (normalize_search(name),now_iso(),brand_id))
        conn.execute("INSERT OR IGNORE INTO vehicle_brand_sources(brand_id,source_code,source_name) VALUES (?,?,?)", (brand_id,source_code,source_name))
        aliases={source_name,name,*BRAND_COMMON_ALIASES.get(name,[])}
        for alias in aliases:
            conn.execute("INSERT OR IGNORE INTO vehicle_brand_aliases(brand_id,alias,search_text) VALUES (?,?,?)", (brand_id,alias,normalize_search(alias)))
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (f"vehicle_catalog_brands_sync_{vehicle_type}",now_iso()))
    conn.commit()
    return len(items)


def sync_vehicle_models_for_brand(conn, brand_id: int):
    brand=conn.execute("SELECT * FROM vehicle_brands_catalog WHERE id=?", (brand_id,)).fetchone()
    if not brand: raise ValueError("Marca não encontrada")
    sources=conn.execute("SELECT * FROM vehicle_brand_sources WHERE brand_id=? ORDER BY id", (brand_id,)).fetchall()
    if not sources: raise RuntimeError("Marca sem código FIPE de origem.")
    api_type=FIPE_VEHICLE_TYPES[brand["vehicle_type"]]
    raw_items=[]
    for source in sources:
        data=_fetch_fipe_json(f"{FIPE_V2_BASE}/{api_type}/brands/{source['source_code']}/models")
        models=data if isinstance(data,list) else (data.get("models") or data.get("modelos") or [])
        for m in models:
            raw_name=str(m.get("name") or m.get("nome") or "").strip()
            source_code=str(m.get("code") or m.get("codigo") or "")
            if raw_name:
                raw_items.append({"name":raw_name,"code":source_code})
        time.sleep(0.04)
    pairs=_collapse_car_candidates(raw_items) if brand["vehicle_type"]=="car" else [(x,generic_model_name("moto",brand["name"],x["name"])) for x in raw_items]
    for item,generic in pairs:
        generic=re.sub(r"\s+", " ", generic).strip(" -/") or item["name"]
        row=conn.execute("SELECT id FROM vehicle_models_catalog WHERE brand_id=? AND name=? COLLATE NOCASE", (brand_id,generic)).fetchone()
        if row: model_id=row["id"]
        else:
            cat=suggested_car_category(generic) if brand["vehicle_type"]=="car" else "moto"
            model_id=conn.execute("INSERT INTO vehicle_models_catalog(brand_id,name,search_text,suggested_category,active,synced_at) VALUES (?,?,?,?,1,?)", (brand_id,generic,normalize_search(generic),cat,now_iso())).lastrowid
        conn.execute("UPDATE vehicle_models_catalog SET search_text=?, synced_at=? WHERE id=?", (normalize_search(generic),now_iso(),model_id))
        conn.execute("INSERT OR IGNORE INTO vehicle_model_aliases(model_id,alias,search_text,source_code) VALUES (?,?,?,?)", (model_id,item["name"],normalize_search(item["name"]),item["code"]))
    conn.execute("UPDATE vehicle_brands_catalog SET models_synced_at=? WHERE id=?", (now_iso(),brand_id))
    conn.commit()
    return len({normalize_search(x[1]) for x in pairs}), len(raw_items)


def sync_vehicle_catalog_all(progress=None):
    summary={"brands":0,"generic_models":0,"raw_models":0,"errors":[]}
    with closing(db_conn()) as conn:
        for vt in ("car","moto"):
            try: sync_vehicle_brands_from_fipe(conn,vt)
            except Exception as exc: summary["errors"].append(f"Marcas {vt}: {exc}")
        brands=conn.execute("SELECT id,name,vehicle_type FROM vehicle_brands_catalog WHERE active=1 ORDER BY vehicle_type,name").fetchall()
        summary["brands"]=len(brands)
        for i,b in enumerate(brands,1):
            try:
                g,r=sync_vehicle_models_for_brand(conn,b["id"]); summary["generic_models"]+=g; summary["raw_models"]+=r
            except Exception as exc:
                summary["errors"].append(f"{b['vehicle_type']} {b['name']}: {exc}")
            if progress: progress(i,len(brands),b["name"])
            time.sleep(0.05)
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('vehicle_catalog_full_sync',?)", (now_iso(),)); conn.commit()
    return summary


def resolve_catalog_vehicle(conn, vehicle_type: str, brand_catalog_id: str, model_catalog_id: str, brand: str, model: str):
    bid=int(brand_catalog_id) if str(brand_catalog_id or "").isdigit() else None
    mid=int(model_catalog_id) if str(model_catalog_id or "").isdigit() else None
    if bid and mid:
        row=conn.execute("""SELECT b.id brand_id,b.name brand_name,m.id model_id,m.name model_name,m.suggested_category
                            FROM vehicle_brands_catalog b JOIN vehicle_models_catalog m ON m.brand_id=b.id
                            WHERE b.id=? AND m.id=? AND b.vehicle_type=? AND b.active=1 AND m.active=1""", (bid,mid,vehicle_type)).fetchone()
        if row:
            return row["brand_name"],row["model_name"],row["brand_id"],row["model_id"]
    return (brand or "").strip(),(model or "").strip(),None,None

def scope_matches(scope: Optional[str], category: str) -> bool:
    """Retorna se um adicional/pergunta é válido para a categoria do veículo."""
    if not scope or scope == "all":
        return True
    if scope == category:
        return True
    return scope == "car" and category in {"car_small", "car_large"}


def payment_label(value: Optional[str]) -> str:
    code = value or ""
    if not code:
        return "Não informado"
    try:
        with closing(db_conn()) as conn:
            row = conn.execute("SELECT name FROM payment_methods WHERE code=?", (code,)).fetchone()
            if row:
                return row["name"]
    except Exception:
        pass
    return PAYMENT_LABELS.get(code, code.replace("_", " ").title())


def get_company_settings(conn=None):
    own = conn is None
    if own:
        conn = db_conn()
    try:
        values = dict(DEFAULT_COMPANY_SETTINGS)
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
        for row in rows:
            if row["key"] in values:
                values[row["key"]] = row["value"] or ""
        return values
    finally:
        if own:
            conn.close()


def get_payment_methods(conn=None, active_only=True):
    own = conn is None
    if own:
        conn = db_conn()
    try:
        sql = "SELECT * FROM payment_methods" + (" WHERE active=1" if active_only else "") + " ORDER BY sort_order,id"
        return conn.execute(sql).fetchall()
    finally:
        if own:
            conn.close()


def current_whatsapp_number(conn=None):
    return re.sub(r"\D", "", get_company_settings(conn).get("whatsapp_number") or WHATSAPP_NUMBER) or WHATSAPP_NUMBER


def create_daily_backup(force=False):
    if not DB_PATH.exists():
        return None
    stamp = date.today().isoformat()
    target = BACKUP_DIR / f"ph_estetica_{stamp}.db"
    if target.exists() and not force:
        return target
    try:
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.close(); src.close()
        retention = 30
        try:
            with closing(db_conn()) as conn:
                retention = max(7, int(setting(conn, "backup_retention_days", "30") or 30))
        except Exception:
            pass
        cutoff = datetime.now() - timedelta(days=retention)
        for item in BACKUP_DIR.glob("ph_estetica_*.db"):
            try:
                if datetime.fromtimestamp(item.stat().st_mtime) < cutoff:
                    item.unlink()
            except OSError:
                pass
        return target
    except Exception:
        return None


def first_name(value: Optional[str]) -> str:
    if not value:
        return "Cliente"
    return (value or "").strip().split()[0]


def format_phone_br(value: Optional[str]) -> str:
    """Formata telefone brasileiro sem alterar o valor salvo no banco."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return value or "—"


def customer_whatsapp_number(value: Optional[str]) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    return f"55{digits}" if digits else ""


def _row_get(row, key: str, default=""):
    try:
        if row is not None and key in row.keys():
            value = row[key]
            return default if value is None else value
    except Exception:
        pass
    return default


def render_whatsapp_template(template: str, row) -> str:
    """Substitui apenas os campos permitidos nas mensagens configuráveis do WhatsApp."""
    name = first_name(_row_get(row, "customer_name", "Cliente"))
    brand = str(_row_get(row, "brand", "")).strip()
    model = str(_row_get(row, "model", "")).strip()
    vehicle = f"{brand} {model}".strip() or "veículo"
    service = str(_row_get(row, "service_name", "serviço")).strip() or "serviço"
    code = str(_row_get(row, "code", "")).strip()
    appointment_date = fmt_date(str(_row_get(row, "appointment_date", "")))
    appointment_time = str(_row_get(row, "appointment_time", "")).strip() or "—"
    raw_total = _row_get(row, "final_total", None)
    if raw_total in (None, ""):
        raw_total = _row_get(row, "estimated_total", None)
    value = brl(raw_total) if raw_total not in (None, "") else "A definir"
    payment_method = str(_row_get(row, "payment_method", "")).strip()
    payment_method_name = payment_label(payment_method) if payment_method else "Não informado"
    payment_status = str(_row_get(row, "payment_status", "pending")).strip().lower()
    payment_status_name = "Pago" if payment_status == "paid" else "Pendente"
    replacements = {
        "{cliente}": name,
        "{veiculo}": vehicle,
        "{servico}": service,
        "{agendamento}": code,
        "{valor}": value,
        "{data}": appointment_date,
        "{horario}": appointment_time,
        "{empresa}": BUSINESS_NAME,
        "{forma_pagamento}": payment_method_name,
        "{status_pagamento}": payment_status_name,
    }
    message = template or ""
    for token, replacement in replacements.items():
        message = message.replace(token, str(replacement))
    return message.strip()


def status_whatsapp_url(row) -> str:
    """Gera link gratuito do WhatsApp usando o modelo editável do status atual."""
    phone = customer_whatsapp_number(_row_get(row, "phone", ""))
    if not phone:
        return "#"
    status = str(_row_get(row, "status", "scheduled"))
    setting_key = f"wa_msg_{status}"
    with closing(db_conn()) as conn:
        company = get_company_settings(conn)
    template = company.get(setting_key) or DEFAULT_COMPANY_SETTINGS.get(setting_key, "")
    if not template:
        template = "Olá, {cliente}! Temos uma atualização sobre o atendimento #{agendamento} do seu {veiculo} na {empresa}."
    message = render_whatsapp_template(template, row)
    return f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"


def payment_reminder_whatsapp_url(row) -> str:
    """Gera a cobrança/lembrete de pagamento sem depender da forma de pagamento."""
    phone = customer_whatsapp_number(_row_get(row, "phone", ""))
    if not phone:
        return "#"
    with closing(db_conn()) as conn:
        company = get_company_settings(conn)
    template = company.get("wa_msg_payment_pending") or DEFAULT_COMPANY_SETTINGS["wa_msg_payment_pending"]
    message = render_whatsapp_template(template, row)
    return f"https://wa.me/{phone}?text={urllib.parse.quote(message)}"


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def hash_pin(pin: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 120_000)
    return f"{salt}${derived.hex()}"


def verify_pin(pin: str, encoded: str) -> bool:
    try:
        salt, stored = encoded.split("$", 1)
        test = hash_pin(pin, salt).split("$", 1)[1]
        return hmac.compare_digest(test, stored)
    except Exception:
        return False


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits[-11:]


def brl(value):
    if value is None:
        return "A definir"
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date(value):
    if not value:
        return "—"
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return value


def fmt_datetime(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def appointment_datetime(row):
    try:
        return datetime.strptime(f"{row['appointment_date']} {row['appointment_time']}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def hours_until_appointment(row):
    dt = appointment_datetime(row)
    if not dt:
        return -9999
    return (dt - datetime.now()).total_seconds() / 3600



FINANCE_V12_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS finance_revenues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL UNIQUE,
    amount REAL NOT NULL DEFAULT 0,
    payment_method TEXT,
    status TEXT NOT NULL DEFAULT 'paid',
    paid_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS finance_revenue_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL,
    old_amount REAL,
    new_amount REAL,
    old_status TEXT,
    new_status TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS finance_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    expense_date TEXT NOT NULL,
    due_date TEXT,
    paid_date TEXT,
    competence TEXT,
    payment_method TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    supplier TEXT,
    notes TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(category_id) REFERENCES expense_categories(id)
);
CREATE TABLE IF NOT EXISTS investment_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS finance_investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    purchase_date TEXT NOT NULL,
    payment_method TEXT,
    supplier TEXT,
    notes TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(category_id) REFERENCES investment_categories(id)
);
CREATE TABLE IF NOT EXISTS owner_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    contribution_date TEXT NOT NULL,
    payment_method TEXT,
    notes TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS finance_helpers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    default_amount REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS appointment_helper_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL UNIQUE,
    helper_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
    FOREIGN KEY(helper_id) REFERENCES finance_helpers(id)
);
CREATE TABLE IF NOT EXISTS helper_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    helper_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_date TEXT NOT NULL,
    payment_method TEXT,
    notes TEXT,
    cancelled_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(helper_id) REFERENCES finance_helpers(id)
);
CREATE INDEX IF NOT EXISTS idx_fin_expense_date ON finance_expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_fin_expense_paid ON finance_expenses(paid_date,status);
CREATE INDEX IF NOT EXISTS idx_fin_investment_date ON finance_investments(purchase_date);
CREATE INDEX IF NOT EXISTS idx_fin_contribution_date ON owner_contributions(contribution_date);
CREATE INDEX IF NOT EXISTS idx_fin_helper_payment_date ON helper_payments(payment_date);
CREATE TABLE IF NOT EXISTS inventory_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    unit TEXT,
    current_quantity REAL,
    minimum_quantity REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    appointment_id INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES inventory_products(id),
    FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL
);
"""

def init_db():
    schema = r'''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL DEFAULT 'customer',
        phone TEXT UNIQUE,
        pin_hash TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        email TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS vehicle_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS vehicle_brands_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_type TEXT NOT NULL,
        name TEXT NOT NULL,
        search_text TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        synced_at TEXT,
        models_synced_at TEXT,
        UNIQUE(vehicle_type,name)
    );
    CREATE TABLE IF NOT EXISTS vehicle_brand_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_id INTEGER NOT NULL,
        source_code TEXT NOT NULL,
        source_name TEXT NOT NULL,
        UNIQUE(brand_id,source_code),
        FOREIGN KEY(brand_id) REFERENCES vehicle_brands_catalog(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicle_brand_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_id INTEGER NOT NULL,
        alias TEXT NOT NULL,
        search_text TEXT NOT NULL,
        UNIQUE(brand_id,alias),
        FOREIGN KEY(brand_id) REFERENCES vehicle_brands_catalog(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicle_models_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        search_text TEXT NOT NULL,
        suggested_category TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        synced_at TEXT,
        UNIQUE(brand_id,name),
        FOREIGN KEY(brand_id) REFERENCES vehicle_brands_catalog(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicle_model_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id INTEGER NOT NULL,
        alias TEXT NOT NULL,
        search_text TEXT NOT NULL,
        source_code TEXT NOT NULL DEFAULT '',
        UNIQUE(model_id,alias,source_code),
        FOREIGN KEY(model_id) REFERENCES vehicle_models_catalog(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        category_code TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        brand TEXT NOT NULL,
        model TEXT NOT NULL,
        year TEXT,
        color TEXT,
        engine_cc TEXT,
        plate TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS service_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_code TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        duration_minutes INTEGER,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS service_extras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL,
        category_code TEXT,
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS condition_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        category_code TEXT,
        weight INTEGER NOT NULL DEFAULT 1,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        customer_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        appointment_date TEXT NOT NULL,
        appointment_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'scheduled',
        condition_text TEXT,
        condition_flags TEXT,
        dirt_level INTEGER,
        estimated_total REAL,
        duration_minutes INTEGER,
        box_id INTEGER,
        payment_method TEXT,
        payment_status TEXT DEFAULT 'pending',
        discount REAL DEFAULT 0,
        created_at TEXT NOT NULL,
        cancelled_at TEXT,
        FOREIGN KEY(customer_id) REFERENCES customers(id),
        FOREIGN KEY(vehicle_id) REFERENCES vehicles(id),
        FOREIGN KEY(service_id) REFERENCES services(id)
    );
    CREATE TABLE IF NOT EXISTS appointment_extras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        extra_id INTEGER NOT NULL,
        price_snapshot REAL,
        FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE,
        FOREIGN KEY(extra_id) REFERENCES service_extras(id)
    );
    CREATE TABLE IF NOT EXISTS availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_date TEXT,
        appointment_time TEXT,
        available INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS business_hours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        weekday INTEGER UNIQUE NOT NULL,
        is_open INTEGER NOT NULL DEFAULT 0,
        open_time TEXT,
        close_time TEXT,
        lunch_start TEXT,
        lunch_end TEXT
    );
    CREATE TABLE IF NOT EXISTS blocked_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        block_date TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        reason TEXT
    );
    CREATE TABLE IF NOT EXISTS waitlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        desired_date TEXT NOT NULL,
        preference TEXT NOT NULL,
        phone TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS vehicle_conditions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicle_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        kind TEXT NOT NULL DEFAULT 'customer',
        path TEXT NOT NULL,
        social_authorized INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER UNIQUE NOT NULL,
        checked_in_at TEXT NOT NULL,
        mileage TEXT,
        notes TEXT,
        existing_damage TEXT,
        fuel_level TEXT,
        FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS service_status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS vehicle_service_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER NOT NULL,
        appointment_id INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        completed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS visual_inspections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        item TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS additional_service_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        extra_name TEXT NOT NULL,
        price REAL,
        status TEXT NOT NULL DEFAULT 'pending',
        requested_at TEXT NOT NULL,
        decided_at TEXT
    );
    CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER UNIQUE NOT NULL,
        rating INTEGER NOT NULL,
        comment TEXT,
        private_feedback TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS loyalty (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER UNIQUE NOT NULL,
        progress INTEGER NOT NULL DEFAULT 0,
        target INTEGER,
        reward_text TEXT
    );
    CREATE TABLE IF NOT EXISTS loyalty_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        appointment_id INTEGER,
        delta INTEGER NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        code TEXT UNIQUE NOT NULL,
        referred_phone TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER,
        appointment_id INTEGER,
        type TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        appointment_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS service_boxes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS promotions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        start_date TEXT,
        end_date TEXT,
        image_path TEXT,
        audience TEXT,
        active INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS payment_methods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS gallery_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_path TEXT NOT NULL,
        title TEXT,
        caption TEXT,
        vehicle_type TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    '''
    with closing(db_conn()) as conn:
        conn.executescript(schema)
        conn.executescript(FINANCE_V12_SCHEMA)
        vehicle_cols = {row[1] for row in conn.execute("PRAGMA table_info(vehicles)").fetchall()}
        if "brand_catalog_id" not in vehicle_cols:
            conn.execute("ALTER TABLE vehicles ADD COLUMN brand_catalog_id INTEGER")
        if "model_catalog_id" not in vehicle_cols:
            conn.execute("ALTER TABLE vehicles ADD COLUMN model_catalog_id INTEGER")
        for code, name in [("moto", "MOTO"), ("car_small", "CARRO PEQUENO/MÉDIO"), ("car_large", "CARRO GRANDE")]:
            conn.execute("INSERT OR IGNORE INTO vehicle_categories(code,name) VALUES (?,?)", (code, name))
            conn.execute("INSERT OR IGNORE INTO service_categories(code,name) VALUES (?,?)", (code, name))
        if conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
            services = [
                ("moto", "Lavagem Simples", "Serviço de manutenção e limpeza essencial do veículo.", 40.0, None, 1),
                ("moto", "Lavagem Detalhada + Cera", "Limpeza mais criteriosa, atenção aos detalhes e aplicação de cera para acabamento e proteção.", 70.0, None, 2),
                ("moto", "Lavagem Detalhada + Cera + Verniz no Motor", "Limpeza detalhada com cera e verniz no motor.", 90.0, None, 3),
                ("car_small", "Lavagem Simples", "Serviço de manutenção e limpeza essencial do veículo.", 70.0, None, 1),
                ("car_small", "Lavagem Detalhada + Cera", "Limpeza mais criteriosa, atenção aos detalhes e aplicação de cera para acabamento e proteção.", 90.0, None, 2),
                ("car_small", "Lavagem Completa", "Serviço mais completo, envolvendo cuidados externos e limpeza interna.", 130.0, None, 3),
                ("car_large", "Lavagem Simples", "Serviço de manutenção e limpeza essencial do veículo.", 90.0, None, 1),
                ("car_large", "Lavagem Detalhada + Cera", "Limpeza mais criteriosa, atenção aos detalhes e aplicação de cera para acabamento e proteção.", 120.0, None, 2),
                ("car_large", "Lavagem Completa", "Serviço mais completo, envolvendo cuidados externos e limpeza interna.", 160.0, None, 3),
            ]
            conn.executemany("INSERT INTO services(category_code,name,description,price,duration_minutes,sort_order) VALUES (?,?,?,?,?,?)", services)
        if conn.execute("SELECT COUNT(*) FROM service_extras").fetchone()[0] == 0:
            extras = [
                "Verniz no motor", "Higienização de bancos", "Limpeza de bancos", "Remoção de pelos de animais",
                "Proteção de vidros", "Remoção de marcas de chuva", "Revitalização de plásticos", "Outros"
            ]
            # Os adicionais iniciais ficam na categoria CARRO. Motos têm uma lista independente.
            conn.executemany("INSERT INTO service_extras(name,price,category_code,active) VALUES (?,NULL,'car',1)", [(x,) for x in extras])
        # Migração V3: adicionais antigos sem categoria passam a ser de carro.
        if setting(conn, "extras_scope_migrated_v3", "") != "1":
            conn.execute("UPDATE service_extras SET category_code='car' WHERE category_code IS NULL OR category_code='' ")
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('extras_scope_migrated_v3','1')")
        if conn.execute("SELECT COUNT(*) FROM condition_questions").fetchone()[0] == 0:
            questions = [
                ("Pouco sujo", None, 1, 1),
                ("Sujeira normal", None, 1, 2),
                ("Muito sujo", None, 2, 3),
                ("Barro / estrada de terra", None, 2, 4),
                ("Muita poeira", None, 2, 5),
                ("Rodas muito sujas", None, 1, 6),
                ("Interior muito sujo", "car", 2, 7),
                ("Bancos sujos", "car", 2, 8),
                ("Manchas", None, 2, 9),
                ("Pelos de animais", "car", 2, 10),
                ("Areia", "car", 2, 11),
                ("Mau cheiro", "car", 2, 12),
                ("Outro", None, 1, 13),
            ]
            conn.executemany("INSERT INTO condition_questions(label,category_code,weight,sort_order) VALUES (?,?,?,?)", questions)
        for wd in range(7):
            conn.execute("INSERT OR IGNORE INTO business_hours(weekday,is_open) VALUES (?,0)", (wd,))
        defaults = {
            "interval_minutes": "0",
            "simultaneous_capacity": "1",
            "loyalty_target": "",
            "loyalty_reward": "",
            **DEFAULT_COMPANY_SETTINGS,
        }
        for k,v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k,v))
        # V12: categorias financeiras iniciais editáveis.
        expense_names = [
            "Produtos químicos", "Água", "Energia", "Ajudantes/mão de obra", "Materiais",
            "Manutenção", "Marketing", "Sistema/assinaturas", "Taxas de pagamento", "Outras despesas"
        ]
        for idx, name in enumerate(expense_names, 1):
            conn.execute("INSERT OR IGNORE INTO expense_categories(name,active,sort_order) VALUES (?,1,?)", (name, idx))
        investment_names = ["Equipamentos", "Estrutura", "Ferramentas", "Marketing inicial", "Tecnologia", "Outros"]
        for idx, name in enumerate(investment_names, 1):
            conn.execute("INSERT OR IGNORE INTO investment_categories(name,active,sort_order) VALUES (?,1,?)", (name, idx))
        # Migra pagamentos já existentes sem duplicar receitas.
        conn.execute("""
            INSERT OR IGNORE INTO finance_revenues(appointment_id,amount,payment_method,status,paid_at,updated_at)
            SELECT a.id, COALESCE(a.estimated_total-COALESCE(a.discount,0),0), a.payment_method,
                   CASE WHEN a.payment_status='paid' AND a.status!='cancelled' THEN 'paid' ELSE 'reversed' END,
                   COALESCE((SELECT MAX(p.created_at) FROM payments p WHERE p.appointment_id=a.id AND p.status='paid'),a.created_at), ?
            FROM appointments a WHERE a.payment_status='paid'
        """, (now_iso(),))
        if setting(conn, "vehicle_catalog_brands_seeded", "") != "2026-08-30":
            seed_vehicle_catalog_brands(conn)
        # Migração V4: reviews podem ser exibidas na home quando autorizadas pelo cliente.
        review_cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
        if "show_on_home" not in review_cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN show_on_home INTEGER NOT NULL DEFAULT 1")
            review_cols.add("show_on_home")
        if "client_authorized_home" not in review_cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN client_authorized_home INTEGER NOT NULL DEFAULT 1")
            conn.execute("UPDATE reviews SET client_authorized_home=COALESCE(show_on_home,1)")
        if "admin_visible" not in review_cols:
            conn.execute("ALTER TABLE reviews ADD COLUMN admin_visible INTEGER NOT NULL DEFAULT 1")
            conn.execute("UPDATE reviews SET admin_visible=COALESCE(show_on_home,1)")
        # Migração V5: financeiro registra valor final efetivamente cobrado.
        appt_cols = {row[1] for row in conn.execute("PRAGMA table_info(appointments)").fetchall()}
        if "final_total" not in appt_cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN final_total REAL")
            appt_cols.add("final_total")
        if "payment_reminder_count" not in appt_cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN payment_reminder_count INTEGER NOT NULL DEFAULT 0")
            appt_cols.add("payment_reminder_count")
        if "payment_reminder_last_at" not in appt_cols:
            conn.execute("ALTER TABLE appointments ADD COLUMN payment_reminder_last_at TEXT")
            appt_cols.add("payment_reminder_last_at")
        conn.execute("UPDATE appointments SET final_total=COALESCE(final_total, estimated_total-COALESCE(discount,0))")
        conn.execute("""UPDATE finance_revenues SET amount=COALESCE((SELECT a.final_total FROM appointments a WHERE a.id=finance_revenues.appointment_id),amount) WHERE appointment_id IN (SELECT id FROM appointments WHERE payment_status='paid')""")
        # Migração V11: corrige os modelos antigos com 'seu veículo' somente se o usuário ainda não os personalizou.
        old_wa_defaults = {
            "wa_msg_scheduled": "Olá, {cliente}! Seu agendamento #{agendamento} na PH ESTÉTICA & DETAIL está confirmado para o seu {veiculo}. Serviço: {servico}. Data: {data} às {horario}.",
            "wa_msg_received": "Olá, {cliente}! Recebemos seu {veiculo} na PH ESTÉTICA & DETAIL. Já vamos iniciar os cuidados.",
            "wa_msg_preparation": "Olá, {cliente}! Seu {veiculo} está em preparação para o atendimento na PH ESTÉTICA & DETAIL.",
            "wa_msg_washing": "Olá, {cliente}! Iniciamos a lavagem do seu {veiculo} na PH ESTÉTICA & DETAIL.",
            "wa_msg_detailing": "Olá, {cliente}! Seu {veiculo} está na etapa de detalhamento na PH ESTÉTICA & DETAIL.",
            "wa_msg_finishing": "Olá, {cliente}! Estamos finalizando os cuidados com seu {veiculo} na PH ESTÉTICA & DETAIL.",
            "wa_msg_inspection": "Olá, {cliente}! Seu {veiculo} está na inspeção final na PH ESTÉTICA & DETAIL.",
            "wa_msg_ready": "Olá, {cliente}! ✨ Seu {veiculo} está pronto para retirada na PH ESTÉTICA & DETAIL. Agradecemos pela confiança!",
            "wa_msg_completed": "Olá, {cliente}! O atendimento do seu {veiculo} foi finalizado. Obrigado por confiar na PH ESTÉTICA & DETAIL! ✨",
            "wa_msg_cancelled": "Olá, {cliente}! O agendamento #{agendamento} do seu {veiculo} foi cancelado. Se precisar, estamos à disposição pelo WhatsApp.",
        }
        if setting(conn, "wa_neutral_vehicle_migrated_v11", "") != "1":
            for key, old_value in old_wa_defaults.items():
                current = setting(conn, key, "")
                if current == old_value:
                    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, DEFAULT_COMPANY_SETTINGS[key]))
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('wa_neutral_vehicle_migrated_v11','1')")
        # Formas de pagamento editáveis. Cartão começa desativado porque pode não haver maquininha.
        if conn.execute("SELECT COUNT(*) FROM payment_methods").fetchone()[0] == 0:
            conn.executemany("INSERT INTO payment_methods(code,name,active,sort_order) VALUES (?,?,?,?)", [
                ("pix","PIX",1,1), ("cash","Dinheiro",1,2), ("card","Cartão",0,3)
            ])
        conn.commit()


def setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def current_customer(request: Request):
    cid = request.session.get("customer_id")
    if not cid:
        return None
    with closing(db_conn()) as conn:
        return conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()


def require_admin(request: Request):
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=401)


def parse_time(t: str):
    return datetime.strptime(t, "%H:%M")


def overlap(start1, end1, start2, end2):
    return start1 < end2 and start2 < end1


def _available_slots_with_conn(conn, target_date: str, service_id: int):
    service = conn.execute("SELECT * FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
    if not service or not service["duration_minutes"]:
        return [], "A duração desse serviço ainda não foi configurada."
    try:
        d = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return [], "Data inválida."
    if d < date.today():
        return [], "Não é possível agendar uma data que já passou."
    bh = conn.execute("SELECT * FROM business_hours WHERE weekday=?", (d.weekday(),)).fetchone()
    if not bh or not bh["is_open"] or not bh["open_time"] or not bh["close_time"]:
        return [], "A empresa não possui expediente configurado para esse dia."
    blocked = conn.execute("SELECT * FROM blocked_times WHERE block_date=?", (target_date,)).fetchall()
    duration = int(service["duration_minutes"])
    interval = int(setting(conn, "interval_minutes", "0") or 0)
    capacity = max(1, int(setting(conn, "simultaneous_capacity", "1") or 1))
    open_dt = datetime.combine(d, parse_time(bh["open_time"]).time())
    close_dt = datetime.combine(d, parse_time(bh["close_time"]).time())
    step = 30
    cur = open_dt
    slots = []
    appointments = conn.execute("""
        SELECT a.*, s.duration_minutes service_duration FROM appointments a
        JOIN services s ON s.id=a.service_id
        WHERE a.appointment_date=? AND a.status NOT IN ('cancelled','completed')
    """, (target_date,)).fetchall()
    while cur + timedelta(minutes=duration) <= close_dt:
        end = cur + timedelta(minutes=duration)
        valid = True
        if d == date.today() and cur <= datetime.now():
            valid = False
        if bh["lunch_start"] and bh["lunch_end"]:
            ls = datetime.combine(d, parse_time(bh["lunch_start"]).time())
            le = datetime.combine(d, parse_time(bh["lunch_end"]).time())
            if overlap(cur, end, ls, le):
                valid = False
        for b in blocked:
            if not b["start_time"] or not b["end_time"]:
                valid = False
                break
            bs = datetime.combine(d, parse_time(b["start_time"]).time())
            be = datetime.combine(d, parse_time(b["end_time"]).time())
            if overlap(cur, end, bs, be):
                valid = False
                break
        if valid:
            concurrent = 0
            for a in appointments:
                ast = datetime.combine(d, parse_time(a["appointment_time"]).time())
                a_duration = int(a["duration_minutes"] or a["service_duration"] or 0)
                aend = ast + timedelta(minutes=a_duration + interval)
                if overlap(cur, end + timedelta(minutes=interval), ast, aend):
                    concurrent += 1
            if concurrent < capacity:
                slots.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=step)
    return slots, None


def available_slots(target_date: str, service_id: int):
    with closing(db_conn()) as conn:
        return _available_slots_with_conn(conn, target_date, service_id)


def next_available():
    with closing(db_conn()) as conn:
        svc = conn.execute("SELECT id FROM services WHERE active=1 AND duration_minutes IS NOT NULL ORDER BY id LIMIT 1").fetchone()
    if not svc:
        return None
    for i in range(14):
        d = date.today() + timedelta(days=i)
        slots, _ = available_slots(d.isoformat(), svc["id"])
        if slots:
            return {"date": d.isoformat(), "time": slots[0]}
    return None


def get_or_create_customer(conn, name: str, phone: str):
    phone = normalize_phone(phone)
    row = conn.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
    if row:
        if name and row["name"] != name:
            conn.execute("UPDATE customers SET name=? WHERE id=?", (name, row["id"]))
            row = conn.execute("SELECT * FROM customers WHERE id=?", (row["id"],)).fetchone()
        return row
    cur = conn.execute("INSERT INTO customers(name,phone,created_at) VALUES (?,?,?)", (name, phone, now_iso()))
    return conn.execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone()


def create_vehicle(conn, customer_id, category, vehicle_type, brand, model, year, color, engine_cc, plate, brand_catalog_id=None, model_catalog_id=None):
    cur = conn.execute("""
        INSERT INTO vehicles(customer_id,category_code,vehicle_type,brand,model,year,color,engine_cc,plate,brand_catalog_id,model_catalog_id,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (customer_id,category,vehicle_type,brand,model,year,color,engine_cc,plate,brand_catalog_id,model_catalog_id,now_iso()))
    return cur.lastrowid


def appointment_detail(conn, appointment_id):
    return conn.execute("""
        SELECT a.*, c.name customer_name, c.phone, v.brand, v.model, v.year, v.color, v.plate, v.category_code,
               s.name service_name, s.price service_price
        FROM appointments a
        JOIN customers c ON c.id=a.customer_id
        JOIN vehicles v ON v.id=a.vehicle_id
        JOIN services s ON s.id=a.service_id
        WHERE a.id=?
    """, (appointment_id,)).fetchone()



def _money(value, default=0.0):
    if value is None:
        return float(default)
    raw = str(value).strip().replace("R$", "").replace(" ", "")
    if not raw:
        return float(default)
    try:
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        return float(raw)
    except (ValueError, TypeError):
        return float(default)


def format_competence(value):
    if not value:
        return "—"
    try:
        dt = datetime.strptime(value[:7], "%Y-%m")
        months = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
        return f"{months[dt.month-1]}/{dt.year}"
    except Exception:
        return value


def _finance_period(request: Request):
    today = date.today()
    mode = request.query_params.get("period", "this_month")
    start_q = request.query_params.get("start", "")
    end_q = request.query_params.get("end", "")
    if mode == "today":
        start = end = today
    elif mode == "week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif mode == "last_month":
        first = today.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
    elif mode == "year":
        start = date(today.year,1,1); end = today
    elif mode == "custom" and start_q and end_q:
        try:
            start = datetime.strptime(start_q, "%Y-%m-%d").date()
            end = datetime.strptime(end_q, "%Y-%m-%d").date()
        except ValueError:
            start = today.replace(day=1); end = today
        if end < start: start, end = end, start
    else:
        mode = "this_month"
        start = today.replace(day=1); end = today
    return {"mode":mode,"start":start.isoformat(),"end":end.isoformat(),"start_date":start,"end_date":end}


def sync_finance_revenue(conn, appointment_id: int, note="Pagamento atualizado"):
    a = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
    if not a:
        return
    desired_status = "paid" if a["payment_status"] == "paid" and a["status"] != "cancelled" else "reversed"
    amount = max(0.0, float(a["final_total"] if a["final_total"] is not None else (float(a["estimated_total"] or 0)-float(a["discount"] or 0))))
    current = conn.execute("SELECT * FROM finance_revenues WHERE appointment_id=?", (appointment_id,)).fetchone()
    paid_row = conn.execute("SELECT MAX(created_at) paid_at FROM payments WHERE appointment_id=? AND status='paid'", (appointment_id,)).fetchone()
    paid_at = (paid_row["paid_at"] if paid_row and paid_row["paid_at"] else now_iso()) if desired_status == "paid" else (current["paid_at"] if current else None)
    if current:
        changed = abs(float(current["amount"] or 0)-amount) > 0.001 or current["status"] != desired_status or (current["payment_method"] or "") != (a["payment_method"] or "")
        if changed:
            conn.execute("INSERT INTO finance_revenue_history(appointment_id,old_amount,new_amount,old_status,new_status,note,created_at) VALUES (?,?,?,?,?,?,?)",
                         (appointment_id,current["amount"],amount,current["status"],desired_status,note,now_iso()))
            conn.execute("UPDATE finance_revenues SET amount=?,payment_method=?,status=?,paid_at=?,updated_at=? WHERE appointment_id=?",
                         (amount,a["payment_method"],desired_status,paid_at,now_iso(),appointment_id))
    elif a["payment_status"] == "paid":
        conn.execute("INSERT INTO finance_revenues(appointment_id,amount,payment_method,status,paid_at,updated_at) VALUES (?,?,?,?,?,?)",
                     (appointment_id,amount,a["payment_method"],desired_status,paid_at,now_iso()))
        conn.execute("INSERT INTO finance_revenue_history(appointment_id,old_amount,new_amount,old_status,new_status,note,created_at) VALUES (?,?,?,?,?,?,?)",
                     (appointment_id,None,amount,None,desired_status,"Receita criada a partir do pagamento",now_iso()))


def _finance_summary(conn, start: str, end: str):
    revenue = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_revenues WHERE status='paid' AND substr(paid_at,1,10) BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    paid_expenses = conn.execute("SELECT COALESCE(SUM(e.amount),0) FROM finance_expenses e WHERE e.status='paid' AND e.cancelled_at IS NULL AND COALESCE(e.paid_date,e.expense_date) BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    helper_generated = conn.execute("""SELECT COALESCE(SUM(h.amount),0) FROM appointment_helper_costs h JOIN appointments a ON a.id=h.appointment_id WHERE a.status!='cancelled' AND a.appointment_date BETWEEN ? AND ?""", (start,end)).fetchone()[0] or 0
    helper_paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM helper_payments WHERE cancelled_at IS NULL AND payment_date BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    investments = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_investments WHERE cancelled_at IS NULL AND purchase_date BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    contributions = conn.execute("SELECT COALESCE(SUM(amount),0) FROM owner_contributions WHERE cancelled_at IS NULL AND contribution_date BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    services = conn.execute("SELECT COUNT(*) FROM appointments WHERE status='completed' AND appointment_date BETWEEN ? AND ?", (start,end)).fetchone()[0] or 0
    categories = {r["name"]: float(r["total"] or 0) for r in conn.execute("""SELECT c.name,COALESCE(SUM(e.amount),0) total FROM expense_categories c LEFT JOIN finance_expenses e ON e.category_id=c.id AND e.status='paid' AND e.cancelled_at IS NULL AND COALESCE(e.paid_date,e.expense_date) BETWEEN ? AND ? GROUP BY c.id""", (start,end)).fetchall()}
    # Resultado gerencial usa custo de ajudante GERADO; caixa usa pagamento efetivamente realizado.
    operating_profit = float(revenue) - float(paid_expenses) - float(helper_generated)
    return {
        "revenue":float(revenue), "expenses":float(paid_expenses), "helper_generated":float(helper_generated), "helper_paid":float(helper_paid),
        "investments":float(investments), "contributions":float(contributions), "services":int(services),
        "ticket": float(revenue)/services if services else 0.0, "operating_profit":operating_profit, "categories":categories,
        "products":categories.get("Produtos químicos",0.0), "water":categories.get("Água",0.0), "energy":categories.get("Energia",0.0),
        "other_expenses":max(0.0,float(paid_expenses)-categories.get("Produtos químicos",0.0)-categories.get("Água",0.0)-categories.get("Energia",0.0)),
    }


def _finance_all_time(conn):
    start = "1900-01-01"; end = "2999-12-31"
    s = _finance_summary(conn,start,end)
    total_invested = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_investments WHERE cancelled_at IS NULL").fetchone()[0] or 0
    total_contributions = conn.execute("SELECT COALESCE(SUM(amount),0) FROM owner_contributions WHERE cancelled_at IS NULL").fetchone()[0] or 0
    cash = float(total_contributions) + s["revenue"] - s["expenses"] - s["helper_paid"] - float(total_invested)
    recovered = min(float(total_invested), max(0.0,s["operating_profit"]))
    pending_helper = max(0.0,s["helper_generated"]-s["helper_paid"])
    pending_expenses = conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_expenses WHERE status='pending' AND cancelled_at IS NULL").fetchone()[0] or 0
    s.update({"total_invested":float(total_invested),"total_contributions":float(total_contributions),"cash":cash,"recovered":recovered,
              "recovery_pct":(recovered/float(total_invested)*100 if total_invested else 0),"remaining_recovery":max(0.0,float(total_invested)-recovered),
              "pending_helper":pending_helper,"pending_expenses":float(pending_expenses),"company_cash_generation":s["revenue"]-s["expenses"]-s["helper_paid"]})
    return s


def _cashflow_rows(conn, start, end, kind="all"):
    rows=[]
    if kind in {"all","receitas"}:
        for r in conn.execute("""SELECT fr.id,substr(fr.paid_at,1,10) d,fr.amount,a.code,c.name customer_name,v.brand,v.model FROM finance_revenues fr JOIN appointments a ON a.id=fr.appointment_id JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id WHERE fr.status='paid' AND substr(fr.paid_at,1,10) BETWEEN ? AND ?""",(start,end)):
            rows.append({"date":r["d"],"type":"Receita","description":f"Atendimento {r['code']} · {r['customer_name']} · {r['brand']} {r['model']}","amount":float(r["amount"]),"direction":1})
    if kind in {"all","despesas"}:
        for r in conn.execute("""SELECT e.*,c.name category_name FROM finance_expenses e JOIN expense_categories c ON c.id=e.category_id WHERE e.status='paid' AND e.cancelled_at IS NULL AND COALESCE(e.paid_date,e.expense_date) BETWEEN ? AND ?""",(start,end)):
            rows.append({"date":r["paid_date"] or r["expense_date"],"type":"Despesa","description":f"{r['description']} · {r['category_name']}","amount":float(r["amount"]),"direction":-1})
    if kind in {"all","investimentos"}:
        for r in conn.execute("SELECT * FROM finance_investments WHERE cancelled_at IS NULL AND purchase_date BETWEEN ? AND ?",(start,end)):
            rows.append({"date":r["purchase_date"],"type":"Investimento","description":r["description"],"amount":float(r["amount"]),"direction":-1})
    if kind in {"all","aportes"}:
        for r in conn.execute("SELECT * FROM owner_contributions WHERE cancelled_at IS NULL AND contribution_date BETWEEN ? AND ?",(start,end)):
            rows.append({"date":r["contribution_date"],"type":"Aporte","description":r["description"],"amount":float(r["amount"]),"direction":1})
    if kind in {"all","ajudantes"}:
        for r in conn.execute("""SELECT hp.*,h.name helper_name FROM helper_payments hp JOIN finance_helpers h ON h.id=hp.helper_id WHERE hp.cancelled_at IS NULL AND hp.payment_date BETWEEN ? AND ?""",(start,end)):
            rows.append({"date":r["payment_date"],"type":"Ajudante","description":f"Pagamento · {r['helper_name']}","amount":float(r["amount"]),"direction":-1})
    rows.sort(key=lambda x:(x["date"],x["type"],x["description"]))
    balance=0.0
    for r in rows:
        balance += r["amount"]*r["direction"]
        r["balance"] = balance
    return rows


def _finance_monthly(conn, year):
    out=[]; running_profit=0.0
    total_inv=0.0
    for m in range(1,13):
        start=f"{year}-{m:02d}-01"
        if m==12: end=f"{year}-12-31"
        else: end=(date(year,m+1,1)-timedelta(days=1)).isoformat()
        s=_finance_summary(conn,start,end)
        inv=conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_investments WHERE cancelled_at IS NULL AND purchase_date BETWEEN ? AND ?",(start,end)).fetchone()[0] or 0
        total_inv += float(inv); running_profit += s["operating_profit"]
        recovered=min(total_inv,max(0.0,running_profit))
        out.append({"month":m,"label":["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"][m-1],"revenue":s["revenue"],"expenses":s["expenses"]+s["helper_generated"],"result":s["operating_profit"],"recovery_pct":(recovered/total_inv*100 if total_inv else 0)})
    return out


def template_ctx(request: Request, **kwargs):
    try:
        with closing(db_conn()) as conn:
            company = get_company_settings(conn)
            logo_path = setting(conn, "brand_logo_path", "")
    except Exception:
        company = dict(DEFAULT_COMPANY_SETTINGS)
        logo_path = ""
    wa = re.sub(r"\D", "", company.get("whatsapp_number") or WHATSAPP_NUMBER) or WHATSAPP_NUMBER
    display = WHATSAPP_DISPLAY
    if len(wa) >= 12 and wa.startswith("55"):
        local = wa[2:]
        if len(local) == 11:
            display = f"({local[:2]}) {local[2:7]}-{local[7:]}"
    return {
        "request": request,
        "business_name": BUSINESS_NAME,
        "whatsapp_display": display,
        "whatsapp_number": wa,
        "customer": current_customer(request),
        "status_labels": STATUS_LABELS,
        "brl": brl,
        "fmt_date": fmt_date,
        "fmt_datetime": fmt_datetime,
        "payment_label": payment_label,
        "payment_labels": PAYMENT_LABELS,
        "format_competence": format_competence,
        "first_name": first_name,
        "format_phone_br": format_phone_br,
        "status_whatsapp_url": status_whatsapp_url,
        "company": company,
        "brand_logo_url": (f"/uploads/{logo_path}" if logo_path else "/static/site_mark.svg"),
        **kwargs,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    upcoming = next_available()
    with closing(db_conn()) as conn:
        promos = conn.execute("SELECT * FROM promotions WHERE active=1 ORDER BY id DESC LIMIT 3").fetchall()
        reviews = conn.execute("""
            SELECT r.rating, r.comment, r.created_at, c.name customer_name, v.brand, v.model
            FROM reviews r
            JOIN appointments a ON a.id=r.appointment_id
            JOIN customers c ON c.id=a.customer_id
            JOIN vehicles v ON v.id=a.vehicle_id
            WHERE COALESCE(r.client_authorized_home,1)=1 AND COALESCE(r.admin_visible,1)=1 AND TRIM(COALESCE(r.comment,'')) <> ''
            ORDER BY r.id DESC LIMIT 6
        """).fetchall()
        review_stats = conn.execute("SELECT COUNT(*) total, COALESCE(AVG(rating),0) avg_rating FROM reviews").fetchone()
        total_services = conn.execute("SELECT COUNT(*) FROM appointments WHERE status IN ('completed','ready')").fetchone()[0]
        home_services = conn.execute("SELECT * FROM services WHERE active=1 ORDER BY category_code,sort_order,id LIMIT 9").fetchall()
        gallery = conn.execute("SELECT * FROM gallery_items WHERE active=1 ORDER BY sort_order,id DESC LIMIT 8").fetchall()
        company = get_company_settings(conn)
    return templates.TemplateResponse(request, "home.html", template_ctx(request, upcoming=upcoming, promos=promos, reviews=reviews, review_stats=review_stats, total_services=total_services, home_services=home_services, gallery=gallery, home_company=company))


@app.get("/api/vehicle-brands")
def api_vehicle_brands(vehicle_type: str, q: str = "", limit: int = 12):
    if vehicle_type not in {"car","moto"}: raise HTTPException(400,"Tipo inválido")
    qn=normalize_search(q); limit=max(1,min(30,limit))
    with closing(db_conn()) as conn:
        count=conn.execute("SELECT COUNT(*) FROM vehicle_brands_catalog WHERE vehicle_type=?", (vehicle_type,)).fetchone()[0]
        if count==0:
            seed_vehicle_catalog_brands(conn); conn.commit()
        params=[vehicle_type]
        where="b.vehicle_type=? AND b.active=1"
        if qn:
            where+=" AND (b.search_text LIKE ? OR EXISTS(SELECT 1 FROM vehicle_brand_aliases ba WHERE ba.brand_id=b.id AND ba.search_text LIKE ?))"
            params.extend([f"%{qn}%",f"%{qn}%"])
        rows=conn.execute(f"SELECT b.id,b.name,b.models_synced_at FROM vehicle_brands_catalog b WHERE {where} ORDER BY CASE WHEN b.search_text LIKE ? THEN 0 ELSE 1 END,b.name LIMIT ?", (*params,f"{qn}%" if qn else "%",limit)).fetchall()
    return {"items":[dict(r) for r in rows]}


@app.get("/api/vehicle-models")
def api_vehicle_models(brand_id: int, q: str = "", limit: int = 15):
    qn=normalize_search(q); limit=max(1,min(40,limit)); sync_error=None
    with closing(db_conn()) as conn:
        brand=conn.execute("SELECT * FROM vehicle_brands_catalog WHERE id=? AND active=1", (brand_id,)).fetchone()
        if not brand: raise HTTPException(404,"Marca não encontrada")
        count=conn.execute("SELECT COUNT(*) FROM vehicle_models_catalog WHERE brand_id=?", (brand_id,)).fetchone()[0]
        if count==0:
            try: sync_vehicle_models_for_brand(conn,brand_id)
            except Exception as exc: sync_error=str(exc)
        params=[brand_id]
        where="m.brand_id=? AND m.active=1"
        if qn:
            where+=" AND (m.search_text LIKE ? OR EXISTS(SELECT 1 FROM vehicle_model_aliases ma WHERE ma.model_id=m.id AND ma.search_text LIKE ?))"
            params.extend([f"%{qn}%",f"%{qn}%"])
        rows=conn.execute(f"SELECT m.id,m.name,m.suggested_category FROM vehicle_models_catalog m WHERE {where} ORDER BY CASE WHEN m.search_text LIKE ? THEN 0 ELSE 1 END,m.name LIMIT ?", (*params,f"{qn}%" if qn else "%",limit)).fetchall()
    return {"items":[dict(r) for r in rows],"sync_error":sync_error}


@app.get("/api/services")
def api_services(category: str):
    if category not in {"moto", "car_small", "car_large"}:
        raise HTTPException(400, "Categoria inválida.")
    with closing(db_conn()) as conn:
        rows = conn.execute("SELECT * FROM services WHERE category_code=? AND active=1 ORDER BY sort_order,id", (category,)).fetchall()
        extras_all = conn.execute("SELECT * FROM service_extras WHERE active=1 ORDER BY id").fetchall()
        questions_all = conn.execute("SELECT * FROM condition_questions WHERE active=1 ORDER BY sort_order,id").fetchall()
        extras = [dict(r) for r in extras_all if scope_matches(r["category_code"], category)]
        conditions = [dict(r) for r in questions_all if scope_matches(r["category_code"], category)]
    return {"services": [dict(r) for r in rows], "extras": extras, "conditions": conditions}


@app.get("/api/availability")
def api_availability(date: str, service_id: int):
    slots, message = available_slots(date, service_id)
    return {"slots": slots, "message": message}


@app.get("/api/calendar-availability")
def api_calendar_availability(year: int, month: int, service_id: int):
    if year < date.today().year or year > date.today().year + 2 or month < 1 or month > 12:
        raise HTTPException(400, "Mês inválido.")
    try:
        first = date(year, month, 1)
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
    except ValueError:
        raise HTTPException(400, "Mês inválido.")

    days = []
    with closing(db_conn()) as conn:
        service = conn.execute("SELECT id FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
        if not service:
            raise HTTPException(404, "Serviço não encontrado.")
        current = first
        while current < next_month:
            iso = current.isoformat()
            if current < date.today():
                days.append({"date": iso, "status": "past", "count": 0})
            else:
                slots, message = _available_slots_with_conn(conn, iso, service_id)
                if slots:
                    status = "available"
                elif message and "expediente" in message.lower():
                    status = "closed"
                else:
                    status = "full"
                days.append({"date": iso, "status": status, "count": len(slots)})
            current += timedelta(days=1)
    return {"year": year, "month": month, "days": days}


@app.get("/agendar", response_class=HTMLResponse)
def booking_page(request: Request):
    prefill = {
        "vehicle_id": request.query_params.get("vehicle_id", ""),
        "service_id": request.query_params.get("service_id", ""),
    }
    saved = []
    customer = current_customer(request)
    with closing(db_conn()) as conn:
        if customer:
            saved = conn.execute("SELECT * FROM vehicles WHERE customer_id=? ORDER BY id DESC", (customer["id"],)).fetchall()
        payment_methods = get_payment_methods(conn, active_only=True)
    return templates.TemplateResponse(request, "booking.html", template_ctx(request, prefill=prefill, saved=saved, payment_methods=payment_methods))


@app.post("/agendar")
async def create_booking(
    request: Request,
    customer_name: str = Form(...), phone: str = Form(...),
    category: str = Form(...), vehicle_type: str = Form(...), saved_vehicle_id: str = Form(""), brand: str = Form(...), model: str = Form(...), brand_catalog_id: str = Form(""), model_catalog_id: str = Form(""),
    year: str = Form(""), color: str = Form(""), engine_cc: str = Form(""), plate: str = Form(""),
    service_id: int = Form(...), extras: str = Form(""), condition_flags: str = Form(""),
    condition_text: str = Form(""), dirt_level: int = Form(1), appointment_date: str = Form(...), appointment_time: str = Form(...),
    payment_method: str = Form(...), social_authorized: str = Form("0"), photos: list[UploadFile] = File(default=[]),
):
    phone_norm = normalize_phone(phone)
    if len(phone_norm) < 10:
        raise HTTPException(400, "Telefone inválido")
    with closing(db_conn()) as conn:
        # BEGIN IMMEDIATE serializa a confirmação e evita duas reservas simultâneas no mesmo último horário.
        conn.execute("BEGIN IMMEDIATE")
        pm = conn.execute("SELECT * FROM payment_methods WHERE code=? AND active=1", (payment_method,)).fetchone()
        if not pm:
            raise HTTPException(400, "Forma de pagamento indisponível.")
        brand, model, resolved_brand_id, resolved_model_id = resolve_catalog_vehicle(conn, vehicle_type, brand_catalog_id, model_catalog_id, brand, model)
        if not brand or not model:
            raise HTTPException(400, "Informe marca e modelo do veículo.")
        slots, message = _available_slots_with_conn(conn, appointment_date, service_id)
        if appointment_time not in slots:
            raise HTTPException(409, message or "Horário indisponível. Atualize a agenda e escolha outro horário.")
        service = conn.execute("SELECT * FROM services WHERE id=? AND active=1", (service_id,)).fetchone()
        if not service or service["category_code"] != category:
            raise HTTPException(400, "Serviço inválido para a categoria selecionada.")
        customer = get_or_create_customer(conn, customer_name.strip(), phone_norm)
        vehicle_id = None
        if saved_vehicle_id.strip().isdigit():
            saved = conn.execute("SELECT * FROM vehicles WHERE id=? AND customer_id=?", (int(saved_vehicle_id), customer["id"])).fetchone()
            if saved and saved["category_code"] == category:
                vehicle_id = saved["id"]
                conn.execute("UPDATE vehicles SET brand=?,model=?,year=?,color=?,engine_cc=?,plate=?,brand_catalog_id=COALESCE(?,brand_catalog_id),model_catalog_id=COALESCE(?,model_catalog_id) WHERE id=?",
                             (brand.strip(),model.strip(),year,color,engine_cc,plate,resolved_brand_id,resolved_model_id,vehicle_id))
        if vehicle_id is None:
            vehicle_id = create_vehicle(conn, customer["id"], category, vehicle_type, brand.strip(), model.strip(), year, color, engine_cc, plate, resolved_brand_id, resolved_model_id)
        extra_ids = [int(x) for x in extras.split(",") if x.strip().isdigit()]
        extras_rows = []
        if extra_ids:
            q = ",".join("?" * len(extra_ids))
            raw_extras = conn.execute(f"SELECT * FROM service_extras WHERE id IN ({q}) AND active=1", extra_ids).fetchall()
            extras_rows = [x for x in raw_extras if scope_matches(x["category_code"], category)]
            if len(extras_rows) != len(set(extra_ids)):
                raise HTTPException(400, "Existe adicional inválido para essa categoria de veículo.")
        condition_ids = [int(x) for x in condition_flags.split(",") if x.strip().isdigit()]
        condition_rows = []
        if condition_ids:
            q = ",".join("?" * len(condition_ids))
            raw_conditions = conn.execute(f"SELECT * FROM condition_questions WHERE id IN ({q}) AND active=1", condition_ids).fetchall()
            condition_rows = [x for x in raw_conditions if scope_matches(x["category_code"], category)]
        condition_labels = [x["label"] for x in condition_rows]
        clean_condition_flags = " | ".join(condition_labels)
        score = sum(max(1, int(x["weight"] or 1)) for x in condition_rows)
        dirt_level = min(5, max(1, (score + 1) // 2))
        extra_total = sum(float(x["price"] or 0) for x in extras_rows)
        estimated_total = float(service["price"]) + extra_total
        code = None
        for _ in range(10):
            code = f"PH{secrets.randbelow(90000)+10000}"
            if not conn.execute("SELECT 1 FROM appointments WHERE code=?", (code,)).fetchone():
                break
        cur = conn.execute("""
            INSERT INTO appointments(code,customer_id,vehicle_id,service_id,appointment_date,appointment_time,status,
                                     condition_text,condition_flags,dirt_level,estimated_total,final_total,duration_minutes,payment_method,payment_status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (code,customer["id"],vehicle_id,service_id,appointment_date,appointment_time,"scheduled",
              condition_text[:300],clean_condition_flags,dirt_level,estimated_total,estimated_total,service["duration_minutes"],payment_method,"pending",now_iso()))
        appt_id = cur.lastrowid
        for er in extras_rows:
            conn.execute("INSERT INTO appointment_extras(appointment_id,extra_id,price_snapshot) VALUES (?,?,?)", (appt_id,er["id"],er["price"]))
        for flag in condition_labels:
            conn.execute("INSERT INTO vehicle_conditions(appointment_id,label) VALUES (?,?)", (appt_id,flag))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)", (appt_id,"scheduled",now_iso()))
        conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)",
                     (customer["id"], appt_id, "booking", f"Agendamento #{code} confirmado para {fmt_date(appointment_date)} às {appointment_time}.", "visible", now_iso()))
        conn.commit()
        safe_count = 0
        for photo in photos[:5]:
            if not photo.filename:
                continue
            ext = Path(photo.filename).suffix.lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            content = await photo.read()
            if len(content) > 8 * 1024 * 1024:
                continue
            fname = f"{code}_{safe_count}_{secrets.token_hex(4)}{ext}"
            (UPLOAD_DIR / fname).write_bytes(content)
            conn.execute("INSERT INTO vehicle_photos(appointment_id,kind,path,social_authorized,created_at) VALUES (?,?,?,?,?)",
                         (appt_id,"customer",fname,1 if social_authorized == "1" else 0,now_iso()))
            safe_count += 1
        conn.commit()
    request.session["last_booking_code"] = code
    return RedirectResponse(f"/confirmado/{code}", status_code=303)


@app.get("/confirmado/{code}", response_class=HTMLResponse)
def confirmed(request: Request, code: str):
    with closing(db_conn()) as conn:
        a = conn.execute("""
            SELECT a.*, c.name customer_name, c.phone, v.brand, v.model, v.category_code, s.name service_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.code=?
        """, (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        extras = conn.execute("""
            SELECT e.name, ae.price_snapshot FROM appointment_extras ae JOIN service_extras e ON e.id=ae.extra_id WHERE ae.appointment_id=?
        """, (a["id"],)).fetchall()
    message = (f"Olá! Fiz um agendamento pela {BUSINESS_NAME}.\n\nAgendamento: #{a['code']}\n"
               f"Veículo: {a['brand']} {a['model']}\nServiço: {a['service_name']}\nData: {fmt_date(a['appointment_date'])}\n"
               f"Horário: {a['appointment_time']}\nValor estimado: {brl(a['estimated_total'])}.")
    wa_number = current_whatsapp_number()
    wa_url = f"https://wa.me/{wa_number}?text={urllib.parse.quote(message)}"
    return templates.TemplateResponse(request, "confirmed.html", template_ctx(request, a=a, extras=extras, wa_url=wa_url, calendar_url=f"/agendamento/{code}.ics"))


@app.post("/cancelar/{code}")
def cancel_booking(request: Request, code: str, phone: str = Form("")):
    with closing(db_conn()) as conn:
        a = conn.execute("SELECT a.*, c.phone FROM appointments a JOIN customers c ON c.id=a.customer_id WHERE a.code=?", (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        customer = current_customer(request)
        authorized = customer and customer["id"] == a["customer_id"]
        if not authorized and normalize_phone(phone) != a["phone"]:
            raise HTTPException(403, "Confirme o telefone do agendamento.")
        if a["status"] in ("completed","cancelled"):
            return RedirectResponse(f"/acompanhar/{code}?phone={a['phone']}", 303)
        min_hours = max(0, int(setting(conn, "cancel_min_hours", "2") or 0))
        if hours_until_appointment(a) < min_hours:
            return RedirectResponse(f"/acompanhar/{code}?phone={a['phone']}&policy=cancel", 303)
        conn.execute("UPDATE appointments SET status='cancelled', cancelled_at=? WHERE id=?", (now_iso(), a["id"]))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)", (a["id"],"cancelled",now_iso()))
        conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)",
                     (a["customer_id"], a["id"], "cancelled", f"Agendamento #{code} cancelado.", "visible", now_iso()))
        sync_finance_revenue(conn, a["id"], "Agendamento cancelado pelo cliente")
        conn.commit()
    return RedirectResponse(f"/acompanhar/{code}?phone={a['phone']}", 303)


@app.get("/remarcar/{code}", response_class=HTMLResponse)
def reschedule_page(request: Request, code: str, phone: str = ""):
    with closing(db_conn()) as conn:
        a = conn.execute("""
            SELECT a.*, c.phone, c.name customer_name, v.brand, v.model, s.name service_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id
            JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.code=?
        """, (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        customer = current_customer(request)
        authorized = customer and customer["id"] == a["customer_id"]
        if not authorized and normalize_phone(phone) != a["phone"]:
            return templates.TemplateResponse(request, "tracking_verify.html", template_ctx(request, code=code, error="Confirme o telefone para remarcar."))
        min_hours = max(0, int(setting(conn, "reschedule_min_hours", "2") or 0))
        allowed = a["status"] == "scheduled" and hours_until_appointment(a) >= min_hours
    return templates.TemplateResponse(request, "reschedule.html", template_ctx(request, a=a, allowed=allowed, min_hours=min_hours, today=date.today().isoformat()))


@app.post("/remarcar/{code}")
def reschedule_booking(request: Request, code: str, appointment_date: str = Form(...), appointment_time: str = Form(...), phone: str = Form("")):
    with closing(db_conn()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        a = conn.execute("SELECT a.*, c.phone FROM appointments a JOIN customers c ON c.id=a.customer_id WHERE a.code=?", (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        customer = current_customer(request)
        authorized = customer and customer["id"] == a["customer_id"]
        if not authorized and normalize_phone(phone) != a["phone"]:
            raise HTTPException(403, "Confirme o telefone do agendamento.")
        min_hours = max(0, int(setting(conn, "reschedule_min_hours", "2") or 0))
        if a["status"] != "scheduled" or hours_until_appointment(a) < min_hours:
            raise HTTPException(403, "O prazo de remarcação deste agendamento foi encerrado.")
        # Libera o próprio horário durante a checagem para não contar conflito consigo mesmo.
        old_status = a["status"]
        conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (a["id"],))
        slots, message = _available_slots_with_conn(conn, appointment_date, a["service_id"])
        conn.execute("UPDATE appointments SET status=? WHERE id=?", (old_status, a["id"]))
        if appointment_time not in slots:
            raise HTTPException(409, message or "Horário indisponível.")
        conn.execute("UPDATE appointments SET appointment_date=?, appointment_time=?, status='scheduled', cancelled_at=NULL WHERE id=?",
                     (appointment_date, appointment_time, a["id"]))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)", (a["id"], "scheduled", now_iso()))
        conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)",
                     (a["customer_id"], a["id"], "rescheduled", f"Agendamento #{code} remarcado para {fmt_date(appointment_date)} às {appointment_time}.", "visible", now_iso()))
        conn.commit()
    return RedirectResponse(f"/acompanhar/{code}?phone={a['phone']}&rescheduled=1", 303)


@app.get("/agendamento/{code}.ics")
def appointment_calendar(code: str):
    with closing(db_conn()) as conn:
        a = conn.execute("""SELECT a.*,v.brand,v.model,s.name service_name FROM appointments a JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id WHERE a.code=?""", (code,)).fetchone()
        if not a:
            raise HTTPException(404)
    start = datetime.strptime(f"{a['appointment_date']} {a['appointment_time']}", "%Y-%m-%d %H:%M")
    duration = int(a["duration_minutes"] or 60)
    end = start + timedelta(minutes=duration)
    body = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//PH Estetica Detail//Agenda//PT-BR", "BEGIN:VEVENT",
        f"UID:{a['code']}@ph-estetica", f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:PH ESTÉTICA & DETAIL - {a['service_name']}", f"DESCRIPTION:{a['brand']} {a['model']} - Agendamento {a['code']}",
        "END:VEVENT", "END:VCALENDAR", ""
    ])
    return HTMLResponse(body, media_type="text/calendar", headers={"Content-Disposition": f"attachment; filename={code}.ics"})


@app.get("/notificacoes", response_class=HTMLResponse)
def customer_notifications(request: Request):
    customer = current_customer(request)
    if not customer:
        return RedirectResponse("/login", 303)
    with closing(db_conn()) as conn:
        rows = conn.execute("SELECT * FROM notifications WHERE customer_id=? ORDER BY id DESC LIMIT 100", (customer["id"],)).fetchall()
    return templates.TemplateResponse(request, "notifications.html", template_ctx(request, rows=rows))


@app.get("/acompanhar", response_class=HTMLResponse)
def tracking_lookup(request: Request):
    return templates.TemplateResponse(request, "tracking_lookup.html", template_ctx(request))


@app.post("/acompanhar")
def tracking_lookup_post(code: str = Form(...), phone: str = Form(...)):
    return RedirectResponse(f"/acompanhar/{code.strip()}?phone={normalize_phone(phone)}", 303)


@app.get("/acompanhar/{code}", response_class=HTMLResponse)
def tracking(request: Request, code: str, phone: str = ""):
    with closing(db_conn()) as conn:
        a = conn.execute("""
            SELECT a.*, c.phone, c.name customer_name, v.brand,v.model,v.year, s.name service_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.code=?
        """, (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        customer = current_customer(request)
        authorized = customer and customer["id"] == a["customer_id"]
        if not authorized and normalize_phone(phone) != a["phone"]:
            return templates.TemplateResponse(request, "tracking_verify.html", template_ctx(request, code=code, error=None))
        hist = conn.execute("SELECT * FROM service_status_history WHERE appointment_id=? ORDER BY id", (a["id"],)).fetchall()
        photos = conn.execute("SELECT * FROM vehicle_photos WHERE appointment_id=? ORDER BY id", (a["id"],)).fetchall()
        extra_requests = conn.execute("SELECT * FROM additional_service_requests WHERE appointment_id=? ORDER BY id DESC", (a["id"],)).fetchall()
        review = conn.execute("SELECT * FROM reviews WHERE appointment_id=?", (a["id"],)).fetchone()
    review_saved = request.query_params.get("review") == "ok"
    return templates.TemplateResponse(request, "tracking.html", template_ctx(request, a=a, hist=hist, photos=photos, extra_requests=extra_requests, review=review, review_saved=review_saved))


@app.post("/acompanhar/{code}/verificar")
def tracking_verify(code: str, phone: str = Form(...)):
    return RedirectResponse(f"/acompanhar/{code}?phone={normalize_phone(phone)}", 303)


@app.post("/extra-request/{request_id}/{decision}")
def decide_extra(request: Request, request_id: int, decision: str, phone: str = Form("")):
    if decision not in ("approved","declined"):
        raise HTTPException(400)
    with closing(db_conn()) as conn:
        r = conn.execute("""
            SELECT r.*, a.customer_id, c.phone FROM additional_service_requests r
            JOIN appointments a ON a.id=r.appointment_id JOIN customers c ON c.id=a.customer_id WHERE r.id=?
        """, (request_id,)).fetchone()
        if not r:
            raise HTTPException(404)
        customer = current_customer(request)
        if not ((customer and customer["id"] == r["customer_id"]) or normalize_phone(phone) == r["phone"]):
            raise HTTPException(403)
        if r["status"] == "pending":
            conn.execute("UPDATE additional_service_requests SET status=?, decided_at=? WHERE id=? AND status='pending'", (decision,now_iso(),request_id))
            if decision == "approved" and r["price"] is not None:
                conn.execute("UPDATE appointments SET estimated_total=COALESCE(estimated_total,0)+?, final_total=COALESCE(final_total,estimated_total,0)+? WHERE id=?", (float(r["price"]),float(r["price"]),r["appointment_id"]))
                sync_finance_revenue(conn, r["appointment_id"], "Serviço adicional aprovado")
        conn.commit()
    return RedirectResponse(request.headers.get("referer", "/"), 303)


@app.post("/avaliar/{code}")
def submit_review(request: Request, code: str, rating: int = Form(...), comment: str = Form(""), private_feedback: str = Form(""), show_on_home: str = Form("0"), phone: str = Form("")):
    if rating < 1 or rating > 5:
        raise HTTPException(400, "Avaliação inválida.")
    with closing(db_conn()) as conn:
        a = conn.execute("""
            SELECT a.*, c.phone FROM appointments a
            JOIN customers c ON c.id=a.customer_id
            WHERE a.code=?
        """, (code,)).fetchone()
        if not a:
            raise HTTPException(404)
        customer = current_customer(request)
        authorized = customer and customer["id"] == a["customer_id"]
        if not authorized and normalize_phone(phone) != a["phone"]:
            raise HTTPException(403, "Confirme o telefone do atendimento para avaliar.")
        if a["status"] not in ("ready", "completed"):
            raise HTTPException(400, "A avaliação fica disponível após a finalização do atendimento.")
        existing = conn.execute("SELECT id FROM reviews WHERE appointment_id=?", (a["id"],)).fetchone()
        authorized_home = 1 if show_on_home == "1" else 0
        payload = (rating, comment[:300].strip(), private_feedback[:400].strip(), authorized_home, authorized_home, now_iso(), a["id"])
        if existing:
            conn.execute("UPDATE reviews SET rating=?, comment=?, private_feedback=?, show_on_home=?, client_authorized_home=?, created_at=? WHERE appointment_id=?", payload)
        else:
            conn.execute("INSERT INTO reviews(rating,comment,private_feedback,show_on_home,client_authorized_home,admin_visible,created_at,appointment_id) VALUES (?,?,?,?,?,?,?,?)",
                         (rating, comment[:300].strip(), private_feedback[:400].strip(), authorized_home, authorized_home, 1, now_iso(), a["id"]))
        conn.commit()
    return RedirectResponse(f"/acompanhar/{code}?phone={normalize_phone(phone) or ''}&review=ok", 303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", template_ctx(request, error=None))


@app.post("/registrar")
def register(request: Request, name: str = Form(...), phone: str = Form(...), pin: str = Form(...)):
    p = normalize_phone(phone)
    if len(p) < 10 or len(pin) < 4:
        return templates.TemplateResponse(request, "login.html", template_ctx(request, error="Use um telefone válido e um PIN com pelo menos 4 caracteres."), status_code=400)
    with closing(db_conn()) as conn:
        if conn.execute("SELECT 1 FROM users WHERE phone=?", (p,)).fetchone():
            return templates.TemplateResponse(request, "login.html", template_ctx(request, error="Este telefone já possui acesso."), status_code=409)
        ucur = conn.execute("INSERT INTO users(role,phone,pin_hash,created_at) VALUES ('customer',?,?,?)", (p,hash_pin(pin),now_iso()))
        existing = conn.execute("SELECT * FROM customers WHERE phone=?", (p,)).fetchone()
        if existing:
            conn.execute("UPDATE customers SET user_id=?, name=? WHERE id=?", (ucur.lastrowid,name.strip(),existing["id"]))
            cid = existing["id"]
        else:
            ccur = conn.execute("INSERT INTO customers(user_id,name,phone,created_at) VALUES (?,?,?,?)", (ucur.lastrowid,name.strip(),p,now_iso()))
            cid = ccur.lastrowid
        conn.commit()
    request.session["customer_id"] = cid
    return RedirectResponse("/garagem", 303)


@app.post("/login")
def login(request: Request, phone: str = Form(...), pin: str = Form(...)):
    p = normalize_phone(phone)
    with closing(db_conn()) as conn:
        row = conn.execute("""
            SELECT u.*, c.id customer_id FROM users u JOIN customers c ON c.user_id=u.id WHERE u.phone=?
        """, (p,)).fetchone()
    if not row or not verify_pin(pin,row["pin_hash"]):
        return templates.TemplateResponse(request, "login.html", template_ctx(request, error="Telefone ou PIN inválido."), status_code=401)
    request.session["customer_id"] = row["customer_id"]
    return RedirectResponse("/garagem",303)


@app.get("/logout")
def logout(request: Request):
    request.session.pop("customer_id", None)
    return RedirectResponse("/",303)


@app.get("/garagem", response_class=HTMLResponse)
def garage(request: Request):
    customer = current_customer(request)
    if not customer:
        return RedirectResponse("/login",303)
    with closing(db_conn()) as conn:
        vehicles = conn.execute("SELECT * FROM vehicles WHERE customer_id=? ORDER BY id DESC", (customer["id"],)).fetchall()
    return templates.TemplateResponse(request, "garage.html", template_ctx(request, vehicles=vehicles))


@app.post("/garagem/adicionar")
def garage_add(request: Request, category: str=Form(...), vehicle_type: str=Form(...), brand: str=Form(...), model: str=Form(...), brand_catalog_id: str=Form(""), model_catalog_id: str=Form(""), year: str=Form(""), color: str=Form(""), engine_cc: str=Form(""), plate: str=Form("")):
    customer = current_customer(request)
    if not customer:
        return RedirectResponse("/login",303)
    with closing(db_conn()) as conn:
        brand, model, bid, mid = resolve_catalog_vehicle(conn, vehicle_type, brand_catalog_id, model_catalog_id, brand, model)
        if not brand or not model: raise HTTPException(400,"Informe marca e modelo.")
        create_vehicle(conn, customer["id"],category,vehicle_type,brand,model,year,color,engine_cc,plate,bid,mid)
        conn.commit()
    return RedirectResponse("/garagem",303)


@app.post("/garagem/{vehicle_id}/excluir")
def garage_delete(request: Request, vehicle_id: int):
    customer = current_customer(request)
    if not customer:
        raise HTTPException(401)
    with closing(db_conn()) as conn:
        used = conn.execute("SELECT 1 FROM appointments WHERE vehicle_id=?", (vehicle_id,)).fetchone()
        if used:
            conn.execute("UPDATE vehicles SET notes=COALESCE(notes,'') || ' [ARQUIVADO]' WHERE id=? AND customer_id=?", (vehicle_id,customer["id"]))
        else:
            conn.execute("DELETE FROM vehicles WHERE id=? AND customer_id=?", (vehicle_id,customer["id"]))
        conn.commit()
    return RedirectResponse("/garagem",303)


@app.get("/historico", response_class=HTMLResponse)
def history(request: Request):
    customer = current_customer(request)
    if not customer:
        return RedirectResponse("/login",303)
    with closing(db_conn()) as conn:
        appts = conn.execute("""
            SELECT a.*, v.brand,v.model, s.name service_name FROM appointments a
            JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.customer_id=? ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """, (customer["id"],)).fetchall()
    return templates.TemplateResponse(request, "history.html", template_ctx(request, appts=appts))


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse(request, "admin_login.html", template_ctx(request, error=None))


@app.post("/admin/login")
def admin_login(request: Request, username: str=Form(...), password: str=Form(...)):
    expected_user = os.getenv("PH_ADMIN_USER", "admin")
    expected_pass = os.getenv("PH_ADMIN_PASSWORD", "admin123")
    if hmac.compare_digest(username, expected_user) and hmac.compare_digest(password, expected_pass):
        request.session["is_admin"] = True
        return RedirectResponse("/admin",303)
    return templates.TemplateResponse(request, "admin_login.html", template_ctx(request,error="Credenciais inválidas."), status_code=401)


@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.pop("is_admin", None)
    return RedirectResponse("/admin/login",303)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login",303)
    today = date.today().isoformat()
    month = date.today().strftime("%Y-%m")
    with closing(db_conn()) as conn:
        today_rows = conn.execute("SELECT * FROM appointments WHERE appointment_date=?", (today,)).fetchall()
        revenue_day = conn.execute("SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN appointments a ON a.id=p.appointment_id WHERE a.appointment_date=? AND p.status='paid'", (today,)).fetchone()[0]
        revenue_month = conn.execute("SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN appointments a ON a.id=p.appointment_id WHERE substr(a.appointment_date,1,7)=? AND p.status='paid'", (month,)).fetchone()[0]
        count_month = conn.execute("SELECT COUNT(*) FROM payments p JOIN appointments a ON a.id=p.appointment_id WHERE substr(a.appointment_date,1,7)=? AND p.status='paid'", (month,)).fetchone()[0]
        top = conn.execute("""SELECT s.name, COUNT(*) n FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.status!='cancelled' GROUP BY s.id ORDER BY n DESC LIMIT 1""").fetchone()
        upcoming = conn.execute("""
            SELECT a.*, c.name customer_name,v.brand,v.model,s.name service_name FROM appointments a
            JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.appointment_date>=? AND a.status NOT IN ('cancelled','completed') ORDER BY a.appointment_date,a.appointment_time LIMIT 8
        """, (today,)).fetchall()
    stats = {
        "today": len(today_rows), "in_service": sum(1 for r in today_rows if r["status"] in ("received","preparation","washing","detailing","finishing","inspection")),
        "waiting": sum(1 for r in today_rows if r["status"]=="scheduled"), "finished": sum(1 for r in today_rows if r["status"] in ("ready","completed")),
        "revenue_day": revenue_day, "revenue_month": revenue_month, "avg": (revenue_month/count_month if count_month else 0), "top": top["name"] if top else "—"
    }
    return templates.TemplateResponse(request, "admin_dashboard.html", template_ctx(request, stats=stats, upcoming=upcoming))


@app.get("/admin/agendamentos", response_class=HTMLResponse)
def admin_appointments(request: Request, category: str=""):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        sql = """SELECT a.*,c.name customer_name,c.phone,v.brand,v.model,v.category_code,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id"""
        params=[]
        if category:
            sql += " WHERE v.category_code=?"; params.append(category)
        sql += " ORDER BY a.appointment_date DESC,a.appointment_time DESC LIMIT 300"
        rows = conn.execute(sql,params).fetchall()
    return templates.TemplateResponse(request, "admin_appointments.html", template_ctx(request, rows=rows, category=category))


@app.get("/admin/agendamentos/registrar", response_class=HTMLResponse)
def admin_register_history_page(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    with closing(db_conn()) as conn:
        services = conn.execute("SELECT * FROM services WHERE active=1 ORDER BY category_code,sort_order,id").fetchall()
        extras = conn.execute("SELECT * FROM service_extras WHERE active=1 ORDER BY name").fetchall()
        vehicles = conn.execute("""
            SELECT v.*, c.name customer_name, c.phone customer_phone
            FROM vehicles v JOIN customers c ON c.id=v.customer_id
            ORDER BY c.name, v.brand, v.model
        """).fetchall()
        payment_methods = get_payment_methods(conn, active_only=True)
    return templates.TemplateResponse(request, "admin_register_history.html", template_ctx(
        request, services=services, extras=extras, vehicles=vehicles, today=date.today().isoformat(), payment_methods=payment_methods
    ))


@app.post("/admin/agendamentos/registrar")
def admin_register_history(
    request: Request,
    existing_vehicle_id: str = Form(""), customer_name: str = Form(""), phone: str = Form(""),
    category: str = Form(""), brand: str = Form(""), model: str = Form(""), brand_catalog_id: str = Form(""), model_catalog_id: str = Form(""), year: str = Form(""),
    color: str = Form(""), plate: str = Form(""), service_id: int = Form(...), extras: str = Form(""),
    appointment_date: str = Form(...), appointment_time: str = Form(...), amount_paid: str = Form(""),
    payment_method: str = Form(...), condition_text: str = Form(""), count_loyalty: str = Form("0"),
):
    if not request.session.get("is_admin"):
        raise HTTPException(401)
    # A forma de pagamento é validada pelo cadastro editável do painel.
    try:
        historical_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "Data inválida.")
    if historical_date > date.today():
        raise HTTPException(400, "O registro retroativo deve ser de hoje ou de uma data anterior.")
    try:
        datetime.strptime(appointment_time, "%H:%M")
    except ValueError:
        raise HTTPException(400, "Horário inválido.")

    with closing(db_conn()) as conn:
        if not conn.execute("SELECT 1 FROM payment_methods WHERE code=? AND active=1", (payment_method,)).fetchone():
            raise HTTPException(400, "Forma de pagamento inválida ou desativada.")
        service = conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        if not service:
            raise HTTPException(400, "Serviço inválido.")

        vehicle = None
        customer = None
        if existing_vehicle_id.strip().isdigit():
            vehicle = conn.execute("""
                SELECT v.*, c.id customer_id_join, c.name customer_name, c.phone customer_phone
                FROM vehicles v JOIN customers c ON c.id=v.customer_id WHERE v.id=?
            """, (int(existing_vehicle_id),)).fetchone()
            if not vehicle:
                raise HTTPException(404, "Veículo cadastrado não encontrado.")
            if vehicle["category_code"] != service["category_code"]:
                raise HTTPException(400, "O serviço escolhido não pertence à categoria desse veículo.")
            customer = conn.execute("SELECT * FROM customers WHERE id=?", (vehicle["customer_id"],)).fetchone()
            vehicle_id = vehicle["id"]
        else:
            phone_norm = normalize_phone(phone)
            if not customer_name.strip():
                raise HTTPException(400, "Informe o nome do cliente.")
            if len(phone_norm) < 10:
                raise HTTPException(400, "Informe um telefone válido.")
            if category not in {"moto", "car_small", "car_large"}:
                raise HTTPException(400, "Selecione a categoria do veículo.")
            if service["category_code"] != category:
                raise HTTPException(400, "O serviço escolhido não pertence à categoria selecionada.")
            if not brand.strip() or not model.strip():
                raise HTTPException(400, "Informe marca e modelo do veículo.")
            customer = get_or_create_customer(conn, customer_name.strip(), phone_norm)
            vehicle_type = "moto" if category == "moto" else "carro"
            # Evita duplicar o mesmo veículo quando a placa já estiver cadastrada para o cliente.
            vehicle_id = None
            if plate.strip():
                found = conn.execute("SELECT id FROM vehicles WHERE customer_id=? AND UPPER(plate)=UPPER(?)",
                                     (customer["id"], plate.strip())).fetchone()
                if found:
                    vehicle_id = found["id"]
            if vehicle_id is None:
                brand_id = int(brand_catalog_id) if brand_catalog_id.strip().isdigit() else None
                model_id = int(model_catalog_id) if model_catalog_id.strip().isdigit() else None
                # Confere se marca/modelo selecionados realmente pertencem ao catálogo e entre si.
                if brand_id:
                    brand_row = conn.execute("SELECT * FROM vehicle_brands_catalog WHERE id=? AND active=1", (brand_id,)).fetchone()
                    expected_type = "moto" if category == "moto" else "car"
                    if not brand_row or brand_row["vehicle_type"] != expected_type:
                        brand_id = None
                        model_id = None
                    elif model_id:
                        model_row = conn.execute("SELECT * FROM vehicle_models_catalog WHERE id=? AND brand_id=? AND active=1", (model_id, brand_id)).fetchone()
                        if not model_row:
                            model_id = None
                vehicle_id = create_vehicle(conn, customer["id"], category, vehicle_type, brand.strip(), model.strip(), year, color, "", plate.strip(), brand_id, model_id)

        actual_category = vehicle["category_code"] if vehicle is not None else category
        extra_ids = [int(x) for x in extras.split(",") if x.strip().isdigit()]
        extras_rows = []
        if extra_ids:
            q = ",".join("?" * len(extra_ids))
            raw_extras = conn.execute(f"SELECT * FROM service_extras WHERE id IN ({q}) AND active=1", extra_ids).fetchall()
            extras_rows = [x for x in raw_extras if scope_matches(x["category_code"], actual_category)]
            if len(extras_rows) != len(set(extra_ids)):
                raise HTTPException(400, "Existe adicional inválido para essa categoria de veículo.")
        computed_total = float(service["price"] or 0) + sum(float(x["price"] or 0) for x in extras_rows)
        if amount_paid.strip():
            try:
                final_total = float(amount_paid.replace(".", "").replace(",", ".") if "," in amount_paid else amount_paid)
            except ValueError:
                raise HTTPException(400, "Valor cobrado inválido.")
        else:
            final_total = computed_total

        code = None
        for _ in range(20):
            code = f"PH{secrets.randbelow(90000)+10000}"
            if not conn.execute("SELECT 1 FROM appointments WHERE code=?", (code,)).fetchone():
                break
        completed_at = f"{appointment_date}T{appointment_time}:00"
        cur = conn.execute("""
            INSERT INTO appointments(code,customer_id,vehicle_id,service_id,appointment_date,appointment_time,status,
                                     condition_text,condition_flags,dirt_level,estimated_total,final_total,duration_minutes,payment_method,payment_status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (code, customer["id"], vehicle_id, service_id, appointment_date, appointment_time, "completed",
              condition_text[:300], "Registro retroativo", 1, final_total, final_total, service["duration_minutes"], payment_method, "paid", now_iso()))
        appointment_id = cur.lastrowid
        conn.execute("INSERT INTO payments(appointment_id,amount,method,status,created_at) VALUES (?,?,?,?,?)",
                     (appointment_id, final_total, payment_method, "paid", now_iso()))
        sync_finance_revenue(conn, appointment_id, "Atendimento retroativo pago")
        for er in extras_rows:
            conn.execute("INSERT INTO appointment_extras(appointment_id,extra_id,price_snapshot) VALUES (?,?,?)",
                         (appointment_id, er["id"], er["price"]))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)",
                     (appointment_id, "completed", completed_at))
        conn.execute("INSERT INTO vehicle_service_history(vehicle_id,appointment_id,service_id,completed_at) VALUES (?,?,?,?)",
                     (vehicle_id, appointment_id, service_id, completed_at))
        if count_loyalty == "1":
            conn.execute("INSERT OR IGNORE INTO loyalty(customer_id,progress) VALUES (?,0)", (customer["id"],))
            conn.execute("UPDATE loyalty SET progress=progress+1 WHERE customer_id=?", (customer["id"],))
            conn.execute("INSERT INTO loyalty_transactions(customer_id,appointment_id,delta,note,created_at) VALUES (?,?,1,?,?)",
                         (customer["id"], appointment_id, "Atendimento retroativo registrado", now_iso()))
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}?created=1", 303)


@app.post("/admin/agendamento/{appointment_id}/excluir")
def admin_delete_appointment(request: Request, appointment_id: int):
    if not request.session.get("is_admin"):
        raise HTTPException(401)
    photo_paths = []
    with closing(db_conn()) as conn:
        a = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not a:
            raise HTTPException(404)
        photo_paths = [r["path"] for r in conn.execute("SELECT path FROM vehicle_photos WHERE appointment_id=?", (appointment_id,)).fetchall()]
        loyalty_delta = conn.execute("SELECT COALESCE(SUM(delta),0) FROM loyalty_transactions WHERE appointment_id=?",
                                     (appointment_id,)).fetchone()[0] or 0
        if loyalty_delta:
            conn.execute("UPDATE loyalty SET progress=MAX(0, progress-?) WHERE customer_id=?",
                         (loyalty_delta, a["customer_id"]))
        # Tabelas que não possuem ON DELETE CASCADE na versão atual do banco.
        for table in ("vehicle_service_history", "visual_inspections", "additional_service_requests", "reviews",
                      "loyalty_transactions", "notifications", "payments"):
            conn.execute(f"DELETE FROM {table} WHERE appointment_id=?", (appointment_id,))
        # As demais tabelas vinculadas ao agendamento são removidas pelo ON DELETE CASCADE.
        conn.execute("DELETE FROM appointments WHERE id=?", (appointment_id,))
        conn.commit()
    for rel_path in photo_paths:
        try:
            target = UPLOAD_DIR / rel_path
            if target.is_file():
                target.unlink()
        except OSError:
            pass
    return RedirectResponse("/admin/agendamentos?deleted=1", 303)


@app.get("/admin/agendamento/{appointment_id}", response_class=HTMLResponse)
def admin_appointment_detail(request: Request, appointment_id: int):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        a = appointment_detail(conn, appointment_id)
        if not a: raise HTTPException(404)
        extras = conn.execute("SELECT e.name,ae.price_snapshot FROM appointment_extras ae JOIN service_extras e ON e.id=ae.extra_id WHERE ae.appointment_id=?", (appointment_id,)).fetchall()
        photos = conn.execute("SELECT * FROM vehicle_photos WHERE appointment_id=? ORDER BY id", (appointment_id,)).fetchall()
        checkin = conn.execute("SELECT * FROM checkins WHERE appointment_id=?", (appointment_id,)).fetchone()
        inspections = conn.execute("SELECT * FROM visual_inspections WHERE appointment_id=? ORDER BY id DESC", (appointment_id,)).fetchall()
        reqs = conn.execute("SELECT * FROM additional_service_requests WHERE appointment_id=? ORDER BY id DESC", (appointment_id,)).fetchall()
        payment_methods = get_payment_methods(conn, active_only=False)
        payment = conn.execute("SELECT * FROM payments WHERE appointment_id=? ORDER BY id DESC LIMIT 1", (appointment_id,)).fetchone()
        review = conn.execute("SELECT * FROM reviews WHERE appointment_id=?", (appointment_id,)).fetchone()
        finance_helpers = conn.execute("SELECT * FROM finance_helpers WHERE active=1 ORDER BY name").fetchall()
        helper_cost = conn.execute("SELECT ah.*,h.name helper_name FROM appointment_helper_costs ah JOIN finance_helpers h ON h.id=ah.helper_id WHERE ah.appointment_id=?", (appointment_id,)).fetchone()
    return templates.TemplateResponse(request, "admin_appointment_detail.html", template_ctx(request,a=a,extras=extras,photos=photos,checkin=checkin,inspections=inspections,reqs=reqs,payment_methods=payment_methods,payment=payment,review=review,finance_helpers=finance_helpers,helper_cost=helper_cost))


@app.post("/admin/agendamento/{appointment_id}/status")
def admin_update_status(request: Request, appointment_id: int, status: str=Form(...)):
    if not request.session.get("is_admin"): raise HTTPException(401)
    if status not in STATUS_LABELS: raise HTTPException(400)
    with closing(db_conn()) as conn:
        a=conn.execute("SELECT * FROM appointments WHERE id=?",(appointment_id,)).fetchone()
        if not a: raise HTTPException(404)
        conn.execute("UPDATE appointments SET status=? WHERE id=?",(status,appointment_id))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)",(appointment_id,status,now_iso()))
        if status=="completed":
            exists=conn.execute("SELECT 1 FROM vehicle_service_history WHERE appointment_id=?",(appointment_id,)).fetchone()
            if not exists:
                conn.execute("INSERT INTO vehicle_service_history(vehicle_id,appointment_id,service_id,completed_at) VALUES (?,?,?,?)",(a["vehicle_id"],appointment_id,a["service_id"],now_iso()))
                conn.execute("INSERT OR IGNORE INTO loyalty(customer_id,progress) VALUES (?,0)",(a["customer_id"],))
                conn.execute("UPDATE loyalty SET progress=progress+1 WHERE customer_id=?",(a["customer_id"],))
                conn.execute("INSERT INTO loyalty_transactions(customer_id,appointment_id,delta,note,created_at) VALUES (?,?,1,?,?)",(a["customer_id"],appointment_id,"Atendimento finalizado",now_iso()))
        status_body = {
            "received": "Seu veículo foi recebido pela PH ESTÉTICA & DETAIL.",
            "washing": "Iniciamos os cuidados com seu veículo.",
            "detailing": "Seu veículo está na etapa de detalhamento.",
            "finishing": "Estamos finalizando os cuidados com seu veículo.",
            "ready": "Seu veículo está pronto para retirada!",
            "completed": "Atendimento finalizado. Obrigado por confiar na PH ESTÉTICA & DETAIL."
        }.get(status)
        if status_body:
            conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)",
                         (a["customer_id"], appointment_id, status, status_body, "visible", now_iso()))
        sync_finance_revenue(conn, appointment_id, "Status do atendimento alterado")
        conn.commit()
    return RedirectResponse(request.headers.get("referer", "/admin/agendamentos"),303)


@app.post("/admin/agendamento/{appointment_id}/checkin")
def admin_checkin(request: Request, appointment_id:int, mileage:str=Form(""), notes:str=Form(""), existing_damage:str=Form(""), fuel_level:str=Form("")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("INSERT OR REPLACE INTO checkins(appointment_id,checked_in_at,mileage,notes,existing_damage,fuel_level) VALUES (?,?,?,?,?,?)",(appointment_id,now_iso(),mileage,notes,existing_damage,fuel_level))
        a = conn.execute("SELECT customer_id FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        conn.execute("UPDATE appointments SET status='received' WHERE id=?",(appointment_id,))
        conn.execute("INSERT INTO service_status_history(appointment_id,status,created_at) VALUES (?,?,?)",(appointment_id,"received",now_iso()))
        if a:
            conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)", (a["customer_id"],appointment_id,"received","Seu veículo foi recebido pela PH ESTÉTICA & DETAIL.","visible",now_iso()))
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}",303)


@app.post("/admin/agendamento/{appointment_id}/inspection")
def admin_inspection(request: Request, appointment_id:int, item:str=Form(...), notes:str=Form("")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO visual_inspections(appointment_id,item,notes,created_at) VALUES (?,?,?,?)",(appointment_id,item,notes,now_iso())); conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}",303)


@app.post("/admin/agendamento/{appointment_id}/extra")
def admin_extra_request(request: Request, appointment_id:int, extra_name:str=Form(...), price:str=Form("")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    p = float(price.replace(",",".")) if price.strip() else None
    with closing(db_conn()) as conn:
        a = conn.execute("SELECT customer_id FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        conn.execute("INSERT INTO additional_service_requests(appointment_id,extra_name,price,status,requested_at) VALUES (?,?,?,'pending',?)",(appointment_id,extra_name,p,now_iso()))
        if a:
            text = f"Encontramos um cuidado adicional para seu veículo: {extra_name}. Abra o acompanhamento para aprovar ou recusar."
            conn.execute("INSERT INTO notifications(customer_id,appointment_id,type,body,status,created_at) VALUES (?,?,?,?,?,?)", (a["customer_id"],appointment_id,"extra_request",text,"visible",now_iso()))
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}",303)


@app.get("/admin/kanban", response_class=HTMLResponse)
def admin_kanban(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        rows = conn.execute("""
          SELECT a.*,c.name customer_name,v.brand,v.model,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
          WHERE a.status NOT IN ('completed','cancelled') ORDER BY a.appointment_date,a.appointment_time
        """).fetchall()
    columns={k:[r for r in rows if r["status"]==k] for k,_ in KANBAN}
    return templates.TemplateResponse(request, "admin_kanban.html",template_ctx(request,columns=columns,kanban=KANBAN))


@app.get("/admin/servicos", response_class=HTMLResponse)
def admin_services(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        services=conn.execute("SELECT * FROM services ORDER BY category_code,sort_order,id").fetchall()
        extras=conn.execute("SELECT * FROM service_extras ORDER BY id").fetchall()
    return templates.TemplateResponse(request, "admin_services.html",template_ctx(request,services=services,extras=extras))


@app.post("/admin/servicos/{service_id}")
def admin_service_update(request: Request, service_id:int, name:str=Form(...), description:str=Form(""), price:float=Form(...), duration_minutes:str=Form(""), active:str=Form("0")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    dur=int(duration_minutes) if duration_minutes.strip().isdigit() else None
    with closing(db_conn()) as conn:
        conn.execute("UPDATE services SET name=?,description=?,price=?,duration_minutes=?,active=? WHERE id=?",(name,description,price,dur,1 if active=="1" else 0,service_id)); conn.commit()
    return RedirectResponse("/admin/servicos",303)


@app.post("/admin/extras/{extra_id}")
def admin_extra_update(request: Request, extra_id:int, name:str=Form(...), price:str=Form(""), category_code:str=Form(""), active:str=Form("0")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    if category_code not in {"all", "car", "moto", "car_small", "car_large"}: raise HTTPException(400, "Categoria inválida.")
    p=float(price.replace(",",".")) if price.strip() else None
    with closing(db_conn()) as conn:
        conn.execute("UPDATE service_extras SET name=?,price=?,category_code=?,active=? WHERE id=?",(name.strip(),p,None if category_code=="all" else category_code,1 if active=="1" else 0,extra_id)); conn.commit()
    return RedirectResponse("/admin/servicos?saved=1",303)


@app.post("/admin/servicos/adicional/novo")
def admin_extra_create(request: Request, name:str=Form(...), price:str=Form(""), category_code:str=Form(...)):
    if not request.session.get("is_admin"): raise HTTPException(401)
    if category_code not in {"all", "car", "moto", "car_small", "car_large"}: raise HTTPException(400, "Categoria inválida.")
    if not name.strip(): raise HTTPException(400, "Informe o nome do adicional.")
    p=float(price.replace(",",".")) if price.strip() else None
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO service_extras(name,price,category_code,active) VALUES (?,?,?,1)",
                     (name.strip(),p,None if category_code=="all" else category_code)); conn.commit()
    return RedirectResponse("/admin/servicos?extra_created=1",303)


@app.post("/admin/extras/{extra_id}/excluir")
def admin_extra_delete(request: Request, extra_id:int):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        used = conn.execute("SELECT COUNT(*) FROM appointment_extras WHERE extra_id=?", (extra_id,)).fetchone()[0]
        if used:
            # Preserva o nome nos atendimentos antigos e apenas remove das novas escolhas.
            conn.execute("UPDATE service_extras SET active=0 WHERE id=?", (extra_id,))
            result = "disabled"
        else:
            conn.execute("DELETE FROM service_extras WHERE id=?", (extra_id,))
            result = "deleted"
        conn.commit()
    return RedirectResponse(f"/admin/servicos?extra_{result}=1",303)


@app.get("/admin/perguntas-veiculo", response_class=HTMLResponse)
def admin_vehicle_questions(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        questions = conn.execute("SELECT * FROM condition_questions ORDER BY sort_order,id").fetchall()
    return templates.TemplateResponse(request, "admin_vehicle_questions.html", template_ctx(request,questions=questions))


@app.post("/admin/perguntas-veiculo/nova")
def admin_vehicle_question_create(request: Request, label:str=Form(...), category_code:str=Form("all"), weight:int=Form(1)):
    if not request.session.get("is_admin"): raise HTTPException(401)
    if category_code not in {"all", "car", "moto", "car_small", "car_large"}: raise HTTPException(400, "Categoria inválida.")
    if not label.strip(): raise HTTPException(400, "Informe a pergunta/condição.")
    weight = 2 if weight >= 2 else 1
    with closing(db_conn()) as conn:
        order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM condition_questions").fetchone()[0]
        conn.execute("INSERT INTO condition_questions(label,category_code,weight,active,sort_order) VALUES (?,?,?,?,?)",
                     (label.strip(),None if category_code=="all" else category_code,weight,1,order)); conn.commit()
    return RedirectResponse("/admin/perguntas-veiculo?created=1",303)


@app.post("/admin/perguntas-veiculo/{question_id}")
def admin_vehicle_question_update(request: Request, question_id:int, label:str=Form(...), category_code:str=Form("all"), weight:int=Form(1), active:str=Form("0")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    if category_code not in {"all", "car", "moto", "car_small", "car_large"}: raise HTTPException(400, "Categoria inválida.")
    if not label.strip(): raise HTTPException(400, "Informe a pergunta/condição.")
    weight = 2 if weight >= 2 else 1
    with closing(db_conn()) as conn:
        conn.execute("UPDATE condition_questions SET label=?,category_code=?,weight=?,active=? WHERE id=?",
                     (label.strip(),None if category_code=="all" else category_code,weight,1 if active=="1" else 0,question_id)); conn.commit()
    return RedirectResponse("/admin/perguntas-veiculo?saved=1",303)


@app.post("/admin/perguntas-veiculo/{question_id}/excluir")
def admin_vehicle_question_delete(request: Request, question_id:int):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("DELETE FROM condition_questions WHERE id=?", (question_id,)); conn.commit()
    return RedirectResponse("/admin/perguntas-veiculo?deleted=1",303)


@app.get("/admin/agenda", response_class=HTMLResponse)
def admin_schedule(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        hours=conn.execute("SELECT * FROM business_hours ORDER BY weekday").fetchall()
        blocks=conn.execute("SELECT * FROM blocked_times ORDER BY block_date DESC,id DESC LIMIT 100").fetchall()
        interval=setting(conn,"interval_minutes","0"); capacity=setting(conn,"simultaneous_capacity","1")
    return templates.TemplateResponse(request, "admin_schedule.html",template_ctx(request,hours=hours,blocks=blocks,interval=interval,capacity=capacity))


@app.post("/admin/agenda/horas")
def admin_schedule_hours(request: Request, weekday:int=Form(...), is_open:str=Form("0"), open_time:str=Form(""), close_time:str=Form(""), lunch_start:str=Form(""), lunch_end:str=Form("")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("UPDATE business_hours SET is_open=?,open_time=?,close_time=?,lunch_start=?,lunch_end=? WHERE weekday=?",(1 if is_open=="1" else 0,open_time or None,close_time or None,lunch_start or None,lunch_end or None,weekday)); conn.commit()
    return RedirectResponse("/admin/agenda",303)


@app.post("/admin/agenda/config")
def admin_schedule_config(request: Request, interval_minutes:int=Form(0), simultaneous_capacity:int=Form(1)):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('interval_minutes',?)",(str(max(0,interval_minutes)),))
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('simultaneous_capacity',?)",(str(max(1,simultaneous_capacity)),)); conn.commit()
    return RedirectResponse("/admin/agenda",303)


@app.post("/admin/agenda/bloquear")
def admin_block(request: Request, block_date:str=Form(...), start_time:str=Form(""), end_time:str=Form(""), reason:str=Form("")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO blocked_times(block_date,start_time,end_time,reason) VALUES (?,?,?,?)",(block_date,start_time or None,end_time or None,reason)); conn.commit()
    return RedirectResponse("/admin/agenda",303)


@app.post("/admin/agenda/bloqueio/{block_id}/excluir")
def admin_unblock(request: Request, block_id:int):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn:
        conn.execute("DELETE FROM blocked_times WHERE id=?",(block_id,)); conn.commit()
    return RedirectResponse("/admin/agenda",303)


@app.get("/admin/clientes", response_class=HTMLResponse)
def admin_customers(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn:
        rows=conn.execute("""
          SELECT c.*, COUNT(DISTINCT v.id) vehicles_count, COUNT(DISTINCT a.id) appointments_count,
                 MAX(a.appointment_date) last_visit, COALESCE(SUM(CASE WHEN a.status!='cancelled' THEN a.estimated_total ELSE 0 END),0) total_spent,
                 COALESCE(l.progress,0) loyalty_progress
          FROM customers c LEFT JOIN vehicles v ON v.customer_id=c.id LEFT JOIN appointments a ON a.customer_id=c.id LEFT JOIN loyalty l ON l.customer_id=c.id
          GROUP BY c.id ORDER BY c.name
        """).fetchall()
    return templates.TemplateResponse(request, "admin_customers.html",template_ctx(request,rows=rows))


@app.get("/admin/boxes", response_class=HTMLResponse)
def admin_boxes(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn: rows=conn.execute("SELECT * FROM service_boxes ORDER BY id").fetchall()
    return templates.TemplateResponse(request, "admin_boxes.html",template_ctx(request,rows=rows))


@app.post("/admin/boxes")
def admin_box_add(request: Request, name:str=Form(...)):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn: conn.execute("INSERT INTO service_boxes(name,active) VALUES (?,1)",(name,)); conn.commit()
    return RedirectResponse("/admin/boxes",303)


@app.post("/admin/boxes/{box_id}/toggle")
def admin_box_toggle(request: Request, box_id:int):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn: conn.execute("UPDATE service_boxes SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(box_id,)); conn.commit()
    return RedirectResponse("/admin/boxes",303)


@app.get("/admin/promocoes", response_class=HTMLResponse)
def admin_promotions(request: Request):
    if not request.session.get("is_admin"): return RedirectResponse("/admin/login",303)
    with closing(db_conn()) as conn: rows=conn.execute("SELECT * FROM promotions ORDER BY id DESC").fetchall()
    return templates.TemplateResponse(request, "admin_promotions.html",template_ctx(request,rows=rows))


@app.post("/admin/promocoes")
def admin_promotion_add(request: Request, title:str=Form(...), description:str=Form(""), start_date:str=Form(""), end_date:str=Form(""), audience:str=Form(""), active:str=Form("0")):
    if not request.session.get("is_admin"): raise HTTPException(401)
    with closing(db_conn()) as conn: conn.execute("INSERT INTO promotions(title,description,start_date,end_date,audience,active) VALUES (?,?,?,?,?,?)",(title,description,start_date or None,end_date or None,audience,1 if active=="1" else 0)); conn.commit()
    return RedirectResponse("/admin/promocoes",303)




def _admin_required(request: Request):
    if not request.session.get("is_admin"):
        raise HTTPException(401)


def _parse_money(value: str, default=0.0):
    raw = (value or "").strip()
    if not raw:
        return float(default or 0)
    try:
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        return float(raw)
    except ValueError:
        raise HTTPException(400, "Valor inválido.")


async def _save_image(upload: UploadFile, prefix: str):
    if not upload or not upload.filename:
        return None
    ext = Path(upload.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(400, "Envie uma imagem JPG, PNG ou WEBP.")
    content = await upload.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "A imagem deve ter no máximo 10 MB.")
    fname = f"{prefix}_{secrets.token_hex(6)}{ext}"
    (UPLOAD_DIR / fname).write_bytes(content)
    return fname


@app.get("/admin/hoje", response_class=HTMLResponse)
def admin_today(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    today = date.today().isoformat()
    with closing(db_conn()) as conn:
        rows = conn.execute("""
            SELECT a.*,c.name customer_name,c.phone,v.brand,v.model,v.category_code,s.name service_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id
            JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.appointment_date=? AND a.status!='cancelled'
            ORDER BY a.appointment_time
        """, (today,)).fetchall()
        pm = {r["code"]: r["name"] for r in get_payment_methods(conn, active_only=False)}
        company = get_company_settings(conn)
    wa_number = re.sub(r"\D", "", company.get("whatsapp_number") or WHATSAPP_NUMBER)
    enriched = []
    for r in rows:
        item = dict(r)
        msg = f"Olá, {r['customer_name'].split()[0]}! Aqui é da PH ESTÉTICA & DETAIL. Seu atendimento de hoje está marcado para {r['appointment_time']} ({r['brand']} {r['model']})."
        item["wa_url"] = f"https://wa.me/55{r['phone'] if not r['phone'].startswith('55') else r['phone'][2:]}?text={urllib.parse.quote(msg)}"
        item["payment_name"] = pm.get(r["payment_method"], payment_label(r["payment_method"]))
        enriched.append(item)
    return templates.TemplateResponse(request, "admin_today.html", template_ctx(request, rows=enriched, today=today))


@app.get("/admin/financeiro", response_class=HTMLResponse)
def admin_finance(request: Request):
    _admin_required(request)
    period = _finance_period(request)
    with closing(db_conn()) as conn:
        # Garante integração dos pagamentos antigos/atuais sem duplicidade.
        for r in conn.execute("SELECT id FROM appointments WHERE payment_status='paid'").fetchall():
            sync_finance_revenue(conn, r["id"], "Sincronização do painel financeiro")
        conn.commit()
        summary = _finance_summary(conn,period["start"],period["end"])
        lifetime = _finance_all_time(conn)
        monthly = _finance_monthly(conn,date.today().year)
        expense_dist = sorted(summary["categories"].items(), key=lambda x:x[1], reverse=True)
        pending_expenses = conn.execute("""SELECT e.*,c.name category_name FROM finance_expenses e JOIN expense_categories c ON c.id=e.category_id WHERE e.status='pending' AND e.cancelled_at IS NULL ORDER BY COALESCE(e.due_date,e.expense_date) LIMIT 30""").fetchall()
        helpers_due = conn.execute("""SELECT h.id,h.name,COALESCE((SELECT SUM(ah.amount) FROM appointment_helper_costs ah JOIN appointments a ON a.id=ah.appointment_id WHERE ah.helper_id=h.id AND a.status!='cancelled'),0) generated,COALESCE((SELECT SUM(hp.amount) FROM helper_payments hp WHERE hp.helper_id=h.id AND hp.cancelled_at IS NULL),0) paid FROM finance_helpers h WHERE h.active=1 ORDER BY h.name""").fetchall()
    return templates.TemplateResponse(request,"admin_finance.html",template_ctx(request,summary=summary,lifetime=lifetime,period=period,monthly=monthly,expense_dist=expense_dist,pending_expenses=pending_expenses,helpers_due=helpers_due))


@app.get("/admin/agendamento/{appointment_id}/cobranca-whatsapp")
def admin_payment_reminder_whatsapp(request: Request, appointment_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row = conn.execute("""
            SELECT a.*,c.name customer_name,c.phone,v.brand,v.model,s.name service_name
            FROM appointments a JOIN customers c ON c.id=a.customer_id
            JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id
            WHERE a.id=?
        """, (appointment_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        if row["payment_status"] == "paid":
            return RedirectResponse(f"/admin/agendamento/{appointment_id}?payment_already_paid=1", 303)
        wa_url = payment_reminder_whatsapp_url(row)
        conn.execute("UPDATE appointments SET payment_reminder_count=COALESCE(payment_reminder_count,0)+1,payment_reminder_last_at=? WHERE id=?", (now_iso(), appointment_id))
        conn.commit()
    return RedirectResponse(wa_url, 303)


@app.post("/admin/agendamento/{appointment_id}/financeiro")
def admin_appointment_finance(request: Request, appointment_id: int, final_total: str = Form(""), discount: str = Form("0"), payment_method: str = Form(""), payment_status: str = Form("pending")):
    _admin_required(request)
    if payment_status not in {"pending", "paid"}:
        raise HTTPException(400, "Status de pagamento inválido.")
    total = _parse_money(final_total, 0)
    disc = max(0, _parse_money(discount, 0))
    with closing(db_conn()) as conn:
        a = conn.execute("SELECT * FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not a:
            raise HTTPException(404)
        if not payment_method:
            payment_method = a["payment_method"] or ""
        if payment_method and not conn.execute("SELECT 1 FROM payment_methods WHERE code=?", (payment_method,)).fetchone():
            raise HTTPException(400, "Forma de pagamento inválida.")
        if total <= 0:
            total = max(0, float(a["estimated_total"] or 0) - disc)
        conn.execute("UPDATE appointments SET final_total=?,discount=?,payment_method=?,payment_status=? WHERE id=?", (total, disc, payment_method, payment_status, appointment_id))
        conn.execute("DELETE FROM payments WHERE appointment_id=?", (appointment_id,))
        if payment_status == "paid":
            conn.execute("INSERT INTO payments(appointment_id,amount,method,status,created_at) VALUES (?,?,?,?,?)", (appointment_id, total, payment_method, "paid", now_iso()))
        sync_finance_revenue(conn, appointment_id, "Pagamento do atendimento alterado")
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}?finance=1", 303)


@app.post("/admin/pagamentos/novo")
def admin_payment_method_create(request: Request, name: str = Form(...), active: str = Form("1")):
    _admin_required(request)
    clean = name.strip()
    if not clean:
        raise HTTPException(400, "Informe o nome da forma de pagamento.")
    code = re.sub(r"[^a-z0-9]+", "_", clean.lower().replace("ã","a").replace("ç","c").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")).strip("_") or secrets.token_hex(3)
    with closing(db_conn()) as conn:
        base = code; n = 2
        while conn.execute("SELECT 1 FROM payment_methods WHERE code=?", (code,)).fetchone():
            code = f"{base}_{n}"; n += 1
        order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM payment_methods").fetchone()[0]
        conn.execute("INSERT INTO payment_methods(code,name,active,sort_order) VALUES (?,?,?,?)", (code,clean,1 if active=="1" else 0,order))
        conn.commit()
    return RedirectResponse("/admin/financeiro/receitas?method_created=1", 303)


@app.post("/admin/pagamentos/{method_id}")
def admin_payment_method_update(request: Request, method_id: int, name: str = Form(...), active: str = Form("0")):
    _admin_required(request)
    with closing(db_conn()) as conn:
        conn.execute("UPDATE payment_methods SET name=?,active=? WHERE id=?", (name.strip(),1 if active=="1" else 0,method_id))
        conn.commit()
    return RedirectResponse("/admin/financeiro/receitas?method_saved=1", 303)


@app.post("/admin/pagamentos/{method_id}/excluir")
def admin_payment_method_delete(request: Request, method_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM payment_methods WHERE id=?", (method_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        used = conn.execute("SELECT COUNT(*) FROM appointments WHERE payment_method=?", (row["code"],)).fetchone()[0]
        if used:
            conn.execute("UPDATE payment_methods SET active=0 WHERE id=?", (method_id,))
        else:
            conn.execute("DELETE FROM payment_methods WHERE id=?", (method_id,))
        conn.commit()
    return RedirectResponse("/admin/financeiro/receitas?method_removed=1", 303)


@app.post("/admin/agendamento/{appointment_id}/foto")
async def admin_appointment_photo(request: Request, appointment_id: int, kind: str = Form(...), photo: UploadFile = File(...)):
    _admin_required(request)
    if kind not in {"before", "after", "checkin"}:
        raise HTTPException(400, "Tipo de foto inválido.")
    with closing(db_conn()) as conn:
        a = conn.execute("SELECT code FROM appointments WHERE id=?", (appointment_id,)).fetchone()
        if not a:
            raise HTTPException(404)
    fname = await _save_image(photo, f"{a['code']}_{kind}")
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO vehicle_photos(appointment_id,kind,path,social_authorized,created_at) VALUES (?,?,?,?,?)", (appointment_id,kind,fname,0,now_iso()))
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}#fotos", 303)


@app.post("/admin/foto/{photo_id}/excluir")
def admin_photo_delete(request: Request, photo_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM vehicle_photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        appt_id = row["appointment_id"]
        conn.execute("DELETE FROM vehicle_photos WHERE id=?", (photo_id,))
        conn.commit()
    try:
        (UPLOAD_DIR / row["path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return RedirectResponse(f"/admin/agendamento/{appt_id}#fotos", 303)


@app.get("/admin/avaliacoes", response_class=HTMLResponse)
def admin_reviews(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    with closing(db_conn()) as conn:
        rows = conn.execute("""
            SELECT r.*,a.code,c.name customer_name,v.brand,v.model,a.appointment_date
            FROM reviews r JOIN appointments a ON a.id=r.appointment_id
            JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id
            ORDER BY r.id DESC
        """).fetchall()
    return templates.TemplateResponse(request, "admin_reviews.html", template_ctx(request, rows=rows))


@app.post("/admin/avaliacoes/{review_id}/visibilidade")
def admin_review_visibility(request: Request, review_id: int, visible: str = Form("0")):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        # O administrador pode ocultar, mas nunca forçar publicação se o cliente não autorizou.
        value = 1 if visible == "1" and row["client_authorized_home"] else 0
        conn.execute("UPDATE reviews SET admin_visible=? WHERE id=?", (value,review_id))
        conn.commit()
    return RedirectResponse("/admin/avaliacoes", 303)


@app.post("/admin/avaliacoes/{review_id}/excluir")
def admin_review_delete(request: Request, review_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
        conn.commit()
    return RedirectResponse("/admin/avaliacoes", 303)


@app.get("/admin/galeria", response_class=HTMLResponse)
def admin_gallery(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    with closing(db_conn()) as conn:
        rows = conn.execute("SELECT * FROM gallery_items ORDER BY sort_order,id DESC").fetchall()
    return templates.TemplateResponse(request, "admin_gallery.html", template_ctx(request, rows=rows))


@app.post("/admin/galeria")
async def admin_gallery_add(request: Request, title: str = Form(""), caption: str = Form(""), vehicle_type: str = Form("car"), active: str = Form("1"), photo: UploadFile = File(...)):
    _admin_required(request)
    if vehicle_type not in {"car", "moto", "both"}:
        raise HTTPException(400, "Categoria inválida.")
    fname = await _save_image(photo, "gallery")
    with closing(db_conn()) as conn:
        order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM gallery_items").fetchone()[0]
        conn.execute("INSERT INTO gallery_items(image_path,title,caption,vehicle_type,active,sort_order,created_at) VALUES (?,?,?,?,?,?,?)", (fname,title[:80],caption[:220],vehicle_type,1 if active=="1" else 0,order,now_iso()))
        conn.commit()
    return RedirectResponse("/admin/galeria?created=1", 303)


@app.post("/admin/galeria/{item_id}")
def admin_gallery_update(request: Request, item_id: int, title: str = Form(""), caption: str = Form(""), vehicle_type: str = Form("car"), active: str = Form("0"), sort_order: int = Form(0)):
    _admin_required(request)
    with closing(db_conn()) as conn:
        conn.execute("UPDATE gallery_items SET title=?,caption=?,vehicle_type=?,active=?,sort_order=? WHERE id=?", (title[:80],caption[:220],vehicle_type,1 if active=="1" else 0,sort_order,item_id))
        conn.commit()
    return RedirectResponse("/admin/galeria", 303)


@app.post("/admin/galeria/{item_id}/excluir")
def admin_gallery_delete(request: Request, item_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row = conn.execute("SELECT * FROM gallery_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        conn.execute("DELETE FROM gallery_items WHERE id=?", (item_id,))
        conn.commit()
    try:
        (UPLOAD_DIR / row["image_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return RedirectResponse("/admin/galeria", 303)


@app.get("/admin/catalogo-veiculos", response_class=HTMLResponse)
def admin_vehicle_catalog(request: Request, vehicle_type: str = "car", q: str = "", brand_id: int = 0):
    _admin_required(request)
    if vehicle_type not in {"car","moto"}: vehicle_type="car"
    with closing(db_conn()) as conn:
        stats=conn.execute("""SELECT
            (SELECT COUNT(*) FROM vehicle_brands_catalog WHERE vehicle_type='car') car_brands,
            (SELECT COUNT(*) FROM vehicle_brands_catalog WHERE vehicle_type='moto') moto_brands,
            (SELECT COUNT(*) FROM vehicle_models_catalog m JOIN vehicle_brands_catalog b ON b.id=m.brand_id WHERE b.vehicle_type='car') car_models,
            (SELECT COUNT(*) FROM vehicle_models_catalog m JOIN vehicle_brands_catalog b ON b.id=m.brand_id WHERE b.vehicle_type='moto') moto_models""").fetchone()
        qn=normalize_search(q)
        params=[vehicle_type]
        where="vehicle_type=?"
        if qn: where+=" AND search_text LIKE ?"; params.append(f"%{qn}%")
        brands=conn.execute(f"SELECT * FROM vehicle_brands_catalog WHERE {where} ORDER BY name LIMIT 250", params).fetchall()
        selected=None; models=[]
        if brand_id:
            selected=conn.execute("SELECT * FROM vehicle_brands_catalog WHERE id=?",(brand_id,)).fetchone()
            if selected:
                models=conn.execute("SELECT * FROM vehicle_models_catalog WHERE brand_id=? ORDER BY name LIMIT 500",(brand_id,)).fetchall()
        last_sync=setting(conn,"vehicle_catalog_full_sync","")
    return templates.TemplateResponse(request,"admin_vehicle_catalog.html",template_ctx(request,stats=stats,brands=brands,selected=selected,models=models,vehicle_type=vehicle_type,q=q,last_sync=last_sync))


@app.post("/admin/catalogo-veiculos/sincronizar-tudo")
def admin_vehicle_catalog_sync_all(request: Request):
    _admin_required(request)
    try:
        summary=sync_vehicle_catalog_all()
        err=len(summary["errors"])
        return RedirectResponse(f"/admin/catalogo-veiculos?full=1&brands={summary['brands']}&models={summary['generic_models']}&raw={summary['raw_models']}&errors={err}",303)
    except Exception as exc:
        return RedirectResponse(f"/admin/catalogo-veiculos?error={urllib.parse.quote(str(exc)[:180])}",303)


@app.post("/admin/catalogo-veiculos/sincronizar-marca/{brand_id}")
def admin_vehicle_catalog_sync_brand(request: Request, brand_id: int):
    _admin_required(request)
    with closing(db_conn()) as conn:
        try:
            generic_count,raw_count=sync_vehicle_models_for_brand(conn,brand_id)
            return RedirectResponse(f"/admin/catalogo-veiculos?brand_id={brand_id}&synced={generic_count}&raw={raw_count}",303)
        except Exception as exc:
            return RedirectResponse(f"/admin/catalogo-veiculos?brand_id={brand_id}&error={urllib.parse.quote(str(exc)[:180])}",303)


@app.post("/admin/catalogo-veiculos/modelo/{model_id}")
def admin_vehicle_catalog_model_update(request: Request, model_id: int, name: str=Form(...), suggested_category: str=Form("car_small"), active: str=Form("0")):
    _admin_required(request)
    if suggested_category not in {"car_small","car_large","moto"}: suggested_category="car_small"
    with closing(db_conn()) as conn:
        row=conn.execute("SELECT brand_id FROM vehicle_models_catalog WHERE id=?",(model_id,)).fetchone()
        if not row: raise HTTPException(404)
        conn.execute("UPDATE vehicle_models_catalog SET name=?,search_text=?,suggested_category=?,active=? WHERE id=?",(name.strip(),normalize_search(name),suggested_category,1 if active=="1" else 0,model_id)); conn.commit()
        bid=row["brand_id"]
    return RedirectResponse(f"/admin/catalogo-veiculos?brand_id={bid}",303)


@app.post("/admin/catalogo-veiculos/marca/{brand_id}")
def admin_vehicle_catalog_brand_update(request: Request, brand_id: int, name: str=Form(...), active: str=Form("0")):
    _admin_required(request)
    with closing(db_conn()) as conn:
        row=conn.execute("SELECT vehicle_type FROM vehicle_brands_catalog WHERE id=?",(brand_id,)).fetchone()
        if not row: raise HTTPException(404)
        conn.execute("UPDATE vehicle_brands_catalog SET name=?,search_text=?,active=? WHERE id=?",(name.strip(),normalize_search(name),1 if active=="1" else 0,brand_id)); conn.commit()
        vt=row["vehicle_type"]
    return RedirectResponse(f"/admin/catalogo-veiculos?vehicle_type={vt}&brand_id={brand_id}",303)


@app.get("/admin/configuracoes", response_class=HTMLResponse)
def admin_settings_page(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    with closing(db_conn()) as conn:
        company = get_company_settings(conn)
        logo_path = setting(conn, "brand_logo_path", "")
    backups = sorted(BACKUP_DIR.glob("ph_estetica_*.db"), key=lambda x:x.stat().st_mtime, reverse=True)[:10]
    return templates.TemplateResponse(request, "admin_settings.html", template_ctx(request, settings=company, logo_path=logo_path, backups=backups))


@app.post("/admin/configuracoes")
def admin_settings_save(request: Request, whatsapp_number: str = Form(""), home_eyebrow: str = Form(""), home_headline: str = Form(""), home_subtitle: str = Form(""), home_gallery_title: str = Form(""), instagram: str = Form(""), cancel_min_hours: int = Form(2), reschedule_min_hours: int = Form(2), backup_retention_days: int = Form(30)):
    _admin_required(request)
    wa = re.sub(r"\D", "", whatsapp_number)
    if wa and not wa.startswith("55"):
        wa = "55" + wa
    values = {
        "whatsapp_number": wa or WHATSAPP_NUMBER,
        "home_eyebrow": home_eyebrow[:100] or DEFAULT_COMPANY_SETTINGS["home_eyebrow"],
        "home_headline": home_headline[:160] or DEFAULT_COMPANY_SETTINGS["home_headline"],
        "home_subtitle": home_subtitle[:320] or DEFAULT_COMPANY_SETTINGS["home_subtitle"],
        "home_gallery_title": home_gallery_title[:120] or DEFAULT_COMPANY_SETTINGS["home_gallery_title"],
        "instagram": instagram[:120],
        "cancel_min_hours": str(max(0,cancel_min_hours)),
        "reschedule_min_hours": str(max(0,reschedule_min_hours)),
        "backup_retention_days": str(max(7,backup_retention_days)),
    }
    with closing(db_conn()) as conn:
        for k,v in values.items():
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (k,v))
        conn.commit()
    return RedirectResponse("/admin/configuracoes?saved=1", 303)


@app.post("/admin/configuracoes/mensagens-whatsapp")
def admin_whatsapp_messages_save(
    request: Request,
    wa_msg_scheduled: str = Form(""), wa_msg_received: str = Form(""),
    wa_msg_preparation: str = Form(""), wa_msg_washing: str = Form(""),
    wa_msg_detailing: str = Form(""), wa_msg_finishing: str = Form(""),
    wa_msg_inspection: str = Form(""), wa_msg_ready: str = Form(""),
    wa_msg_completed: str = Form(""), wa_msg_cancelled: str = Form(""),
    wa_msg_payment_pending: str = Form(""),
):
    _admin_required(request)
    submitted = {
        "wa_msg_scheduled": wa_msg_scheduled,
        "wa_msg_received": wa_msg_received,
        "wa_msg_preparation": wa_msg_preparation,
        "wa_msg_washing": wa_msg_washing,
        "wa_msg_detailing": wa_msg_detailing,
        "wa_msg_finishing": wa_msg_finishing,
        "wa_msg_inspection": wa_msg_inspection,
        "wa_msg_ready": wa_msg_ready,
        "wa_msg_completed": wa_msg_completed,
        "wa_msg_cancelled": wa_msg_cancelled,
        "wa_msg_payment_pending": wa_msg_payment_pending,
    }
    with closing(db_conn()) as conn:
        for key, value in submitted.items():
            clean = (value or "").strip()[:1200]
            if not clean:
                clean = DEFAULT_COMPANY_SETTINGS[key]
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, clean))
        conn.commit()
    return RedirectResponse("/admin/configuracoes?wa_messages=1#mensagens-whatsapp", 303)


@app.post("/admin/configuracoes/mensagens-whatsapp/restaurar")
def admin_whatsapp_messages_reset(request: Request):
    _admin_required(request)
    keys = [key for key in DEFAULT_COMPANY_SETTINGS if key.startswith("wa_msg_")]
    with closing(db_conn()) as conn:
        for key in keys:
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, DEFAULT_COMPANY_SETTINGS[key]))
        conn.commit()
    return RedirectResponse("/admin/configuracoes?wa_messages_reset=1#mensagens-whatsapp", 303)


@app.post("/admin/configuracoes/logo")
async def admin_logo_upload(request: Request, logo: UploadFile = File(...)):
    _admin_required(request)
    fname = await _save_image(logo, "brand_logo")
    with closing(db_conn()) as conn:
        old = setting(conn, "brand_logo_path", "")
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('brand_logo_path',?)", (fname,))
        conn.commit()
    if old:
        try: (UPLOAD_DIR / old).unlink(missing_ok=True)
        except OSError: pass
    return RedirectResponse("/admin/configuracoes?logo=1", 303)


@app.post("/admin/configuracoes/imagem-home/{slot}")
async def admin_home_image_upload(request: Request, slot: str, photo: UploadFile = File(...)):
    _admin_required(request)
    if slot not in HOME_IMAGE_SLOTS:
        raise HTTPException(404, "Área de imagem inválida.")
    key, _label = HOME_IMAGE_SLOTS[slot]
    fname = await _save_image(photo, f"home_{slot}")
    new_value = f"/uploads/{fname}"
    with closing(db_conn()) as conn:
        old_value = setting(conn, key, DEFAULT_COMPANY_SETTINGS[key])
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key,new_value))
        conn.commit()
    if old_value.startswith("/uploads/"):
        try:
            (UPLOAD_DIR / old_value.split("/uploads/",1)[1]).unlink(missing_ok=True)
        except OSError:
            pass
    return RedirectResponse(f"/admin/configuracoes?image={slot}", 303)


@app.post("/admin/configuracoes/imagem-home/{slot}/restaurar")
def admin_home_image_reset(request: Request, slot: str):
    _admin_required(request)
    if slot not in HOME_IMAGE_SLOTS:
        raise HTTPException(404, "Área de imagem inválida.")
    key, _label = HOME_IMAGE_SLOTS[slot]
    with closing(db_conn()) as conn:
        old_value = setting(conn, key, DEFAULT_COMPANY_SETTINGS[key])
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key,DEFAULT_COMPANY_SETTINGS[key]))
        conn.commit()
    if old_value.startswith("/uploads/"):
        try:
            (UPLOAD_DIR / old_value.split("/uploads/",1)[1]).unlink(missing_ok=True)
        except OSError:
            pass
    return RedirectResponse(f"/admin/configuracoes?image_reset={slot}", 303)


@app.get("/admin/backup")
def admin_backup_download(request: Request):
    _admin_required(request)
    path = create_daily_backup(force=True)
    if not path:
        raise HTTPException(500, "Não foi possível gerar o backup.")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@app.get("/admin/lembretes", response_class=HTMLResponse)
def admin_reminders(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse("/admin/login", 303)
    tomorrow = (date.today()+timedelta(days=1)).isoformat()
    with closing(db_conn()) as conn:
        rows = conn.execute("""SELECT a.*,c.name customer_name,c.phone,v.brand,v.model,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id WHERE a.appointment_date=? AND a.status='scheduled' ORDER BY a.appointment_time""", (tomorrow,)).fetchall()
        wa_business = current_whatsapp_number(conn)
    items=[]
    for r in rows:
        msg=f"Olá, {r['customer_name'].split()[0]}! Passando para lembrar que seu horário na PH ESTÉTICA & DETAIL é amanhã, {fmt_date(r['appointment_date'])}, às {r['appointment_time']}. Veículo: {r['brand']} {r['model']}."
        phone = r['phone'] if r['phone'].startswith('55') else '55'+r['phone']
        item=dict(r); item['wa_url']=f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"; items.append(item)
    return templates.TemplateResponse(request, "admin_reminders.html", template_ctx(request, rows=items, tomorrow=tomorrow))


@app.get("/tv", response_class=HTMLResponse)
def tv_mode(request: Request):
    today=date.today().isoformat()
    with closing(db_conn()) as conn:
        rows=conn.execute("""SELECT a.code,a.appointment_time,a.status,v.model FROM appointments a JOIN vehicles v ON v.id=a.vehicle_id WHERE a.appointment_date=? AND a.status!='cancelled' ORDER BY a.appointment_time""",(today,)).fetchall()
    return templates.TemplateResponse(request, "tv.html",template_ctx(request,rows=rows,now=datetime.now()))


@app.get("/saude")
def health():
    return {"ok": True, "app": BUSINESS_NAME}


# ==================================================
# V12 — MÓDULO FINANCEIRO COMPLETO
# ==================================================
FINANCE_TABS = [
    ("/admin/financeiro","Visão Geral"),("/admin/financeiro/receitas","Receitas"),("/admin/financeiro/despesas","Despesas"),
    ("/admin/financeiro/investimentos","Investimentos"),("/admin/financeiro/aportes","Aportes"),("/admin/financeiro/ajudantes","Ajudantes"),
    ("/admin/financeiro/fluxo-caixa","Fluxo de Caixa"),("/admin/financeiro/fechamento","Fechamento Mensal")
]


def _finance_ctx(request, **kwargs):
    return template_ctx(request, finance_tabs=FINANCE_TABS, **kwargs)


@app.get("/admin/financeiro/receitas", response_class=HTMLResponse)
def finance_revenues_page(request: Request):
    _admin_required(request); p=_finance_period(request)
    with closing(db_conn()) as conn:
        for r in conn.execute("SELECT id FROM appointments WHERE payment_status='paid'").fetchall(): sync_finance_revenue(conn,r["id"],"Sincronização de receitas")
        conn.commit()
        rows=conn.execute("""SELECT fr.*,a.code,a.appointment_date,c.name customer_name,v.brand,v.model,s.name service_name FROM finance_revenues fr JOIN appointments a ON a.id=fr.appointment_id JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id WHERE substr(fr.paid_at,1,10) BETWEEN ? AND ? ORDER BY fr.paid_at DESC""",(p["start"],p["end"])).fetchall()
        total=sum(float(r["amount"] or 0) for r in rows if r["status"]=="paid")
        methods=get_payment_methods(conn,active_only=False)
        pending_rows=conn.execute("""SELECT a.*,c.name customer_name,c.phone,v.brand,v.model,s.name service_name FROM appointments a JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id JOIN services s ON s.id=a.service_id WHERE a.payment_status!='paid' AND a.status!='cancelled' ORDER BY a.appointment_date,a.appointment_time LIMIT 300""").fetchall()
        by_method=conn.execute("SELECT payment_method,COUNT(*) n,COALESCE(SUM(amount),0) total FROM finance_revenues WHERE status='paid' AND substr(paid_at,1,10) BETWEEN ? AND ? GROUP BY payment_method ORDER BY total DESC",(p["start"],p["end"])).fetchall()
    return templates.TemplateResponse(request,"admin_finance_revenues.html",_finance_ctx(request,period=p,rows=rows,total=total,methods=methods,pending_rows=pending_rows,by_method=by_method))


@app.get("/admin/financeiro/despesas", response_class=HTMLResponse)
def finance_expenses_page(request: Request):
    _admin_required(request); p=_finance_period(request)
    with closing(db_conn()) as conn:
        categories=conn.execute("SELECT * FROM expense_categories ORDER BY sort_order,name").fetchall()
        methods=get_payment_methods(conn,active_only=False)
        rows=conn.execute("""SELECT e.*,c.name category_name FROM finance_expenses e JOIN expense_categories c ON c.id=e.category_id WHERE e.cancelled_at IS NULL AND e.expense_date BETWEEN ? AND ? ORDER BY e.expense_date DESC,e.id DESC""",(p["start"],p["end"])).fetchall()
        totals={"paid":sum(float(r["amount"]) for r in rows if r["status"]=="paid"),"pending":sum(float(r["amount"]) for r in rows if r["status"]=="pending")}
    return templates.TemplateResponse(request,"admin_finance_expenses.html",_finance_ctx(request,period=p,categories=categories,methods=methods,rows=rows,totals=totals))


@app.post("/admin/financeiro/despesas/novo")
def finance_expense_create(request: Request,description:str=Form(...),category_id:int=Form(...),amount:str=Form(...),expense_date:str=Form(...),due_date:str=Form(""),paid_date:str=Form(""),competence:str=Form(""),payment_method:str=Form(""),status:str=Form("pending"),supplier:str=Form(""),notes:str=Form("")):
    _admin_required(request)
    if status not in {"pending","paid"}: raise HTTPException(400,"Status inválido")
    value=_money(amount)
    if value<=0: raise HTTPException(400,"Informe um valor válido")
    if status=="paid" and not paid_date: paid_date=expense_date
    with closing(db_conn()) as conn:
        if not conn.execute("SELECT 1 FROM expense_categories WHERE id=?",(category_id,)).fetchone(): raise HTTPException(400,"Categoria inválida")
        conn.execute("INSERT INTO finance_expenses(description,category_id,amount,expense_date,due_date,paid_date,competence,payment_method,status,supplier,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(description.strip(),category_id,value,expense_date,due_date or None,paid_date or None,competence or expense_date[:7],payment_method,status,supplier.strip(),notes.strip(),now_iso()))
        conn.commit()
    return RedirectResponse("/admin/financeiro/despesas?created=1",303)


@app.post("/admin/financeiro/despesas/{expense_id}/pagar")
def finance_expense_pay(request: Request,expense_id:int,paid_date:str=Form(""),payment_method:str=Form("")):
    _admin_required(request)
    with closing(db_conn()) as conn:
        e=conn.execute("SELECT * FROM finance_expenses WHERE id=? AND cancelled_at IS NULL",(expense_id,)).fetchone()
        if not e: raise HTTPException(404)
        conn.execute("UPDATE finance_expenses SET status='paid',paid_date=?,payment_method=COALESCE(NULLIF(?,''),payment_method) WHERE id=?",(paid_date or date.today().isoformat(),payment_method,expense_id)); conn.commit()
    return RedirectResponse("/admin/financeiro/despesas?paid=1",303)


@app.post("/admin/financeiro/despesas/{expense_id}/cancelar")
def finance_expense_cancel(request: Request,expense_id:int):
    _admin_required(request)
    with closing(db_conn()) as conn: conn.execute("UPDATE finance_expenses SET cancelled_at=? WHERE id=?",(now_iso(),expense_id)); conn.commit()
    return RedirectResponse("/admin/financeiro/despesas?cancelled=1",303)


@app.post("/admin/financeiro/categorias-despesa")
def finance_expense_category_create(request: Request,name:str=Form(...)):
    _admin_required(request)
    with closing(db_conn()) as conn:
        order=conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM expense_categories").fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO expense_categories(name,active,sort_order) VALUES (?,1,?)",(name.strip(),order)); conn.commit()
    return RedirectResponse("/admin/financeiro/despesas?category=1",303)


@app.get("/admin/financeiro/investimentos", response_class=HTMLResponse)
def finance_investments_page(request: Request):
    _admin_required(request); p=_finance_period(request)
    with closing(db_conn()) as conn:
        cats=conn.execute("SELECT * FROM investment_categories ORDER BY sort_order,name").fetchall(); methods=get_payment_methods(conn,active_only=False)
        rows=conn.execute("""SELECT i.*,c.name category_name FROM finance_investments i JOIN investment_categories c ON c.id=i.category_id WHERE i.cancelled_at IS NULL AND i.purchase_date BETWEEN ? AND ? ORDER BY i.purchase_date DESC,i.id DESC""",(p["start"],p["end"])).fetchall()
        total=sum(float(r["amount"]) for r in rows)
    return templates.TemplateResponse(request,"admin_finance_investments.html",_finance_ctx(request,period=p,categories=cats,methods=methods,rows=rows,total=total))


@app.post("/admin/financeiro/investimentos/novo")
def finance_investment_create(request: Request,description:str=Form(...),category_id:int=Form(...),amount:str=Form(...),purchase_date:str=Form(...),payment_method:str=Form(""),supplier:str=Form(""),notes:str=Form("")):
    _admin_required(request); value=_money(amount)
    if value<=0: raise HTTPException(400,"Informe um valor válido")
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO finance_investments(description,category_id,amount,purchase_date,payment_method,supplier,notes,created_at) VALUES (?,?,?,?,?,?,?,?)",(description.strip(),category_id,value,purchase_date,payment_method,supplier.strip(),notes.strip(),now_iso())); conn.commit()
    return RedirectResponse("/admin/financeiro/investimentos?created=1",303)


@app.post("/admin/financeiro/investimentos/{investment_id}/cancelar")
def finance_investment_cancel(request: Request,investment_id:int):
    _admin_required(request)
    with closing(db_conn()) as conn: conn.execute("UPDATE finance_investments SET cancelled_at=? WHERE id=?",(now_iso(),investment_id)); conn.commit()
    return RedirectResponse("/admin/financeiro/investimentos?cancelled=1",303)


@app.get("/admin/financeiro/aportes", response_class=HTMLResponse)
def finance_contributions_page(request: Request):
    _admin_required(request); p=_finance_period(request)
    with closing(db_conn()) as conn:
        methods=get_payment_methods(conn,active_only=False)
        rows=conn.execute("SELECT * FROM owner_contributions WHERE cancelled_at IS NULL AND contribution_date BETWEEN ? AND ? ORDER BY contribution_date DESC,id DESC",(p["start"],p["end"])).fetchall()
        lifetime=_finance_all_time(conn)
    return templates.TemplateResponse(request,"admin_finance_contributions.html",_finance_ctx(request,period=p,methods=methods,rows=rows,lifetime=lifetime))


@app.post("/admin/financeiro/aportes/novo")
def finance_contribution_create(request: Request,description:str=Form(...),amount:str=Form(...),contribution_date:str=Form(...),payment_method:str=Form(""),notes:str=Form("")):
    _admin_required(request); value=_money(amount)
    if value<=0: raise HTTPException(400,"Informe um valor válido")
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO owner_contributions(description,amount,contribution_date,payment_method,notes,created_at) VALUES (?,?,?,?,?,?)",(description.strip(),value,contribution_date,payment_method,notes.strip(),now_iso())); conn.commit()
    return RedirectResponse("/admin/financeiro/aportes?created=1",303)


@app.post("/admin/financeiro/aportes/{contribution_id}/cancelar")
def finance_contribution_cancel(request: Request,contribution_id:int):
    _admin_required(request)
    with closing(db_conn()) as conn: conn.execute("UPDATE owner_contributions SET cancelled_at=? WHERE id=?",(now_iso(),contribution_id)); conn.commit()
    return RedirectResponse("/admin/financeiro/aportes?cancelled=1",303)


@app.get("/admin/financeiro/ajudantes", response_class=HTMLResponse)
def finance_helpers_page(request: Request):
    _admin_required(request); p=_finance_period(request)
    with closing(db_conn()) as conn:
        helpers=conn.execute("SELECT * FROM finance_helpers ORDER BY active DESC,name").fetchall(); methods=get_payment_methods(conn,active_only=False)
        data=[]
        for h in helpers:
            generated=conn.execute("""SELECT COALESCE(SUM(ah.amount),0) FROM appointment_helper_costs ah JOIN appointments a ON a.id=ah.appointment_id WHERE ah.helper_id=? AND a.status!='cancelled'""",(h["id"],)).fetchone()[0] or 0
            paid=conn.execute("SELECT COALESCE(SUM(amount),0) FROM helper_payments WHERE helper_id=? AND cancelled_at IS NULL",(h["id"],)).fetchone()[0] or 0
            period_generated=conn.execute("""SELECT COALESCE(SUM(ah.amount),0) FROM appointment_helper_costs ah JOIN appointments a ON a.id=ah.appointment_id WHERE ah.helper_id=? AND a.status!='cancelled' AND a.appointment_date BETWEEN ? AND ?""",(h["id"],p["start"],p["end"])).fetchone()[0] or 0
            data.append({"row":h,"generated":float(generated),"paid":float(paid),"pending":max(0,float(generated)-float(paid)),"period_generated":float(period_generated)})
        payments=conn.execute("""SELECT hp.*,h.name helper_name FROM helper_payments hp JOIN finance_helpers h ON h.id=hp.helper_id WHERE hp.cancelled_at IS NULL AND hp.payment_date BETWEEN ? AND ? ORDER BY hp.payment_date DESC,hp.id DESC""",(p["start"],p["end"])).fetchall()
        service_costs=conn.execute("""SELECT ah.*,h.name helper_name,a.code,a.appointment_date,c.name customer_name,v.brand,v.model FROM appointment_helper_costs ah JOIN finance_helpers h ON h.id=ah.helper_id JOIN appointments a ON a.id=ah.appointment_id JOIN customers c ON c.id=a.customer_id JOIN vehicles v ON v.id=a.vehicle_id WHERE a.appointment_date BETWEEN ? AND ? AND a.status!='cancelled' ORDER BY a.appointment_date DESC""",(p["start"],p["end"])).fetchall()
    return templates.TemplateResponse(request,"admin_finance_helpers.html",_finance_ctx(request,period=p,helpers=data,helper_rows=helpers,methods=methods,payments=payments,service_costs=service_costs))


@app.post("/admin/financeiro/ajudantes/novo")
def finance_helper_create(request: Request,name:str=Form(...),phone:str=Form(""),default_amount:str=Form(""),active:str=Form("1")):
    _admin_required(request); default=_money(default_amount,None) if default_amount.strip() else None
    with closing(db_conn()) as conn:
        conn.execute("INSERT INTO finance_helpers(name,phone,default_amount,active,created_at) VALUES (?,?,?,?,?)",(name.strip(),normalize_phone(phone) if phone else None,default,1 if active=="1" else 0,now_iso())); conn.commit()
    return RedirectResponse("/admin/financeiro/ajudantes?created=1",303)


@app.post("/admin/financeiro/ajudantes/{helper_id}/editar")
def finance_helper_update(request: Request,helper_id:int,name:str=Form(...),phone:str=Form(""),default_amount:str=Form(""),active:str=Form("0")):
    _admin_required(request); default=_money(default_amount) if default_amount.strip() else None
    with closing(db_conn()) as conn:
        conn.execute("UPDATE finance_helpers SET name=?,phone=?,default_amount=?,active=? WHERE id=?",(name.strip(),normalize_phone(phone) if phone else None,default,1 if active=="1" else 0,helper_id)); conn.commit()
    return RedirectResponse("/admin/financeiro/ajudantes?saved=1",303)


@app.post("/admin/financeiro/ajudantes/pagar")
def finance_helper_payment(request: Request,helper_id:int=Form(...),amount:str=Form(...),payment_date:str=Form(...),payment_method:str=Form(""),notes:str=Form("")):
    _admin_required(request); value=_money(amount)
    if value<=0: raise HTTPException(400,"Valor inválido")
    with closing(db_conn()) as conn:
        generated=conn.execute("""SELECT COALESCE(SUM(ah.amount),0) FROM appointment_helper_costs ah JOIN appointments a ON a.id=ah.appointment_id WHERE ah.helper_id=? AND a.status!='cancelled'""",(helper_id,)).fetchone()[0] or 0
        paid=conn.execute("SELECT COALESCE(SUM(amount),0) FROM helper_payments WHERE helper_id=? AND cancelled_at IS NULL",(helper_id,)).fetchone()[0] or 0
        pending=max(0,float(generated)-float(paid))
        if value-pending>0.001: raise HTTPException(400,f"Pagamento maior que o saldo pendente ({brl(pending)}).")
        conn.execute("INSERT INTO helper_payments(helper_id,amount,payment_date,payment_method,notes,created_at) VALUES (?,?,?,?,?,?)",(helper_id,value,payment_date,payment_method,notes.strip(),now_iso())); conn.commit()
    return RedirectResponse("/admin/financeiro/ajudantes?paid=1",303)


@app.post("/admin/agendamento/{appointment_id}/ajudante")
def appointment_helper_cost_save(request: Request,appointment_id:int,has_helper:str=Form("0"),helper_id:str=Form(""),amount:str=Form(""),notes:str=Form("")):
    _admin_required(request)
    with closing(db_conn()) as conn:
        if has_helper != "1":
            conn.execute("DELETE FROM appointment_helper_costs WHERE appointment_id=?",(appointment_id,)); conn.commit(); return RedirectResponse(f"/admin/agendamento/{appointment_id}?helper=0",303)
        if not helper_id.isdigit(): raise HTTPException(400,"Selecione o ajudante")
        h=conn.execute("SELECT * FROM finance_helpers WHERE id=? AND active=1",(int(helper_id),)).fetchone()
        if not h: raise HTTPException(400,"Ajudante inválido")
        value=_money(amount,h["default_amount"] or 0)
        if value<=0: raise HTTPException(400,"Informe o valor do ajudante")
        if conn.execute("SELECT 1 FROM appointment_helper_costs WHERE appointment_id=?",(appointment_id,)).fetchone():
            conn.execute("UPDATE appointment_helper_costs SET helper_id=?,amount=?,notes=?,updated_at=? WHERE appointment_id=?",(int(helper_id),value,notes.strip(),now_iso(),appointment_id))
        else:
            conn.execute("INSERT INTO appointment_helper_costs(appointment_id,helper_id,amount,notes,created_at,updated_at) VALUES (?,?,?,?,?,?)",(appointment_id,int(helper_id),value,notes.strip(),now_iso(),now_iso()))
        conn.commit()
    return RedirectResponse(f"/admin/agendamento/{appointment_id}?helper=1",303)


@app.get("/admin/financeiro/fluxo-caixa", response_class=HTMLResponse)
def finance_cashflow_page(request: Request):
    _admin_required(request); p=_finance_period(request); kind=request.query_params.get("kind","all")
    if kind not in {"all","receitas","despesas","investimentos","aportes","ajudantes"}: kind="all"
    with closing(db_conn()) as conn:
        rows=_cashflow_rows(conn,p["start"],p["end"],kind)
        # Saldo disponível global, independente do filtro visual.
        cash=_finance_all_time(conn)["cash"]
    return templates.TemplateResponse(request,"admin_finance_cashflow.html",_finance_ctx(request,period=p,rows=rows,kind=kind,cash=cash))


@app.get("/admin/financeiro/fechamento", response_class=HTMLResponse)
def finance_closing_page(request: Request):
    _admin_required(request)
    competence=request.query_params.get("competence",date.today().strftime("%Y-%m"))
    try: dt=datetime.strptime(competence,"%Y-%m")
    except ValueError: dt=datetime.today(); competence=dt.strftime("%Y-%m")
    start=f"{competence}-01"; end=(date(dt.year+1,1,1)-timedelta(days=1) if dt.month==12 else date(dt.year,dt.month+1,1)-timedelta(days=1)).isoformat()
    with closing(db_conn()) as conn:
        s=_finance_summary(conn,start,end); lifetime=_finance_all_time(conn)
        pending_exp=conn.execute("SELECT COALESCE(SUM(amount),0) FROM finance_expenses WHERE status='pending' AND cancelled_at IS NULL AND competence=?",(competence,)).fetchone()[0] or 0
        helper_pending=lifetime["pending_helper"]
        paid_exp=s["expenses"]; investments=s["investments"]
        helper_service_count=conn.execute("""SELECT COUNT(*) FROM appointment_helper_costs ah JOIN appointments a ON a.id=ah.appointment_id WHERE a.status!='cancelled' AND a.appointment_date BETWEEN ? AND ?""",(start,end)).fetchone()[0] or 0
        avg_helper=(s["helper_generated"]/helper_service_count if helper_service_count else 0)
        service_analysis=conn.execute("""SELECT s.name service_name,COUNT(DISTINCT a.id) qty,COALESCE(SUM(fr.amount),0) revenue,COALESCE(SUM((SELECT amount FROM appointment_helper_costs ah WHERE ah.appointment_id=a.id)),0) helper_cost FROM appointments a JOIN services s ON s.id=a.service_id JOIN finance_revenues fr ON fr.appointment_id=a.id AND fr.status='paid' WHERE a.appointment_date BETWEEN ? AND ? GROUP BY s.id ORDER BY revenue DESC""",(start,end)).fetchall()
    return templates.TemplateResponse(request,"admin_finance_closing.html",_finance_ctx(request,competence=competence,start=start,end=end,summary=s,lifetime=lifetime,pending_expenses=float(pending_exp),helper_pending=helper_pending,paid_expenses=paid_exp,investments=investments,avg_helper=avg_helper,service_analysis=service_analysis))

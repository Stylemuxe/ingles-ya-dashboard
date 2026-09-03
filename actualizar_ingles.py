#!/usr/bin/env python3
# actualizar_ingles.py — Inglés YA Dashboard
# Uso: python actualizar_ingles.py              (mes actual)
#      python actualizar_ingles.py --mes 2026-05 (mes específico)

import os, json, csv, io, re, sys, argparse, calendar
import requests
from datetime import datetime, date

# ─── ARGUMENTOS ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--mes', default=None, help='Mes a procesar YYYY-MM (default: mes actual)')
args = parser.parse_args()

if args.mes:
    year, month = map(int, args.mes.split('-'))
    ultimo_dia  = calendar.monthrange(year, month)[1]
    HOY         = date(year, month, ultimo_dia)
    MES_ACTUAL  = args.mes
else:
    HOY        = date.today()
    MES_ACTUAL = HOY.strftime('%Y-%m')

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TOKEN      = os.environ.get('TOKEN_INGLES_YA', '')
AD_ACCOUNT = 'act_181774505226108'
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
API_BASE   = 'https://graph.facebook.com/v19.0'

SHEET_SEG_ID  = '1mlIqrmxvEou-occ3Osv7DJv_O_jvU0c-'
# GID por mes — agregar cada mes nuevo aqui
SHEET_SEG_GIDS = {
    '2026-05': '1913702244',
    '2026-06': '768692381',
    '2026-07': '1235374062',
    '2026-08': '686971736',
    '2026-09': '701082000',
}
SHEET_SEG_GID = SHEET_SEG_GIDS.get(MES_ACTUAL, '768692381')
SHEET_AGE_ID  = '1MtKus1GkNxZGriSN2Ku5kNNaaROK6hoL'
SHEET_AGE_GIDS = {
    'LINDAVISTA': '60143132',
    'IZTACALCO':  '1436665808',
    'ERMITA':     '801240161',
}

SUCURSALES = ['LINDAVISTA', 'IZTACALCO', 'ERMITA']

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def si(v, d=0):
    try: return int(str(v).replace(',', '').strip() or d)
    except: return d

def sf(v, d=0.0):
    try: return float(str(v).replace(',', '').strip() or d)
    except: return d

def money(v, d=0.0):
    """Convierte celdas de dinero a float, sin importar si Vic las tecleó
    como '$14,239.00' (coma=miles, punto=decimales) o como '29.568' /
    '891,00' (formato mixto que a veces captura a mano). Antes esta función
    solo quitaba $/espacios y asumía SIEMPRE coma=miles, punto=decimal — eso
    interpretaba '29.568' como 29.568 pesos (÷1000) y '891,00' como 89100
    pesos (x100) en vez de 29,568 y 891. Ahora detecta el formato real de
    cada celda antes de convertir."""
    s = re.sub(r'[^0-9.,\-]', '', str(v)).strip()
    if s in ('', '-', '.', ','):
        return d
    try:
        tiene_coma = ',' in s
        tiene_punto = '.' in s
        if tiene_coma and tiene_punto:
            # El último separador que aparece es el decimal; el otro es de miles.
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.', '').replace(',', '.')   # 1.234,56 -> 1234.56
            else:
                s = s.replace(',', '')                      # 1,234.56 -> 1234.56
        elif tiene_coma:
            entero, _, frac = s.rpartition(',')
            # 3 dígitos exactos tras la coma y hay parte entera -> separador de
            # miles ('29,568' -> 29568). Si no, es coma decimal ('891,00'/'45,5').
            s = s.replace(',', '') if (entero and len(frac) == 3) else s.replace(',', '.')
        elif tiene_punto:
            entero, _, frac = s.rpartition('.')
            # Mismo criterio pero con punto: '29.568'/'12.000' -> miles;
            # '29.50' (2 dígitos, centavos normales) se deja como decimal.
            if entero and len(frac) == 3:
                s = s.replace('.', '')
        return float(s) if s not in ('', '-', '.') else d
    except: return d

MESES_TXT = {
    '01':'Enero','02':'Febrero','03':'Marzo','04':'Abril','05':'Mayo','06':'Junio',
    '07':'Julio','08':'Agosto','09':'Septiembre','10':'Octubre','11':'Noviembre','12':'Diciembre'
}

def parse_fecha(s):
    s = str(s).strip()
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%y'):
        try: return datetime.strptime(s, fmt).date()
        except: pass
    return None

def fetch_csv_sheet(sheet_id, gid):
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}'
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.text
        print(f'  AVISO: Sheet HTTP {r.status_code}')
        return None
    except Exception as e:
        print(f'  ERROR al leer Sheet: {e}')
        return None

# ─── META ADS ────────────────────────────────────────────────────────────────
class MetaAPIError(Exception):
    pass

def meta_get(endpoint, params):
    params['access_token'] = TOKEN
    r = requests.get(f'{API_BASE}/{endpoint}', params=params, timeout=30)
    j = r.json()
    if 'error' in j:
        err = j['error']
        raise MetaAPIError(f"{err.get('message', '?')} (code {err.get('code', '?')})")
    return j

def time_range():
    return json.dumps({'since': f'{MES_ACTUAL}-01', 'until': HOY.strftime('%Y-%m-%d')})

def fetch_campanas():
    tr = time_range()
    resp = meta_get(f'{AD_ACCOUNT}/campaigns', {
        'fields': f'name,status,daily_budget,insights.time_range({tr}){{spend,impressions,reach,actions}}',
        'limit':  25,
    })
    out = []
    for c in resp.get('data', []):
        ins   = ((c.get('insights') or {}).get('data') or [{}])[0]
        leads = next((si(a['value']) for a in ins.get('actions', [])
                      if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), 0)
        gasto = sf(ins.get('spend', 0))
        out.append({
            'id':              c['id'],
            'nombre':          c['name'],
            'status':          c['status'],
            'presupuesto_dia': round(sf(c.get('daily_budget', 0)) / 100, 2),
            'gasto':           round(gasto, 2),
            'impresiones':     si(ins.get('impressions', 0)),
            'alcance':         si(ins.get('reach', 0)),
            'leads':           leads,
            'cpl':             round(gasto / leads, 2) if leads else 0,
        })
    return out

def fetch_adsets():
    tr = time_range()
    resp = meta_get(f'{AD_ACCOUNT}/adsets', {
        'fields': f'name,status,daily_budget,campaign_id,insights.time_range({tr}){{spend,actions}}',
        'limit':  50,
    })
    out = []
    for a in resp.get('data', []):
        ins   = ((a.get('insights') or {}).get('data') or [{}])[0]
        leads = next((si(x['value']) for x in ins.get('actions', [])
                      if x['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), 0)
        gasto = sf(ins.get('spend', 0))
        out.append({
            'nombre':          a['name'],
            'status':          a['status'],
            'campaign_id':     a.get('campaign_id', ''),
            'presupuesto_dia': round(sf(a.get('daily_budget', 0)) / 100, 2),
            'gasto':           round(gasto, 2),
            'leads':           leads,
            'cpl':             round(gasto / leads, 2) if leads else 0,
        })
    return out

def fetch_diario_meta():
    resp = meta_get(f'{AD_ACCOUNT}/insights', {
        'fields':         'date_start,spend,actions',
        'time_increment': 1,
        'time_range':     time_range(),
        'level':          'account',
        'limit':          60,
    })
    out = {}
    for d in resp.get('data', []):
        leads = next((si(a['value']) for a in d.get('actions', [])
                      if a['action_type'] == 'onsite_conversion.messaging_conversation_started_7d'), 0)
        out[d['date_start']] = {'leads': leads, 'gasto': round(sf(d.get('spend', 0)), 2)}
    return out

# ─── SEGUIMIENTO ─────────────────────────────────────────────────────────────
def parse_seguimiento(text):
    rows    = list(csv.reader(io.StringIO(text)))
    totales = {s: dict(leads=0, llamadas=0, no_contesta=0, citas=0, visitas=0, inscritos=0)
               for s in SUCURSALES}
    diario  = {}
    cur_date = None

    for row in rows:
        if not any(c.strip() for c in row):
            continue
        col0 = row[0].strip() if row else ''
        col1 = row[1].strip() if len(row) > 1 else ''

        d = parse_fecha(col1) or parse_fecha(col0)
        if d:
            cur_date = d
            continue

        suc, offset = None, None
        if col1.upper() in SUCURSALES:
            suc, offset = col1.upper(), 2
        elif col0.upper() in SUCURSALES:
            suc, offset = col0.upper(), 1

        if not suc or not cur_date or cur_date.strftime('%Y-%m') != MES_ACTUAL:
            continue

        # Columnas: leads, llamadas, %llamadas, no_contesta, %no_contesta,
        #           citas, %citas, cita_efectiva, %cita_ef, %visita, inscritos
        try:
            leads       = si(row[offset + 0])
            llamadas    = si(row[offset + 1])
            no_contesta = si(row[offset + 3])
            citas       = si(row[offset + 5])
            visitas     = si(row[offset + 7])
            inscritos   = si(row[offset + 10])
        except IndexError:
            continue

        t = totales[suc]
        t['leads']       += leads
        t['llamadas']    += llamadas
        t['no_contesta'] += no_contesta
        t['citas']       += citas
        t['visitas']     += visitas
        t['inscritos']   += inscritos

        ds = cur_date.strftime('%Y-%m-%d')
        diario.setdefault(ds, {})[suc] = {
            'leads': leads, 'llamadas': llamadas,
            'citas': citas, 'visitas': visitas, 'inscritos': inscritos,
        }

    return totales, diario

def parse_seguimiento_mensual(text):
    """Lee el bloque 'ACUMULADO MENSUAL' (columna 'M', a la derecha del sheet)
    en vez de sumar los bloques diarios uno por uno. Yolanda/CC ya lo calculan
    ahi mismo con formulas de Sheets, por lo que es inmune a typos de fecha en
    las filas diarias (ej. '6/4/2026' en vez de '6/7/2026') y coincide con lo
    que reporta el Contact Center."""
    rows = list(csv.reader(io.StringIO(text)))
    totales = {s: dict(leads=0, llamadas=0, no_contesta=0, citas=0, visitas=0, inscritos=0)
               for s in SUCURSALES}
    cur_section = None

    for row in rows:
        if len(row) <= 19:
            continue
        col18 = row[18].strip() if len(row) > 18 else ''
        if col18 and col18.upper() not in SUCURSALES:
            cur_section = col18.upper()
            continue
        if cur_section != 'M' or col18.upper() not in SUCURSALES:
            continue

        suc = col18.upper()
        try:
            totales[suc] = dict(
                leads       = si(row[19]),
                llamadas    = si(row[20]),
                no_contesta = si(row[22]),
                citas       = si(row[24]),
                visitas     = si(row[26]),
                inscritos   = si(row[29]),
            )
        except IndexError:
            continue

    return totales

def parse_financiero(text):
    """Lee el bloque financiero de cierre de mes que Vic llena a mano en el
    sheet de seguimiento (columnas M/META/FABIÁN/YOLANDA, filas
    GASTOS/INGRESOS/UTILIDAD/TICKET PROM que aparecen al final del embudo
    diario). Cada mes vive en su propia pestaña del Sheet (ver
    SHEET_SEG_GIDS), así que basta con leer ese bloque una vez por texto — no
    hace falta filtrar por nombre de mes. Si el mes aún no tiene ese bloque
    (no ha cerrado o Vic no lo ha llenado), devuelve todo en cero."""
    rows = list(csv.reader(io.StringIO(text)))
    resultado = dict(gasto_meta=0.0, gasto_fabian=0.0, gasto_yolanda=0.0,
                      ingresos=0.0, utilidad=0.0, ticket_prom=0.0)

    for row in rows:
        if not any(c.strip() for c in row):
            continue
        # La etiqueta (GASTOS/INGRESOS/UTILIDAD/TICKET PROM) vive en la
        # columna 19 (0-index), un lugar a la derecha del bloque 'S1'/'M' del
        # embudo (columna 18) — así quedó tecleado a mano en el Sheet.
        col19 = row[19].strip().upper() if len(row) > 19 else ''
        if col19 == 'GASTOS' and len(row) > 22:
            resultado['gasto_meta']    = money(row[20])
            resultado['gasto_fabian']  = money(row[21])
            resultado['gasto_yolanda'] = money(row[22])
        elif col19 == 'INGRESOS' and len(row) > 20:
            resultado['ingresos'] = money(row[20])
        elif col19 == 'UTILIDAD' and len(row) > 20:
            resultado['utilidad'] = money(row[20])
        elif col19 == 'TICKET PROM' and len(row) > 20:
            resultado['ticket_prom'] = money(row[20])

    return resultado

# ─── ASISTENCIA (desde HOJA AGENDA) ──────────────────────────────────────────
def calc_asistencia(agenda, sucursales):
    """Tasa de asistencia real: de las citas registradas en la Hoja Agenda de
    cada sucursal (columna ASIS: SÍ/NO/en blanco), cuántas efectivamente
    acudieron. 'asistio' ahora es tri-estado (True/False/None) para no contar
    una cita sin dato todavía capturado como si fuera un 'no vino'.

    'tasa_asistencia' (la que se muestra como principal) se calcula sobre el
    TOTAL de citas agendadas -- las que aún no tienen SÍ/NO capturado cuentan
    en el denominador como pendientes/no confirmadas, así el % no se ve
    inflado por captura atrasada (pedido de Vic, 2026-08-20). La versión
    'tasa_asistencia_con_dato' (solo sobre citas con SÍ/NO ya capturado) se
    conserva como referencia secundaria."""
    totales = {s: dict(citas_agendadas=0, asistieron=0, no_asistieron=0, sin_dato=0)
               for s in sucursales}
    for a in agenda:
        suc = a.get('sucursal')
        if suc not in totales:
            continue
        totales[suc]['citas_agendadas'] += 1
        asis = a.get('asistio')
        if asis is True:
            totales[suc]['asistieron'] += 1
        elif asis is False:
            totales[suc]['no_asistieron'] += 1
        else:
            totales[suc]['sin_dato'] += 1
    for s in totales:
        t = totales[s]
        con_dato = t['asistieron'] + t['no_asistieron']
        t['tasa_asistencia']          = round(100 * t['asistieron'] / t['citas_agendadas'], 1) if t['citas_agendadas'] else 0.0
        t['tasa_asistencia_con_dato'] = round(100 * t['asistieron'] / con_dato, 1) if con_dato else 0.0
    return totales

# ─── AGENDA ──────────────────────────────────────────────────────────────────
SKIP_KW = ('HOJA AGENDA', 'SUCURSAL:', 'FECHA:')

def tri(v):
    """SÍ/SI -> True, NO -> False, cualquier otra cosa (vacío, 'pendiente',
    etc.) -> None (sin dato todavía). Evita contar 'sin dato' como 'no vino'."""
    v = (v or '').strip().upper()
    if v in ('SÍ', 'SI'):
        return True
    if v == 'NO':
        return False
    return None

def parse_agenda(text, sucursal):
    rows     = list(csv.reader(io.StringIO(text)))
    agenda   = []
    cur_date = None

    for row in rows:
        if not any(c.strip() for c in row):
            continue
        col0      = row[0].strip()
        full_text = ' '.join(row).upper()

        if any(kw in full_text for kw in SKIP_KW):
            continue
        if col0.upper() in ('NOMBRE', 'TEL', 'CORREO', 'CORREO ELECTRÓNICO'):
            continue

        # Detectar fila de fecha (encabezado de sección) — incluye typos como 15-06026
        d = parse_fecha(col0)
        if d:
            cur_date = d
            continue
        if re.match(r'^\s*\d{2}[-/]\d{2}[-/]?\d{2,4}\s*$', col0):
            continue

        nombre = re.sub(r'^(SÍ|SI|NO)\s+', '', col0, flags=re.IGNORECASE).strip()
        if not nombre or len(nombre) < 3:
            continue

        # Solo prospectos cuya sección de fecha corresponde al mes actual
        if cur_date is None or cur_date.strftime('%Y-%m') != MES_ACTUAL:
            continue

        try:
            tel  = row[1].strip() if len(row) > 1 else ''
            fecha= row[3].strip() if len(row) > 3 else ''
            asis = tri(row[4] if len(row) > 4 else '')
            insc = tri(row[5] if len(row) > 5 else '')
            obs  = row[6].strip() if len(row) > 6 else ''
        except Exception:
            continue

        if nombre and (tel or fecha):
            agenda.append({
                'sucursal':   sucursal,
                'nombre':     nombre,
                'tel':        tel,
                'fecha_cita': fecha,
                'asistio':    asis,
                'inscrito':   insc,
                'obs':        obs,
            })

    return agenda

# ─── GUARDAR HISTÓRICO ────────────────────────────────────────────────────────
def guardar_historico(data):
    # Archivo mensual
    mes_path = os.path.join(BASE_DIR, f'data_{MES_ACTUAL}.json')
    with open(mes_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'    Guardado: data_{MES_ACTUAL}.json')

    # Índice de meses disponibles
    meses_path = os.path.join(BASE_DIR, 'meses.json')
    meses = []
    if os.path.exists(meses_path):
        try:
            with open(meses_path, 'r', encoding='utf-8') as f:
                meses = json.load(f)
        except: pass
    if MES_ACTUAL not in meses:
        meses.append(MES_ACTUAL)
    meses.sort(reverse=True)
    with open(meses_path, 'w', encoding='utf-8') as f:
        json.dump(meses, f, ensure_ascii=False)

    # Si es el mes actual también actualiza data_ingles.js (para compatibilidad)
    if MES_ACTUAL == date.today().strftime('%Y-%m'):
        js_path = os.path.join(BASE_DIR, 'data_ingles.js')
        with open(js_path, 'w', encoding='utf-8') as f:
            f.write('const DATA_INGLES = ')
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write(';\n')
        json_path = os.path.join(BASE_DIR, 'data_ingles.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'    Guardado: data_ingles.js (mes actual)')

META_INSCRITOS_MKT = 45   # alumnos nuevos que debe aportar MKT al mes

# ─── METAS (leads del mes anterior por sucursal) ─────────────────────────────
def cargar_metas_leads():
    year, month = map(int, MES_ACTUAL.split('-'))
    if month == 1:
        mes_ant = f'{year-1}-12'
    else:
        mes_ant = f'{year}-{month-1:02d}'
    path = os.path.join(BASE_DIR, f'data_{mes_ant}.json')
    if not os.path.exists(path):
        return {s: 0 for s in SUCURSALES}
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        suc = d.get('sucursales', {})
        return {s: suc.get(s, {}).get('leads', 0) for s in SUCURSALES}
    except Exception:
        return {s: 0 for s in SUCURSALES}

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print(f'=== INGLÉS YA · {MES_ACTUAL} (proceso: {HOY.strftime("%d/%m/%Y")}) ===\n')

    if not TOKEN:
        print('ERROR: TOKEN_INGLES_YA no está en variables de entorno')
        sys.exit(1)

    # Si Meta API falla (token bloqueado/vencido), NO escribir ceros:
    # conservar los datos Meta del JSON anterior del mes.
    meta_ok = True
    meta_actualizado = datetime.now().strftime('%d/%m/%Y %H:%M')
    try:
        print('[1] Meta Ads — campañas...')
        campanas = fetch_campanas()
        print(f'    {len(campanas)} campañas')

        print('[2] Meta Ads — ad sets...')
        adsets = fetch_adsets()
        print(f'    {len(adsets)} ad sets')

        print('[3] Meta Ads — datos diarios...')
        diario_meta = fetch_diario_meta()
        print(f'    {len(diario_meta)} días con datos')
    except MetaAPIError as e:
        meta_ok = False
        print(f'    ERROR Meta API: {e}')
        campanas, adsets, diario_meta = [], [], {}
        prev_path = os.path.join(BASE_DIR, f'data_{MES_ACTUAL}.json')
        if os.path.exists(prev_path):
            try:
                with open(prev_path, encoding='utf-8') as f:
                    prev = json.load(f)
                campanas    = prev.get('campanas', [])
                adsets      = prev.get('adsets', [])
                diario_meta = prev.get('diario_meta', {})
                meta_actualizado = prev.get('meta_actualizado', prev.get('actualizado', ''))
                print(f'    CONSERVANDO datos Meta previos (última actualización Meta: {meta_actualizado})')
            except Exception as e2:
                print(f'    AVISO: no se pudo leer JSON previo: {e2}')
        else:
            print('    AVISO: no hay JSON previo del mes, datos Meta quedan vacíos')

    print('[4] Google Sheets — seguimiento diario...')
    csv_seg = fetch_csv_sheet(SHEET_SEG_ID, SHEET_SEG_GID)
    if csv_seg:
        totales_diario, diario_suc = parse_seguimiento(csv_seg)
        totales_mensual = parse_seguimiento_mensual(csv_seg)
        # El bloque ACUMULADO MENSUAL del Sheet es la fuente autoritativa (la
        # calcula el mismo CC con formulas de Sheets); si aun no existe ese
        # bloque para el mes, se usa la suma diaria como respaldo.
        if any(v['leads'] for v in totales_mensual.values()):
            totales_suc = totales_mensual
        else:
            totales_suc = totales_diario
            print('    AVISO: no se encontro bloque ACUMULADO MENSUAL, usando suma diaria')
        insc_total = sum(v['inscritos'] for v in totales_suc.values())
        print(f'    OK - {insc_total} inscritos en el mes')
    else:
        totales_suc = {s: dict(leads=0, llamadas=0, no_contesta=0, citas=0, visitas=0, inscritos=0)
                       for s in SUCURSALES}
        diario_suc = {}

    # ─── Override manual (temporal: mientras se corrigen fechas del Sheet) ──
    # Si existe ajuste_manual.json con el mes actual, reemplaza los totales
    # por sucursal. Eliminar el bloque del mes cuando el Sheet quede corregido.
    ajuste_path = os.path.join(BASE_DIR, 'ajuste_manual.json')
    if os.path.exists(ajuste_path):
        try:
            with open(ajuste_path, encoding='utf-8') as f:
                ajuste = json.load(f)
            mes_aj = ajuste.get(MES_ACTUAL)
            if mes_aj:
                for suc in SUCURSALES:
                    if suc in mes_aj:
                        totales_suc[suc] = mes_aj[suc]
                ins = sum(v.get('inscritos', 0) for v in totales_suc.values())
                cit = sum(v.get('citas', 0) for v in totales_suc.values())
                print(f'    OVERRIDE manual {MES_ACTUAL}: {ins} inscritos, {cit} citas')
        except Exception as e:
            print(f'    AVISO: no se pudo leer ajuste_manual.json: {e}')

    print('[4b] Google Sheets — finanzas del mes (gastos/ingresos)...')
    financiero = parse_financiero(csv_seg) if csv_seg else dict(
        gasto_meta=0.0, gasto_fabian=0.0, gasto_yolanda=0.0,
        ingresos=0.0, utilidad=0.0, ticket_prom=0.0)
    if financiero['ingresos'] or financiero['gasto_fabian']:
        print(f"    OK - Ingresos: ${financiero['ingresos']:,.2f} | "
              f"Gastos (Meta/Fabián/Yolanda): ${financiero['gasto_meta']:,.2f} / "
              f"${financiero['gasto_fabian']:,.2f} / ${financiero['gasto_yolanda']:,.2f}")
    else:
        print('    AVISO: sin bloque de finanzas para este mes todavía (Vic lo llena al cierre)')

    print('[5] Google Sheets — agenda (3 sucursales)...')
    agenda = []
    for suc, gid in SHEET_AGE_GIDS.items():
        csv_age = fetch_csv_sheet(SHEET_AGE_ID, gid)
        if csv_age:
            prospectos = parse_agenda(csv_age, suc)
            agenda.extend(prospectos)
            print(f'    {suc}: {len(prospectos)} prospectos')
        else:
            print(f'    {suc}: sin datos')
    print(f'    Total: {len(agenda)} prospectos')

    print('[5c] Tasa de asistencia (desde Hoja Agenda)...')
    asistencia_suc  = calc_asistencia(agenda, SUCURSALES)
    total_citas_ag  = sum(v['citas_agendadas'] for v in asistencia_suc.values())
    total_asis_ag   = sum(v['asistieron']       for v in asistencia_suc.values())
    total_noasis_ag = sum(v['no_asistieron']    for v in asistencia_suc.values())
    total_sindato_ag= sum(v['sin_dato']         for v in asistencia_suc.values())
    total_con_dato  = total_asis_ag + total_noasis_ag
    tasa_asistencia          = round(100 * total_asis_ag / total_citas_ag, 1) if total_citas_ag else 0.0
    tasa_asistencia_con_dato = round(100 * total_asis_ag / total_con_dato, 1) if total_con_dato else 0.0
    print(f'    {total_asis_ag} asistieron / {total_noasis_ag} no asistieron / {total_sindato_ag} sin dato '
          f'(de {total_citas_ag} citas) = {tasa_asistencia}% asistencia sobre total agendados '
          f'({tasa_asistencia_con_dato}% sobre citas con dato)')

    print('[5b] Metas de leads (mes anterior)...')
    metas_leads = cargar_metas_leads()
    print(f'    {", ".join(f"{k}:{v}" for k,v in metas_leads.items())}')

    total_leads   = sum(c['leads']   for c in campanas)
    total_gasto   = sum(c['gasto']   for c in campanas)
    total_insc    = sum(v['inscritos'] for v in totales_suc.values())
    total_citas   = sum(v['citas']    for v in totales_suc.values())
    total_visitas = sum(v['visitas']  for v in totales_suc.values())
    cpl           = round(total_gasto / total_leads, 2) if total_leads else 0

    MESES_ES = {
        '01':'Enero','02':'Febrero','03':'Marzo','04':'Abril',
        '05':'Mayo','06':'Junio','07':'Julio','08':'Agosto',
        '09':'Septiembre','10':'Octubre','11':'Noviembre','12':'Diciembre'
    }
    mes_nombre = f"{MESES_ES[MES_ACTUAL[5:]]} {MES_ACTUAL[:4]}"

    # Ticket promedio: usa el que Vic captura a mano (TICKET PROM); si aún no
    # lo llena ese mes, lo calculamos como ingresos / inscritos.
    ticket_promedio = financiero['ticket_prom'] or (
        round(financiero['ingresos'] / total_insc, 2) if total_insc else 0.0)

    # Fusiona citas_agendadas/asistieron/tasa_asistencia (de la Hoja Agenda)
    # dentro de cada sucursal, junto a los datos del embudo diario.
    for s in SUCURSALES:
        totales_suc.setdefault(s, {})
        totales_suc[s].update(asistencia_suc.get(s, {}))
        asis_s = totales_suc[s].get('asistieron', 0)
        insc_s = totales_suc[s].get('inscritos', 0)
        totales_suc[s]['conv_asistio_inscrito'] = round(100 * insc_s / asis_s, 1) if asis_s else 0.0

    conv_asistio_inscrito = round(100 * total_insc / total_asis_ag, 1) if total_asis_ag else 0.0

    data = {
        'actualizado': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'meta_actualizado': meta_actualizado,
        'meta_ok':     meta_ok,
        'mes':         mes_nombre,
        'mes_id':      MES_ACTUAL,
        'kpis': {
            'leads_meta': total_leads,
            'gasto':      round(total_gasto, 2),
            'cpl':        cpl,
            'citas':      total_citas,
            'visitas':    total_visitas,
            'inscritos':  total_insc,
            'citas_agendadas': total_citas_ag,
            'asistieron':      total_asis_ag,
            'no_asistieron':   total_noasis_ag,
            'sin_dato_asistencia': total_sindato_ag,
            'tasa_asistencia':          tasa_asistencia,
            'tasa_asistencia_con_dato': tasa_asistencia_con_dato,
            'conv_asistio_inscrito':    conv_asistio_inscrito,
            'ingresos':        financiero['ingresos'],
            'ticket_promedio': ticket_promedio,
        },
        'financiero': {
            'ingresos':  financiero['ingresos'],
            'utilidad':  financiero['utilidad'],
            'ticket_promedio': ticket_promedio,
            'gastos': {
                'meta_ads': financiero['gasto_meta'],
                'fabian':   financiero['gasto_fabian'],
                'yolanda':  financiero['gasto_yolanda'],
                'total':    round(financiero['gasto_meta'] + financiero['gasto_fabian'] + financiero['gasto_yolanda'], 2),
            },
        },
        'campanas':    campanas,
        'adsets':      adsets,
        'diario_meta': diario_meta,
        'sucursales':  totales_suc,
        'metas_leads':        metas_leads,
        'meta_inscritos_mkt': META_INSCRITOS_MKT,
        'diario_suc':  diario_suc,
        'agenda':      agenda,
    }

    print('\n[6] Guardando archivos...')
    guardar_historico(data)

    print(f'\nOK Leads: {total_leads} | Gasto: ${total_gasto:,.2f} | CPL: ${cpl:,.2f} | Inscritos: {total_insc}')
    print(f'OK Asistencia: {tasa_asistencia}% | Ingresos: ${financiero["ingresos"]:,.2f} | Ticket prom: ${ticket_promedio:,.2f}')


if __name__ == '__main__':
    main()

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
SHEET_SEG_GID = '1913702244'
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
def meta_get(endpoint, params):
    params['access_token'] = TOKEN
    r = requests.get(f'{API_BASE}/{endpoint}', params=params, timeout=30)
    return r.json()

def time_range():
    return json.dumps({'since': f'{MES_ACTUAL}-01', 'until': HOY.strftime('%Y-%m-%d')})

def fetch_campanas():
    resp = meta_get(f'{AD_ACCOUNT}/campaigns', {
        'fields':     'name,status,daily_budget,insights{spend,impressions,reach,actions}',
        'time_range': time_range(),
        'limit':      25,
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
    resp = meta_get(f'{AD_ACCOUNT}/adsets', {
        'fields':     'name,status,daily_budget,campaign_id,insights{spend,actions}',
        'time_range': time_range(),
        'limit':      50,
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

        try:
            v = [si(row[offset + i]) for i in range(6)]
        except IndexError:
            continue

        t = totales[suc]
        t['leads']       += v[0]
        t['llamadas']    += v[1]
        t['no_contesta'] += v[2]
        t['citas']       += v[3]
        t['visitas']     += v[4]
        t['inscritos']   += v[5]

        ds = cur_date.strftime('%Y-%m-%d')
        diario.setdefault(ds, {})[suc] = {
            'leads': v[0], 'llamadas': v[1],
            'citas': v[3], 'visitas': v[4], 'inscritos': v[5],
        }

    return totales, diario

# ─── AGENDA ──────────────────────────────────────────────────────────────────
SKIP_KW = ('HOJA AGENDA', 'SUCURSAL:', 'FECHA:')

def parse_agenda(text, sucursal):
    rows  = list(csv.reader(io.StringIO(text)))
    agenda = []

    for row in rows:
        if not any(c.strip() for c in row):
            continue
        col0      = row[0].strip()
        full_text = ' '.join(row).upper()

        if any(kw in full_text for kw in SKIP_KW):
            continue
        if col0.upper() in ('NOMBRE', 'TEL', 'CORREO', 'CORREO ELECTRÓNICO'):
            continue
        if parse_fecha(col0) or re.match(r'^\s*\d{2}[-/]\d{2}[-/]\d{2,4}\s*$', col0):
            continue

        nombre = re.sub(r'^(SÍ|SI|NO)\s+', '', col0, flags=re.IGNORECASE).strip()
        if not nombre or len(nombre) < 3:
            continue

        try:
            tel  = row[1].strip() if len(row) > 1 else ''
            fecha= row[3].strip() if len(row) > 3 else ''
            asis = 'SÍ' in (row[4].strip().upper() if len(row) > 4 else '')
            insc = 'SÍ' in (row[5].strip().upper() if len(row) > 5 else '')
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

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print(f'=== INGLÉS YA · {MES_ACTUAL} (proceso: {HOY.strftime("%d/%m/%Y")}) ===\n')

    if not TOKEN:
        print('ERROR: TOKEN_INGLES_YA no está en variables de entorno')
        sys.exit(1)

    print('[1] Meta Ads — campañas...')
    campanas = fetch_campanas()
    print(f'    {len(campanas)} campañas')

    print('[2] Meta Ads — ad sets...')
    adsets = fetch_adsets()
    print(f'    {len(adsets)} ad sets')

    print('[3] Meta Ads — datos diarios...')
    diario_meta = fetch_diario_meta()
    print(f'    {len(diario_meta)} días con datos')

    print('[4] Google Sheets — seguimiento diario...')
    csv_seg = fetch_csv_sheet(SHEET_SEG_ID, SHEET_SEG_GID)
    if csv_seg:
        totales_suc, diario_suc = parse_seguimiento(csv_seg)
        insc_total = sum(v['inscritos'] for v in totales_suc.values())
        print(f'    OK - {insc_total} inscritos en el mes')
    else:
        totales_suc = {s: dict(leads=0, llamadas=0, no_contesta=0, citas=0, visitas=0, inscritos=0)
                       for s in SUCURSALES}
        diario_suc = {}

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

    data = {
        'actualizado': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'mes':         mes_nombre,
        'mes_id':      MES_ACTUAL,
        'kpis': {
            'leads_meta': total_leads,
            'gasto':      round(total_gasto, 2),
            'cpl':        cpl,
            'citas':      total_citas,
            'visitas':    total_visitas,
            'inscritos':  total_insc,
        },
        'campanas':    campanas,
        'adsets':      adsets,
        'diario_meta': diario_meta,
        'sucursales':  totales_suc,
        'diario_suc':  diario_suc,
        'agenda':      agenda,
    }

    print('\n[6] Guardando archivos...')
    guardar_historico(data)

    print(f'\nOK Leads: {total_leads} | Gasto: ${total_gasto:,.2f} | CPL: ${cpl:,.2f} | Inscritos: {total_insc}')


if __name__ == '__main__':
    main()

from flask import Flask, request, jsonify
from datetime import datetime
import logging, os, re, random
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)

_session = None
_last_login = None
LOGIN_TTL = 25 * 60

IVAS_EMAIL    = os.environ.get('IVAS_EMAIL', '')
IVAS_PASSWORD = os.environ.get('IVAS_PASSWORD', '')
API_SECRET    = os.environ.get('API_SECRET', '')

BASE_URL    = 'https://www.ivasms.com'
LOGIN_URL   = f'{BASE_URL}/login'
SMS_URL     = f'{BASE_URL}/portal/sms/received/getsms'
NUM_URL     = f'{BASE_URL}/portal/sms/received/getsms/number'
SMS_DET_URL = f'{BASE_URL}/portal/sms/received/getsms/number/sms'

# Webshare residential proxies
PROXIES = [
    '38.154.203.95:5863:khopockz:ku4svcurqwcb',
    '198.105.121.200:6462:khopockz:ku4svcurqwcb',
    '64.137.96.74:6641:khopockz:ku4svcurqwcb',
    '209.127.138.10:5784:khopockz:ku4svcurqwcb',
    '38.154.185.97:6370:khopockz:ku4svcurqwcb',
    '84.247.60.125:6095:khopockz:ku4svcurqwcb',
    '142.111.67.146:5611:khopockz:ku4svcurqwcb',
    '191.96.254.138:6185:khopockz:ku4svcurqwcb',
    '31.58.9.4:6077:khopockz:ku4svcurqwcb',
    '104.239.107.47:5699:khopockz:ku4svcurqwcb',
]

def get_proxy():
    p = random.choice(PROXIES)
    ip, port, user, pwd = p.split(':')
    proxy_url = f'http://{user}:{pwd}@{ip}:{port}'
    return {'http': proxy_url, 'https': proxy_url}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

AJAX_HEADERS = {
    'Accept': 'text/html, */*; q=0.01',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
    'Origin': BASE_URL,
    'Referer': f'{BASE_URL}/portal/sms/received',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
}

def extract_csrf(html):
    m = re.search(r'name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html)
    if m: return m.group(1)
    m = re.search(r'name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']', html)
    return m.group(1) if m else None

def login():
    global _session, _last_login
    from curl_cffi import requests as cf

    proxy = get_proxy()
    logger.info(f'Using proxy: {proxy["https"].split("@")[1]}')

    s = cf.Session(impersonate='chrome136', proxies=proxy)
    r = s.get(LOGIN_URL, headers=HEADERS, timeout=30)
    logger.info(f'Login page status: {r.status_code}')

    if r.status_code != 200:
        raise Exception(f'Login page returned {r.status_code}')

    csrf = extract_csrf(r.text)
    if not csrf:
        raise Exception('No CSRF token on login page')

    r2 = s.post(LOGIN_URL, data={
        '_token': csrf, 'email': IVAS_EMAIL, 'password': IVAS_PASSWORD
    }, headers={**HEADERS, 'Content-Type': 'application/x-www-form-urlencoded', 'Referer': LOGIN_URL})

    if '/portal' not in r2.url and 'dashboard' not in r2.text.lower():
        raise Exception(f'Login failed at {r2.url}')

    _session = s
    _last_login = datetime.now()
    logger.info('✅ Login successful!')
    return s

def get_session():
    global _session, _last_login
    if not _session or not _last_login or (datetime.now()-_last_login).seconds > LOGIN_TTL:
        login()
    return _session

def fetch_sms(from_date, to_date):
    s = get_session()
    r = s.get(f'{BASE_URL}/portal/sms/received', headers=HEADERS)
    csrf = extract_csrf(r.text)
    if not csrf: raise Exception('No CSRF from portal')
    r = s.post(SMS_URL, data=f'from={from_date}&to={to_date}&_token={csrf}', headers=AJAX_HEADERS)
    if r.status_code != 200: raise Exception(f'SMS URL {r.status_code}')
    soup = BeautifulSoup(r.text, 'html.parser')
    group_ids = []
    for e in soup.select('div.pointer'):
        m = re.search(r"getDetials\('(.+?)'\)", e.get('onclick',''))
        if m: group_ids.append(m.group(1))
    messages = []
    for gid in group_ids:
        r2 = s.post(NUM_URL, data=f'start={from_date}&end={to_date}&range={gid}&_token={csrf}', headers=AJAX_HEADERS)
        soup2 = BeautifulSoup(r2.text, 'html.parser')
        phones = [e.get_text(strip=True) for e in soup2.select('div[onclick*="getDetialsNumber"]')]
        for phone in phones:
            r3 = s.post(SMS_DET_URL, data=f'start={from_date}&end={to_date}&Number={phone}&Range={gid}&_token={csrf}', headers=AJAX_HEADERS)
            soup3 = BeautifulSoup(r3.text, 'html.parser')
            for row in soup3.select('tr'):
                cols = row.select('td')
                if len(cols) >= 2:
                    messages.append({'range': gid, 'phone': phone,
                                     'message': cols[-1].get_text(strip=True),
                                     'time': cols[0].get_text(strip=True)})
    return messages

@app.route('/')
def index():
    return jsonify({'status': 'alive', 'endpoint': '/sms?date=DD/MM/YYYY'})

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'logged_in': _session is not None})

@app.route('/test')
def test():
    from curl_cffi import requests as cf
    results = {}
    for p in PROXIES[:3]:
        ip, port, user, pwd = p.split(':')
        proxy_url = f'http://{user}:{pwd}@{ip}:{port}'
        proxy = {'http': proxy_url, 'https': proxy_url}
        try:
            s = cf.Session(impersonate='chrome136', proxies=proxy)
            r = s.get(LOGIN_URL, headers=HEADERS, timeout=15)
            results[ip] = r.status_code
        except Exception as e:
            results[ip] = str(e)[:80]
    return jsonify(results)

@app.route('/relogin', methods=['POST'])
def relogin():
    try:
        login()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/sms')
def sms():
    if API_SECRET:
        key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if key != API_SECRET:
            return jsonify({'error': 'Unauthorized'}), 401
    date = request.args.get('date', datetime.now().strftime('%d/%m/%Y'))
    to_date = request.args.get('to_date', date)
    try:
        msgs = fetch_sms(date, to_date)
        return jsonify({'status': 'success', 'date': date, 'count': len(msgs), 'messages': msgs})
    except Exception as e:
        global _session, _last_login
        _session = None; _last_login = None
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

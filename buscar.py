import re
import subprocess
import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import urlparse

# ─── 0) LISTA DE PERSONAS (define aquí tus datos) ─────────────────────────
PERSONAS = [
    {
        "Nombre completo": "Cesar Mateo Vera Andrade",
        "CI": "-",
        "Género": "M",
        "Edad": "21",
        "Fecha nacimiento": "-",
        "Organización política": "-",
        "Departamento": "Chuquisaca",
        "Cargo": "-",
        "Usuario": "-"
    },
    {
        "Nombre completo": "Dina Ie Guaguasubera",
        "CI": "9524040",
        "Género": "F",
        "Edad": "32",
        "Fecha nacimiento": "17/08/1993",
        "Organización política": "CONSEJO INDÍGENA YUQUI BIA RECUATE",
        "Departamento": "Cochabamba",
        "Cargo": "Suplente Diputados de Circunscripciones Especiales",
        "Usuario": "—"
    },
    # Agrega aquí más diccionarios con el mismo formato para cada persona
]

# ─── Configuración de dominios de confianza ────────────────────────────────
SOCIAL_DOMAINS = {
    'facebook.com', 'instagram.com', 'twitter.com', 'x.com',
    'linkedin.com', 'youtube.com', 'tiktok.com'
}
OFFICIAL_DOMAINS = {
    '.gob.bo', 'oep.org.bo', 'tribunal.org.bo',
    'eldeber.com.bo', 'lapatria.bo', 'la-razon.com', 'ahoraelpueblo.bo'
}

# ─── 1) BÚSQUEDA CON CONTEXTO ENRIQUECIDO ─────────────────────────────────
try:
    from googlesearch import search as google_search_nocreds
    def google_search_social(person, num_per_query=5):
        name = person['Nombre completo']
        ci = person.get('CI', '')
        org = person.get('Organización política', '')
        dept = person.get('Departamento', '')
        # Patrones enriquecidos con CI, organización y departamento
        patterns = [
            f'"{name}" {ci} Bolivia',
            f'"{name}" {org} Bolivia',
            f'"{name}" {dept} Bolivia',
            f'"{name}" Bolivia Instagram',
            f'"{name}" Bolivia Facebook',
            f'"{name}" Bolivia Twitter',
            f'"{name}" Bolivia LinkedIn'
        ]
        urls = []
        for q in patterns:
            for url in google_search_nocreds(q, num_results=num_per_query):
                if any(d in url for d in SOCIAL_DOMAINS.union(OFFICIAL_DOMAINS)):
                    urls.append(url)
        return list(dict.fromkeys(urls))
except ModuleNotFoundError:
    from duckduckgo_search import ddg
    def google_search_social(person, num_per_query=5):
        name = person['Nombre completo']
        query = f'"{name}" Bolivia Instagram OR Facebook OR Twitter OR LinkedIn'
        results = ddg(query, region='xl-es', safesearch='Off', max_results=num_per_query*4)
        return list({r['href'] for r in results if any(d in r['href'] for d in SOCIAL_DOMAINS)})

# ─── 2) DESCARGA Y PARSEO HTML ─────────────────────────────────────────────
def get_page_content(url):
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return ''

# ─── 3) EXTRACCIÓN DE CONTACTOS ─────────────────────────────────────────────
def extract_contacts(html):
    # Validar presencia de nombre en contenido antes de extraer
    text = BeautifulSoup(html, 'html.parser').get_text()
    # correos @gmail.com
    emails = re.findall(r'[A-Za-z0-9._%+-]+@gmail\.com', text)
    # teléfonos bolivianos: +591 o 8 dígitos
    intl = re.findall(r'\+591[-\s]?\d{8}', text)
    local = re.findall(r'(?<!\d)\d{8}(?!\d)', text)
    return set(emails), set(intl + local)

# ─── 4) CLASIFICACIÓN DE FUENTE Y CONFIANZA ─────────────────────────────────
def classify_source(url):
    hostname = urlparse(url).hostname or ''
    for dom in OFFICIAL_DOMAINS:
        if dom in hostname:
            return 'sitio_oficial', 'alta'
    for soc in SOCIAL_DOMAINS:
        if soc in hostname:
            return 'perfil', 'media'
    return 'web_general', 'baja'

# ─── 5) SHERLOCK (opcional) ─────────────────────────────────────────────────
def run_sherlock(username, timeout=60):
    try:
        proc = subprocess.run([
            'sherlock', username, '--print-found', f'--timeout={timeout}'
        ], capture_output=True, text=True, check=True)
        return [line.split()[1] for line in proc.stdout.splitlines() if 'Found' in line]
    except Exception:
        return []

# ─── 6) PROCESO POR PERSONA CON VALIDACIÓN DE CONTENIDO ───────────────────────
def process_person(person):
    name = person['Nombre completo']
    ci = str(person.get('CI', ''))
    results = []

    # 6.1 búsqueda enriquecida
    urls = google_search_social(person)
    for url in urls:
        tipo, conf = classify_source(url)
        html = get_page_content(url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else ''
        desc = ''
        tag = soup.find('meta', attrs={'name':'description'})
        if tag and 'content' in tag.attrs:
            desc = tag['content']
        # validar coincidencia de nombre en title o descripción
        if not re.search(re.escape(name), title + desc, flags=re.IGNORECASE):
            continue
        # agregar URL válida
        results.append({'tipo': tipo, 'fuente': urlparse(url).hostname,
                        'url': url, 'confianza': conf})
        # 6.2 extraer contactos si es relevante
        emails, phones = extract_contacts(html)
        for e in emails:
            if name.split()[0].lower() in e.lower():  # validar parte de nombre en email
                results.append({'tipo':'email','fuente':urlparse(url).hostname,
                                'dato':e,'confianza':'alta' if conf=='alta' else 'media'})
        for p in phones:
            # validar prefijo móvil
            if p.lstrip('+591').startswith(('6','7')):
                results.append({'tipo':'telefono','fuente':urlparse(url).hostname,
                                'dato':p,'confianza':'alta' if conf=='alta' else 'media'})

    # 6.3 variantes Sherlock
    parts = name.lower().split()
    variants = {''.join(parts), '.'.join(parts), parts[0]+parts[-1], parts[0]+'_'+parts[-1]}
    for usr in variants:
        for url in run_sherlock(usr):
            tipo, conf = classify_source(url)
            results.append({'tipo':'perfil_sherlock','fuente':urlparse(url).hostname,
                            'url':url,'confianza':conf})

    # 6.4 ordenar y filtrar top
    nivel = {'alta':0,'media':1,'baja':2}
    results.sort(key=lambda x: nivel[x['confianza']])
    top = [r for r in results if r['confianza']=='alta'] or results
    return {'nombre':name,'ci':ci,'resultados':top[:5]}

# ─── 7) EJECUCIÓN PRINCIPAL ─────────────────────────────────────────────────
def main():
    output = [process_person(p) for p in PERSONAS]
    with open('resultados.json','w',encoding='utf-8') as f:
        json.dump(output,f,ensure_ascii=False,indent=4)
    print('✅ resultados.json generado con éxito.')

if __name__=='__main__':
    main()

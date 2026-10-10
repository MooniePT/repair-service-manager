# -*- coding: utf-8 -*-
"""Gestão de Assistências — aplicação Flask para gerir clientes e assistências
técnicas de uma pequena empresa.

Fluxo das assistências:
    Pendente -> Em andamento -> Aguarda Verificação -> Concluída
    (qualquer estado pode passar a Cancelada)
"""

import hmac
import os
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, render_template, request, redirect, flash,
                   url_for, session, g)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# A base de dados com os dados reais da empresa vive em database/assistencias.db
# (era também o caminho usado pelo Docker: /app/database/assistencias.db).
DB_PATH = os.environ.get('DATABASE_PATH') or os.path.join(BASE_DIR, 'database', 'assistencias.db')
BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), 'backups')

# ---------------------------------------------------------------- estados ---
ESTADO_PENDENTE = 'Pendente'
ESTADO_ANDAMENTO = 'Em andamento'
ESTADO_AGUARDA = 'Aguarda Verificação'
ESTADO_CONCLUIDA = 'Concluída'
ESTADO_CANCELADA = 'Cancelada'

ESTADOS_ABERTOS = (ESTADO_PENDENTE, ESTADO_ANDAMENTO)
ESTADOS_FINAIS = (ESTADO_CONCLUIDA, ESTADO_CANCELADA)
TODOS_ESTADOS = (ESTADO_PENDENTE, ESTADO_ANDAMENTO, ESTADO_AGUARDA,
                 ESTADO_CONCLUIDA, ESTADO_CANCELADA)

TIPOS_ASSISTENCIA = ('Reparação', 'Substituição', 'Manutenção',
                     'Instalação', 'Entregar', 'Recolher')
URGENCIAS = ('Normal', 'Urgente', 'Não urgente')

ESTADOS_ENCOMENDA = ('Por encomendar', 'Já encomendado', 'Recebido')


def _carregar_secret_key():
    """Usa SECRET_KEY do ambiente ou gera uma chave persistida em instance/."""
    chave = os.environ.get('SECRET_KEY')
    if chave:
        return chave
    ficheiro = os.path.join(BASE_DIR, 'instance', 'secret_key')
    try:
        if os.path.exists(ficheiro):
            with open(ficheiro, 'r', encoding='utf-8') as f:
                guardada = f.read().strip()
            if guardada:
                return guardada
        os.makedirs(os.path.dirname(ficheiro), exist_ok=True)
        nova = secrets.token_hex(32)
        with open(ficheiro, 'w', encoding='utf-8') as f:
            f.write(nova)
        return nova
    except OSError:
        return secrets.token_hex(32)


app = Flask(__name__)
app.secret_key = _carregar_secret_key()

# --- sessão e cookies ---
# SESSION_COOKIE_SECURE só deve ser ativado quando a app está servida por
# HTTPS (produção/acesso externo); em HTTP local impediria o login.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Atrás de um reverse proxy (Nginx/Traefik/Cloudflare Tunnel), ativar
# BEHIND_PROXY=1 para a app respeitar X-Forwarded-For/-Proto/-Host.
if os.environ.get('BEHIND_PROXY', '0') == '1':
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# --- proteção CSRF (token por sessão, validado em todos os POST) ---

def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def validar_csrf():
    if request.method == 'POST':
        esperado = session.get('_csrf_token', '')
        recebido = request.form.get('_csrf_token', '')
        if not esperado or not recebido or not hmac.compare_digest(esperado, recebido):
            flash('Por segurança, o pedido foi rejeitado (sessão expirada ou inválida). '
                  'Tente novamente.', 'danger')
            destino = urlparse(request.referrer or '').path or url_for('login')
            return redirect(destino)


# --- headers de segurança ---

@app.after_request
def headers_seguranca(resposta):
    resposta.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resposta.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resposta.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resposta.headers.setdefault('Permissions-Policy',
                                'camera=(), microphone=(), geolocation=()')
    # Chart.js é servido localmente; Bootstrap vem do jsdelivr e o
    # Font Awesome (CSS + webfonts) do cdnjs. Sem scripts inline.
    resposta.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; form-action 'self'; frame-ancestors 'self'")
    return resposta


# ----------------------------------------------------------- base de dados ---

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def fechar_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _criar_backup(motivo):
    """Cópia de segurança da BD antes de qualquer alteração de esquema."""
    if not os.path.exists(DB_PATH):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    nome = 'assistencias-%s-%s.db' % (datetime.now().strftime('%Y%m%d-%H%M%S'), motivo)
    destino = os.path.join(BACKUP_DIR, nome)
    shutil.copy2(DB_PATH, destino)
    return destino


def init_db():
    """Cria as tabelas em falta e aplica migrações aditivas, sem nunca
    apagar dados existentes. Idempotente — corre a cada arranque."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                nif TEXT,
                contacto TEXT,
                morada TEXT
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS assistencias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER,
                data TEXT,
                hora TEXT,
                avaria TEXT,
                tipo TEXT,
                descricao TEXT,
                feito TEXT,
                status TEXT DEFAULT 'Pendente',
                pago INTEGER DEFAULT 0,
                data_conclusao TEXT,
                urgencia TEXT,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT
            )''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS encomendas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao TEXT NOT NULL,
                quantidade INTEGER,
                fornecedor TEXT,
                data_encomenda TEXT,
                status TEXT DEFAULT 'Por encomendar',
                data_recebimento TEXT
            )''')

        if cur.execute('SELECT COUNT(*) FROM usuarios').fetchone()[0] == 0:
            cur.execute('INSERT INTO usuarios (username, password) VALUES (?, ?)',
                        ('admin', generate_password_hash('admin123')))

        # --- migrações aditivas (novas colunas) ---
        colunas_cli = {r[1] for r in cur.execute('PRAGMA table_info(clientes)')}
        colunas_ass = {r[1] for r in cur.execute('PRAGMA table_info(assistencias)')}
        novas = []
        if 'email' not in colunas_cli:
            novas.append(('clientes', 'email', 'TEXT'))
        if 'observacoes' not in colunas_cli:
            novas.append(('clientes', 'observacoes', 'TEXT'))
        if 'valor' not in colunas_ass:
            novas.append(('assistencias', 'valor', 'REAL'))

        # --- normalização de estados/tipos antigos ---
        estados_antigos = cur.execute(
            "SELECT COUNT(*) FROM assistencias WHERE status IN "
            "('Anulada/Cancelada', 'Aguarda aprovação de cliente', 'Concluído') "
            "OR tipo = 'Reparo'").fetchone()[0]

        if novas or estados_antigos:
            _criar_backup('migracao')
            for tabela, coluna, tipo_sql in novas:
                cur.execute('ALTER TABLE %s ADD COLUMN %s %s' % (tabela, coluna, tipo_sql))
            cur.execute("UPDATE assistencias SET status = ? WHERE status = 'Anulada/Cancelada'",
                        (ESTADO_CANCELADA,))
            cur.execute("UPDATE assistencias SET status = ? WHERE status = 'Aguarda aprovação de cliente'",
                        (ESTADO_PENDENTE,))
            cur.execute("UPDATE assistencias SET status = ? WHERE status = 'Concluído'",
                        (ESTADO_CONCLUIDA,))
            cur.execute("UPDATE assistencias SET tipo = 'Reparação' WHERE tipo = 'Reparo'")

        conn.commit()
    finally:
        conn.close()


init_db()


# ------------------------------------------------------------- utilitários ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Por favor, inicie sessão para aceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.template_filter('data_pt')
def filtro_data_pt(valor):
    """2025-02-19 -> 19/02/2025"""
    if not valor:
        return '—'
    try:
        return datetime.strptime(valor, '%Y-%m-%d').strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        return valor


@app.template_filter('euros')
def filtro_euros(valor):
    if valor in (None, ''):
        return '—'
    try:
        return ('%.2f €' % float(valor)).replace('.', ',')
    except (ValueError, TypeError):
        return valor


@app.context_processor
def injetar_globais():
    contadores = {'abertas': 0, 'aguarda': 0, 'encomendas': 0}
    if 'user_id' in session:
        try:
            db = get_db()
            contadores['abertas'] = db.execute(
                'SELECT COUNT(*) FROM assistencias WHERE status IN (?, ?)',
                ESTADOS_ABERTOS).fetchone()[0]
            contadores['aguarda'] = db.execute(
                'SELECT COUNT(*) FROM assistencias WHERE status = ?',
                (ESTADO_AGUARDA,)).fetchone()[0]
            contadores['encomendas'] = db.execute(
                "SELECT COUNT(*) FROM encomendas WHERE status != 'Recebido'").fetchone()[0]
        except sqlite3.Error:
            pass
    return {
        'contadores': contadores,
        'TODOS_ESTADOS': TODOS_ESTADOS,
        'ESTADOS_ABERTOS': ESTADOS_ABERTOS,
        'TIPOS_ASSISTENCIA': TIPOS_ASSISTENCIA,
        'URGENCIAS': URGENCIAS,
        'hoje': date.today().isoformat(),
    }


def pesquisar_assistencias(estados, q='', data_de='', data_ate='',
                           cliente_id=None, ordem='a.data DESC, a.hora DESC'):
    """Pesquisa assistências por texto livre (cliente, NIF, contacto, morada,
    avaria, descrição, tipo, estado ou data) e por intervalo de datas."""
    sql = ('SELECT a.*, c.nome AS cliente_nome, c.nif AS cliente_nif, '
           'c.contacto AS cliente_contacto '
           'FROM assistencias a LEFT JOIN clientes c ON c.id = a.cliente_id '
           'WHERE a.status IN (%s)' % ','.join('?' * len(estados)))
    params = list(estados)
    if q:
        like = '%' + q.strip() + '%'
        sql += (' AND (c.nome LIKE ? OR c.nif LIKE ? OR c.contacto LIKE ? '
                'OR c.morada LIKE ? OR a.avaria LIKE ? OR a.descricao LIKE ? '
                'OR a.tipo LIKE ? OR a.status LIKE ? OR a.data LIKE ?)')
        params += [like] * 9
    if data_de:
        sql += ' AND a.data >= ?'
        params.append(data_de)
    if data_ate:
        sql += ' AND a.data <= ?'
        params.append(data_ate)
    if cliente_id:
        sql += ' AND a.cliente_id = ?'
        params.append(cliente_id)
    sql += ' ORDER BY ' + ordem
    return get_db().execute(sql, params).fetchall()


def _validar_cliente(form):
    """Devolve (dados, lista_de_erros)."""
    erros = []
    nome = (form.get('nome') or '').strip()
    nif = (form.get('nif') or '').strip() or None
    contacto = (form.get('contacto') or '').strip() or None
    morada = (form.get('morada') or '').strip() or None
    email = (form.get('email') or '').strip() or None
    observacoes = (form.get('observacoes') or '').strip() or None

    if not nome:
        erros.append('O nome do cliente é obrigatório.')
    if nif and not re.fullmatch(r'\d{9}', nif):
        erros.append('O NIF deve ter exatamente 9 dígitos.')
    if email and '@' not in email:
        erros.append('O email indicado não é válido.')
    return {'nome': nome, 'nif': nif, 'contacto': contacto, 'morada': morada,
            'email': email, 'observacoes': observacoes}, erros


def _validar_assistencia(form):
    erros = []
    cliente_id = form.get('cliente_id')
    data_str = (form.get('data') or '').strip()
    hora = (form.get('hora') or '').strip()
    avaria = (form.get('avaria') or '').strip()
    tipo = (form.get('tipo') or '').strip()
    urgencia = (form.get('urgencia') or 'Normal').strip()
    descricao = (form.get('descricao') or '').strip()
    valor_str = (form.get('valor') or '').strip().replace(',', '.')

    if not cliente_id or not str(cliente_id).isdigit():
        erros.append('Selecione um cliente válido.')
    if not avaria:
        erros.append('A descrição da avaria é obrigatória.')
    if tipo not in TIPOS_ASSISTENCIA:
        erros.append('Tipo de assistência inválido.')
    if urgencia not in URGENCIAS:
        urgencia = 'Normal'
    try:
        datetime.strptime(data_str, '%Y-%m-%d')
    except ValueError:
        erros.append('A data indicada não é válida.')
    valor = None
    if valor_str:
        try:
            valor = float(valor_str)
            if valor < 0:
                erros.append('O valor não pode ser negativo.')
        except ValueError:
            erros.append('O valor deve ser um número (ex.: 45,50).')

    return {'cliente_id': cliente_id, 'data': data_str, 'hora': hora,
            'avaria': avaria, 'tipo': tipo, 'urgencia': urgencia,
            'descricao': descricao, 'valor': valor}, erros


TAMANHOS_PAGINA = (10, 20, 50)


def aplicar_paginacao(itens):
    """Pagina uma lista em memória conforme ?pagina= e ?por_pagina=.
    Devolve (itens_da_pagina, info) — info alimenta a macro de paginação."""
    try:
        por_pagina = int(request.args.get('por_pagina', 20))
    except (TypeError, ValueError):
        por_pagina = 20
    if por_pagina not in TAMANHOS_PAGINA:
        por_pagina = 20
    try:
        pagina = max(1, int(request.args.get('pagina', 1)))
    except (TypeError, ValueError):
        pagina = 1

    total = len(itens)
    total_paginas = max(1, -(-total // por_pagina))
    pagina = min(pagina, total_paginas)
    inicio = (pagina - 1) * por_pagina
    info = {
        'pagina': pagina, 'total_paginas': total_paginas,
        'por_pagina': por_pagina, 'total': total,
        'inicio': inicio + 1 if total else 0,
        'fim': min(inicio + por_pagina, total),
    }
    return itens[inicio:inicio + por_pagina], info


@app.template_global()
def url_atual(**alteracoes):
    """URL da página atual com alguns parâmetros alterados (para paginação)."""
    params = request.args.to_dict()
    params.update({k: str(v) for k, v in alteracoes.items()})
    return url_for(request.endpoint, **(request.view_args or {}), **params)


def _redirect_seguro(next_url, predefinido='listar_assistencias'):
    """Só aceita redirects relativos dentro da aplicação."""
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(url_for(predefinido))


# ---------------------------------------------------------------- sessão ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = get_db().execute('SELECT * FROM usuarios WHERE username = ?',
                                (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            if check_password_hash(user['password'], 'admin123'):
                flash('Está a usar a palavra-passe inicial. Por segurança, '
                      'altere-a na página Configuração.', 'warning')
            return redirect(url_for('index'))
        flash('Utilizador ou palavra-passe incorretos.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Sessão terminada com sucesso.', 'success')
    return redirect(url_for('login'))


@app.route('/configuracao', methods=['GET', 'POST'])
@login_required
def configuracao():
    if request.method == 'POST':
        atual = request.form.get('current_password') or ''
        nova = request.form.get('new_password') or ''
        confirmacao = request.form.get('confirm_password') or ''

        if len(nova) < 6:
            flash('A nova palavra-passe deve ter pelo menos 6 caracteres.', 'danger')
        elif nova != confirmacao:
            flash('A confirmação não coincide com a nova palavra-passe.', 'danger')
        else:
            db = get_db()
            user = db.execute('SELECT * FROM usuarios WHERE id = ?',
                              (session['user_id'],)).fetchone()
            if user and check_password_hash(user['password'], atual):
                db.execute('UPDATE usuarios SET password = ? WHERE id = ?',
                           (generate_password_hash(nova), session['user_id']))
                db.commit()
                flash('Palavra-passe alterada com sucesso!', 'success')
                return redirect(url_for('index'))
            flash('A palavra-passe atual está incorreta.', 'danger')
    return render_template('configuracao.html')


# -------------------------------------------------------------- dashboard ---

@app.route('/')
@login_required
def index():
    db = get_db()
    hoje = date.today().isoformat()
    limite_antigas = (date.today() - timedelta(days=14)).isoformat()

    def um(sql, params=()):
        return db.execute(sql, params).fetchone()[0]

    stats = {
        'clientes': um('SELECT COUNT(*) FROM clientes'),
        'total': um('SELECT COUNT(*) FROM assistencias'),
        'pendentes': um('SELECT COUNT(*) FROM assistencias WHERE status = ?', (ESTADO_PENDENTE,)),
        'andamento': um('SELECT COUNT(*) FROM assistencias WHERE status = ?', (ESTADO_ANDAMENTO,)),
        'abertas': um('SELECT COUNT(*) FROM assistencias WHERE status IN (?, ?)', ESTADOS_ABERTOS),
        'aguarda': um('SELECT COUNT(*) FROM assistencias WHERE status = ?', (ESTADO_AGUARDA,)),
        'concluidas': um('SELECT COUNT(*) FROM assistencias WHERE status = ?', (ESTADO_CONCLUIDA,)),
        'canceladas': um('SELECT COUNT(*) FROM assistencias WHERE status = ?', (ESTADO_CANCELADA,)),
        'por_pagar': um('SELECT COUNT(*) FROM assistencias WHERE status = ? AND pago = 0', (ESTADO_CONCLUIDA,)),
        'urgentes_abertas': um("SELECT COUNT(*) FROM assistencias WHERE status IN (?, ?) AND urgencia = 'Urgente'", ESTADOS_ABERTOS),
        'antigas_abertas': um('SELECT COUNT(*) FROM assistencias WHERE status IN (?, ?) AND data < ?',
                              ESTADOS_ABERTOS + (limite_antigas,)),
        'faturado': um('SELECT COALESCE(SUM(valor), 0) FROM assistencias WHERE status = ?', (ESTADO_CONCLUIDA,)),
        'por_receber': um('SELECT COALESCE(SUM(valor), 0) FROM assistencias WHERE status = ? AND pago = 0', (ESTADO_CONCLUIDA,)),
        'valor_medio': um('SELECT COALESCE(AVG(valor), 0) FROM assistencias WHERE status = ? AND valor IS NOT NULL', (ESTADO_CONCLUIDA,)),
        'com_valor': um('SELECT COUNT(*) FROM assistencias WHERE valor IS NOT NULL'),
    }

    ultimas = db.execute('''
        SELECT a.*, c.nome AS cliente_nome FROM assistencias a
        LEFT JOIN clientes c ON c.id = a.cliente_id
        ORDER BY a.id DESC LIMIT 6''').fetchall()

    proximas = db.execute('''
        SELECT a.*, c.nome AS cliente_nome FROM assistencias a
        LEFT JOIN clientes c ON c.id = a.cliente_id
        WHERE a.status IN (?, ?) AND a.data >= ?
        ORDER BY a.data ASC, a.hora ASC LIMIT 6''',
        ESTADOS_ABERTOS + (hoje,)).fetchall()

    top_clientes = db.execute('''
        SELECT c.id, c.nome, COUNT(a.id) AS total FROM clientes c
        JOIN assistencias a ON a.cliente_id = c.id
        GROUP BY c.id ORDER BY total DESC LIMIT 5''').fetchall()

    stats['este_mes'] = um("SELECT COUNT(*) FROM assistencias WHERE substr(data, 1, 7) = ?",
                           (hoje[:7],))
    stats['encomendas_pendentes'] = um("SELECT COUNT(*) FROM encomendas WHERE status != 'Recebido'")

    # ---------- dados para os gráficos (Chart.js) ----------
    # evolução mensal: últimos 12 meses (criadas vs concluídas)
    meses = []
    ano, mes = date.today().year, date.today().month
    for _ in range(12):
        meses.append('%04d-%02d' % (ano, mes))
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    meses.reverse()
    criadas_por_mes = dict(db.execute('''
        SELECT substr(data, 1, 7) AS mes, COUNT(*) FROM assistencias
        WHERE data IS NOT NULL GROUP BY mes''').fetchall())
    concluidas_por_mes = dict(db.execute('''
        SELECT substr(data_conclusao, 1, 7) AS mes, COUNT(*) FROM assistencias
        WHERE status = ? AND data_conclusao IS NOT NULL GROUP BY mes''',
        (ESTADO_CONCLUIDA,)).fetchall())

    tipos = db.execute('''
        SELECT COALESCE(tipo, 'Sem tipo') AS tipo, COUNT(*) AS total
        FROM assistencias GROUP BY tipo ORDER BY total DESC''').fetchall()

    # idade das assistências em aberto (dias desde a data agendada/criada)
    idades = [0, 0, 0, 0]  # 0–3, 4–7, 8–14, 15+
    for linha in db.execute('SELECT data FROM assistencias WHERE status IN (?, ?)',
                            ESTADOS_ABERTOS):
        try:
            dias = (date.today() - datetime.strptime(linha['data'], '%Y-%m-%d').date()).days
        except (ValueError, TypeError):
            continue
        if dias <= 3:
            idades[0] += 1
        elif dias <= 7:
            idades[1] += 1
        elif dias <= 14:
            idades[2] += 1
        else:
            idades[3] += 1

    pagas = um('SELECT COUNT(*) FROM assistencias WHERE status = ? AND pago = 1',
               (ESTADO_CONCLUIDA,))
    valor_pago = um('SELECT COALESCE(SUM(valor), 0) FROM assistencias '
                    'WHERE status = ? AND pago = 1', (ESTADO_CONCLUIDA,))

    graficos = {
        'estados': {
            'labels': ['Pendente', 'Em andamento', 'Aguarda Verificação', 'Concluída', 'Cancelada'],
            'valores': [stats['pendentes'], stats['andamento'], stats['aguarda'],
                        stats['concluidas'], stats['canceladas']],
        },
        'meses': {
            'labels': [m[5:] + '/' + m[:4] for m in meses],
            'criadas': [criadas_por_mes.get(m, 0) for m in meses],
            'concluidas': [concluidas_por_mes.get(m, 0) for m in meses],
        },
        'tipos': {
            'labels': [t['tipo'] for t in tipos],
            'valores': [t['total'] for t in tipos],
        },
        'pagamentos': {
            'pagas': pagas,
            'por_pagar': stats['por_pagar'],
            'valor_pago': valor_pago,
            'valor_por_receber': stats['por_receber'],
        },
        'top_clientes': {
            'labels': [c['nome'] for c in top_clientes],
            'valores': [c['total'] for c in top_clientes],
        },
        'idades': {
            'labels': ['0–3 dias', '4–7 dias', '8–14 dias', '15+ dias'],
            'valores': idades,
        },
    }

    return render_template('index.html', stats=stats, ultimas=ultimas,
                           proximas=proximas, top_clientes=top_clientes,
                           graficos=graficos)


# --------------------------------------------------------------- clientes ---

@app.route('/clientes')
@login_required
def listar_clientes():
    q = (request.args.get('q') or '').strip()
    sql = '''SELECT c.*, COUNT(a.id) AS total_assistencias,
                    SUM(CASE WHEN a.status IN (?, ?) THEN 1 ELSE 0 END) AS abertas
             FROM clientes c LEFT JOIN assistencias a ON a.cliente_id = c.id'''
    params = list(ESTADOS_ABERTOS)
    if q:
        like = '%' + q + '%'
        sql += ''' WHERE c.nome LIKE ? OR c.nif LIKE ? OR c.contacto LIKE ?
                   OR c.morada LIKE ? OR c.email LIKE ?'''
        params += [like] * 5
    sql += ' GROUP BY c.id ORDER BY c.nome COLLATE NOCASE'
    todos = get_db().execute(sql, params).fetchall()
    clientes, pag = aplicar_paginacao(todos)
    return render_template('clientes.html', clientes=clientes, q=q, pag=pag)


@app.route('/clientes/<int:id>')
@login_required
def ver_cliente(id):
    db = get_db()
    cliente = db.execute('SELECT * FROM clientes WHERE id = ?', (id,)).fetchone()
    if cliente is None:
        flash('Cliente não encontrado.', 'warning')
        return redirect(url_for('listar_clientes'))
    assistencias = pesquisar_assistencias(TODOS_ESTADOS, cliente_id=id)
    return render_template('cliente_detalhe.html', cliente=cliente,
                           assistencias=assistencias)


@app.route('/clientes/novo', methods=['POST'])
@login_required
def add_cliente():
    dados, erros = _validar_cliente(request.form)
    destino = request.form.get('next') or ''
    db = get_db()

    if not erros and dados['nif']:
        existente = db.execute('SELECT id, nome FROM clientes WHERE nif = ?',
                               (dados['nif'],)).fetchone()
        if existente:
            erros.append('Já existe um cliente com esse NIF: %s (n.º %d).'
                         % (existente['nome'], existente['id']))
    if erros:
        for e in erros:
            flash(e, 'danger')
        return _redirect_seguro(destino, 'listar_clientes')

    repetido = db.execute('SELECT id FROM clientes WHERE nome = ? COLLATE NOCASE',
                          (dados['nome'],)).fetchone()
    cur = db.execute('''INSERT INTO clientes (nome, nif, contacto, morada, email, observacoes)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                     (dados['nome'], dados['nif'], dados['contacto'],
                      dados['morada'], dados['email'], dados['observacoes']))
    db.commit()
    flash('Cliente «%s» adicionado com sucesso!' % dados['nome'], 'success')
    if repetido:
        flash('Atenção: já existia outro cliente com o mesmo nome. '
              'Verifique se não é um duplicado.', 'warning')

    if destino:
        # voltar ao fluxo de criação de assistência com o cliente pré-selecionado
        return redirect(url_for('listar_assistencias', cliente_id=cur.lastrowid, novo=1))
    return redirect(url_for('listar_clientes'))


@app.route('/clientes/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    db = get_db()
    cliente = db.execute('SELECT * FROM clientes WHERE id = ?', (id,)).fetchone()
    if cliente is None:
        flash('Cliente não encontrado.', 'warning')
        return redirect(url_for('listar_clientes'))

    if request.method == 'POST':
        dados, erros = _validar_cliente(request.form)
        if not erros and dados['nif']:
            existente = db.execute('SELECT id FROM clientes WHERE nif = ? AND id != ?',
                                   (dados['nif'], id)).fetchone()
            if existente:
                erros.append('Já existe outro cliente com esse NIF.')
        if erros:
            for e in erros:
                flash(e, 'danger')
        else:
            db.execute('''UPDATE clientes SET nome=?, nif=?, contacto=?, morada=?,
                          email=?, observacoes=? WHERE id=?''',
                       (dados['nome'], dados['nif'], dados['contacto'],
                        dados['morada'], dados['email'], dados['observacoes'], id))
            db.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('ver_cliente', id=id))
    return render_template('editar_cliente.html', cliente=cliente)


@app.route('/clientes/<int:id>/apagar', methods=['POST'])
@login_required
def deletar_cliente(id):
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM assistencias WHERE cliente_id = ?',
                       (id,)).fetchone()[0]
    if total > 0:
        flash('Não é possível apagar este cliente: tem %d assistência(s) associada(s). '
              'Apague ou reatribua primeiro as assistências.' % total, 'danger')
        return redirect(url_for('ver_cliente', id=id))
    db.execute('DELETE FROM clientes WHERE id = ?', (id,))
    db.commit()
    flash('Cliente apagado com sucesso.', 'success')
    return redirect(url_for('listar_clientes'))


# ------------------------------------------------------------ assistências ---

@app.route('/assistencias')
@login_required
def listar_assistencias():
    q = (request.args.get('q') or '').strip()
    estado = request.args.get('estado') or ''
    estados = (estado,) if estado in ESTADOS_ABERTOS else ESTADOS_ABERTOS
    todas = pesquisar_assistencias(estados, q=q,
                                   ordem='a.data ASC, a.hora ASC')
    assistencias, pag = aplicar_paginacao(todas)
    clientes = get_db().execute(
        'SELECT * FROM clientes ORDER BY nome COLLATE NOCASE').fetchall()
    return render_template('assistencias.html', assistencias=assistencias,
                           clientes=clientes, q=q, estado=estado, pag=pag,
                           cliente_pre=request.args.get('cliente_id', ''),
                           abrir_form=request.args.get('novo') == '1')


@app.route('/assistencias/nova', methods=['POST'])
@login_required
def add_assistencia():
    dados, erros = _validar_assistencia(request.form)
    if erros:
        for e in erros:
            flash(e, 'danger')
        return redirect(url_for('listar_assistencias'))

    db = get_db()
    cliente = db.execute('SELECT id FROM clientes WHERE id = ?',
                         (dados['cliente_id'],)).fetchone()
    if cliente is None:
        flash('O cliente selecionado já não existe.', 'danger')
        return redirect(url_for('listar_assistencias'))

    db.execute('''INSERT INTO assistencias
                  (cliente_id, data, hora, avaria, tipo, urgencia, descricao, valor, status, pago)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)''',
               (dados['cliente_id'], dados['data'], dados['hora'], dados['avaria'],
                dados['tipo'], dados['urgencia'], dados['descricao'],
                dados['valor'], ESTADO_PENDENTE))
    db.commit()
    flash('Assistência criada com sucesso! Ficou na lista «Em Aberto».', 'success')
    return redirect(url_for('listar_assistencias'))


@app.route('/assistencias/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_assistencia(id):
    db = get_db()
    assistencia = db.execute('SELECT * FROM assistencias WHERE id = ?', (id,)).fetchone()
    if assistencia is None:
        flash('Assistência não encontrada.', 'warning')
        return redirect(url_for('listar_assistencias'))

    destino = request.args.get('next') or request.form.get('next') or ''

    if request.method == 'POST':
        dados, erros = _validar_assistencia(request.form)
        status = request.form.get('status') or assistencia['status']
        if status not in TODOS_ESTADOS:
            erros.append('Estado inválido.')
        if erros:
            for e in erros:
                flash(e, 'danger')
        else:
            data_conclusao = (request.form.get('data_conclusao') or '').strip() or None
            # ao terminar/concluir sem data de conclusão, assume-se hoje
            if status in (ESTADO_AGUARDA, ESTADO_CONCLUIDA) and not data_conclusao:
                data_conclusao = date.today().isoformat()
            if status in ESTADOS_ABERTOS:
                data_conclusao = None
            pago = 1 if request.form.get('pago') else 0

            db.execute('''UPDATE assistencias SET cliente_id=?, data=?, hora=?, avaria=?,
                          descricao=?, tipo=?, urgencia=?, status=?, data_conclusao=?,
                          valor=?, pago=? WHERE id=?''',
                       (dados['cliente_id'], dados['data'], dados['hora'],
                        dados['avaria'], dados['descricao'], dados['tipo'],
                        dados['urgencia'], status, data_conclusao,
                        dados['valor'], pago, id))
            db.commit()
            flash('Assistência atualizada com sucesso!', 'success')
            return _redirect_seguro(destino)

    clientes = db.execute('SELECT * FROM clientes ORDER BY nome COLLATE NOCASE').fetchall()
    return render_template('editar_assistencia.html', assistencia=assistencia,
                           clientes=clientes, next=destino)


@app.route('/assistencias/<int:id>/estado', methods=['POST'])
@login_required
def mudar_estado(id):
    """Muda o estado de uma assistência (ações rápidas das listas)."""
    novo = request.form.get('estado') or ''
    if novo not in TODOS_ESTADOS:
        flash('Estado inválido.', 'danger')
        return _redirect_seguro(request.form.get('next'))

    db = get_db()
    assistencia = db.execute('SELECT * FROM assistencias WHERE id = ?', (id,)).fetchone()
    if assistencia is None:
        flash('Assistência não encontrada.', 'warning')
        return _redirect_seguro(request.form.get('next'))

    data_conclusao = assistencia['data_conclusao']
    if novo in (ESTADO_AGUARDA, ESTADO_CONCLUIDA) and not data_conclusao:
        data_conclusao = date.today().isoformat()
    if novo in ESTADOS_ABERTOS:
        data_conclusao = None

    pago = assistencia['pago']
    if request.form.get('pago'):
        pago = 1

    db.execute('UPDATE assistencias SET status = ?, data_conclusao = ?, pago = ? WHERE id = ?',
               (novo, data_conclusao, pago, id))
    db.commit()

    mensagens = {
        ESTADO_ANDAMENTO: 'Assistência marcada como «Em andamento».',
        ESTADO_AGUARDA: 'Trabalho concluído — a assistência passou para «Aguarda Verificação».',
        ESTADO_CONCLUIDA: 'Assistência aprovada e movida para o Histórico.',
        ESTADO_CANCELADA: 'Assistência cancelada e movida para o Histórico.',
        ESTADO_PENDENTE: 'Assistência reaberta como «Pendente».',
    }
    flash(mensagens.get(novo, 'Estado atualizado.'), 'success')
    return _redirect_seguro(request.form.get('next'))


@app.route('/assistencias/<int:id>/pago', methods=['POST'])
@login_required
def alternar_pago(id):
    db = get_db()
    assistencia = db.execute('SELECT pago FROM assistencias WHERE id = ?', (id,)).fetchone()
    if assistencia is None:
        flash('Assistência não encontrada.', 'warning')
    else:
        novo = 0 if assistencia['pago'] else 1
        db.execute('UPDATE assistencias SET pago = ? WHERE id = ?', (novo, id))
        db.commit()
        flash('Assistência marcada como %s.' % ('paga' if novo else 'não paga'), 'success')
    return _redirect_seguro(request.form.get('next'), 'concluidos')


@app.route('/assistencias/<int:id>/apagar', methods=['POST'])
@login_required
def deletar_assistencia(id):
    db = get_db()
    db.execute('DELETE FROM assistencias WHERE id = ?', (id,))
    db.commit()
    flash('Assistência apagada com sucesso.', 'success')
    return _redirect_seguro(request.form.get('next'))


@app.route('/aguarda-verificacao')
@login_required
def aguarda_verificacao():
    q = (request.args.get('q') or '').strip()
    todas = pesquisar_assistencias((ESTADO_AGUARDA,), q=q,
                                   ordem='a.data_conclusao DESC, a.data DESC')
    assistencias, pag = aplicar_paginacao(todas)
    return render_template('aguarda_verificacao.html', assistencias=assistencias,
                           q=q, pag=pag)


@app.route('/historico')
@login_required
def concluidos():
    q = (request.args.get('q') or '').strip()
    data_de = request.args.get('data_de') or ''
    data_ate = request.args.get('data_ate') or ''
    estado = request.args.get('estado') or ''
    vista = 'clientes' if request.args.get('vista') == 'clientes' else 'lista'
    estados = (estado,) if estado in ESTADOS_FINAIS else ESTADOS_FINAIS
    todas = pesquisar_assistencias(estados, q=q, data_de=data_de,
                                   data_ate=data_ate,
                                   ordem='a.data_conclusao DESC, a.data DESC')

    if vista == 'clientes':
        # agrupar por cliente, ordenado pela assistência mais recente
        grupos_por_chave, ordem_chaves = {}, []
        for a in todas:
            chave = a['cliente_id'] if a['cliente_id'] else 'sem-cliente-%d' % a['id']
            if chave not in grupos_por_chave:
                grupos_por_chave[chave] = {'cliente_id': a['cliente_id'],
                                           'cliente_nome': a['cliente_nome'],
                                           'itens': []}
                ordem_chaves.append(chave)
            grupos_por_chave[chave]['itens'].append(a)
        grupos, pag = aplicar_paginacao([grupos_por_chave[c] for c in ordem_chaves])
        return render_template('concluidos.html', grupos=grupos, assistencias=[],
                               vista=vista, q=q, data_de=data_de,
                               data_ate=data_ate, estado=estado, pag=pag)

    assistencias, pag = aplicar_paginacao(todas)
    return render_template('concluidos.html', assistencias=assistencias, grupos=[],
                           vista=vista, q=q, data_de=data_de,
                           data_ate=data_ate, estado=estado, pag=pag)


# -------------------------------------------------------------- encomendas ---

def _validar_encomenda(form):
    erros = []
    descricao = (form.get('descricao') or '').strip()
    fornecedor = (form.get('fornecedor') or '').strip() or None
    quantidade_str = (form.get('quantidade') or '').strip()
    data_encomenda = (form.get('data_encomenda') or '').strip() or date.today().isoformat()

    if not descricao:
        erros.append('A descrição da encomenda é obrigatória.')
    quantidade = None
    if quantidade_str:
        if quantidade_str.isdigit() and int(quantidade_str) > 0:
            quantidade = int(quantidade_str)
        else:
            erros.append('A quantidade deve ser um número inteiro positivo.')
    try:
        datetime.strptime(data_encomenda, '%Y-%m-%d')
    except ValueError:
        erros.append('A data da encomenda não é válida.')
    return {'descricao': descricao, 'quantidade': quantidade,
            'fornecedor': fornecedor, 'data_encomenda': data_encomenda}, erros


@app.route('/encomendas')
@login_required
def encomendas():
    q = (request.args.get('q') or '').strip()
    db = get_db()
    sql_extra, params = '', []
    if q:
        like = '%' + q + '%'
        sql_extra = ' AND (descricao LIKE ? OR fornecedor LIKE ?)'
        params = [like, like]
    pendentes = db.execute(
        "SELECT * FROM encomendas WHERE status != 'Recebido'" + sql_extra +
        ' ORDER BY data_encomenda DESC, id DESC', params).fetchall()
    recebidas = db.execute(
        "SELECT * FROM encomendas WHERE status = 'Recebido'" + sql_extra +
        ' ORDER BY data_recebimento DESC, id DESC', params).fetchall()
    return render_template('encomendas.html', pendentes=pendentes,
                           recebidas=recebidas, q=q)


@app.route('/encomendas/nova', methods=['POST'])
@login_required
def add_encomenda():
    dados, erros = _validar_encomenda(request.form)
    if erros:
        for e in erros:
            flash(e, 'danger')
        return redirect(url_for('encomendas'))
    db = get_db()
    db.execute('''INSERT INTO encomendas (descricao, quantidade, fornecedor,
                  data_encomenda, status) VALUES (?, ?, ?, ?, 'Por encomendar')''',
               (dados['descricao'], dados['quantidade'], dados['fornecedor'],
                dados['data_encomenda']))
    db.commit()
    flash('Encomenda adicionada com sucesso!', 'success')
    return redirect(url_for('encomendas'))


@app.route('/encomendas/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_encomenda(id):
    db = get_db()
    encomenda = db.execute('SELECT * FROM encomendas WHERE id = ?', (id,)).fetchone()
    if encomenda is None:
        flash('Encomenda não encontrada.', 'warning')
        return redirect(url_for('encomendas'))

    if request.method == 'POST':
        dados, erros = _validar_encomenda(request.form)
        status = request.form.get('status') or encomenda['status']
        if status not in ESTADOS_ENCOMENDA:
            erros.append('Estado da encomenda inválido.')
        if erros:
            for e in erros:
                flash(e, 'danger')
        else:
            data_recebimento = (request.form.get('data_recebimento') or '').strip() or None
            if status == 'Recebido' and not data_recebimento:
                data_recebimento = date.today().isoformat()
            if status != 'Recebido':
                data_recebimento = None
            db.execute('''UPDATE encomendas SET descricao=?, quantidade=?, fornecedor=?,
                          data_encomenda=?, status=?, data_recebimento=? WHERE id=?''',
                       (dados['descricao'], dados['quantidade'], dados['fornecedor'],
                        dados['data_encomenda'], status, data_recebimento, id))
            db.commit()
            flash('Encomenda atualizada com sucesso!', 'success')
            return redirect(url_for('encomendas'))
    return render_template('editar_encomenda.html', encomenda=encomenda)


@app.route('/encomendas/<int:id>/estado', methods=['POST'])
@login_required
def mudar_estado_encomenda(id):
    novo = request.form.get('estado') or ''
    if novo not in ESTADOS_ENCOMENDA:
        flash('Estado da encomenda inválido.', 'danger')
        return redirect(url_for('encomendas'))
    db = get_db()
    encomenda = db.execute('SELECT * FROM encomendas WHERE id = ?', (id,)).fetchone()
    if encomenda is None:
        flash('Encomenda não encontrada.', 'warning')
        return redirect(url_for('encomendas'))
    data_recebimento = date.today().isoformat() if novo == 'Recebido' else None
    db.execute('UPDATE encomendas SET status = ?, data_recebimento = ? WHERE id = ?',
               (novo, data_recebimento, id))
    db.commit()
    mensagens = {
        'Já encomendado': 'Encomenda marcada como «Já encomendado».',
        'Recebido': 'Encomenda marcada como recebida e movida para o histórico.',
        'Por encomendar': 'Encomenda devolvida a «Por encomendar».',
    }
    flash(mensagens.get(novo, 'Estado atualizado.'), 'success')
    return redirect(url_for('encomendas'))


@app.route('/encomendas/<int:id>/apagar', methods=['POST'])
@login_required
def deletar_encomenda(id):
    db = get_db()
    db.execute('DELETE FROM encomendas WHERE id = ?', (id,))
    db.commit()
    flash('Encomenda apagada com sucesso.', 'success')
    return redirect(url_for('encomendas'))


# -------------------------------------------------------------------- erros ---

@app.errorhandler(404)
def pagina_nao_encontrada(e):
    return render_template('erro.html', codigo=404,
                           mensagem='A página que procura não existe.'), 404


@app.errorhandler(500)
def erro_interno(e):
    return render_template('erro.html', codigo=500,
                           mensagem='Ocorreu um erro interno. Tente novamente.'), 500


if __name__ == '__main__':
    # Em produção usar gunicorn (ver Dockerfile); debug só com FLASK_DEBUG=1.
    app.run(host='0.0.0.0', port=5000,
            debug=os.environ.get('FLASK_DEBUG', '0') == '1')

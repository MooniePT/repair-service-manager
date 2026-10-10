# Gestão de Assistências

Aplicação web (Flask + SQLite) para gerir clientes e assistências técnicas de uma pequena empresa.

> 📖 **Documentação completa na pasta [`docs/`](README.md):**
> [Manual da aplicação](MANUAL.md) (configuração, Docker, backups, migração) ·
> [Guia Cloudflare](CLOUDFLARE.md) (acesso externo, emails, país).

## Fluxo das assistências

```
Nova assistência  →  Pendente / Em andamento  →  Aguarda Verificação  →  Concluída (Histórico)
                                                                     ↘  Cancelada (Histórico)
```

- Uma nova assistência entra automaticamente no estado **Pendente** (lista «Em Aberto»).
- Quando o trabalho está feito, passa para **Aguarda Verificação** (botão ✓ ou edição).
- Depois de verificada/aprovada (com ou sem pagamento), passa para **Concluída** e aparece no **Histórico**.
- Assistências **Canceladas** também ficam no Histórico.

## Listas e histórico

- Todas as listas grandes (clientes, em aberto, aguarda verificação, histórico) têm **paginação** com escolha de 10 | 20 | 50 linhas por página.
- O **histórico** tem duas vistas: **Lista** (todas as assistências) e **Por cliente** (uma linha por cliente com a assistência mais recente; clicar expande o histórico completo desse cliente).

## Encomendas

Módulo de encomendas de material (recuperado da versão de produção): cada encomenda tem descrição, quantidade, fornecedor e datas, com o fluxo **Por encomendar → Já encomendado → Recebido**. As recebidas ficam num histórico próprio na mesma página.

## Como executar

### Localmente (Windows/Linux/Mac)

```bash
pip install -r requirements.txt
python app.py
```

A aplicação fica disponível em http://localhost:5000.

**Login inicial:** utilizador `admin`, palavra-passe `admin123` — a aplicação avisa no login enquanto esta palavra-passe não for alterada (página Configuração).

### Com Docker

```bash
docker compose up --build
```

As pastas `database/` (dados) e `instance/` (secret key) são montadas como volumes, pelo que sobrevivem a rebuilds. O contentor corre com utilizador **não-root** e o gunicorn serve a aplicação.

## Variáveis de ambiente

| Variável | Predefinição | Quando usar |
|---|---|---|
| `SECRET_KEY` | gerada e persistida em `instance/secret_key` | **Obrigatório definir em produção** (`openssl rand -hex 32`) |
| `SESSION_COOKIE_SECURE` | `0` | Pôr a `1` quando a app está servida por **HTTPS**. Em HTTP local deve ficar a `0`, senão o login deixa de funcionar (o browser não envia o cookie) |
| `BEHIND_PROXY` | `0` | Pôr a `1` quando há um reverse proxy à frente (ativa o `ProxyFix` para respeitar `X-Forwarded-Proto/For/Host`) |
| `FLASK_DEBUG` | `0` | Apenas em desenvolvimento local. **Nunca** em produção |
| `DATABASE_PATH` | `database/assistencias.db` | Para mudar a localização da base de dados |

## Segurança

Medidas ativas na aplicação:

- **Login obrigatório** em todas as rotas (exceto a própria página de login);
- **Passwords com hash** (`werkzeug.security`), nunca em texto simples;
- **Proteção CSRF** em todos os formulários POST (token por sessão, comparação em tempo constante);
- **Cookies de sessão**: `HttpOnly`, `SameSite=Lax`, validade de 12 horas, `Secure` configurável;
- **Queries 100% parametrizadas** (sem SQL injection);
- **Headers de segurança**: `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`;
- **Chart.js servido localmente** (sem dependência de CDN para os gráficos);
- Aviso automático enquanto a palavra-passe inicial não for alterada.

### Acesso externo: HTTPS é fortemente recomendado

Se expuser a aplicação à Internet **apenas por HTTP**, o login e os cookies de sessão circulam **em claro** — qualquer pessoa na mesma rede (ou no caminho) pode capturar a palavra-passe e a sessão. Use sempre HTTPS para acesso externo.

Configuração recomendada com reverse proxy (Nginx, Traefik ou Cloudflare Tunnel):

1. O proxy termina o HTTPS (certificado Let's Encrypt ou Cloudflare) e encaminha para `http://127.0.0.1:5000`;
2. No `docker-compose.yml`, mude a porta para `"127.0.0.1:5000:5000"` para a app só ser acessível através do proxy;
3. Defina `BEHIND_PROXY=1` (a app passa a respeitar `X-Forwarded-Proto`, gerando URLs corretos);
4. Defina `SESSION_COOKIE_SECURE=1` (cookies só por HTTPS);
5. Defina um `SECRET_KEY` próprio.

Exemplo de bloco Nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

O que **depende da infraestrutura** (fora da aplicação): obter o certificado TLS, firewall, atualizações do servidor, e backups externos da pasta `database/`.

## Base de dados

- Ficheiro: `database/assistencias.db` (SQLite).
- No arranque, a aplicação cria as tabelas em falta e aplica migrações **aditivas** (nunca apaga dados). Antes de qualquer migração é criada uma cópia de segurança em `database/backups/`.
- As pastas `db/` e `instance/` continham bases de dados antigas/órfãs; foram movidas para `database/backups/` (ficheiros `legado-*`).

### Backup manual

Basta copiar o ficheiro `database/assistencias.db`. Com Docker:

```bash
docker cp <nome-do-contentor>:/app/database/assistencias.db C:\backup-banco\
```

Para exportar o contentor Docker completo para outra máquina:

```bash
docker commit <nome-do-contentor> meu-app-backup
docker save -o C:\backup\meu-app.tar meu-app-backup
docker export -o C:\backup\meu-container.tar <nome-do-contentor>
```

## Estrutura do projeto

```
app.py                  — toda a lógica Flask (rotas, BD, validações, segurança)
templates/
  base.html             — layout base (navbar, mensagens)
  _macros.html          — macros partilhadas (badges, pesquisa, tabelas)
  index.html            — dashboard (cartões, gráficos, alertas)
  clientes.html         — lista + criação de clientes
  cliente_detalhe.html  — ficha do cliente + histórico
  editar_cliente.html
  assistencias.html     — em aberto + nova assistência
  aguarda_verificacao.html
  concluidos.html       — histórico
  editar_assistencia.html
  encomendas.html / editar_encomenda.html — encomendas de material
  login.html / configuracao.html / erro.html
static/
  css/style.css         — identidade visual (paleta verde)
  js/script.js          — usabilidade (confirmações, auto-preenchimento)
  js/dashboard.js       — gráficos do dashboard
  js/vendor/chart.umd.min.js — Chart.js servido localmente
database/
  assistencias.db       — base de dados ativa
  backups/              — cópias de segurança automáticas
```

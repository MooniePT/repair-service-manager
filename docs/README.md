# Documentação — Gestão de Assistências

Bem-vindo. Esta pasta contém tudo o que precisa para usar, manter e migrar a
aplicação.

## Por onde começar

| Documento | Para quê |
|---|---|
| **[MANUAL.md](MANUAL.md)** | Manual geral: o que faz a app, configuração, Docker, **backups** e **migração sem perder dados**, resolução de problemas. |
| **[CLOUDFLARE.md](CLOUDFLARE.md)** | Acesso externo seguro: domínio, túnel, autorização por **email** e bloqueio por **país**. |

## Perguntas rápidas

- **Como faço backup?** → Copiar `database/assistencias.db`. Ver [MANUAL §7](MANUAL.md#7-backups).
- **Vou mudar de computador.** → [MANUAL §8](MANUAL.md#8-mudar-de-máquina--migrar-sem-perder-nada).
- **Como arranco no Docker?** → [MANUAL §5](MANUAL.md#5-pôr-a-correr-no-docker).
- **Quem pode aceder de fora?** → Eu controlo a lista de emails. [CLOUDFLARE §6](CLOUDFLARE.md#6-proteção-por-email--país-cloudflare-access).
- **Esqueci-me de uma variável de configuração.** → [MANUAL §4](MANUAL.md#4-configuração-variáveis-de-ambiente).

## Diagramas

- [Arquitetura](img/arquitetura.svg) — como o pedido viaja do utilizador até aos dados.
- [Camadas de segurança](img/camadas-seguranca.svg) — país → email → login.
- [Fluxo de migração](img/fluxo-migracao.svg) — mudar de máquina em 5 passos.
- [Ecrã: Public Hostname](img/cf-tunnel-hostname.svg) e [Ecrã: Política de Acesso](img/cf-access-policy.svg) — referência visual dos ecrãs do Cloudflare.

> Os diagramas dos ecrãs do Cloudflare são **ilustrações** dos campos a
> preencher (não capturas reais), para reconhecer onde clicar.

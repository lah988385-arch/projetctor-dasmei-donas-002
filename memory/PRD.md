# PRD — PGMEI / Painel Donas (clone & setup)

## Problema original
Clonar e configurar o repo existente `lah988385-arch/projetctor-dasmei-donas-001` na sandbox Emergent (/app), preservando `.git`, `.emergent`, `frontend/.env`, `backend/.env`. Rodar o código como está, sem alterar arquitetura. Garantir JWT_SECRET forte e login admin funcionando.

## Arquitetura
- Backend: FastAPI (`/app/backend/server.py`) + módulos `admin_painel.py`, `das_pdf.py`, `pgmei_import.py`, `pgmei_sessao.py`, `pgmei_motor.py`. Prefixo `/api`.
- Frontend: React CRA (craco) em `/app/frontend`, servido via dev server (`yarn start`).
- Banco: MongoDB via `MONGO_URL` / `DB_NAME` (não alterados).

## Observações importantes (repo real difere do enunciado)
- NÃO existe `pix_generator.py` nem `admin_routes.py`; `server.py` não os importa. PIX é gerado pela rota `GET /api/das/pix/{cnpj}/{ano}`. As rotas `/api/pix/*` não existem nesta versão.
- Login admin: `POST /api/admin/login` com body `{"usuario","senha"}`, resposta `{"token","usuario"}`. Rota protegida: `GET /api/admin/me`.
- Não há `seed_admin()` nem collection `admins`/bcrypt. As credenciais vêm do ambiente, obrigatórias (sem fallback): `ADMIN_USER`, `ADMIN_PASSWORD`, `JWT_SECRET`.

## O que foi feito (2026-06)
- Repo sincronizado em /app (preservados .git, .emergent, ambos .env).
- `backend/.env`: adicionados `ADMIN_USER=donas`, `ADMIN_PASSWORD=Seinao10@@`, `JWT_SECRET` forte aleatório.
- Dependências: `yarn install` OK; backend instalado (full requirements teve conflito de resolver pip entre o wheel pinado `litellm` e `emergentintegrations`, ambos já pré-instalados e não usados pelo app — restante instalado, todos os módulos importam).
- Serviços reiniciados via supervisor; validado e2e: `GET /api/` 200, login retorna JWT, `/api/admin/me` 200 com Bearer e 401 sem token. Frontend `/` e `/donaspainel` carregam.

## Credenciais
- Admin: usuário `donas` / senha `Seinao10@@` (rota `/donaspainel`).

## Backlog / próximos (P2)
- Instalar browsers do Playwright se a automação de sessão gov.br for usada em runtime.

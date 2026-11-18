# 🤝 Acolher e Transformar — MVP de Gestão Comunitária

Sistema web leve para a **Associação Acolher e Transformar**, instituição comunitária do **Jardim das Flores (São Paulo/SP)** que atende cerca de **180 famílias** e conta com **15 voluntários** na distribuição de cestas básicas e doações.

> Projeto acadêmico de Engenharia de Software. A associação e o cenário são fictícios, criados para fins de estudo.

---

## 📌 Sumário

1. [Problema social](#-problema-social)
2. [Conexão com o ODS 2](#-conexão-com-o-ods-2--fome-zero-e-agricultura-sustentável)
3. [Funcionalidades](#-funcionalidades)
4. [Arquitetura em camadas](#-arquitetura-em-camadas)
5. [Modelo de dados](#-modelo-de-dados)
6. [Segurança (OWASP)](#-segurança-owasp)
7. [Acessibilidade (WCAG 2.1 AA)](#-acessibilidade-wcag-21-aa)
8. [Estrutura do projeto](#-estrutura-do-projeto)
9. [Instalação e execução](#-instalação-e-execução)
10. [Testes](#-testes)
11. [Guia rápido de uso](#-guia-rápido-de-uso)
12. [Limitações e próximos passos](#-limitações-e-próximos-passos)

---

## 🌍 Problema social

Organizações comunitárias costumam controlar atendimentos e doações em cadernos e planilhas soltas. Com ~180 famílias e 15 voluntários se revezando, isso gera:

- **Retrabalho e falhas de registro** — não fica claro quais famílias já receberam a cesta do mês.
- **Falta de visibilidade** — o voluntário não sabe rapidamente o que está pendente, em atendimento ou concluído.
- **Dificuldade de prestar contas** — sem dados organizados, é trabalhoso gerar relatórios para doadores e parceiros.

O MVP oferece um **painel simples, seguro e acessível** para cadastrar atendimentos, acompanhar o status de cada um e exportar os dados.

## 🎯 Conexão com o ODS 2 — Fome Zero e Agricultura Sustentável

O projeto contribui com o **Objetivo de Desenvolvimento Sustentável 2** da ONU, em especial com a **Meta 2.1**: *acabar com a fome e garantir o acesso de todas as pessoas, em particular os pobres e em situação vulnerável, a alimentos seguros, nutritivos e suficientes durante todo o ano*.

Como o sistema ajuda: organiza a fila de famílias a atender, evita atendimentos duplicados ou esquecidos, dá transparência à distribuição das doações e gera dados (CSV) para planejar compras e campanhas.

## ✅ Funcionalidades

| Código | Requisito | Onde está |
|--------|-----------|-----------|
| **RF01** | Cadastro de voluntário com e-mail único e senha mínima de 6 caracteres | `auth.cadastrar_usuario`, aba “Cadastrar voluntário” |
| **RF02** | Login seguro com sessão (`st.session_state`) e logout | `auth.autenticar`, `app.py` |
| **RF03** | Cadastro de atendimentos, listagem por operador, busca (nome/descrição), filtro por status e atualização de status | Aba “Painel de gestão” |
| **RF04** | Exportação CSV (`utf-8-sig`) com feedback visual de sucesso | Aba “Exportar CSV” |

Detalhes úteis:

- A busca ignora maiúsculas e acentos (`familia` encontra `Família`).
- Cada operador **só vê e altera os próprios registros**.
- Status permitidos: `Pendente`, `Em atendimento`, `Atendida`.
- O CSV usa **separador `;`** (padrão do Excel em português) e codificação `utf-8-sig` (BOM), para que os acentos abram corretamente.
- Bloqueio temporário de 60 s após 5 tentativas de login incorretas na mesma sessão.

## 🏗️ Arquitetura em camadas

Arquitetura **monolítica em camadas**, em um único processo Python, com dependências sempre apontando de cima para baixo:

```
┌───────────────────────────────────────────────────────────┐
│  APRESENTAÇÃO / UI            app.py                      │
│  Streamlit: telas, CSS acessível, estado de sessão        │
└──────────────────────────────┬────────────────────────────┘
                               │ chama
┌──────────────────────────────▼────────────────────────────┐
│  REGRAS DE NEGÓCIO / AUTENTICAÇÃO     auth.py             │
│  validação de cadastro, PBKDF2 + salt, login              │
└──────────────────────────────┬────────────────────────────┘
                               │ chama
┌──────────────────────────────▼────────────────────────────┐
│  PERSISTÊNCIA DE DADOS        database.py                 │
│  SQLite3 (acolher_transformar.db), CRUD, exportação CSV   │
└───────────────────────────────────────────────────────────┘
```

| Camada | Arquivo | Responsabilidade |
|--------|---------|------------------|
| Apresentação | `app.py` | Telas (Login/Cadastro, Painel, Exportação), CSS acessível, mensagens de feedback |
| Regras de negócio | `auth.py` | Validação, hash de senha, autenticação |
| Persistência | `database.py` | Esquema, consultas parametrizadas, CRUD, seed e serialização do CSV |

Stack: **Python 3.12**, **Streamlit ≥ 1.32.0**, **Pandas** e **SQLite3** embarcado (biblioteca padrão).

## 🗄️ Modelo de dados

**`usuarios`**

| Coluna | Tipo | Restrições |
|--------|------|-----------|
| `id_usuario` | INTEGER | PK, autoincrement |
| `nome` | TEXT | NOT NULL |
| `email` | TEXT | NOT NULL, UNIQUE |
| `senha_hash` | TEXT | NOT NULL |
| `data_cadastro` | TEXT | NOT NULL |

**`registros_mvp`**

| Coluna | Tipo | Restrições |
|--------|------|-----------|
| `id_registro` | INTEGER | PK, autoincrement |
| `titulo` | TEXT | NOT NULL (ex.: Família / Item) |
| `descricao` | TEXT | — |
| `status` | TEXT | NOT NULL, `CHECK` em (`Pendente`, `Em atendimento`, `Atendida`) |
| `data_criacao` | TEXT | NOT NULL |
| `id_usuario` | INTEGER | NOT NULL, FK → `usuarios.id_usuario` |

## 🔐 Segurança (OWASP)

| Risco (OWASP Top 10:2021) | Medida adotada |
|---------------------------|----------------|
| **A02 – Falhas criptográficas** | Senhas com `hashlib.pbkdf2_hmac('sha256', ...)`, **salt exclusivo de 16 bytes via `os.urandom`** e **600.000 iterações**. Formato armazenado: `pbkdf2_sha256$iterações$salt$hash`. Nunca texto plano, MD5 ou SHA-1. |
| **A03 – Injeção** | **100% das consultas parametrizadas (`?`)**. Nenhum dado do usuário é concatenado ao SQL. Curingas do `LIKE` (`%`, `_`) são escapados. Testes automatizados com payloads de SQL Injection. |
| **A07 – Falhas de identificação e autenticação** | Comparação em tempo constante (`hmac.compare_digest`), mensagem de erro genérica, custo de hash equivalente para e-mail inexistente, limite de tamanho de senha (128) e bloqueio temporário após tentativas inválidas. |
| **A04 – Design inseguro / controle de acesso** | Toda consulta e alteração de registro filtra por `id_usuario` (o operador não acessa dados de outro). Chaves estrangeiras ativas e `CHECK` de status no banco. |
| **CSV/Formula Injection** | Textos iniciados por `=`, `+`, `-` ou `@` recebem apóstrofo no CSV para não serem executados como fórmula pelo Excel/Calc. |
| **Segredos e dados** | `.gitignore` bloqueia `*.db`, `.env` e `.venv/`, evitando publicar dados de pessoas atendidas. |

## ♿ Acessibilidade (WCAG 2.1 AA)

CSS customizado em `app.py` (`CSS_ACESSIVEL`) e tema claro em `.streamlit/config.toml`:

- **Alvos de toque ≥ 48 px** (acima do mínimo de 44×44 px) em botões, campos, abas e opções de rádio.
- **Alto contraste**: texto `#1A1A1A` sobre `#FFFFFF` (~17:1) e botões `#FFFFFF` sobre `#0B3D91` (~10:1), ambos acima de 4,5:1.
- **Rótulos persistentes** acima de todos os campos (sem depender de *placeholder*).
- **Alertas com ícone + texto** (✅ Sucesso, ❌ Erro, ⚠️ Atenção, ℹ️ Informação): a informação nunca depende só de cor.
- **Foco de teclado visível** (contorno de 3 px) e navegação completa por teclado.

> As cores foram escolhidas com razões de contraste calculadas. Recomenda-se, antes de uso real, uma revisão com leitor de tela e ferramentas como o WAVE ou o axe DevTools.

## 📁 Estrutura do projeto

```
.
├── app.py               # Camada de apresentação (Streamlit)
├── auth.py              # Regras de negócio e autenticação (PBKDF2)
├── database.py          # Persistência (SQLite), CRUD, seed e CSV
├── test_app.py          # Testes unitários (unittest)
├── requirements.txt     # Dependências
├── .streamlit/
│   └── config.toml      # Tema claro de alto contraste
├── .gitignore
└── README.md
```

O banco `acolher_transformar.db` é criado automaticamente na primeira execução (e não é versionado).

## ⚙️ Instalação e execução

Pré-requisito: **Python 3.12** instalado.

### Windows (PowerShell)

```powershell
git clone <URL-DO-SEU-REPOSITORIO>
cd <PASTA-DO-REPOSITORIO>

python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Se o PowerShell bloquear scripts: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

python -m pip install --upgrade pip
pip install -r requirements.txt

streamlit run app.py
```

### Linux / macOS

```bash
git clone <URL-DO-SEU-REPOSITORIO>
cd <PASTA-DO-REPOSITORIO>

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

streamlit run app.py
```

O navegador abrirá em `http://localhost:8501`.

## 🧪 Testes

```bash
python -m unittest test_app -v
```

Os testes usam um banco temporário (o banco real não é tocado) e cobrem:

- hash PBKDF2: formato, salt exclusivo, verificação correta/incorreta e hash malformado;
- cadastro: e-mail duplicado (inclusive com maiúsculas), senha mínima, e-mail inválido e confirmação de senha;
- autenticação, incluindo payloads de SQL Injection;
- CRUD no SQLite: criação, listagem, busca, filtro, atualização, exclusão, isolamento entre operadores, `CHECK` de status e chave estrangeira;
- exportação CSV: BOM `utf-8-sig`, acentos e neutralização de fórmulas.

## 🚀 Guia rápido de uso

1. Abra a aba **Cadastrar voluntário**, crie sua conta e depois entre na aba **Entrar**.
2. No **Painel de gestão**, cadastre famílias ou itens. Se estiver vazio, use **Carregar dados de demonstração** (dados fictícios).
3. Use **Buscar e filtrar** para localizar atendimentos por nome ou status.
4. Em **Atualizar status**, selecione o atendimento e escolha o novo status.
5. Na aba **Exportar CSV**, escolha entre os registros filtrados ou todos, confira a pré-visualização e clique em **Baixar arquivo CSV**.
6. Use **Sair (logout)** na barra lateral ao terminar.

## ⚠️ Limitações e próximos passos

- É um **MVP**: o bloqueio de tentativas de login vale por sessão do navegador, não globalmente. Em produção, usar limitação por IP/conta no servidor.
- O SQLite embarcado atende bem a um pequeno grupo de voluntários; para uso intenso e simultâneo, migrar para PostgreSQL.
- Sem recuperação de senha por e-mail e sem perfis de acesso (coordenador x voluntário).
- **LGPD**: evite registrar dados pessoais sensíveis nas descrições. Em uso real, defina base legal, política de retenção e backups criptografados.
- Evoluções possíveis: controle de estoque com alerta de nível mínimo, triagem por documento, relatórios mensais e HTTPS atrás de proxy reverso.

## 👤 Autoria

Bruno Oliveira — projeto acadêmico de Engenharia de Software.

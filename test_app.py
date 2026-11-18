"""
Testes unitários (unittest) - Associação Acolher e Transformar.

Executar:
    python -m unittest test_app -v

Cada teste usa um banco SQLite temporário e isolado; o arquivo
`acolher_transformar.db` real nunca é tocado.
"""

import hashlib
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import auth
import database
from database import (
    DadosInvalidosError,
    EmailDuplicadoError,
    StatusInvalidoError,
)

ITERACOES_RAPIDAS = 1_000  # acelera testes que não verificam a força do hash


class BancoTemporarioTestCase(unittest.TestCase):
    """Base: cria um banco temporário novo a cada teste."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "teste.db")
        database.init_db(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def novo_usuario(self, email="voluntario@exemplo.com", nome="Voluntário Teste"):
        return database.criar_usuario(nome, email, "hash-qualquer", self.db)


# --------------------------------------------------------------------------- #
# Hash e verificação de senha (RNF01)
# --------------------------------------------------------------------------- #
class TestHashSenha(unittest.TestCase):
    def test_formato_e_iteracoes_padrao(self):
        senha = "segredo123"
        resultado = auth.gerar_hash_senha(senha)
        algoritmo, iteracoes, salt_hex, hash_hex = resultado.split("$")
        self.assertEqual(algoritmo, "pbkdf2_sha256")
        self.assertGreaterEqual(int(iteracoes), 600_000)
        self.assertEqual(len(bytes.fromhex(salt_hex)), 16)
        self.assertEqual(len(bytes.fromhex(hash_hex)), 32)
        self.assertNotIn(senha, resultado)

    def test_salt_exclusivo_para_mesma_senha(self):
        h1 = auth.gerar_hash_senha("mesma-senha", ITERACOES_RAPIDAS)
        h2 = auth.gerar_hash_senha("mesma-senha", ITERACOES_RAPIDAS)
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1.split("$")[2], h2.split("$")[2])

    def test_hash_confere_com_pbkdf2_hmac_da_biblioteca_padrao(self):
        resultado = auth.gerar_hash_senha("abc123", ITERACOES_RAPIDAS)
        _, iteracoes, salt_hex, hash_hex = resultado.split("$")
        esperado = hashlib.pbkdf2_hmac(
            "sha256", b"abc123", bytes.fromhex(salt_hex), int(iteracoes)
        )
        self.assertEqual(esperado.hex(), hash_hex)

    def test_verificacao_correta_e_incorreta(self):
        h = auth.gerar_hash_senha("senha-correta", ITERACOES_RAPIDAS)
        self.assertTrue(auth.verificar_senha("senha-correta", h))
        self.assertFalse(auth.verificar_senha("senha-errada", h))
        self.assertFalse(auth.verificar_senha("", h))

    def test_senha_com_acentos_e_unicode(self):
        h = auth.gerar_hash_senha("coração-ação-123", ITERACOES_RAPIDAS)
        self.assertTrue(auth.verificar_senha("coração-ação-123", h))
        self.assertFalse(auth.verificar_senha("coracao-acao-123", h))

    def test_hash_malformado_nunca_lanca_excecao(self):
        for invalido in ("", "abc", "a$b$c$d", "pbkdf2_sha256$x$y$z",
                         "pbkdf2_sha256$0$aa$bb", "md5$1000$aa$bb", None):
            with self.subTest(hash=invalido):
                self.assertFalse(auth.verificar_senha("qualquer", invalido))


# --------------------------------------------------------------------------- #
# Cadastro (RF01)
# --------------------------------------------------------------------------- #
class TestCadastro(BancoTemporarioTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(auth, "ITERACOES", ITERACOES_RAPIDAS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cadastro_valido_grava_hash_e_nao_a_senha(self):
        id_usuario = auth.cadastrar_usuario(
            "  Maria Silva ", "  MARIA@Exemplo.com ", "senha123", "senha123", self.db
        )
        self.assertGreater(id_usuario, 0)
        usuario = database.buscar_usuario_por_email("maria@exemplo.com", self.db)
        self.assertEqual(usuario["nome"], "Maria Silva")
        self.assertEqual(usuario["email"], "maria@exemplo.com")
        self.assertNotEqual(usuario["senha_hash"], "senha123")
        self.assertNotIn("senha123", usuario["senha_hash"])
        self.assertTrue(auth.verificar_senha("senha123", usuario["senha_hash"]))

    def test_email_duplicado_e_bloqueado(self):
        auth.cadastrar_usuario("Ana", "ana@exemplo.com", "senha123", db_path=self.db)
        with self.assertRaises(EmailDuplicadoError):
            auth.cadastrar_usuario("Outra Ana", "ana@exemplo.com", "outra123", db_path=self.db)
        self.assertEqual(database.contar_usuarios(self.db), 1)

    def test_email_duplicado_ignora_maiusculas_e_espacos(self):
        auth.cadastrar_usuario("Ana", "ana@exemplo.com", "senha123", db_path=self.db)
        with self.assertRaises(EmailDuplicadoError):
            auth.cadastrar_usuario("Ana 2", "  ANA@EXEMPLO.COM ", "senha123", db_path=self.db)

    def test_duplicidade_tambem_e_barrada_na_camada_de_persistencia(self):
        database.criar_usuario("A", "a@exemplo.com", "h", self.db)
        with self.assertRaises(EmailDuplicadoError):
            database.criar_usuario("B", "a@exemplo.com", "h2", self.db)

    def test_senha_minima_de_6_caracteres(self):
        with self.assertRaises(auth.ErroValidacao):
            auth.cadastrar_usuario("Ana", "ana@exemplo.com", "12345", db_path=self.db)
        self.assertEqual(database.contar_usuarios(self.db), 0)
        auth.cadastrar_usuario("Ana", "ana@exemplo.com", "123456", db_path=self.db)
        self.assertEqual(database.contar_usuarios(self.db), 1)

    def test_email_invalido(self):
        for email in ("", "semarroba", "a@b", "a@@b.com", "a b@exemplo.com"):
            with self.subTest(email=email):
                with self.assertRaises(auth.ErroValidacao):
                    auth.cadastrar_usuario("Ana", email, "senha123", db_path=self.db)

    def test_nome_obrigatorio(self):
        with self.assertRaises(auth.ErroValidacao):
            auth.cadastrar_usuario("   ", "ana@exemplo.com", "senha123", db_path=self.db)

    def test_confirmacao_de_senha_diferente(self):
        with self.assertRaises(auth.ErroValidacao):
            auth.cadastrar_usuario("Ana", "ana@exemplo.com", "senha123", "senha124", self.db)


# --------------------------------------------------------------------------- #
# Autenticação (RF02)
# --------------------------------------------------------------------------- #
class TestAutenticacao(BancoTemporarioTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(auth, "ITERACOES", ITERACOES_RAPIDAS)
        patcher.start()
        self.addCleanup(patcher.stop)
        auth.cadastrar_usuario("Carlos", "carlos@exemplo.com", "senha123", db_path=self.db)

    def test_login_com_credenciais_corretas(self):
        usuario = auth.autenticar("Carlos@Exemplo.com", "senha123", self.db)
        self.assertIsNotNone(usuario)
        self.assertEqual(usuario["nome"], "Carlos")
        self.assertEqual(usuario["email"], "carlos@exemplo.com")
        self.assertNotIn("senha_hash", usuario)

    def test_login_com_senha_errada(self):
        self.assertIsNone(auth.autenticar("carlos@exemplo.com", "errada123", self.db))

    def test_login_com_email_inexistente(self):
        self.assertIsNone(auth.autenticar("ninguem@exemplo.com", "senha123", self.db))

    def test_login_com_entradas_vazias_ou_invalidas(self):
        self.assertIsNone(auth.autenticar("", "", self.db))
        self.assertIsNone(auth.autenticar("carlos@exemplo.com", "", self.db))
        self.assertIsNone(auth.autenticar(None, "senha123", self.db))
        self.assertIsNone(auth.autenticar("carlos@exemplo.com", "x" * 500, self.db))

    def test_payloads_de_sql_injection_nao_autenticam_e_nao_quebram_o_banco(self):
        payloads = ["' OR '1'='1", "carlos@exemplo.com' --", "'; DROP TABLE usuarios; --"]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(auth.autenticar(payload, payload, self.db))
        self.assertEqual(database.contar_usuarios(self.db), 1)


# --------------------------------------------------------------------------- #
# CRUD no SQLite (RF03)
# --------------------------------------------------------------------------- #
class TestEsquema(BancoTemporarioTestCase):
    def test_tabelas_criadas_e_init_idempotente(self):
        database.init_db(self.db)  # segunda chamada não deve falhar
        with database.conexao(self.db) as conn:
            nomes = {
                linha["name"]
                for linha in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        self.assertTrue({"usuarios", "registros_mvp"}.issubset(nomes))

    def test_check_constraint_rejeita_status_invalido_direto_no_banco(self):
        id_usuario = self.novo_usuario()
        with self.assertRaises(sqlite3.IntegrityError):
            with database.conexao(self.db) as conn:
                conn.execute(
                    "INSERT INTO registros_mvp (titulo, descricao, status, data_criacao, id_usuario) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("X", "", "Inventado", "2026-01-01 00:00:00", id_usuario),
                )

    def test_chave_estrangeira_exige_usuario_existente(self):
        with self.assertRaises(sqlite3.IntegrityError):
            database.criar_registro("Família Fantasma", "", id_usuario=9999, db_path=self.db)


class TestCrudRegistros(BancoTemporarioTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.novo_usuario()

    def test_criar_e_listar_do_mais_recente_para_o_mais_antigo(self):
        a = database.criar_registro("Família A", "obs A", self.uid, db_path=self.db)
        b = database.criar_registro("Família B", "obs B", self.uid, db_path=self.db)
        registros = database.listar_registros(self.uid, db_path=self.db)
        self.assertEqual([r["id_registro"] for r in registros], [b, a])
        self.assertEqual(registros[0]["status"], "Pendente")
        self.assertEqual(registros[0]["id_usuario"], self.uid)

    def test_titulo_obrigatorio(self):
        with self.assertRaises(DadosInvalidosError):
            database.criar_registro("   ", "x", self.uid, db_path=self.db)

    def test_status_invalido_na_criacao_e_na_atualizacao(self):
        with self.assertRaises(StatusInvalidoError):
            database.criar_registro("A", "", self.uid, status="Concluído", db_path=self.db)
        id_registro = database.criar_registro("A", "", self.uid, db_path=self.db)
        with self.assertRaises(StatusInvalidoError):
            database.atualizar_status(id_registro, "Concluído", self.uid, self.db)

    def test_atualizar_status(self):
        id_registro = database.criar_registro("Família A", "", self.uid, db_path=self.db)
        for novo in ("Em atendimento", "Atendida"):
            self.assertTrue(database.atualizar_status(id_registro, novo, self.uid, self.db))
            atual = database.listar_registros(self.uid, db_path=self.db)[0]
            self.assertEqual(atual["status"], novo)

    def test_atualizar_registro_inexistente_retorna_false(self):
        self.assertFalse(database.atualizar_status(12345, "Atendida", self.uid, self.db))

    def test_operador_nao_altera_nem_exclui_registro_de_outro(self):
        outro = self.novo_usuario("outro@exemplo.com", "Outro Voluntário")
        id_registro = database.criar_registro("Família A", "", self.uid, db_path=self.db)
        self.assertFalse(database.atualizar_status(id_registro, "Atendida", outro, self.db))
        self.assertFalse(database.excluir_registro(id_registro, outro, self.db))
        registro = database.listar_registros(self.uid, db_path=self.db)[0]
        self.assertEqual(registro["status"], "Pendente")

    def test_listagem_isola_registros_por_operador(self):
        outro = self.novo_usuario("outro@exemplo.com", "Outro Voluntário")
        database.criar_registro("Família do Primeiro", "", self.uid, db_path=self.db)
        database.criar_registro("Família do Segundo", "", outro, db_path=self.db)
        titulos = [r["titulo"] for r in database.listar_registros(self.uid, db_path=self.db)]
        self.assertEqual(titulos, ["Família do Primeiro"])

    def test_excluir_registro(self):
        id_registro = database.criar_registro("Família A", "", self.uid, db_path=self.db)
        self.assertTrue(database.excluir_registro(id_registro, self.uid, self.db))
        self.assertEqual(database.listar_registros(self.uid, db_path=self.db), [])
        self.assertFalse(database.excluir_registro(id_registro, self.uid, self.db))

    def test_contar_por_status(self):
        database.criar_registro("A", "", self.uid, "Pendente", self.db)
        database.criar_registro("B", "", self.uid, "Pendente", self.db)
        database.criar_registro("C", "", self.uid, "Atendida", self.db)
        self.assertEqual(
            database.contar_por_status(self.uid, self.db),
            {"Pendente": 2, "Em atendimento": 0, "Atendida": 1},
        )


class TestBuscaEFiltros(BancoTemporarioTestCase):
    def setUp(self):
        super().setUp()
        self.uid = self.novo_usuario()
        database.criar_registro("Família Silva", "4 pessoas", self.uid, "Pendente", self.db)
        database.criar_registro("Família Oliveira", "Prioridade: crianças", self.uid, "Em atendimento", self.db)
        database.criar_registro("Item: Arroz 5 kg", "Doação de outubro", self.uid, "Atendida", self.db)

    def titulos(self, **filtros):
        return sorted(r["titulo"] for r in database.listar_registros(self.uid, db_path=self.db, **filtros))

    def test_busca_por_titulo_sem_diferenciar_maiusculas_e_acentos(self):
        self.assertEqual(self.titulos(busca="familia"), ["Família Oliveira", "Família Silva"])
        self.assertEqual(self.titulos(busca="FAMÍLIA SILVA"), ["Família Silva"])

    def test_busca_tambem_considera_a_descricao(self):
        self.assertEqual(self.titulos(busca="criancas"), ["Família Oliveira"])

    def test_filtro_por_status(self):
        self.assertEqual(self.titulos(status="Atendida"), ["Item: Arroz 5 kg"])

    def test_busca_combinada_com_status(self):
        self.assertEqual(self.titulos(busca="família", status="Pendente"), ["Família Silva"])
        self.assertEqual(self.titulos(busca="arroz", status="Pendente"), [])

    def test_curingas_do_like_sao_tratados_como_texto(self):
        self.assertEqual(self.titulos(busca="%"), [])
        self.assertEqual(self.titulos(busca="_"), [])

    def test_busca_vazia_retorna_todos(self):
        self.assertEqual(len(self.titulos(busca="   ")), 3)

    def test_filtro_com_status_invalido(self):
        with self.assertRaises(StatusInvalidoError):
            database.listar_registros(self.uid, status="Qualquer", db_path=self.db)

    def test_sql_injection_na_busca_nao_afeta_o_banco(self):
        for payload in ("'; DROP TABLE registros_mvp; --", "' OR 1=1 --", '" OR ""="'):
            with self.subTest(payload=payload):
                self.assertEqual(self.titulos(busca=payload), [])
        self.assertEqual(len(self.titulos()), 3)


class TestSeedDemo(BancoTemporarioTestCase):
    def test_seed_insere_dados_uma_unica_vez(self):
        uid = self.novo_usuario()
        inseridos = database.popular_dados_demo(uid, self.db)
        self.assertEqual(inseridos, len(database.DADOS_DEMO))
        self.assertEqual(len(database.listar_registros(uid, db_path=self.db)), inseridos)
        self.assertEqual(database.popular_dados_demo(uid, self.db), 0)


# --------------------------------------------------------------------------- #
# Exportação CSV (RF04)
# --------------------------------------------------------------------------- #
class TestExportacaoCsv(BancoTemporarioTestCase):
    def test_csv_utf8_sig_com_bom_acentos_e_cabecalho(self):
        uid = self.novo_usuario()
        database.criar_registro("Família São José", "Criança; 2 anos", uid, db_path=self.db)
        df = database.registros_para_dataframe(database.listar_registros(uid, db_path=self.db))
        dados = database.dataframe_para_csv_bytes(df)

        self.assertTrue(dados.startswith(b"\xef\xbb\xbf"))  # BOM do utf-8-sig
        texto = dados.decode("utf-8-sig")
        self.assertTrue(texto.startswith("ID;Título;Descrição;Status;Data de criação"))
        self.assertIn("Família São José", texto)
        self.assertIn('"Criança; 2 anos"', texto)  # separador dentro do texto vem entre aspas

    def test_csv_de_lista_vazia_tem_apenas_cabecalho(self):
        df = database.registros_para_dataframe([])
        texto = database.dataframe_para_csv_bytes(df).decode("utf-8-sig")
        self.assertEqual(texto.strip(), "ID;Título;Descrição;Status;Data de criação")

    def test_neutraliza_formulas_em_planilhas(self):
        uid = self.novo_usuario()
        database.criar_registro("=HYPERLINK(\"http://x\")", "+cmd", uid, db_path=self.db)
        df = database.registros_para_dataframe(database.listar_registros(uid, db_path=self.db))
        texto = database.dataframe_para_csv_bytes(df).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", texto)
        self.assertIn("'+cmd", texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)

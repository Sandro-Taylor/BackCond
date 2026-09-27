-- =====================================================
-- ESTRUTURA DO BANCO – GESTÃO CONDOMINIAL
-- =====================================================
-- Recria o banco do zero. Usado pelo docker-compose na
-- primeira criação do volume (docker-entrypoint-initdb.d)
-- e pode ser rodado manualmente para zerar o ambiente.
-- ATENÇÃO: apaga todas as tabelas e dados.
-- =====================================================

BEGIN;

-- 0. LIMPEZA
DROP TABLE IF EXISTS tarefas, projetos, colaboradores, setores, veiculos, vagas,
  pessoas_apartamentos, apartamentos, pessoas, usuarios_condominios, condominios, users CASCADE;
DROP TYPE IF EXISTS user_status;

-- Fuso horário de Brasília para todas as conexões novas
DO $$ BEGIN
  EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'America/Sao_Paulo');
END $$;

-- Atualiza updated_at automaticamente em qualquer UPDATE
CREATE OR REPLACE FUNCTION atualizar_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. LOGIN
CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email         varchar(255) NOT NULL UNIQUE CHECK (email = lower(email)),
  password_hash text NOT NULL,
  full_name     varchar(150) NOT NULL,
  status        varchar(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo','inativo','bloqueado')),
  admin_sistema boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- 2. CONDOMÍNIO (CNPJ numérico ou alfanumérico, sem máscara)
CREATE TABLE condominios (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nome        varchar(150) NOT NULL,
  cnpj        varchar(14) UNIQUE CONSTRAINT condominios_cnpj_check CHECK (cnpj ~ '^[0-9A-Z]{12}[0-9]{2}$'),
  cep         varchar(8) CHECK (cep ~ '^[0-9]{8}$'),
  logradouro  varchar(200),
  numero      varchar(20),
  complemento varchar(100),
  bairro      varchar(100),
  cidade      varchar(100),
  uf          char(2) CHECK (uf ~ '^[A-Z]{2}$'),
  telefone    varchar(11) CHECK (telefone ~ '^[0-9]{10,11}$'),
  email       varchar(255) CHECK (email = lower(email)),
  ativo       boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 3. PESSOAS (moradores, síndico, conselheiros, colaboradores)
CREATE TABLE pessoas (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id   uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  user_id         uuid REFERENCES users(id) ON DELETE SET NULL,
  perfil          varchar(20) NOT NULL DEFAULT 'MORADOR'
                  CONSTRAINT pessoas_perfil_check CHECK (perfil IN ('MORADOR','SINDICO','CONSELHEIRO','COLABORADOR','PRESTADOR')),
  nome            varchar(150) NOT NULL,
  cpf             varchar(11) CHECK (cpf ~ '^[0-9]{11}$'),
  email           varchar(255) CHECK (email = lower(email)),
  telefone        varchar(11) CHECK (telefone ~ '^[0-9]{10,11}$'),
  data_nascimento date,
  ativo           boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (condominio_id, cpf),
  UNIQUE (condominio_id, user_id)
);

-- 4. APARTAMENTOS E VÍNCULOS
CREATE TABLE apartamentos (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  bloco         varchar(20) NOT NULL DEFAULT '',
  numero        varchar(10) NOT NULL,
  andar         smallint,
  observacao    text,
  ativo         boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (condominio_id, bloco, numero)
);

CREATE TABLE pessoas_apartamentos (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pessoa_id      uuid NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
  apartamento_id uuid NOT NULL REFERENCES apartamentos(id) ON DELETE CASCADE,
  tipo_relacao   varchar(20) NOT NULL CONSTRAINT pessoas_apartamentos_tipo_relacao_check
                 CHECK (tipo_relacao IN ('PROPRIETARIO','INQUILINO','RESIDENTE')),
  reside         boolean NOT NULL DEFAULT true,   -- proprietário: mora ou não no prédio
  titular_vinculo_id uuid REFERENCES pessoas_apartamentos(id) ON DELETE CASCADE,  -- residente: a quem está ligado
  parentesco     varchar(30) CONSTRAINT pessoas_apartamentos_parentesco_check
                 CHECK (parentesco IN ('CONJUGE','FILHO','ENTEADO','PAI_MAE','SOGRO','IRMAO',
                                       'AVO','NETO','OUTRO_PARENTE','EMPREGADO_DOMESTICO','OUTRO')),
  principal      boolean NOT NULL DEFAULT false,
  ativo          boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pessoa_id, apartamento_id),
  -- residente exige titular e parentesco; proprietário/inquilino não têm nenhum dos dois
  CONSTRAINT pessoas_apartamentos_residente_check CHECK (
    (tipo_relacao = 'RESIDENTE' AND titular_vinculo_id IS NOT NULL AND parentesco IS NOT NULL)
    OR (tipo_relacao <> 'RESIDENTE' AND titular_vinculo_id IS NULL AND parentesco IS NULL)
  ),
  -- só o proprietário pode não residir
  CONSTRAINT pessoas_apartamentos_reside_check CHECK (tipo_relacao = 'PROPRIETARIO' OR reside)
);
CREATE UNIQUE INDEX pessoas_apartamentos_um_principal
  ON pessoas_apartamentos (pessoa_id) WHERE principal;

-- 5. VAGAS E VEÍCULOS
CREATE TABLE vagas (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id  uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  -- FIXA: pode ser de um apartamento (ou estar livre); ROTATIVA: uso comum, sem apartamento
  tipo           varchar(10) NOT NULL DEFAULT 'FIXA' CHECK (tipo IN ('FIXA','ROTATIVA')),
  apartamento_id uuid REFERENCES apartamentos(id) ON DELETE SET NULL,
  numero         varchar(20) NOT NULL,
  localizacao    varchar(100),
  observacao     text,
  ativo          boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (condominio_id, numero),
  CONSTRAINT vagas_rotativa_sem_apartamento_check CHECK (tipo = 'FIXA' OR apartamento_id IS NULL)
);

CREATE TABLE veiculos (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  apartamento_id uuid NOT NULL REFERENCES apartamentos(id) ON DELETE CASCADE,
  pessoa_id     uuid REFERENCES pessoas(id) ON DELETE SET NULL,  -- condutor (opcional)
  vaga_id       uuid REFERENCES vagas(id) ON DELETE SET NULL,
  placa         varchar(7) CHECK (placa ~ '^[A-Z0-9]{7}$'),
  marca         varchar(50),
  modelo        varchar(80),
  cor           varchar(30),
  descricao     varchar(255),
  ativo         boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (condominio_id, placa)
);
CREATE INDEX veiculos_pessoa_idx ON veiculos (pessoa_id);
CREATE INDEX veiculos_apartamento_idx ON veiculos (apartamento_id);

-- 6. SETORES E COLABORADORES
CREATE TABLE setores (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  nome          varchar(120) NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (condominio_id, nome)
);

CREATE TABLE colaboradores (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  pessoa_id     uuid NOT NULL UNIQUE REFERENCES pessoas(id) ON DELETE CASCADE,
  setor_id      uuid NOT NULL REFERENCES setores(id) ON DELETE RESTRICT,
  cargo         varchar(120),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- 7. PROJETOS (obras/melhorias) E TAREFAS
CREATE TABLE projetos (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id     uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  nome              varchar(180) NOT NULL,
  descricao         text,
  ativo             boolean NOT NULL DEFAULT true,
  data_arquivamento timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX projetos_condominio_idx ON projetos (condominio_id);

CREATE TABLE tarefas (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  condominio_id     uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
  projeto_id        uuid NOT NULL REFERENCES projetos(id) ON DELETE RESTRICT,
  responsavel_id    uuid NOT NULL REFERENCES pessoas(id) ON DELETE RESTRICT,
  titulo            varchar(240) NOT NULL,
  descricao         text,
  prioridade        varchar(10) NOT NULL DEFAULT 'media'
                    CHECK (prioridade IN ('baixa','media','alta','urgente')),
  status            varchar(20) NOT NULL DEFAULT 'pendente'
                    CHECK (status IN ('pendente','em_andamento','concluida','cancelada')),
  prazo             timestamptz,
  data_conclusao    timestamptz,
  ativo             boolean NOT NULL DEFAULT true,
  data_arquivamento timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tarefas_condominio_idx  ON tarefas (condominio_id);
CREATE INDEX tarefas_projeto_idx     ON tarefas (projeto_id);
CREATE INDEX tarefas_responsavel_idx ON tarefas (responsavel_id);

-- 8. TRIGGERS DE updated_at
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['users','condominios','pessoas','apartamentos','vagas',
                           'veiculos','colaboradores','projetos','tarefas']
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%1$s_updated_at BEFORE UPDATE ON %1$I
       FOR EACH ROW EXECUTE FUNCTION atualizar_updated_at()', t);
  END LOOP;
END $$;

COMMIT;

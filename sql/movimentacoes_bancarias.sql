-- ---------------------------------------------------------
-- MOVIMENTAÇÕES BANCÁRIAS (extrato mensal do banco)
-- ---------------------------------------------------------
-- extratos_importados ...... um registro por arquivo enviado (mês)
-- movimentacoes_bancarias .. um registro por lançamento do extrato
-- Valor negativo = SAÍDA; positivo = ENTRADA (coluna tipo).
-- As linhas de saldo do extrato ("SALDO ANTERIOR" e
-- "SALDO TOTAL DISPONÍVEL DIA") não viram lançamento: o saldo
-- inicial e o final ficam guardados no extrato importado.
-- Rodar uma vez, no banco do sistema.
-- ---------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS extratos_importados (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id       uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
    nome_arquivo        varchar(255) NOT NULL,
    titular             varchar(200),                 -- "Nome:" do extrato
    agencia             varchar(20),
    conta               varchar(30),
    periodo_inicio      date NOT NULL,
    periodo_fim         date NOT NULL,
    saldo_anterior      numeric(14,2),
    saldo_final         numeric(14,2),
    total_entradas      numeric(14,2) NOT NULL DEFAULT 0,
    total_saidas        numeric(14,2) NOT NULL DEFAULT 0, -- guardado negativo, como no extrato
    quantidade          integer NOT NULL DEFAULT 0,
    enviado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_extratos_periodo CHECK (periodo_fim >= periodo_inicio),
    -- o mesmo período da mesma conta não pode ser enviado duas vezes (o sistema substitui)
    CONSTRAINT uq_extratos_periodo UNIQUE (condominio_id, agencia, conta, periodo_inicio, periodo_fim)
);

CREATE INDEX IF NOT EXISTS ix_extratos_condominio ON extratos_importados (condominio_id, periodo_inicio);

CREATE TABLE IF NOT EXISTS movimentacoes_bancarias (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id  uuid NOT NULL REFERENCES condominios(id) ON DELETE RESTRICT,
    extrato_id     uuid NOT NULL REFERENCES extratos_importados(id) ON DELETE CASCADE,
    data           date NOT NULL,
    lancamento     varchar(255) NOT NULL,             -- descrição do banco
    razao_social   varchar(255),
    cpf_cnpj       varchar(14),                       -- só números
    valor          numeric(14,2) NOT NULL,            -- como veio no extrato (negativo = saída)
    tipo           varchar(7) NOT NULL,               -- ENTRADA ou SAIDA
    ordem          integer NOT NULL,                  -- posição da linha no extrato
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_movimentacoes_tipo CHECK (tipo IN ('ENTRADA', 'SAIDA')),
    CONSTRAINT ck_movimentacoes_sinal CHECK ((tipo = 'ENTRADA' AND valor >= 0) OR (tipo = 'SAIDA' AND valor < 0))
);

CREATE INDEX IF NOT EXISTS ix_movimentacoes_condominio_data ON movimentacoes_bancarias (condominio_id, data);
CREATE INDEX IF NOT EXISTS ix_movimentacoes_extrato ON movimentacoes_bancarias (extrato_id);

COMMIT;

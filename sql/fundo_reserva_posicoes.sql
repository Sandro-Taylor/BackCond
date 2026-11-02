-- ---------------------------------------------------------
-- POSIÇÕES DO FUNDO DE RESERVA (saldo líquido dos CDBs, informado à mão)
-- ---------------------------------------------------------
-- Uma linha por conta de investimento e data (ex.: CDB da conta 04645-2
-- em 02/11/2026 = R$ 47.016,03). O saldo do fundo de cada conta passa a
-- ser: última posição + aplicações - resgates feitos depois dela.
-- A diferença entre posições aparece como RENDIMENTO.
-- Rodar uma vez, no banco do sistema.
-- ---------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS fundo_reserva_posicoes (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id       uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    agencia             varchar(20) NOT NULL,
    conta               varchar(30) NOT NULL,
    descricao           varchar(100),                  -- ex.: "CDB-DI Itaú"
    data_posicao        date NOT NULL,
    saldo_liquido       numeric(14,2) NOT NULL,
    informado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_fundo_posicao UNIQUE (condominio_id, agencia, conta, data_posicao)
);

CREATE INDEX IF NOT EXISTS ix_fundo_posicoes_condominio ON fundo_reserva_posicoes (condominio_id, data_posicao);

COMMIT;

-- ---------------------------------------------------------
-- LANÇAMENTOS FUTUROS (entram na previsão)
-- ---------------------------------------------------------
-- Pagamentos/recebimentos combinados que ainda não estão no extrato,
-- ex.: 3 parcelas de R$ 1.200 para a empresa K1 (via PIX).
-- Cada parcela é uma linha; parcelas do mesmo acordo têm o mesmo grupo_id.
-- Na previsão só entram as datas DEPOIS do último extrato enviado (as
-- anteriores já devem estar no extrato).
-- Rodar os comandos abaixo (sem bloco $$).
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS lancamentos_futuros (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id      uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    grupo_id           uuid NOT NULL,
    descricao          varchar(200) NOT NULL,
    favorecido         varchar(200),
    tipo               varchar(7) NOT NULL,
    valor              numeric(14,2) NOT NULL,
    data               date NOT NULL,
    parcela            smallint NOT NULL DEFAULT 1,
    total_parcelas     smallint NOT NULL DEFAULT 1,
    criado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_lancamentos_futuros_tipo CHECK (tipo IN ('ENTRADA', 'SAIDA')),
    CONSTRAINT ck_lancamentos_futuros_valor CHECK (valor > 0)
);

CREATE INDEX IF NOT EXISTS ix_lancamentos_futuros_condominio ON lancamentos_futuros (condominio_id, data);

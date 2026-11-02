-- ---------------------------------------------------------
-- SALDO INICIAL DE CADA CONTA BANCÁRIA (preenchido à mão)
-- ---------------------------------------------------------
-- Saldo da conta = saldo_inicial (na data_saldo_inicial)
--                + lançamentos do extrato DEPOIS dessa data.
-- O "SALDO ANTERIOR" e o "SALDO TOTAL" do extrato não entram no
-- saldo (servem só para conferir lançamento repetido).
-- Rodar uma vez, no banco do sistema (PostgreSQL 15 ou mais novo).
-- ---------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS saldos_iniciais_conta (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id          uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    agencia                varchar(20),
    conta                  varchar(30),
    saldo_inicial          numeric(14,2) NOT NULL DEFAULT 0,
    data_saldo_inicial     date NOT NULL,
    atualizado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_saldo_inicial_conta UNIQUE NULLS NOT DISTINCT (condominio_id, agencia, conta)
);

COMMIT;

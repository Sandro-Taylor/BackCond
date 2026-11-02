-- ---------------------------------------------------------
-- FUNDO DE RESERVA (um por condomínio)
-- ---------------------------------------------------------
-- Saldo do fundo = saldo_inicial (na data_saldo_inicial)
--                + aplicações (saídas do extrato com texto_aplicacao)
--                - resgates   (entradas do extrato com texto_resgate)
-- Só contam lançamentos DEPOIS da data_saldo_inicial.
-- Rodar uma vez, no banco do sistema.
-- ---------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS fundos_reserva (
    condominio_id         uuid PRIMARY KEY REFERENCES condominios(id) ON DELETE CASCADE,
    saldo_inicial         numeric(14,2) NOT NULL DEFAULT 0,
    data_saldo_inicial    date NOT NULL,
    texto_aplicacao       varchar(100) NOT NULL DEFAULT 'APLICACAO CDB DI',
    texto_resgate         varchar(100) NOT NULL DEFAULT 'RESGATE CDB',
    atualizado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

COMMIT;

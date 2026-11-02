-- ---------------------------------------------------------
-- SALDOS INFORMADOS (tabela única; substitui saldos_iniciais_conta,
-- fundos_reserva e fundo_reserva_posicoes)
-- ---------------------------------------------------------
-- Cada linha = um saldo lido no banco numa data, digitado pela gestão:
--   tipo CONTA ... saldo da conta corrente
--   tipo CDB ..... saldo LÍQUIDO do CDB (fundo de reserva)
-- O sistema calcula a partir do último saldo informado:
--   CONTA: + lançamentos do extrato depois da data
--   CDB:   + aplicações ("APLICACAO CDB DI") - resgates ("RESGATE CDB")
--          depois da data; a diferença entre dois saldos = rendimento
-- Rodar uma vez, no banco do sistema (PostgreSQL 15 ou mais novo).
-- Se as tabelas antigas existirem, os dados delas são copiados e elas
-- são apagadas.
-- ---------------------------------------------------------

BEGIN;

CREATE TABLE IF NOT EXISTS saldos_informados (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id         uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    tipo                  varchar(5) NOT NULL,           -- CONTA ou CDB
    agencia               varchar(20) NOT NULL,
    conta                 varchar(30) NOT NULL,
    descricao             varchar(100),
    data                  date NOT NULL,
    valor                 numeric(14,2) NOT NULL,
    informado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_saldos_informados_tipo CHECK (tipo IN ('CONTA', 'CDB')),
    CONSTRAINT uq_saldos_informados UNIQUE (condominio_id, tipo, agencia, conta, data)
);
CREATE INDEX IF NOT EXISTS ix_saldos_informados_condominio ON saldos_informados (condominio_id, tipo, data);

-- copia o que já foi digitado nas tabelas antigas (se existirem) e apaga as antigas
DO $$
BEGIN
    IF to_regclass('public.saldos_iniciais_conta') IS NOT NULL THEN
        INSERT INTO saldos_informados (condominio_id, tipo, agencia, conta, data, valor, informado_por_user_id)
        SELECT condominio_id, 'CONTA', coalesce(agencia, ''), coalesce(conta, ''), data_saldo_inicial, saldo_inicial, atualizado_por_user_id
        FROM saldos_iniciais_conta
        ON CONFLICT DO NOTHING;
        DROP TABLE saldos_iniciais_conta;
    END IF;

    IF to_regclass('public.fundo_reserva_posicoes') IS NOT NULL THEN
        INSERT INTO saldos_informados (condominio_id, tipo, agencia, conta, descricao, data, valor, informado_por_user_id)
        SELECT condominio_id, 'CDB', agencia, conta, descricao, data_posicao, saldo_liquido, informado_por_user_id
        FROM fundo_reserva_posicoes
        ON CONFLICT DO NOTHING;
        DROP TABLE fundo_reserva_posicoes;
    END IF;

    -- o saldo inicial antigo do fundo não tinha conta: vira um CDB da conta corrente
    -- que mais aparece nos extratos do condomínio (a mesma onde as aplicações acontecem)
    IF to_regclass('public.fundos_reserva') IS NOT NULL THEN
        INSERT INTO saldos_informados (condominio_id, tipo, agencia, conta, descricao, data, valor, informado_por_user_id)
        SELECT f.condominio_id, 'CDB', e.agencia, e.conta, 'Saldo inicial do fundo', f.data_saldo_inicial, f.saldo_inicial, f.atualizado_por_user_id
        FROM fundos_reserva f
        JOIN LATERAL (
            SELECT agencia, conta FROM extratos_importados x
            WHERE x.condominio_id = f.condominio_id AND x.agencia IS NOT NULL AND x.conta IS NOT NULL
            GROUP BY agencia, conta ORDER BY count(*) DESC LIMIT 1
        ) e ON true
        ON CONFLICT DO NOTHING;
        DROP TABLE fundos_reserva;
    END IF;
END $$;

COMMIT;

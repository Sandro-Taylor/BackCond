-- ---------------------------------------------------------
-- INVESTIMENTOS (CDB do fundo de reserva), digitados à mão
-- ---------------------------------------------------------
-- Cada linha = um lançamento do investimento, copiado do app do banco:
--   SALDO ....... posição (saldo líquido) numa data
--   APLICACAO ... dinheiro que entrou no CDB (saiu da conta corrente)
--   RESGATE ..... dinheiro que saiu do CDB (voltou para a conta)
--   RENDIMENTO .. juro do período
-- Investimento = agência + conta + nome (ex.: 0428 / 04645-2 / CDB DI).
-- Rodar os comandos abaixo, um por vez se preferir (sem bloco $$).
-- As posições de CDB já digitadas em saldos_informados são copiadas
-- para cá e apagadas de lá (saldos_informados fica só com conta corrente).
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS investimentos_lancamentos (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id         uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    agencia               varchar(20) NOT NULL,
    conta                 varchar(30) NOT NULL,
    nome                  varchar(60) NOT NULL DEFAULT 'CDB',
    data                  date NOT NULL,
    tipo                  varchar(10) NOT NULL,
    valor                 numeric(14,2) NOT NULL,          -- SALDO: saldo líquido
    valor_bruto           numeric(14,2),                   -- SALDO: saldo bruto (opcional)
    imposto               numeric(14,2),                   -- SALDO: IR + IOF (opcional)
    observacao            varchar(200),
    informado_por_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_investimentos_tipo CHECK (tipo IN ('SALDO', 'APLICACAO', 'RESGATE', 'RENDIMENTO'))
);

CREATE INDEX IF NOT EXISTS ix_investimentos_condominio ON investimentos_lancamentos (condominio_id, data);

INSERT INTO investimentos_lancamentos (condominio_id, agencia, conta, nome, data, tipo, valor, informado_por_user_id, created_at)
SELECT condominio_id, agencia, conta, 'CDB', data, 'SALDO', valor, informado_por_user_id, created_at
FROM saldos_informados WHERE tipo = 'CDB';

DELETE FROM saldos_informados WHERE tipo = 'CDB';

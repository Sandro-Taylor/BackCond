-- ---------------------------------------------------------
-- MANUTENÇÕES E PRESTADORES (planilha Controle_Manutencoes_Condominio.xlsx)
-- ---------------------------------------------------------
-- manutencoes: aba "Controle" (o próximo vencimento, os dias restantes e o
--   status são calculados pelo sistema: última execução + intervalo).
-- prestadores: aba "Fornecedores" (sem tipo e validade).
-- condominios.alerta_manutencao_dias: "Alerta (dias de antecedência)".
-- Os dados da planilha entram no condomínio da conta 04645-2 (Lafayette).
-- Rodar os comandos abaixo (sem bloco $$). Rodar UMA vez (os INSERT duplicam).
-- ---------------------------------------------------------

ALTER TABLE condominios ADD COLUMN IF NOT EXISTS alerta_manutencao_dias smallint NOT NULL DEFAULT 30;

CREATE TABLE IF NOT EXISTS manutencoes (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id     uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    ordem             integer NOT NULL DEFAULT 0,
    categoria         varchar(80) NOT NULL,
    item              varchar(200) NOT NULL,
    empresa           varchar(150),
    periodicidade     varchar(60),
    intervalo_meses   smallint,
    base_legal        varchar(200),
    responsavel       varchar(150),
    ultima_execucao   date,
    observacoes       text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_manutencoes_intervalo CHECK (intervalo_meses IS NULL OR intervalo_meses > 0)
);
CREATE INDEX IF NOT EXISTS ix_manutencoes_condominio ON manutencoes (condominio_id, ordem);

CREATE TABLE IF NOT EXISTS prestadores (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    condominio_id     uuid NOT NULL REFERENCES condominios(id) ON DELETE CASCADE,
    ordem             integer NOT NULL DEFAULT 0,
    empresa           varchar(150) NOT NULL,
    setor             varchar(150),
    pessoa            varchar(150),
    cnpj              varchar(20),
    telefone          varchar(30),
    custo             numeric(12,2),
    observacoes       text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_prestadores_condominio ON prestadores (condominio_id, ordem);

INSERT INTO manutencoes (condominio_id, ordem, categoria, item, empresa, periodicidade, intervalo_meses, base_legal, responsavel, ultima_execucao, observacoes)
SELECT c.condominio_id, v.*
FROM (SELECT condominio_id FROM extratos_importados
      WHERE ltrim(regexp_replace(conta, '\D', '', 'g'), '0') = '46452' LIMIT 1) c
CROSS JOIN (VALUES
  (1, 'Incêndio e segurança', 'AVCB – renovação (Corpo de Bombeiros)', NULL, 'A cada 5 anos', 60, 'LC Estadual 1.257/2015; residencial: 5 anos', NULL, DATE '2024-02-26', NULL),
  (2, 'Incêndio e segurança', 'Extintores – recarga', NULL, 'Anual', 12, 'ABNT NBR 12962', NULL, DATE '2026-02-13', NULL),
  (3, 'Incêndio e segurança', 'Extintores – teste hidrostático', NULL, 'A cada 5 anos', 60, 'ABNT NBR 12962', NULL, NULL, NULL),
  (4, 'Incêndio e segurança', 'Extintores – inspeção visual (zelador)', NULL, 'Mensal', 1, 'ABNT NBR 12962', NULL, DATE '2026-10-01', NULL),
  (5, 'Incêndio e segurança', 'Mangueiras de incêndio – inspeção', NULL, 'Semestral', 6, 'ABNT NBR 12779', NULL, NULL, NULL),
  (6, 'Incêndio e segurança', 'Mangueiras de incêndio – manutenção / teste', NULL, 'Anual', 12, 'ABNT NBR 12779', NULL, NULL, NULL),
  (7, 'Incêndio e segurança', 'Hidrantes e bomba de incêndio – manutenção', NULL, 'Anual', 12, 'Instruções Técnicas CBPMESP', NULL, NULL, NULL),
  (8, 'Incêndio e segurança', 'Iluminação de emergência – teste', NULL, 'Mensal', 1, 'ABNT NBR 10898', NULL, DATE '2026-10-01', NULL),
  (9, 'Incêndio e segurança', 'Iluminação de emergência – manutenção', NULL, 'Anual', 12, 'ABNT NBR 10898', NULL, NULL, NULL),
  (10, 'Incêndio e segurança', 'Brigada de incêndio – treinamento / reciclagem', NULL, 'Anual', 12, 'IT 17 CBPMESP (quando exigida)', NULL, DATE '2025-02-02', NULL),
  (11, 'Incêndio e segurança', 'SPDA (para-raios) – inspeção visual', NULL, 'Anual', 12, 'ABNT NBR 5419', NULL, NULL, NULL),
  (12, 'Incêndio e segurança', 'SPDA (para-raios) – laudo completo com ART', NULL, 'A cada 1 a 3 anos', 36, 'ABNT NBR 5419 (ajustar conforme laudo)', NULL, NULL, NULL),
  (13, 'Água e higiene', 'Limpeza caixa d''água superior e inferior', NULL, 'Semestral', 6, 'Vigilância Sanitária SP; empresa licenciada', NULL, DATE '2026-10-02', NULL),
  (14, 'Água e higiene', 'Análise de potabilidade da água', NULL, 'Semestral (após limpeza)', 6, 'Recomendado', NULL, NULL, NULL),
  (15, 'Água e higiene', 'Dedetização e desratização', NULL, 'Semestral', 6, 'Empresa licenciada; guardar certificado', NULL, DATE '2026-02-18', NULL),
  (16, 'Água e higiene', 'Limpeza caixas de gordura e esgoto', NULL, 'Trimestral a semestral', 6, 'Boa prática', NULL, NULL, NULL),
  (17, 'Água e higiene', 'Limpeza de calhas e telhado', NULL, 'Semestral (antes das chuvas)', 6, 'Boa prática', NULL, NULL, NULL),
  (18, 'Água e higiene', 'Bombas de recalque – manutenção preventiva', NULL, 'Trimestral', 3, 'Boa prática / contrato', NULL, NULL, NULL),
  (19, 'Elevadores', 'Manutenção preventiva (empresa cadastrada)', NULL, 'Mensal', 1, 'Lei Municipal SP 10.348/1987', NULL, NULL, NULL),
  (20, 'Elevadores', 'RIA – Relatório de Inspeção Anual', NULL, 'Anual', 12, 'Lei Municipal SP 10.348/1987', NULL, DATE '2025-08-01', NULL),
  (21, 'Elevadores', 'Cabos de aço e componentes – avaliação', NULL, 'Anual', 12, 'Conforme laudo da conservadora', NULL, NULL, NULL),
  (22, 'Instalações', 'Gás – teste de estanqueidade', NULL, 'A cada 5 anos', 60, 'Recomendado; e após obras', NULL, NULL, NULL),
  (23, 'Instalações', 'Laudo / inspeção elétrica (quadros, medidores)', NULL, 'A cada 5 anos', 60, 'ABNT NBR 5410 – recomendado', NULL, NULL, NULL),
  (24, 'Instalações', 'Portões automáticos – manutenção', NULL, 'Mensal', 1, 'Contrato', NULL, NULL, NULL),
  (25, 'Instalações', 'Interfone, CFTV, controle de acesso, reconhecimento facial', NULL, 'Mensal', 1, 'Contrato', NULL, NULL, NULL),
  (26, 'Instalações', 'Gerador (se houver) – manutenção', NULL, 'Anual', 12, 'Fabricante', NULL, NULL, NULL),
  (27, 'Estrutura e conservação', 'Inspeção predial', NULL, 'A cada 5 anos', 60, 'ABNT NBR 16747 – recomendado', NULL, NULL, NULL),
  (28, 'Estrutura e conservação', 'Fachada / marquises – vistoria', NULL, 'A cada 5 anos', 60, 'Boa prática', NULL, NULL, NULL),
  (29, 'Estrutura e conservação', 'Impermeabilização (laje, caixas d''água) – revisão', NULL, 'Anual', 12, 'Boa prática', NULL, NULL, NULL),
  (30, 'Estrutura e conservação', 'Plano de manutenção do edifício – revisão', NULL, 'Anual', 12, 'ABNT NBR 5674', NULL, NULL, NULL),
  (31, 'Administrativo', 'Seguro obrigatório do condomínio', NULL, 'Anual', 12, 'Código Civil art. 1.346', NULL, DATE '2026-06-15', NULL),
  (32, 'Administrativo', 'Assembleia Geral Ordinária (contas e orçamento)', NULL, 'Anual', 12, 'Convenção art. 10; CC art. 1.350', NULL, NULL, NULL),
  (33, 'Administrativo', 'Mandato do síndico e conselho', NULL, 'A cada 2 anos', 24, 'Convenção art. 15; CC art. 1.347', NULL, DATE '2026-04-13', NULL),
  (34, 'Administrativo', 'PGR – Programa de Gerenciamento de Riscos', NULL, 'A cada 2 anos', 24, 'NR-1', NULL, DATE '2025-08-01', NULL),
  (35, 'Administrativo', 'PCMSO – relatório analítico', NULL, 'Anual', 12, 'NR-7', NULL, NULL, NULL),
  (36, 'Administrativo', 'Exames médicos periódicos (ASO) dos funcionários', NULL, 'Anual', 12, 'NR-7', NULL, NULL, NULL),
  (37, 'Administrativo', 'Dissídio / convenção coletiva dos funcionários', NULL, 'Anual (data-base)', 12, 'Sindicato da categoria', NULL, NULL, NULL),
  (38, 'Administrativo', 'Certificado digital', NULL, 'Anual (data-base)', 12, 'Contrato', 'Certmark', DATE '2026-06-09', NULL)
) AS v(ordem, categoria, item, empresa, periodicidade, intervalo_meses, base_legal, responsavel, ultima_execucao, observacoes);

INSERT INTO prestadores (condominio_id, ordem, empresa, setor, pessoa, cnpj, telefone, custo)
SELECT c.condominio_id, v.*
FROM (SELECT condominio_id FROM extratos_importados
      WHERE ltrim(regexp_replace(conta, '\D', '', 'g'), '0') = '46452' LIMIT 1) c
CROSS JOIN (VALUES
  (1, 'Condominio', 'Sindico', 'MARCO ANTONIO FREIBERGER SACHET', NULL, '11 99334-8460', 0),
  (2, 'Condominio', 'Porteiro', 'EDILSON PEDRO DE TORRES', NULL, NULL, 2194),
  (3, 'Condominio', 'Porteiro', 'FRANCISCO EDIVAN NASCIMENTO SILVA', NULL, '11 964234583', 2495),
  (4, 'Condominio', 'Conselheira', 'MONICA FREELAND CHALABI', NULL, '11 999365114', 0),
  (5, 'Condominio', 'Conselheiro', 'RICARDO ALVES MARTIRANI (Pichi)', NULL, '11 98165-9923', 0),
  (6, 'Condominio', 'Conselheiro', 'RENATO FERNANDES CASTRO', NULL, '11 98196-7420', 0),
  (7, 'Condominio', 'Conselheira', 'CARLA LEIRNER', NULL, '11 99605-7570', 0),
  (8, 'REGINALDO BERNARDINO DE SOUZA', 'Reparos Gerais menos eletrica', 'REGINALDO BERNARDINO DE SOUZA', '27.917.132/0001-39', '11 99234-6236', 0),
  (9, 'Alpgrem Adm Condomínio', 'Administradora do condominio', 'Bianca / Ana Carolina', '05.518.619/0001-06', '11 97435-0542', 1388.3),
  (10, 'CPU', 'Monitoramento - Totem', NULL, NULL, NULL, 550),
  (11, 'CPU', 'Monitoramento - CFTV', 'Henrique', NULL, '11 94717-7840', 665.36),
  (12, 'Tec-Easy', 'Monitoramento - CFTV', 'Elton TI GV', NULL, '11 97223-2102', 0),
  (13, 'Plasfot', 'Produtos de Limpeza', NULL, NULL, '11 3826-4843', 0),
  (14, 'Eletrica', 'Eletricista', 'CARLOS ALBERTO UTAGAWA', NULL, '11 95958-5757', 0),
  (15, 'Vivo', 'Internet', 'vivo', NULL, '10615', 109.99),
  (16, 'RS Elevadores', 'Elevadores', 'Eliana Alves', '02.664.668/0001-69', '11 94701-8170', 537.79),
  (17, 'Sabesp', 'Água/esgoto', NULL, NULL, NULL, NULL),
  (18, 'Fhorthcom', 'Reformas', NULL, NULL, NULL, NULL),
  (19, 'Enel', 'Energia', NULL, NULL, NULL, NULL),
  (20, 'Tokio Marine', 'Seguro', NULL, NULL, NULL, NULL)
) AS v(ordem, empresa, setor, pessoa, cnpj, telefone, custo);

-- conferência: 38 manutenções e 20 prestadores
SELECT (SELECT count(*) FROM manutencoes) AS manutencoes, (SELECT count(*) FROM prestadores) AS prestadores;

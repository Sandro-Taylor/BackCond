-- ---------------------------------------------------------
-- FRAÇÃO IDEAL ("Relatório de Unidades - Conferência de Frações")
-- ---------------------------------------------------------
-- Colunas na própria tabela apartamentos: nome do relatório e frações (%).
-- Liga pelo número do apartamento (000011 -> 11).
-- Rodar os comandos abaixo (sem bloco $$).
-- ---------------------------------------------------------

ALTER TABLE apartamentos ADD COLUMN IF NOT EXISTS fracao_ideal   numeric(9,6);
ALTER TABLE apartamentos ADD COLUMN IF NOT EXISTS fracao_garagem numeric(9,6);
ALTER TABLE apartamentos ADD COLUMN IF NOT EXISTS fracao_extra   numeric(9,6);
ALTER TABLE apartamentos ADD COLUMN IF NOT EXISTS nome_cobranca  varchar(200);

-- colunas de uma versão anterior (não são mais usadas)
ALTER TABLE apartamentos DROP COLUMN IF EXISTS codigo_unidade;
ALTER TABLE apartamentos DROP COLUMN IF EXISTS codigo_cliente;
ALTER TABLE apartamentos DROP COLUMN IF EXISTS endereco_cobranca;
ALTER TABLE apartamentos DROP COLUMN IF EXISTS endereco_correspondencia;
ALTER TABLE apartamentos DROP COLUMN IF EXISTS expedicao;
ALTER TABLE apartamentos DROP COLUMN IF EXISTS etiqueta;

UPDATE apartamentos a
SET fracao_ideal = v.fracao, nome_cobranca = v.nome
FROM (VALUES
  ('11', 'CARLA LEIRNER',                      6.210000),
  ('12', 'KARINA BIDERMANN MONTE A. FORLENZA', 8.900000),
  ('21', 'ANTONIO MARIO DA SILVA',             4.780000),
  ('22', 'HUGO KOVENSKY E/OU',                 6.490000),
  ('31', 'FERNANDO DE CAMPOS GONZAGA',         4.120000),
  ('32', 'LUIZ FELIPE DE SOUZA CALAZANS E/OU', 6.420000),
  ('41', 'NILZA GUIMARÃES MAGIOLI MATA',       4.120000),
  ('42', 'CARINE PEREIRA QUADROS',             6.420000),
  ('51', 'SONIA MARIA SCALA PADALINO',         4.780000),
  ('52', 'AURELIO W.CAIXETA DE CASTRO',        6.420000),
  ('61', 'FERNANDO MILIS TONIOLO E/OU REGINA', 4.780000),
  ('62', 'RICARDO ALVES MARTIRANI',            6.420000),
  ('71', 'EDSON SILVA MARTINS',                4.780000),
  ('72', 'ELIZABETH TIMAR',                    6.490000),
  ('81', 'VERA CRISTINA WEY',                  4.000000),
  ('82', 'HENRI CHALABI',                      6.290000),
  ('91', 'MARIO ITO BOCCHINI',                 8.580000)
) AS v(apto, nome, fracao)
WHERE a.condominio_id = (SELECT condominio_id FROM extratos_importados
                         WHERE ltrim(regexp_replace(conta, '\D', '', 'g'), '0') = '46452' LIMIT 1)
  AND ltrim(regexp_replace(a.numero, '\D', '', 'g'), '0') = v.apto;

-- conferência: deve dar 17 apartamentos e 100.000000
SELECT count(*) AS apartamentos, sum(fracao_ideal) AS total FROM apartamentos WHERE fracao_ideal IS NOT NULL;

-- ---------------------------------------------------------
-- MANUTENÇÃO LIGADA AO PRESTADOR (sem duplicar dados)
-- ---------------------------------------------------------
-- Antes: manutencoes.empresa e manutencoes.responsavel eram texto solto.
-- Agora: manutencoes.prestador_id aponta para a tabela prestadores, e a
-- tela mostra "Empresa: <empresa do prestador>" / "Responsável: <pessoa>".
-- Passos:
--   1) cria a coluna prestador_id
--   2) o texto que já existia e não está em prestadores vira um prestador
--      (só se ainda não existir com o mesmo nome)
--   3) liga cada manutenção ao prestador de mesmo nome
--   4) apaga as colunas de texto
-- Rodar os comandos abaixo, em ordem (sem bloco $$).
-- ---------------------------------------------------------

ALTER TABLE manutencoes ADD COLUMN IF NOT EXISTS prestador_id uuid REFERENCES prestadores(id) ON DELETE SET NULL;

INSERT INTO prestadores (condominio_id, ordem, empresa)
SELECT DISTINCT m.condominio_id, 999, trim(coalesce(m.empresa, m.responsavel))
FROM manutencoes m
WHERE trim(coalesce(m.empresa, m.responsavel, '')) <> ''
  AND NOT EXISTS (SELECT 1 FROM prestadores p
                  WHERE p.condominio_id = m.condominio_id
                    AND upper(trim(p.empresa)) = upper(trim(coalesce(m.empresa, m.responsavel))));

UPDATE manutencoes m
SET prestador_id = (SELECT p.id FROM prestadores p
                    WHERE p.condominio_id = m.condominio_id
                      AND upper(trim(p.empresa)) = upper(trim(coalesce(m.empresa, m.responsavel)))
                    ORDER BY p.ordem LIMIT 1)
WHERE trim(coalesce(m.empresa, m.responsavel, '')) <> '' AND m.prestador_id IS NULL;

ALTER TABLE manutencoes DROP COLUMN IF EXISTS empresa;
ALTER TABLE manutencoes DROP COLUMN IF EXISTS responsavel;

CREATE INDEX IF NOT EXISTS ix_manutencoes_prestador ON manutencoes (prestador_id);

-- conferência: manutenções ligadas a um prestador
SELECT m.item, p.empresa, p.pessoa FROM manutencoes m JOIN prestadores p ON p.id = m.prestador_id;

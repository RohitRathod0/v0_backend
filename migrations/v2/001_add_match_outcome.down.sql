-- Overview: 001_add_match_outcome.sql ko reverse karta hai - dono columns drop.
ALTER TABLE `match`
  DROP COLUMN `outcome`,
  DROP COLUMN `outcome_reason`;

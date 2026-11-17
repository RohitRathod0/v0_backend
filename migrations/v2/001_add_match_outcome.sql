-- Overview: Match table mein `outcome` (kaise match khatam hua: regular / walkover ...)
-- aur optional `outcome_reason` add karta hai. DEFAULT 'regular' se saare purane rows
-- automatic backfill ho jaate hain, alag data migration ki zarurat nahi.
ALTER TABLE `match`
  ADD COLUMN `outcome` VARCHAR(20) NOT NULL DEFAULT 'regular',
  ADD COLUMN `outcome_reason` VARCHAR(255) NULL;

# Benchmark

Does correcting one migration make the next one better? The agent learns from human
corrections on two training migrations (SAP and NetSuite exports), then maps migrations it
has never seen. Mode: rules (no AI model). Human corrections are simulated from the known answers.

## Unseen migrations

| | Before learning | After learning |
| --- | --- | --- |
| Mapping accuracy | 91.4% | 100.0% |
| Fields a human must review | 27 | 5 |

| Migration | Same system seen in training? | Before | After |
| --- | --- | --- | --- |
| SAP export #2 | Yes | 87.5% | 100.0% |
| NetSuite export #2 | Yes | 86.7% | 100.0% |
| QuickBooks export | No | 100.0% | 100.0% |

## What the agent learned

From 25 corrections: 22 rules kept, 2 discarded because they didn't help, 1 blocked by the safety check.

| Rule | Decision | Detail |
| --- | --- | --- |
| ORT01 -> BillingCity | kept | accuracy 87.1% -> 93.3%, reviews 22 -> 21 |
| ignore MANDT | discarded (no improvement) | accuracy 93.3% -> 93.3%, reviews 21 -> 21 |
| entityid -> AccountNumber | kept | accuracy 93.3% -> 100.0%, reviews 21 -> 20 |
| ignore subsidiary | discarded (no improvement) | accuracy 100.0% -> 100.0%, reviews 20 -> 20 |
| KTOKD -> AccountNumber | blocked by safety check | AccountNumber must be unique, but the column is only 1.3% unique |
| ZZSTATUS -> IsActive__c | kept | accuracy 100.0% -> 100.0%, reviews 20 -> 19 |
| STRAS -> BillingStreet | kept | accuracy 100.0% -> 100.0%, reviews 19 -> 18 |
| ZZSALESREP -> SalesRep__c | kept | accuracy 100.0% -> 100.0%, reviews 18 -> 17 |
| TELF1 -> Phone | kept | accuracy 100.0% -> 100.0%, reviews 17 -> 16 |
| REGIO -> BillingState | kept | accuracy 100.0% -> 100.0%, reviews 16 -> 15 |
| ZTERM -> PaymentTerms__c | kept | accuracy 100.0% -> 100.0%, reviews 15 -> 14 |
| KUNNR -> AccountNumber | kept | accuracy 100.0% -> 100.0%, reviews 14 -> 13 |
| SMTP_ADDR -> Email__c | kept | accuracy 100.0% -> 100.0%, reviews 13 -> 12 |
| PSTLZ -> BillingPostalCode | kept | accuracy 100.0% -> 100.0%, reviews 12 -> 11 |
| KLIMK -> CreditLimit__c | kept | accuracy 100.0% -> 100.0%, reviews 11 -> 10 |
| ERDAT -> CustomerSince__c | kept | accuracy 100.0% -> 100.0%, reviews 10 -> 9 |
| billstate -> BillingState | kept | accuracy 100.0% -> 100.0%, reviews 9 -> 8 |
| billaddr1 -> BillingStreet | kept | accuracy 100.0% -> 100.0%, reviews 8 -> 7 |
| creditlimit -> CreditLimit__c | kept | accuracy 100.0% -> 100.0%, reviews 7 -> 6 |
| datecreated -> CustomerSince__c | kept | accuracy 100.0% -> 100.0%, reviews 6 -> 5 |
| billzip -> BillingPostalCode | kept | accuracy 100.0% -> 100.0%, reviews 5 -> 4 |
| companyname -> Name | kept | accuracy 100.0% -> 100.0%, reviews 4 -> 3 |
| billcity -> BillingCity | kept | accuracy 100.0% -> 100.0%, reviews 3 -> 2 |
| salesrep -> SalesRep__c | kept | accuracy 100.0% -> 100.0%, reviews 2 -> 1 |
| isactive -> IsActive__c | kept | accuracy 100.0% -> 100.0%, reviews 1 -> 0 |

## Limits of this benchmark

- The data is synthetic and the human reviewer is simulated from the known answers.
- Learned rules are exact column names. They carry over to later exports from the same
  system (SAP after SAP), which is how real migrations run, in waves. They do not help on
  a new system: QuickBooks shows no gain, and no harm.
- One wrong correction was added on purpose to test the safety check.
- This run uses rule-based matching. AI matching is supported but not benchmarked here.

Run it yourself: `python -m migration_pilot.benchmark`

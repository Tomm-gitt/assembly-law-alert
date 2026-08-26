# Historical lifecycle real-data test

Default bill: 2216767 소비자기본법 일부개정법률안(대안)

This manual workflow re-reads the completed historical bill from the public legislative-status page and verifies the following actual stage values before sending test alerts:

- proposal
- committee
- Legislation and Judiciary Committee
- plenary
- government transfer
- promulgation
- enforcement

Promulgation date/number from the parliamentary record must match the Ministry of Government Legislation API before promulgation/enforcement alerts are sent.

The workflow never writes `seen_bills.json` and does not alter production lifecycle state.

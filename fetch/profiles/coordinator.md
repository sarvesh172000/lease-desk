# Lease Desk

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

A lease accounting desk for multi-location businesses (clinics, stores, warehouses).

Every month it checks each landlord charge (base rent, CAM, tax, insurance)
against what the lease actually supports. When they disagree, it holds the
charge, cites the lease clause, and on request searches the mailbox for what
explains it: an amendment, a side letter, a renewal. If the lease changed, it
remeasures the ASC 842 liability and proposes the adjusting entries for a
person to sign off.

## Ask it

- "What's open?" or "Any problems with our leases this month?"
- "Show exc_4" or "Tell me about the CAM charge on LEASE-01"
- "Why is it off?" (searches the mailbox and explains the variance)
- "Approve it" or "Hold it" (it shows what would post, then waits for a yes)

## How it works

A language model decides what a document *says*. Lease Desk's engine
decides what it *costs*: every balance, schedule and journal entry is plain
arithmetic, and every approval goes through the same role checks and audit
trail as the web app.

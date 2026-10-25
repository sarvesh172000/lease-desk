# Northbay Lease Desk

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Lease accounting for Northbay PT, a multi-clinic physical therapy group, inside ASI:One.

Every month Lease Desk checks each landlord charge (base rent, CAM, tax,
insurance) against what the lease supports. When they disagree it holds the
charge and cites the clause. From this chat you can see what needs you, review
a held charge with its sources and trust explanation, have the mailbox searched
for what explains it, answer questions and approve — **as yourself**, under your
own Lease Desk role and region.

## Start

1. In the Lease Desk web app: **your name (top right) → Connect chat** gives a one-time code.
2. Send `pair XXXX-XXXX` here. The code works once, for ten minutes.

## Ask it

- `what needs me this week?`
- `review 42` — the held charge as a card: billed, what the lease supports, sources, why
- `investigate 42` or `why is 42 off?` — the investigation agent searches the mailbox
- `what is Clinic 03's escalation and where does it say so?` — the rulebook agent, with page and quote
- `answer 42 yes, suite 110 is ours` · `uphold 42 the lease caps CAM at 5%` · `hold 42 waiting on the landlord`

Plain language works too: ASI:One's model reads what the fixed commands don't
catch. It can look things up for you, but it never takes an action: it shows
the exact command and you send it (or press the button).

## The team behind this chat

Four agents: this front desk, a **rulebook** agent (lease terms with citations),
an **investigation** agent (mailbox search and remeasurement) and an
**approvals** agent (your queue and your actions). The specialists answer this
front desk only. Every action goes through Lease Desk's role checks and
hash-chained audit trail, and a refusal is recorded too.

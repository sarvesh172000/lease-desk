# Demo script: Lease Desk (3 minutes)

Projector at 1280×800, dark theme, live API on a fresh desk
(`frontend/scripts/reset-desk.sh`, then `frontend/scripts/disputes-sweep.sh`
after the uphold if the backend's dispute sweep isn't wired yet). The path is
the one timed in `frontend/docs/REHEARSAL.md`. Backup: the same path in
fixtures mode with the network off (`NEXT_PUBLIC_USE_FIXTURES=1`).

Say the **bold** lines; the rest is what to click.

---

## 0:00: The hook (/welcome)

> **"$443,255.70 was missing from this company's balance sheet, and nobody
> knew."**

> "A lease was amended nine months ago. The landlord billed the new rent, and
> the books kept running the old schedule. Lease Desk fills the lease
> accountant's seat: it reads every lease, checks every bill against what the
> lease actually says, and holds only the money that's wrong."

Click **Open the desk**.

## 0:20: Sign in as the controller (Today)

Click **Priya Raghunathan, Controller**.

> "This is Priya's morning. July's bills are in. One item needs her first."

Point at the hero card: Base rent · July 2026 · Daly City, Suite 210, billed
$17,400.00 against the $19,626.65 the lease supports.

## 0:35: The money screen

Click **Open**.

> "On the left, the landlord's invoice with the billed line boxed. On the
> right, the lease clause the schedule comes from. Same page, real PDFs, every
> box placed by the extraction."

Click **Run investigation**.

> "Now the agent asks *why*. It searches the mailbox…" (3D stack fans out)
> "…finds an executed amendment from the landlord, trust rank one, that cut
> the rent to $17,400 and extended the lease three years…" (email lands)
> "…and the accounting engine remeasures the lease under ASC 842: liability
> from $559,665.35 to $1,002,921.05. That's the $443,255.70." (count-up)
> "Four journal entries, balanced, proposed and **not posted**: a person
> approves."

Click **Why?**, show the answer and the audit rows behind it, then close it.

> "Every answer cites the rows behind it."

## 1:25: January: what it caught

Switch persona to **Dana Whitfield, Regional manager** (persona menu).
Open the **$4,820.00 Base rent** item for Serramonte Hand Therapy.

> "January: 12 charges checked, 5 held for $25,736.36. This one is rent for
> Suite 118. The lease is for Suite 115. Nothing in it is supported."

Click **Uphold hold**, then confirm.

> "Dana upholds it. Nothing is paid; the $4,820 stays held, and the agent
> drafts the dispute letter to the landlord."

Open **Disputes**, then **DSP-000006**.

## 2:00: Trust (Audit trail)

Open **Audit trail**.

> "Every action, by people and agents, is sealed into a hash chain. These red
> blocks are attempts the system refused: the agent trying to post to the
> ledger, which Postgres itself denied; a manager trying to approve an item she
> answered a question on, which separation of duties denied. They stay in the
> chain, and the chain still verifies."

Click a red row to show the `prev_hash → hash` link.

## 2:25: The rest of the desk (fast)

- **Month run:** "the whole month as a pipeline; the stage waiting on a person
  glows."
- **Leases:** "the portfolio as a runway from today to each lease's end."
- **LEASE-01:** "and here is Claude's reading of the lease: 13 terms, every
  one cited to the box on the page it came from."

## 2:45: Close

> "It reads, checks and proposes. People approve. Only the gateway posts.
> Every step is on record. Built with Claude for reading leases and the
> agents, Fetch.ai's ASI:One as the chat front door, SpacetimeDB for the live
> mirror, on Postgres with four database roles and a hash-chained audit trail."

---

## If something goes wrong

- **API down:** the app shows a full-width "API unreachable" banner, never
  silent fixtures. Switch to the fixtures build and say so.
- **Investigation already ran:** the result shows at once; press **Replay**.
- **Disputes empty:** run `frontend/scripts/disputes-sweep.sh`, or skip to
  the audit trail.

## Known gaps (don't demo these until the backend lands them)

- Approving the four remeasurement entries from the money screen (investigation
  → approvable item) is not wired yet; say "proposed, for the controller to
  approve" and move on.
- The dispute sweep after an uphold and the obligations job are run by script,
  not by the monthly run, until backend task K1 lands.

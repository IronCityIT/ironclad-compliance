# Examples

## Sample evidence (`evidence/`)

Synthetic. Iron City's own internal control descriptions, written to exercise
the engine end to end without a client's documents anywhere near a repository.

Used by the `End-to-end` CI job and by anyone who wants to see the product work
before they have evidence of their own:

```sh
python -m ironclad.cli assess --client "icit-internal" --framework soc2 \
  --evidence-dir examples/evidence/ --group deep --out out/
```

Nothing here is a real control assertion about Iron City IT Advisors. It is
plausible text with the shape and vocabulary of real evidence, which is what the
matcher needs and all it needs.

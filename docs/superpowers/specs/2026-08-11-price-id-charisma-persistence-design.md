# Price ID Charisma persistence

## Goal

Remember Charisma across Price ID visits, and clear that memory when Checklist Reset is confirmed.

## Design

- Store a single integer under `nethack-tools:price-id:cha`.
- On Price ID load, if localStorage is available and the value is an integer in 3–25, use it for every observation; otherwise default to 11.
- Changing any observation’s Charisma field updates every observation’s Charisma (and hints), then writes the key.
- New observations are seeded from the remembered value.
- Sell direction still ignores Charisma for pricing math; the field stays synced and disabled as today.
- Storage failures are silent (same try/catch pattern as Checklist); no “saved” chrome on Price ID.
- Checklist’s confirmed Reset removes both `nethack-tools:checklist:v1` and `nethack-tools:price-id:cha`.

## Scope

No other Price ID settings are persisted. Checklist import/export does not include Charisma.

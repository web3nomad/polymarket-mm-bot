# ⚠️ DEPRECATED — DO NOT USE

This project is deprecated and should not be used.

## Why deprecated

- Architecture was designed before understanding Polymarket's actual trading model
- Not crypto-native (doesn't properly use wallet signing)
- Strategies were theoretical, never validated with real data
- Missing proper CLOB integration

## New approach

Starting fresh with:
1. **Wallet-first**: Use existing EVM wallet for signing
2. **py-clob-client**: Official Python library for CLOB interaction
3. **Clean strategy design**: Build from ground up based on actual market behavior

See: `polymarket-setup.md` in workspace for new plan.

---

*Archived: 2026-05-04*

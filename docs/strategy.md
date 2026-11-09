# Pricing strategy

The rules are pure functions in
[`domain/pricing.py`](../services/engine/src/autolister_engine/domain/pricing.py):
no network, no clock, no state. Their parameters live in
[`config/strategy.yaml`](../config/strategy.yaml), which is reviewed like code.
The emergency stop is the one rule that lives elsewhere, in
[`autolister_core.guard`](../libs/core/src/autolister_core/guard.py), because
the signer enforces it too.

## The objective

LooksRare's listing-rewards programme paid sellers whose listings sat near a
collection's floor price. We hold NFT positions for investors and earn those
rewards on them. The positions are the capital, so the rewards must be earned
**without selling them**. That means steering between two risks:

- **Too close to the floor**, and a market move or a floor sweep buys the NFT,
  often for less than it is worth.
- **Too far from the floor** (more than 10% above it), and the listing earns
  nothing.

The floor moves constantly, on several marketplaces, while dozens of other bots
compete for the same band.

## Definitions

| Term | Meaning |
|---|---|
| **Global floor** | The cheapest price across LooksRare and OpenSea |
| **LooksRare floor** | The cheapest ask on LooksRare |
| **Rewards band** | From the global floor up to 10% above it |
| **Cheaper competitors** | Asks from *other* wallets priced below ours. Our own wallets are left out, so investor accounts never price against each other |
| **Emergency floor** | The 21st cheapest ask, counting every ask, our own included: at least 20 asks always stand in front of us |

Asks under 0.1 ETH are ignored throughout. They are troll listings, and they
would otherwise drag every one of these numbers down.

## Choosing a price

```
premium = 7%
price   = global floor × (1 + premium)
while price is not more than 3% above the LooksRare floor:   # the global floor may be on OpenSea
    premium = premium + 0.3%
    price   = global floor × (1 + premium)
if fewer than 30 competitors are cheaper than price, or premium > 10%:
    price = the 31st cheapest competitor's price               # exactly 30 in front
```

The fallback applies when the order book is too thin for the premium to be safe,
or when clearing the LooksRare floor would push the price out of the rewards
band.

## Deciding what to do

Every cycle, for every account, the engine finds the account's live listing in
the order book and checks, in order:

| Condition | Action |
|---|---|
| No live listing | **List** at the chosen price |
| Less than 3% above the global floor | **Cancel and relist** |
| Less than 1.5% above the LooksRare floor | **Cancel and relist** |
| Fewer than 25 cheaper competitors | **Cancel and relist** |
| More than 10% above the global floor | **Lower** |
| Otherwise | **Hold**, and renew if the listing expires within 65 minutes |

- **Cancel and relist** sends one on-chain transaction that invalidates every
  open order for the wallet, the only action that costs gas. It then waits until
  ten minutes have passed since the collection's last sale, because the floor is
  probably still moving, and lists at a freshly chosen price.
- **Lower** waits 60 seconds, or 120 after the floor has dropped by more than
  5%, so that competing bots reprice first. It then lists below the current
  price. No cancellation is needed: the cheaper ask fills first. If the book
  offers no safe lower price, it holds.
- **Renewal** never raises the price, because LooksRare rejects a second,
  higher-priced ask for the same token. If the freshly chosen price is higher,
  the renewal goes a hair (0.0000001 ETH) under the current one.

## Safety rails

1. **The emergency stop, enforced twice.** The engine never publishes a price
   below the emergency floor, and the signer recomputes the emergency floor from
   its own read of the order book and refuses anything below it.
2. **The rewards gate.** The engine pauses while the collection is not among the
   top five listing-rewards collections.
3. **The post-sale cooldown.** No relisting within ten minutes of a sale.

The property tests in
[`tests/test_properties.py`](../services/engine/tests/test_properties.py) check
these rules against generated order books, a thousand per property in CI: no
proposal ever undercuts the emergency floor, any listing the engine holds is
both safe and inside the rewards band, and no renewal raises a price.

## Worked example

The global floor is 1.600 ETH, on OpenSea; the LooksRare floor is 1.630 ETH.

1. Start at +7%: 1.600 × 1.07 = **1.712 ETH**. That is 5.0% above the LooksRare
   floor, comfortably more than 3%, so no stepping is needed.
2. 64 competing asks are cheaper than 1.712 ETH, more than 30, so 1.712 ETH
   stands.
3. The 21st cheapest ask is 1.651 ETH, so 1.712 ETH clears the emergency floor.
   The engine publishes "list at 1.712 ETH", and the signer, having checked the
   order book again, lists every token the wallet holds.
4. The market rallies and the global floor rises to 1.680 ETH. The listing is now
   only 1.9% above it, so the engine cancels, waits out the cooldown, and relists
   at 1.680 × 1.07 = 1.798 ETH.

## Changing the strategy

Edit [`config/strategy.yaml`](../config/strategy.yaml) in a pull request. The
engine validates it at start-up, including consistency checks such as the
target premium sitting inside the rewards band. Ship the change with trading
disabled first and read the decisions it logs, as described in the
[runbook](runbook.md#change-the-strategy).

## Parameters

| Parameter | Value | Meaning |
|---|---|---|
| `target_premium_pct` | 7.0 | Preferred premium over the global floor |
| `premium_step_pct` | 0.3 | Step used to clear the LooksRare floor |
| `min_premium_over_looksrare_pct` | 3.0 | Minimum clearance over the LooksRare floor |
| `rewards_ceiling_pct` | 10.0 | Top of the rewards band |
| `cancel_below_global_pct` | 3.0 | Cancel when closer than this to the global floor |
| `cancel_below_looksrare_pct` | 1.5 | Cancel when closer than this to the LooksRare floor |
| `cancel_rank` | 25 | Cancel with fewer cheaper competitors than this |
| `rank_buffer` | 5 | Extra depth a new listing keeps in front (so 30 in all) |
| `emergency_stop_rank` | 20 | Asks that must always stand in front |
| `sharp_drop_ratio` | 0.95 | A floor below 95% of the previous one is a sharp drop |
| `settle_delay_s` | 60 | Wait before lowering |
| `sharp_drop_extra_delay_s` | 60 | Extra wait after a sharp drop |
| `post_sale_cooldown_min` | 10 | No relisting within this long after a sale |
| `rewards_top_n` | 5 | The collection must be among the top N rewards collections |
| `listing_duration_days` | 3 | Lifetime of each ask |
| `renew_before_expiry_min` | 65 | Renewal window before expiry |
| `listings_to_scan` | 200 | Order-book depth read each cycle |
| `min_price_to_scan_wei` | 0.1 ETH | Asks below this are ignored as troll listings |

The signer's side of the emergency stop (`emergency_stop_rank` and the 0.1 ETH
threshold) is configured separately, in its own settings, so that no strategy
change can loosen it. A test fails the build if the two ever disagree.

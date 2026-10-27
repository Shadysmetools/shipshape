# License options (decided: MIT)

**Decision, 27 Oct 2026:** the owner chose the **MIT License** (see [LICENSE](LICENSE)). The comparison below is kept for the record.

Before this decision ShipShape had **no license**: `plugin.json` said `"license": "UNLICENSED"` and the repo had no `LICENSE` file. Until the owner picks one, the default copyright rules apply: people can read the public code, but they get no right to use, copy, change or resell it. **The owner decides.** This page only compares the options for a product that is sold. It is not legal advice, so have a lawyer check the final choice.

## The question
ShipShape is meant to be sold to clients (see [docs/FOR-BUYERS.md](docs/FOR-BUYERS.md)), and the repo is public. The license decides whether a buyer, or anyone who finds the repo, can use it without paying, change it, or resell it.

## Comparison

| | Proprietary / commercial | BSL 1.1 (Business Source License) | MIT | Apache-2.0 |
|---|---|---|---|---|
| Open source? | No | No (source-available); becomes open source on the change date | Yes | Yes |
| Can a stranger use it for free? | No; only with a paid license | Yes, within the "Additional Use Grant" (e.g. non-production, or below a size limit) | Yes, for anything | Yes, for anything |
| Can a competitor resell or host it? | No | Not in the restricted use, until the change date | Yes | Yes |
| Patent grant | As written in the contract | None stated | None stated | Explicit, with patent retaliation |
| What the owner must write | A EULA or license agreement (custom, needs a lawyer) | The standard BSL text plus three parameters: the use grant, the change date (at most 4 years), and the change license (often Apache-2.0) | Nothing, standard text | Nothing, standard text (+ a `NOTICE` file if wanted) |
| Fits a public repo? | Awkward: the code is visible but not usable, so the repo would usually go private | Yes, that's what it's designed for | Yes | Yes |
| Contributor PRs | Need a CLA or assignment | Usually need a CLA | Easy: inbound = outbound | Easy: inbound = outbound (section 5) |
| Revenue model | License fees | License fees for the restricted use; support | Support, setup, managed service, a hosted tier | Support, setup, managed service, a hosted tier |
| Examples | Most commercial software | MariaDB MaxScale, HashiCorp Terraform (since 2023) | many CLIs and libraries | Kubernetes, many company-backed projects |

## How the options fit ShipShape
- **Sell the code itself** (buyers pay to use it): proprietary, or BSL to keep the repo public. With proprietary, consider making the repo private, since a public repo under a closed license confuses buyers and contributors.
- **Sell setup, support and the Managed tier** (the code is free): MIT or Apache-2.0. Apache-2.0 adds a patent grant and a clear contribution clause. MIT is the shortest.
- **Mixed**: an open core under MIT/Apache, with paid extras (managed scheduling, templates, support) kept in a separate private repo.

## After the decision
1. Add the `LICENSE` file (and `NOTICE` for Apache-2.0).
2. Set `license` in `.claude-plugin/plugin.json` to the SPDX id (`MIT`, `Apache-2.0`, `BUSL-1.1`) or keep `UNLICENSED` for proprietary.
3. Update the README's last line and `CONTRIBUTING.md` (add a CLA if proprietary or BSL).
4. Fill in the tier table in `docs/FOR-BUYERS.md`.

# Test plan: <feature or release>

- **Goal:** <one sentence a user would say, e.g. "a new customer can sign up and reach checkout in English and Arabic">
- **Build / URL under test:** <staging URL or local> (allowed hosts: <list>)
- **Owner of decisions:** <name of the role, not a person's email> · **Approver for production:** <role>
- **Test data:** <test accounts, fake cards, example.com emails>. Never real customers, never real payments.
- **Out of scope:** <what is deliberately not tested, and why>
- **Environment checks before grading:** account language/preferences, feature flags, cached sessions, leftover test data, build version.

## Cases
One row per check. Every case has an expected result written BEFORE the run, and evidence after it.

| ID | Area | Steps (as a user) | Expected result | Lang | Evidence | Result |
|---|---|---|---|---|---|---|
| TC-01 | Sign-up | Open /signup, submit empty | "Please enter your name." shows, nothing is created | EN | video 00:05 | |
| TC-02 | Sign-up | Fill test user, submit | Welcome page greets the test user | EN | video 00:15 | |
| TC-03 | Payment | Click "Pay now" | Run STOPS (never-pay rule); a human checks the payment page | EN | video end | BLOCKED by design |

Multi-item issues: grade every item, or list the item as NOT CHECKED. Never grade a half-checked issue as a pass.

## Regression list (re-run on every round)
- Cases that failed before and pass now (from `qa_history.py`).
- Flaky cases (two passes disagreed) until they are stable twice in a row.

## Result line
`N pass / M fail / K flaky / B blocked / X not checked (T total)`, with the report link. Never "all green".

# launch: prepare a dry test for approval

## Parameters

| parameter | required | description |
| offer | yes | Product, service, or idea to test |
| audience | no | Target customer segment |
| platform | no | Instagram, TikTok, X, Google Search, or mixed |
| budget_jpy | no | Total budget cap in JPY |
| duration_days | no | Test duration in days |

## Procedure

1. Restate the test hypothesis.
2. Select or infer one target audience.
3. Select one primary platform unless the user explicitly asks for multiple. Default to Instagram for beauty/hairstylist/local visual-service tests.
4. Draft the funnel even if the user did not ask for it. Default to landing page + lightweight signup form + thank-you message.
   - If a landing page, signup form, or public URL is required, check/invoke the `build` skill before implementation and return here after the URL is ready.
5. Draft 3-5 ad variants with hooks, copy, CTA, and creative direction.
6. Add tracking: UTM naming, source labels, and metrics table.
7. Set budget, duration, success criteria, and kill criteria.
8. Treat launch preparation as end-to-end by default. Follow `references/ad-account-setup.md` to prepare the ad account, billing readiness, and campaign/ad draft as far as possible unless the user explicitly wants strategy-only output.
9. End with an approval checklist.

## Hard Stop

Stop before any action that spends money, publishes ads, connects payment methods, or changes live campaign settings. Ask for explicit approval before live spend.

For payment methods, do not collect full card numbers or CVV in chat/files. Navigate to the official payment screen and ask the human to enter sensitive details directly.

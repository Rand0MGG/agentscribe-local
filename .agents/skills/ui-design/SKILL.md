---
name: ui-design
description: Design, implement, refine, or critique web, mobile, and desktop interfaces. Use for requested UI/UX work, layouts, design systems, visual polish, and interface audits. Follow the existing product and platform; Uizze references are optional when they answer a concrete design question.
license: Apache-2.0
metadata:
  uizze-version: uizze-design-v13
  design-stack-version: 4.4.0
---

# Uizze UI Design

## Work from the product

Inspect the requested surface and its relevant components, tokens, assets, and existing product/design documentation. Read what the task needs and reuse context already inspected unless it may have changed. In AgentScribe, follow [UI_DESIGN.md](../../../docs/UI_DESIGN.md) and the existing PySide6/Qt implementation. The user's request and project constraints outrank this skill. Preserve an established visual system for extensions and polish; replace it only for an authorized redesign. Missing PRODUCT.md or DESIGN.md does not block work.

Identify the audience, primary task, important states, and intended result. Ask only about missing choices that would materially change the work. A precise request is enough to proceed; do not turn a small fix into a discovery workshop.

## Select the workflow

Load the playbook for the requested action, plus the platform and craft guidance needed to execute it:

- New interface or major redesign: [new-work](reference/new-work.md)
- Product or dashboard work: [operate](reference/operate.md)
- Refinement and polish: [polish](reference/polish.md)
- Simplification: [distill](reference/distill.md)
- Explicit audit: [audit](reference/audit.md), read-only unless fixes were requested
- Native iOS: [iOS](reference/ios.md), alongside the action's playbook
- Explicit `/overdrive`, “Uizze Overdrive”, or a request for exceptional interaction work: [Overdrive](reference/overdrive.md)

For implementation, use [craft](reference/craft.md) after the direction is settled. Load only relevant files; multiple complementary playbooks are allowed. Overdrive is opt-in, not the default for ordinary UI work. It requires a chosen direction before implementation.

“Use Uizze Overdrive on this screen” works through this router; a native slash command depends on the host. These are self-contained Markdown playbooks, not an installer, background service, or executable engine.

## Optional Uizze evidence

Read [the reference policy](references/uizze-reference-policy.md) before using `find_ui_references` or `find_ui_materials`. Inspect relevant visual evidence when it can inform the layout, state, interaction, or assets. Use the host's available tools, not invented calls or connections. Paid retrieval is optional; missing access does not block local design work.

Distinguish an exact reference, a related example, no match, and a service error. Briefly disclose a limitation that affected the result. Never claim an image was inspected or a state was found without evidence.

## Finish

Build the requested scope and exercise its important states. Render and inspect the real result at representative sizes and input modes supported by the actual product, including the user's reported failing size. For desktop Qt, check the relevant window sizes and display scaling; mobile or touch checks apply only when supported. Compare it with the chosen direction or supplied reference, not just with the absence of runtime errors.

Fix material problems in a batch, then render and inspect again. Stop once the requested result is verified; do not keep inventing work. Continue with another viable approach within the authorized scope when a check fails. If the remaining work requires a missing decision, permission, or unavailable capability, explain the limitation and request only the input needed to proceed; do not claim a pass. When rendering is unavailable, distinguish code checks from visual verification.

Keep the handoff concise: what changed, what was actually tested, and any remaining limitation. A skill does not authorize publishing, purchases, new dependencies, account changes, or destructive actions.

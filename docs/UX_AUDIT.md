# REMEM PWA - UX/UI Audit (2026-11-08)

Scope: the student PWA at 375 x 812, dark and light scheme, local build with a seeded test account (5 concepts from the Newton's Laws topic, 3 answered). Routes: Today, Notes (topic picker), Practice (question + feedback), Retention curve, Concepts, Me. Method: DOM probes (contrast, tap targets, naming, overflow, Hick/Fitts, design-system counts, Gestalt/emphasis, LTR/English, focus) + screenshots + a reading pass + a check of what the API returns. Not covered: Login/Consent screens (read only), the Streamlit dashboard, real-phone testing, screen-reader testing, the offline queue.

## Summary
8 findings: 0 critical, 5 major, 3 notes. All 8 are fixed; 06 is only partly fixed (focus ring done, bold share left). What already works is listed at the end.

## Findings

**01 - Major - Practice feedback.** Wrong/right answers are explained only by colour, and the notes sentence behind the question is never shown.
A wrong answer showed the headline "Not quite" and then the body "Not quite. Next review in about 2.7 day(s)." The correct option was marked only by a green tint (SC 1.4.1 Use of Colour). The API already stores `source_span` for every concept, but `/respond` did not return it, so the learner never saw why the answer was right.
EVIDENCE: `Not quite` / `Not quite. Next review in about 2.7 day(s).`; DB column `concepts.source_span` populated, no UI use.
FIX (done): options are prefixed "✓ Correct answer:" / "✗ Your answer:"; feedback shows `From your notes: "<source sentence>"`; the message no longer repeats the headline.

**02 - Major - Retention curve.** Chart labels render at 5.9 px on a phone.
SVG viewBox is 640 wide, shown at 343 px (scale 0.536) with an 11-unit font.
EVIDENCE: `fontSize 11 x scale 0.536 = 5.9px` for all 12 labels.
FIX (done): font 22 units and wider margins, giving 11.8 px effective; labels no longer collide with the plot.

**03 - Major - Hedged plurals in every status sentence.** "day(s)", "session(s)", "answer(s)".
EVIDENCE: `You have practised it in 1 session(s); your last review was 0.0 day(s) ago.` (Today, curve), `Mastery 20% - 1 answer(s)` (Concepts), `Next review in about 2.7 day(s).` (feedback). English plural rules need only one/other; "0.0 day(s) ago" also reads as machine output.
FIX (done): `plural()` helpers in backend and app; "You just practised this." replaces "0.0 days ago"; "3.0 days" prints as "3 days". Test added.

**04 - Major - Today screen.** No primary action, and one 30-word jargon paragraph repeated on every card.
First screen: 5 interactive elements, none a call to action; each "Coming up" card repeated "is still fresh - estimated recall is 100% (target 85%) ... tend to retain this for about 3 day(s)". 100% recall right after one answer is overconfident, and "target 85%" is internal vocabulary.
EVIDENCE: three cards carry the same sentence; `hickIndexFirstScreen 2.58`, `primaryActions: []`.
FIX (done): summary line ("1 new concept to try"), a full-width primary button ("Start reviewing" / "Take your first quiz"), "You're all caught up" state, one-line card text. The long explanation stays on the curve screen with softer wording.

**05 - Major - Navigation at the top of a phone-first app.** The four tabs sit in the header, the farthest place from the thumb, and are 36 px tall.
EVIDENCE: Fitts distance 703-720 px from the thumb origin for every tab (index 4.35-4.4); height 36 px (below the 44 px recommendation; SC 2.5.8 minimum of 24 px is met).
FIX (done): fixed bottom tab bar, 56 px targets, safe-area padding, `aria-current="page"`. Brand link made a 44 px target.

**06 - Note - Focus and emphasis.** Focus ring is the browser default (0.8 px; contrast 6.96:1, passes SC 1.4.11 but reads weak); 78% of on-screen text is semibold or heavier.
EVIDENCE: `outlineWidth 0.8px`, `proportionBold 78%`.
FIX (done for focus): 3 px brand-colour `:focus-visible` outline. Bold share left as is; the cards use bold for names only, so the probe overstates it - recheck on a real phone.

**07 - Note - Practice has no context.** The screen was titled only "Practice"; the learner could not tell which concept a question belonged to.
FIX (done): concept name shown above the title; `/question/next` returns it.

**08 - Note - Curve x-axis.** The curve always spans 30 days, so the first few days where the scheduling decision happens are squeezed. FIX (done, follow-up commit): the axis now spans about 3x the next-review interval (minimum 8 days, whole multiples of 4 days, always showing the 'now' dot), so a concept reviewed in 1 day shows an 8-day plot instead of 30.

## What works (measured)
- Contrast: 26 text elements measured on Today, 0 failures; 0 failures on Notes, Concepts and Curve in light scheme too.
- No horizontal overflow at 375 px on any route; one `h1` per screen with no skipped heading levels; skip link, `lang="en"`, landmarks present; no unnamed controls.
- Design-system consistency: 5 font sizes, 1 font family, 3 border radii, 4 text colours.
- First paint 52 ms, DOM ready 41 ms locally; no long tasks.
- Topic cards have plain labels and a suggested topic first.

## Where to start (impact / effort)
Done in this commit: 03, 05, 01, 04, 02, 07, 06 (focus). Remaining: a real-phone pass (screen reader, offline queue, install to home screen).

## Round 2 - visual redesign (2026-11-08)
Goal: remove generic template-style patterns and raise perceived speed. Re-measured with the same probes at 375 px (light and dark).

Removed: emoji topic icons; uppercase tracked section labels; the grey "pill" badge on every row; identical bordered cards for every list; teal-on-near-black palette; clickable `div` cards (rows are now real links); hidden-chrome "Role:" line.
Added: one signature element, the **freshness bar** (a meter of how much of a concept is still remembered; green when fresh, amber when below target) on Today and Concepts; one loud block per screen (the "next up" panel on Today); lettered answer keys with a text label for the result; skeleton placeholders instead of "Loading..."; the last Today list is drawn instantly from the previous visit and refreshed underneath (no second render when nothing changed); bar animation plays once and is disabled for `prefers-reduced-motion`; system fonts only (nothing to download); smooth scroll of feedback into view after answering.

Measured after: contrast failures 0 on 6 routes in dark and 0 in light; tap targets under 44 px: 0 (the 18 px "Report a bad question" link was found and fixed); one primary action on Today; Hick index 3.58 (first screen); headline-to-body ratio 2.13; 3 border radii; bold share 50% (was 78%); DOM ready 178 ms locally.

## Round 3 - final pass (2026-11-09)
Method: an automated design-rule checker run over `webapp/`, the platform design guidelines for tab bars, accessibility, typography and layout, and the measured probes from rounds 1 and 2 at 375 px in light and dark. This is a web PWA, so platform conventions were applied as principles, not as native components.

Found and fixed:
1. **Side stripe on callouts.** The "From your notes" quote used a 3 px coloured left border. Now a tinted block with no stripe.
2. **Labels above headings.** The subject label over each topic title and the concept name over the question are removed. The suggested topic is the one prominent block under the heading "Suggested for you"; the other topics are plain rows. The quiz screen has a back row ("Today") with the concept name on the right.
3. **Text glyphs standing in for icons.** The check, cross and back chevron are drawn SVGs in one stroke style; the tab bar has four drawn icons.
4. **Tab bar.** Icon plus single-word label, and a badge for the number of concepts due on Today.
5. **Text scaling.** Body text starts at 17 px using the system body size (Dynamic Type on iOS Safari) and every size is in rem. Checked at 100%, 150% and 200% text size: no horizontal overflow on Today, Notes or Quiz.
6. **Type scale.** 10 distinct sizes reduced to 7 steps (0.75, 0.8, 0.9, 1, 1.25, 1.5, 2 rem).
7. **Keyboard and screen-reader orientation.** A route change moves focus to the new heading and updates the page title (SC 2.4.2); `main` is no longer an `aria-live` region.
8. **Browser surfaces.** `color-scheme` for native controls and scrollbars, themed selection/caret/scrollbar colours, `theme-color` for light and dark, increased-contrast support, landscape safe-area padding, balanced heading wrapping, hover states for pointer devices.
9. **Login.** Show/Hide password button.
10. **States.** Buttons show `aria-busy` while a quiz is being made; reduced motion keeps the bars filled and drops the movement.

Measured after: contrast failures 0 on 6 screens in light and 0 in dark; tap targets under 44 px: 0; no horizontal overflow; one h1 per screen; focus ring 2.4 px at 7.08:1; Today has one primary action; the design-rule checker reports 0 findings.

Not done, on purpose: title-case buttons (the app consistently uses sentence case), a swipe-back gesture, pull-to-refresh. Not yet checked: a screen-reader pass and offline answers on a real phone.

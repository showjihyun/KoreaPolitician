# r/politicalscience 게시글 초안

**Title**

> Open-source relational map of South Korea's 22nd National Assembly — automated extraction of inter-legislator conflict from news text. Looking for methodological critique.

**Body**

I've been building a public dashboard that treats the 296 sitting members of South Korea's National Assembly as a graph, and infers edges between them from Korean-language news coverage rather than from roll-call votes. It's live and open source, and I'd genuinely like this sub to poke holes in the method.

**Live board:** https://korea-politician.vercel.app
**Source:** https://github.com/showjihyun/KoreaPolitician

---

**What the graph contains right now**

- 296 Member nodes, 8 Party nodes
- 296 party-affiliation edges
- 39 directed sentiment edges between legislators (36 conflict, 3 alliance)
- 368 co-mention edges

**How edges are derived**

A nightly job pulls articles from the politics, economy, and society sections of a major Korean news portal, extracts the body text, and resolves which legislators are named. Name resolution is the part I spent the most time on: Korean given names are short and frequently appear inside unrelated words, so I use longest-match masking plus a boundary check rather than substring matching. A directed sentiment edge is written when the text supports one legislator taking a position against or alongside another.

**Two different time bases, deliberately**

This is the design decision I'd most like feedback on. The board reports two things on different windows, and says so in the UI:

- **Relations are cumulative.** A conflict, once observed, is never dropped. The claim "these two have clashed" doesn't expire.
- **Attention is a 7-day rolling window.** News mentions plus log-normalized YouTube view counts. This one is meant to answer "who is being talked about now," so old coverage falls out.

Mixing a cumulative measure and a rolling one in the same view is a real risk of misreading, so each panel carries its window as a visible label and an explanatory tooltip. I'm not sure that's sufficient.

**Attention scoring**

News and video engagement aren't on comparable scales — raw view counts run into the millions while a news mention is one event. YouTube views are log-compressed (1k views → 0, 10M → 100) before being added to the news component, and an article naming many legislators contributes 1/sqrt(n) to each rather than a full count, so roundup pieces don't inflate everyone equally.

---

**Where I know it's weak**

- **The dataset is new.** Continuous collection started 2026-08-30, so the "cumulative" relation set is currently days old, not years. The architecture is the deliverable right now; the longitudinal data isn't there yet.
- **No inter-coder reliability.** Sentiment edges come from automated extraction over Korean text with no human-validated sample. I have no precision/recall numbers, and that's the biggest gap.
- **Source concentration.** One news portal, three sections. Outlet-level slant is not controlled for.
- **Coverage bias is baked in.** An attention score derived from media volume measures coverage, not influence. A backbench legislator doing consequential committee work registers as nothing.
- **Conflict is over-represented relative to alliance** (36 vs 3). I suspect this is real — adversarial framing is more newsworthy — but it could equally be an artifact of the extraction favoring negative markers.

**What I'd like input on**

1. For inferring legislator-to-legislator relations, is media co-occurrence defensible at all as a complement to vote-based measures like W-NOMINATE, or is the coverage bias fatal?
2. What's the minimum validation you'd want to see before the sentiment edges should be treated as data rather than as illustration? A hand-coded sample of n=200 with a reported kappa?
3. Has anyone dealt well with the cumulative-vs-rolling presentation problem? Splitting them into separate views feels like it loses the thing that makes the graph interesting.

Everything is MIT-licensed and the collection pipeline is in the repo, so the extraction logic is inspectable and criticizable. Happy to add an endpoint dumping the raw edge list with source article URLs if anyone wants to audit it.
